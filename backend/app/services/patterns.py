"""Curated scam-pattern matcher (rule engine). Works with no API key, no network.

The pattern library lives in ../data/scam_patterns.json and is curated per
language (Bangla, English, Hindi, Urdu). Matching is keyword-based and
language-aware, with a severity weighting and a small bonus for messages that
match multiple distinct red-flag keywords of the same pattern.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PATTERNS_FILE = DATA_DIR / "scam_patterns.json"

# Phrases that flip the meaning of a following keyword. "Staff will never ask for your
# PIN" must not count as a PIN-theft match — that sentence is the opposite of a scam ask.
NEGATION_CUES = (
    "never", "do not", "don't", "dont", "no one", "nobody", "avoid", "instead of",
    "we will never", "will never", "never ask", "not ask", "কখনো", "করবেন না", "নেবেন না",
    "দেবেন না", "শেয়ার করবেন না", "করো না", "कभी नहीं", "न करें", "मत करें", "न दें", "न बताएं",
    "ہرگز نہیں", "نہ کریں", "مت کریں", "نہ دیں", "نہ بتائیں",
)
_NEG_WINDOW = 46


@lru_cache(maxsize=8192)
def _keyword_regex(keyword: str) -> re.Pattern[str]:
    """Compiled word-boundary matcher for one keyword (cached: the library is re-scanned
    on every request, and recompiling ~2,000 regexes per call dominated the request time)."""
    return re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")


def is_negated(text: str, index: int) -> bool:
    """True when the keyword at ``index`` sits inside a negation clause."""
    window = text[max(0, index - _NEG_WINDOW): index]
    return any(cue in window for cue in NEGATION_CUES)


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s\u0600-\u06FF\u0750-\u077F\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F]", re.UNICODE)


@lru_cache
def load_patterns() -> dict[str, Any]:
    with open(PATTERNS_FILE, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache
def _pattern_index() -> list[dict[str, Any]]:
    data = load_patterns()
    out = []
    for p in data["patterns"]:
        kw_flat: list[tuple[str, str]] = []
        for lang, words in p.get("keywords", {}).items():
            for w in words:
                kw_flat.append((lang, w))
        weak = {normalize(w) for w in p.get("weak_keywords", [])}
        out.append({**p, "_keywords": kw_flat, "_weak": weak})
    return out


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def get_pattern(pattern_id: str) -> dict[str, Any] | None:
    for p in _pattern_index():
        if p["id"] == pattern_id:
            return p
    return None


def list_patterns() -> list[dict[str, Any]]:
    """Public list for the Learn tab (no internal fields)."""
    return [
        {
            "id": p["id"],
            "category": p["category"],
            "severity": p["severity"],
            "name": p["name"],
            "summary": p["summary"],
            "psychology": p.get("psychology", []),
            "safe_response": p.get("safe_response", ""),
            "red_flag_hints": p.get("red_flag_hints", []),
        }
        for p in _pattern_index()
    ]


@dataclass
class PatternMatch:
    pattern_id: str
    name: dict[str, str]
    summary: dict[str, str]
    category: str
    score: float
    severity: float
    matched_keywords: list[str] = field(default_factory=list)
    matched_languages: list[str] = field(default_factory=list)
    red_flag_hints: list[str] = field(default_factory=list)
    psychology: list[str] = field(default_factory=list)
    safe_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "category": self.category,
            "score": round(self.score, 3),
            "severity": self.severity,
            "matched_keywords": self.matched_keywords[:8],
            "languages": self.matched_languages,
            "red_flag_hints": self.red_flag_hints,
            "psychology": self.psychology,
        }


def match_patterns(text: str, language: str | None = None, min_score: float = 0.18) -> list[PatternMatch]:
    """Return patterns sorted by match strength.

    Score = severity * coverage where coverage grows with the share of distinct
    keywords present (saturating), so a single weak keyword cannot alone decide
    the verdict.
    """
    norm = normalize(text)
    if not norm:
        return []
    tokens = set(norm.split())
    matches: list[PatternMatch] = []

    for p in _pattern_index():
        hits: list[str] = []
        langs: set[str] = set()
        for lang, kw in p["_keywords"]:
            kw_norm = normalize(kw)
            if not kw_norm:
                continue
            # Word-boundary match. The lookarounds use \w, which is Unicode-aware, so
            # Bangla / Devanagari / Arabic scripts get boundaries too. Without this,
            # short keywords match inside unrelated words ("rin" inside "printed").
            positions = [m.start() for m in _keyword_regex(kw_norm).finditer(norm)]
            if not positions and len(kw_norm) >= 6 and len(kw_norm.split()) == 1:
                # Allow inflected forms by prefix only ("بھیجیں" -> "بھیجئے"): the token must
                # START with the keyword, never merely contain it.
                positions = [
                    m.start() for t in tokens if t.startswith(kw_norm) and len(t) <= len(kw_norm) + 4
                    for m in _keyword_regex(kw_norm).finditer(t)
                ]
            # A keyword inside a negation clause is the opposite of evidence.
            positions = [i for i in positions if not is_negated(norm, i)]
            if positions:
                hits.append(kw)
                langs.add(lang)

        if not hits:
            continue

        # A brand name, "link" or "parcel" on its own is not evidence for a specific
        # pattern: legitimate services use those words too. A pattern whose ONLY matched
        # keywords are weak gets its score halved, and strong matches rank first.
        strong_hits = [h for h in hits if normalize(h) not in p.get("_weak", set())]
        coverage = 1 - (0.62 ** len(hits))          # 1 hit -> 0.38, 2 -> 0.616, 3 -> 0.762 ...
        lang_bonus = 0.1 if language and language in langs else 0.0
        score = min(1.0, p["severity"] * (0.55 * coverage + 0.45 * min(1.0, len(hits) / 4)) + lang_bonus)
        if not strong_hits:
            score *= 0.5
        if score >= min_score:
            matches.append(PatternMatch(
                pattern_id=p["id"],
                name=p["name"],
                summary=p.get("summary", {}),
                category=p["category"],
                score=round(score, 4),
                severity=float(p["severity"]),
                matched_keywords=hits,
                matched_languages=sorted(langs),
                red_flag_hints=p.get("red_flag_hints", []),
                psychology=p.get("psychology", []),
                safe_response=p.get("safe_response", ""),
            ))

    # Rank by (number of strong matched keywords, score): specificity beats bag-of-words size.
    strong_counts = {}
    for p in _pattern_index():
        strong_counts[p["id"]] = p.get("_weak", set())
    matches.sort(
        key=lambda m: (
            len([h for h in m.matched_keywords if normalize(h) not in strong_counts.get(m.pattern_id, set())]),
            m.score,
        ),
        reverse=True,
    )
    return matches


def pattern_score(matches: list[PatternMatch]) -> float:
    """Combined rule-engine score: strongest match plus a small multi-pattern bonus."""
    if not matches:
        return 0.0
    top = matches[0].score
    extra = 0.05 * min(3, len(matches) - 1)
    return round(min(1.0, top + extra), 4)


def highlight_spans(text: str, matches: list[PatternMatch]) -> list[dict[str, Any]]:
    """Locate matched keywords inside the ORIGINAL text for UI highlighting."""
    spans: list[dict[str, Any]] = []
    lowered = text.lower()
    for m in matches[:3]:
        for kw in m.matched_keywords:
            needle = kw.lower()
            start = lowered.find(needle)
            if start == -1:
                # try a loose match ignoring punctuation/whitespace differences
                continue
            spans.append({
                "start": start,
                "end": start + len(needle),
                "text": text[start:start + len(needle)],
                "pattern_id": m.pattern_id,
                "weight": round(min(1.0, 0.4 + m.score * 0.6), 3),
                "source": "pattern_library",
            })
    spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    deduped, seen = [], set()
    for s in spans:
        key = (s["start"], s["end"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
    return deduped[:12]
