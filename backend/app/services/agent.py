"""ScamLens agent.

Two execution paths, both producing the same strict ``AgentResult`` JSON:

1. **Gemini tool-use loop** (default when GEMINI_API_KEY is set)
   The model is given 8 tools and up to ``AGENT_MAX_STEPS`` (6) steps. Every tool
   result comes from real local computation or a real Gemini vision call — the
   model never invents numbers.

2. **Groq tool-use loop** (automatic when Gemini is rate-limited/unavailable)
   The same loop and tools run against Groq's OpenAI-compatible endpoint, so a
   Gemini 429 no longer drops the request to offline mode.

3. **Deterministic local agent** (fallback, or no keys at all)
   ML classifier + URL analyzer + pattern library + calibrated ensemble produce
   the verdict, red flags, actions, report draft, family alert and lesson with
   localised templates. The UI shows a "degraded mode" banner.

Honesty guarantees:
* ``evidence`` is always overwritten with the values actually computed locally,
  even when the model supplies its own numbers.
* the final risk score is the calibrated ensemble, not a free-form model guess;
  the model's judgement enters as the ``llm`` signal with the published weight.
* the agent trace records, per step, whether a tool ran because the model asked
  for it or because it was pre-computed for latency (and re-used).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..schemas import AgentResult, Evidence, InputKind, MicroLesson, RedFlag, Verdict
from . import ensemble, i18n
from .llm import FallbackLLMClient, LLMUnavailable, build_llm_client, extract_json_object
from .ml_classifier import TextClassifierService, TextPrediction
from .patterns import get_pattern, highlight_spans, list_patterns, match_patterns, pattern_score
import re

from .pii import redact, restore
from .url_analyzer import TextCleaner, analyze_url, extract_urls

log = logging.getLogger("scamlens.agent")


# --------------------------------------------------------------------------- #
# Tool schemas exposed to Gemini
# --------------------------------------------------------------------------- #
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "extract_content",
        "description": "Normalise a voice transcript or transcribe a screenshot when image bytes are provided to this tool. When the screenshot is already attached to the current request, read it directly with vision instead of calling this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "The raw content or transcript"},
                "kind": {"type": "string", "enum": ["text", "url", "image", "audio_transcript"]},
            },
            "required": ["input"],
        },
    },
    {
        "name": "classify_text",
        "description": "Run the local ML scam classifier (multilingual sentence embeddings + calibrated logistic regression). Returns scam probability 0-1 and the top contributing tokens.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "analyze_url",
        "description": "Lexically analyse a URL: length, digits, subdomain depth, punycode/homoglyphs, suspicious TLDs, shorteners, edit-distance brand impersonation (bKash, Nagad, PayPal, banks...). Optionally inspects the redirect chain with a safe HEAD-only request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "probe_redirects": {"type": "boolean", "description": "Run the safe HEAD redirect probe (never renders the page)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "match_pattern",
        "description": "Match the text against the curated scam-pattern library (22 documented playbooks) and return matched patterns, matched keywords, psychology tricks and the safe response.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "language": {"type": "string", "enum": ["bn", "en", "hi", "ur", "unknown"]},
            },
            "required": ["text"],
        },
    },
    {
        "name": "detect_pii",
        "description": "Find phone numbers, emails, OTPs, card numbers, account numbers and NID numbers in the text and return the redacted version. Always call this before analysing.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "draft_report",
        "description": "Draft a ready-to-send complaint for the relevant bank, mobile-money provider, platform or police cyber cell, in the user's language.",
        "input_schema": {
            "type": "object",
            "properties": {
                "analysis": {"type": "string", "description": "Short summary of the analysis to base the complaint on"},
                "language": {"type": "string", "enum": ["bn", "en", "hi", "ur"]},
                "authority": {"type": "string", "description": "e.g. bKash, my bank, police cyber cell"},
            },
            "required": ["analysis"],
        },
    },
    {
        "name": "generate_family_alert",
        "description": "Write a short, very simple warning the user can forward to elderly relatives on WhatsApp (2-4 sentences, no jargon).",
        "input_schema": {
            "type": "object",
            "properties": {
                "analysis": {"type": "string"},
                "language": {"type": "string", "enum": ["bn", "en", "hi", "ur"]},
            },
            "required": ["analysis"],
        },
    },
    {
        "name": "create_micro_lesson",
        "description": "Create a 60-second digital-literacy micro-lesson with a 3-question quiz for the detected scam pattern, in the user's language.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "pattern id from match_pattern"},
                "language": {"type": "string", "enum": ["bn", "en", "hi", "ur"]},
                "level": {"type": "string", "enum": ["basic", "intermediate"]},
            },
            "required": ["pattern"],
        },
    },
]

AGENT_SYSTEM_PROMPT = """You are ScamLens, an anti-scam agent that protects everyday users in South Asia \
(Bangladesh, India, Pakistan) and teaches them digital literacy.

Your task each turn:
1. Call `detect_pii` first (the pipeline already redacts, but confirm).
2. Call the analysis tools you need: `classify_text`, `analyze_url` for each link and `match_pattern`. Read an attached screenshot directly with vision; use `extract_content` only to transcribe image bytes passed to that tool or normalize a voice transcript.
3. Then call the output tools if requested: `draft_report`, `generate_family_alert`, `create_micro_lesson`.
4. Finally, reply with ONE JSON object and nothing else.

Hard rules:
- NEVER click, fetch or render the message's page content; only `analyze_url`'s HEAD probe may touch the network.
- Never invent numbers. Scores must come from tool results.
- Explanations must be simple, short sentences — understandable by a 13-year-old or an elderly first-time smartphone user. No jargon like "heuristic" or "ensemble".
- Always write the user-facing text (explanation, lesson, report, family alert) in the user's language: {language_name} ({language_code}).
- Be careful, not alarmist. If the message looks legitimate, say so clearly.

Return exactly this JSON shape:
{{
  "verdict": "SAFE" | "SUSPICIOUS" | "SCAM",
  "risk_score": <0-100 integer>,
  "confidence": <0-1 float>,
  "language": "bn"|"en"|"hi"|"ur"|"unknown",
  "scam_type": "<pattern id or 'legitimate' or 'unknown'>",
  "red_flags": [{{"text_span": "<exact words from the user's message>", "reason": "<plain-language reason>", "severity": <0-1>}}],
  "explanation": "<3-5 short sentences, 6th-grade level, in the user's language>",
  "recommended_actions": ["<ordered, concrete step>", ...],
  "report_draft": "<ready-to-send complaint or null>",
  "family_alert": "<short forwardable warning or null>",
  "lesson": {{"title": "...", "pattern_id": "...", "language": "bn", "level": "basic", "seconds": 60,
             "body": "...", "key_takeaways": ["..."],
             "quiz": [{{"question": "...", "options": ["..."], "answer_index": 0, "explanation": "..."}}]}},
  "llm_score": <0-1 float, your own risk judgement>
}}"""


LANGUAGE_NAMES = {"bn": "Bangla", "en": "English", "hi": "Hindi", "ur": "Urdu", "unknown": "English"}

# A scam message has to make an ask. These patterns detect the ask in four scripts plus
# romanised South-Asian English. Used by the actionability check below — the check is
# reported to the user, never used to hide a signal.
# A scam has to make a *request*: send money, share a code, click a link, install an app,
# call a number, register, or verify KYC. Matching bare nouns ("payment", "otp") fires on
# legitimate notifications, so each pattern below pairs a request verb with its object, and
# every token is matched on word boundaries (an early version matched the Bangla "ফি" inside
# "ফিরবো" = "I will return"). A negation filter then removes defensive advice such as
# "never share your OTP" — that sentence is the opposite of an ask.
_B = lambda body: rf"(?<![\w]){body}(?![\w])"  # noqa: E731 - word boundaries, Unicode-aware

_MONEY = r"(?:money|taka|tk|bdt|cash|amount|fee|charge|payment|sum|rupees?|rupaye|paisa|poisa|dollars?|usdt|bitcoin|btc)"
_CODE = r"(?:otp|o[ -]?t[ -]?p|code|pin|password|cvv|card number|verification code|6 digit code)"
CHANNEL = r"(?:link|url|number|no\.?|account|wallet|app|whatsapp|telegram)"

REQUEST_PATTERNS = [
    # English: send/pay/transfer money · share a code · click a link · install an app
    _B(rf"(?:send|transfer|pay|deposit|top ?up|cash ?in|give|provide)\s+(?:me\s+)?(?:the\s+|your\s+|a\s+|this\s+)?{_MONEY}"),
    _B(rf"(?:send|forward|share|tell|give|reply with)\s+(?:me\s+)?(?:the\s+|your\s+|that\s+|this\s+|us\s+)?{_CODE}"),
    _B(rf"(?:click|open|tap|visit|follow)\s+(?:this\s+|the\s+|here|on\s+the\s+)?{CHANNEL}"),
    _B(rf"(?:install|download)\s+(?:this\s+|the\s+|our\s+)?(?:app|application|anydesk|teamviewer|quick ?support|apk)"),
    _B(rf"(?:register|subscribe|sign ?up|join)\s+(?:now|today|here|immediately|with|using)?"),
    _B(rf"(?:verify|confirm|update|complete)\s+(?:your\s+)?(?:kyc|account|identity|card|details|information|sim)"),
    _B(rf"(?:pay|clear|settle|submit)\s+(?:the\s+|a\s+|your\s+)?(?:fee|charge|fine|penalty|due|bill|clearance|customs|advance|tax)"),
    # Bangla
    _B(r"(?:টাকা|অর্থ|ফি|চার্জ|বিল|জরিমানা)(?:\s+\S+){0,4}\s*(?:পাঠান|পাঠাও|পাঠিয়ে|দিন|জমা|বিকাশ|নগদ|পে|পরিশোধ|করুন)"),
    _B(r"(?:পাঠান|পাঠাও|জমা\s*দিন|বিকাশ\s*করুন|বিকাশ\s*কর|নগদ\s*করুন)\s*(?:এই|আমার|এ)?\s*(?:নাম্বারে|নম্বরে|একাউন্টে|টাকা|ফি)?"),
    _B(r"(?:ওটিপি|পিন|কোড|পাসওয়ার্ড)\s*(?:দিন|শেয়ার\s*করুন|পাঠান|বলুন|লিখুন)"),
    _B(r"(?:ক্লিক|ট্যাপ)\s*(?:করুন|কর|করে)"),
    _B(r"(?:ইনস্টল|ডাউনলোড)\s*(?:করুন|কর)"),
    _B(r"(?:কল|ফোন|যোগাযোগ)\s*(?:করুন|কর)"),
    _B(r"(?:কেওয়াইসি|কিওয়াইসি|একাউন্ট|তথ্য|যাচাই|সিম)\s*(?:আপডেট|ভেরিফাই|করুন|দিন)"),
    # Hindi
    _B(r"(?:पैसे|पैसा|रुपये|रकम|फीस|शुल्क|बिल|जुर्माना)(?:\s+\S+){0,4}\s*(?:भेजें|भेजो|भेजिए|जमा|ट्रांसफर|दें|करें)"),
    _B(r"(?:ओटीपी|पिन|कोड|पासवर्ड)\s*(?:बताएं|शेयर|भेजें|दें|लिखें)"),
    _B(r"(?:क्लिक|टैप|लिंक)\s*(?:करें|करो|खोलें)"),
    _B(r"(?:इंस्टॉल|डाउनलोड)\s*(?:करें|करो)"),
    _B(r"(?:कॉल|फोन|संपर्क)\s*(?:करें|करो)"),
    _B(r"(?:केवाईसी|अकाउंट|खाता|जानकारी|सिम)\s*(?:अपडेट|वेरिफाई|करें|दें)"),
    # Urdu
    _B(r"(?:رقم|روپے|پیسے|فیس|بل|جرمانہ)(?:\s+\S+){0,4}\s*(?:بھیجیں|بھیج|جمع|ٹرانسفر|دیں|کریں)"),
    _B(r"(?:او\s?ٹی\s?پی|پن|کوڈ|پاس\s?ورڈ)\s*(?:بتائیں|شیئر|بھیجیں|دیں|لکھیں)"),
    _B(r"(?:کلک|ٹیپ|لنک)\s*(?:کریں|کر|کھولیں)"),
    _B(r"(?:انسٹال|ڈاؤن\s*لوڈ)\s*(?:کریں|کر)"),
    _B(r"(?:کال|رابطہ)\s*(?:کریں|کر)"),
    _B(r"(?:کے\s?وائی\s?سی|اکاؤنٹ|معلومات|سم)\s*(?:اپڈیٹ|تصدیق|کریں|دیں)"),
    # Romanised South Asian English ("500 taka bKash korun 017… number e")
    _B(r"(?:bKash|Nagad|Rocket|Easypaisa|JazzCash)\s+(?:korun|koro|karo|karein|kar|send|kro)"),
    _B(rf"(?:bhejo|bhejein|bhej|pathao|pathan|pay|send|transfer|deposit)\s+(?:me\s+)?(?:the\s+|is\s+|ei\s+|ei\s+number\s+)?{_MONEY}"),
    _B(r"(?:is|ei|this|amar|mera)\s+(?:number|nombor|nambor|account|account e|number par|number pe)\b.{0,24}(?:bhejo|pathao|send|transfer|korun|koro)"),
    _B(rf"(?:otp|pin|code)\s+(?:ta\s+|da\s+|do|de|din|den|batao|bata\s+do|share\s+koro|bhejo)"),
]
_REQUEST_RES = [re.compile(p, re.IGNORECASE) for p in REQUEST_PATTERNS]

from .patterns import NEGATION_CUES as _NEGATION_CUES

# Asking the reader to use a channel they already trust (the number printed on their own
# card, the bank's official app) is advice, not a scam ask — the sender gains nothing.
SELF_SERVE_CUES = (
    "printed on your card", "printed on the card", "on the back of your card",
    "on your card", "printed on your statement", "official app", "official website",
    "your bank's app", "through our app in the", "আপনার কার্ডে লেখা", "কার্ডের পেছনে",
    "কার্ডে লেখা", "कार्ड पर लिखा", "कार्ड के पीछे", "کارڈ پر لکھا", "کارڈ کے پیچھے",
)


# --------------------------------------------------------------------------- #
@dataclass
class ToolTrace:
    steps: list[dict[str, Any]] = field(default_factory=list)
    llm_score: float | None = None
    llm_verdict: str | None = None
    llm_error: str | None = None
    used_tools: set[str] = field(default_factory=set)

    def add(self, name: str, source: str, duration_ms: int, summary: str, ok: bool = True) -> None:
        self.steps.append({
            "step": len(self.steps) + 1,
            "tool": name,
            "source": source,          # "agent_call" = model asked for it, "precomputed" = cached fast path
            "duration_ms": duration_ms,
            "ok": ok,
            "summary": summary[:220],
        })
        if source == "agent_call":
            self.used_tools.add(name)


class _Toolbox:
    """All tool implementations. Every one returns real, reproducible output."""

    def __init__(self, settings: Settings, ml: TextClassifierService, url_model=None,
                 llm: FallbackLLMClient | None = None) -> None:
        self.settings = settings
        self.ml = ml
        self.url_model = url_model
        self.llm = llm
        self.cache: dict[str, Any] = {}

    # -- 1. extract_content -------------------------------------------------
    def extract_content(self, input_text: str, kind: str = "text",
                        image_bytes: bytes | None = None, media_type: str | None = None) -> dict:
        if kind == "image" and image_bytes:
            if self.llm and self.llm.available:
                text = self.llm.vision_extract(
                    image_bytes, media_type or "image/png",
                    "Transcribe every piece of text in this screenshot. Include sender names, "
                    "phone numbers, URLs and amounts exactly as written.",
                )
                return {"text": text, "source": "gemini_vision_ocr", "ok": True}
            return {
                "text": input_text or "",
                "source": "unavailable",
                "ok": False,
                "error": "Screenshot reading needs the Gemini vision model. Paste the text or type it instead.",
            }
        if kind == "audio_transcript":
            return {"text": input_text, "source": "browser_web_speech_api", "ok": True,
                    "note": "Transcript produced on the device by the Web Speech API."}
        return {"text": input_text, "source": "raw_text", "ok": True}

    # -- 2. classify_text ---------------------------------------------------
    def classify_text(self, text: str) -> dict:
        pred = self.ml.predict(text)
        return pred.to_dict()

    # -- 3. analyze_url -----------------------------------------------------
    def analyze_url(self, url: str, probe_redirects: bool = True) -> dict:
        return analyze_url(
            url,
            model=self.url_model,
            probe=bool(probe_redirects and self.settings.url_probe_enabled),
            timeout=self.settings.url_probe_timeout_seconds,
        )

    # -- 4. match_pattern ---------------------------------------------------
    def match_pattern(self, text: str, language: str | None = None) -> dict:
        matches = match_patterns(text, language=language)
        return {
            "matches": [m.to_dict() for m in matches],
            "top_pattern": matches[0].pattern_id if matches else None,
            "pattern_score": pattern_score(matches),
            "library_size": len(list_patterns()),
        }

    # -- 5. detect_pii ------------------------------------------------------
    def detect_pii(self, text: str) -> dict:
        res = redact(text)
        return {
            "redacted_text": res.redacted_text,
            "entities": [e.to_dict() for e in res.entities],
            "count": res.count,
        }

    # -- 6. draft_report ----------------------------------------------------
    def draft_report(self, analysis: str, language: str = "en", authority: str | None = None) -> dict:
        if self.llm and self.llm.available:
            try:
                prompt = (
                    f"Write a ready-to-send complaint about a scam attempt.\n"
                    f"Language: {LANGUAGE_NAMES.get(language, 'English')} ({language}).\n"
                    f"Suggested authority: {authority or 'the relevant bank / mobile money provider / police cyber cell'}.\n"
                    f"Analysis: {analysis}\n\n"
                    "Rules: 120-200 words, formal but simple, include placeholders [YOUR NAME], [YOUR PHONE], "
                    "[DATE], [TRANSACTION ID]. Ask them to block the number/account and to log the complaint. "
                    "Reply with the complaint text only."
                )
                resp = self.llm.messages_create(
                    system="You write short, formal complaints for fraud victims in South Asia.",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=700, temperature=0.2,
                )
                return {"report": resp.text.strip(), "source": self.llm.last_provider or "llm"}
            except LLMUnavailable as exc:
                log.warning("draft_report LLM failed: %s", exc)
        return {"report": None, "source": "unavailable"}

    # -- 7. generate_family_alert -------------------------------------------
    def generate_family_alert(self, analysis: str, language: str = "en") -> dict:
        if self.llm and self.llm.available:
            try:
                prompt = (
                    f"Write a 2-4 sentence WhatsApp warning in {LANGUAGE_NAMES.get(language, 'English')} ({language}) "
                    "that an adult can forward to elderly relatives. Very simple words, no jargon, one emoji at most, "
                    "tell them exactly what not to do. Context: " + analysis
                )
                resp = self.llm.messages_create(
                    system="You write short family safety messages.",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300, temperature=0.4,
                )
                return {"alert": resp.text.strip(), "source": self.llm.last_provider or "llm"}
            except LLMUnavailable as exc:
                log.warning("generate_family_alert LLM failed: %s", exc)
        return {"alert": None, "source": "unavailable"}

    # -- 8. create_micro_lesson --------------------------------------------
    def create_micro_lesson(self, pattern: str, language: str = "en", level: str = "basic") -> dict:
        if self.llm and self.llm.available:
            try:
                p = get_pattern(pattern) or {}
                prompt = (
                    f"Create a 60-second digital-literacy micro-lesson in {LANGUAGE_NAMES.get(language, 'English')} "
                    f"({language}) for level '{level}' about this scam pattern: {p.get('name', {}).get('en', pattern)}. "
                    f"Documented red flags: {p.get('red_flag_hints', [])}. "
                    f"Return JSON: {{\"title\": str, \"body\": 80-130 words in simple language, "
                    f"\"key_takeaways\": [3 short strings], \"quiz\": [3 items with \"question\", \"options\" (3 options), "
                    f"\"answer_index\", \"explanation\"]}}. Only JSON."
                )
                resp = self.llm.messages_create(
                    system="You are a patient digital-literacy teacher for first-time smartphone users.",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1200, temperature=0.3, json_mode=True,
                )
                data = extract_json_object(resp.text)
                data.update({"pattern_id": pattern, "language": language, "level": level, "seconds": 60})
                return {"lesson": data, "source": self.llm.last_provider or "llm"}
            except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
                log.warning("create_micro_lesson LLM failed: %s", exc)
        return {"lesson": None, "source": "unavailable"}


# --------------------------------------------------------------------------- #
def _verdict_str(value: Any) -> str:
    """Verdict name as a plain string.

    i18n dictionaries are keyed by "SCAM" / "SUSPICIOUS" / "SAFE". Passing the Verdict enum
    instead used to miss the lookup (enum hashes by name, not by string value) and produced
    an empty explanation, which the schema then rejected.
    """
    return str(getattr(value, "value", value))


def _truncate(text: str, n: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


class ScamLensAgent:
    def __init__(self, settings: Settings, ml: TextClassifierService, url_model=None) -> None:
        self.settings = settings
        self.ml = ml
        self.url_model = url_model
        self.llm = build_llm_client(settings)
        self.toolbox = _Toolbox(settings, ml, url_model, self.llm)

    # ------------------------------------------------------------------ entry
    def analyze(self, *, text: str, kind: InputKind = InputKind.TEXT, language: str | None = None,
                device_id: str = "unknown", image_bytes: bytes | None = None,
                media_type: str | None = None, make_lesson: bool = True,
                make_report: bool = True, make_family_alert: bool = True,
                url_override: str | None = None) -> AgentResult:
        started = time.perf_counter()
        trace = ToolTrace()

        # --- Step 0: PII redaction happens BEFORE anything is sent to the LLM ---
        pii = redact(text)
        safe_text = pii.redacted_text
        urls = extract_urls(url_override or text)

        # --- Step 1: real, local signals (memoised fast path for the tools) ---
        guess = i18n.detect_language(text)
        lang = language if language and language != "unknown" else guess.language

        # A submission that is nothing but a link is not prose: the classifier was trained
        # on sentences, and its opinion of a URL string is noise that would outvote the
        # dedicated URL model (which is why https://www.bkash.com/terms once landed in the
        # SUSPICIOUS band). Text features are only used when there is text around the link.
        link_only = bool(urls) and len(TextCleaner.strip_urls(text)) < 12
        if link_only:
            # There is no prose to detect a language from, and romanised tokens inside a URL
            # ("bkash", "login") used to tip detection to Bangla, so an English-interface user
            # submitting a bare link got a Bangla verdict. The requested language wins; the
            # default is English.
            guess = i18n.LanguageGuess(
                language=("en" if not language or language == "unknown" else language),
                confidence=0.0,
            )
            lang = guess.language  # `lang` was derived from the old guess one line too early
            # score=None (not 0.0) so the ensemble *excludes* the text signal and
            # renormalises its weights. A zero would count as "the classifier saw nothing
            # suspicious here" and dilute the URL evidence instead of deferring to it.
            ml_pred = TextPrediction(
                available=False, score=None, model_used="skipped_link_only",
                reason="submission is a bare link — the URL analyser decides",
            )
            trace.add("classify_text", "skipped", 0,
                      "input is a bare link — URL model decides (text model skipped)")
        else:
            t0 = time.perf_counter()
            ml_pred = self.ml.predict(safe_text)
            trace.add("classify_text", "precomputed", int((time.perf_counter() - t0) * 1000),
                      f"ml score={ml_pred.score} model={ml_pred.model_used}")

        url_results: list[dict] = []
        for u in urls:
            t0 = time.perf_counter()
            res = self.toolbox.analyze_url(u, probe_redirects=True)
            url_results.append(res)
            trace.add("analyze_url", "precomputed", int((time.perf_counter() - t0) * 1000),
                      f"{u[:60]} -> score={res['score']} ({res['score_source']})")
        url_score = max((r["score"] for r in url_results), default=None)

        t0 = time.perf_counter()
        matches = match_patterns(safe_text, language=lang)
        p_score = pattern_score(matches)
        trace.add("match_pattern", "precomputed", int((time.perf_counter() - t0) * 1000),
                  f"{len(matches)} pattern(s), top={matches[0].pattern_id if matches else None}, score={p_score}")

        # --- Step 2: the agent reasoning loop ---------------------------------
        llm_confidence: float | None = None
        mode: str = "agent"
        degraded_reason: str | None = None
        llm_json: dict | None = None

        if self.llm.available:
            try:
                llm_json = self._run_gemini_loop(
                    safe_text=safe_text, kind=kind, lang=lang, trace=trace,
                    image_bytes=image_bytes, media_type=media_type, urls=urls,
                    ml_pred=ml_pred, matches=matches, p_score=p_score,
                    url_results=url_results, guess=guess, pii=pii,
                    make_lesson=make_lesson, make_report=make_report,
                    make_family_alert=make_family_alert,
                )
            except LLMUnavailable as exc:
                degraded_reason = f"Gemini and Groq unavailable ({exc})"
                log.warning("Agent loop failed: %s", exc)
        else:
            if self.llm.cooldown_remaining > 0:
                degraded_reason = (
                    f"AI providers are cooling down after a quota error — running the local agent; "
                    f"AI mode retries in ~{int(self.llm.cooldown_remaining)}s"
                )
            elif not self.llm.primary_configured and not self.llm.fallback_configured:
                degraded_reason = "GEMINI_API_KEY and GROQ_API_KEY are not configured on the server"
            else:
                degraded_reason = "AI providers unavailable — running the local agent"

        # --- Step 3: local result --------------------------------------------
        local = self._local_result(
            trace, safe_text, kind, lang, guess, ml_pred, matches, p_score,
            url_results, url_score, pii, make_lesson, make_report, make_family_alert,
        )

        if llm_json is None:
            if not self.settings.enable_local_agent_fallback:
                raise LLMUnavailable(degraded_reason or "LLM unavailable and fallback disabled")
            local.mode = "local_fallback"
            local.degraded_reason = degraded_reason
            result = local
        else:
            result = self._merge_llm_result(local, llm_json, trace)
            result.mode = "agent"

        # --- Step 4: honest evidence -----------------------------------------
        result.evidence.agent_steps = trace.steps
        result.evidence.model_versions = {
            "text_classifier": (self.ml.metadata().get("version") or "unavailable"),
            "url_model": (getattr(self.url_model, "get", lambda *_: None)("version") or "rule_based"),
            "pattern_library": "1.0.0",
            "llm_provider": self.llm.last_provider or self.llm.provider,
            "gemini_model": self.llm.primary.model if self.llm.primary_configured else "not_configured",
            "groq_model": (
                self.llm.fallback.model
                if self.llm.fallback_configured and self.llm.fallback is not None
                else "not_configured"
            ),
        }
        result.pii_redacted = pii.count > 0
        result.analysis_id = uuid.uuid4().hex[:16]
        result.created_at = datetime.now(timezone.utc).isoformat()

        # Restore the user's OWN values into the returned draft (never sent to the model).
        if result.report_draft:
            result.report_draft = restore(result.report_draft, pii.entities)
        if result.family_alert:
            result.family_alert = restore(result.family_alert, pii.entities)

        log.info("analyze done id=%s verdict=%s risk=%s mode=%s in %.0f ms",
                 result.analysis_id, result.verdict, result.risk_score, result.mode,
                 (time.perf_counter() - started) * 1000)
        return result

    # ------------------------------------------------------------------ Gemini
    def _run_gemini_loop(self, *, safe_text: str, kind: InputKind, lang: str, trace: ToolTrace,
                         image_bytes: bytes | None, media_type: str | None, urls: list[str],
                         ml_pred, matches, p_score: float, url_results: list[dict], guess,
                         pii, make_lesson: bool, make_report: bool,
                         make_family_alert: bool) -> dict | None:
        toolbox = self.toolbox
        context = {
            "input_kind": kind.value,
            "language_guess": guess.to_dict(),
            "pii_entities_found": pii.count,
            "precomputed_signals": {
                "ml_score": ml_pred.score,
                "ml_model": ml_pred.model_used,
                "pattern_score": p_score,
                "top_patterns": [m.pattern_id for m in matches[:3]],
                "urls": [{"url": r["url"], "score": r["score"], "findings": [f["type"] for f in r["findings"]]} for r in url_results],
            },
            "outputs_requested": {
                "report_draft": make_report,
                "family_alert": make_family_alert,
                "lesson": make_lesson,
            },
        }
        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Analyse this user submission for scam risk and produce the JSON verdict.\n\n"
                    f"<submission kind=\"{kind.value}\">\n{safe_text.strip()}\n</submission>\n\n"
                    f"<pipeline_context>{json.dumps(context, ensure_ascii=False)}</pipeline_context>\n\n"
                    "Ask for any tool you need, then output the JSON object only."
                ),
            }
        ]
        if image_bytes and kind == InputKind.IMAGE:
            import base64

            user_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type or "image/png",
                           "data": base64.b64encode(image_bytes).decode("ascii")},
            })

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        system = AGENT_SYSTEM_PROMPT.format(
            language_name=LANGUAGE_NAMES.get(lang, "English"), language_code=lang
        )

        for step in range(self.settings.agent_max_steps):
            resp = self.llm.messages_create(system=system, messages=messages, tools=TOOL_SCHEMAS)
            messages.append({"role": "assistant", "content": resp.raw_blocks})

            if resp.tool_calls:
                results: list[dict[str, Any]] = []
                for call in resp.tool_calls:
                    t0 = time.perf_counter()
                    out, summary, ok = self._execute_tool(
                        call["name"], call.get("input") or {},
                        safe_text=safe_text, lang=lang,
                        image_bytes=image_bytes, media_type=media_type,
                    )
                    trace.add(call["name"], "agent_call", int((time.perf_counter() - t0) * 1000), summary, ok)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "name": call["name"],
                        "content": json.dumps(out, ensure_ascii=False)[:12000],
                        "is_error": not ok,
                    })
                messages.append({"role": "user", "content": results})
                continue

            # No tool call: expect the final JSON
            if resp.text:
                try:
                    data = extract_json_object(resp.text)
                    trace.llm_score = float(data.get("llm_score")) if data.get("llm_score") is not None else None
                    trace.llm_verdict = data.get("verdict")
                    return data
                except LLMUnavailable:
                    messages.append({
                        "role": "user",
                        "content": "That was not valid JSON. Reply with the single JSON object only — no prose, no code fences.",
                    })
                    continue
            break

        raise LLMUnavailable(f"agent did not produce valid JSON within {self.settings.agent_max_steps} steps")

    def _execute_tool(self, name: str, args: dict, *, safe_text: str, lang: str,
                      image_bytes: bytes | None = None, media_type: str | None = None) -> tuple[dict, str, bool]:
        tb = self.toolbox
        try:
            if name == "detect_pii":
                out = tb.detect_pii(args.get("text") or safe_text)
                return out, f"found {out['count']} PII entit(ies)", True
            if name == "classify_text":
                out = tb.classify_text(args.get("text") or safe_text)
                return out, f"score={out.get('score')} via {out.get('model_used')}", out.get("available", False)
            if name == "analyze_url":
                out = tb.analyze_url(args.get("url", ""), bool(args.get("probe_redirects", True)))
                return out, f"score={out['score']} findings={len(out['findings'])}", True
            if name == "match_pattern":
                out = tb.match_pattern(args.get("text") or safe_text, args.get("language") or lang)
                return out, f"top={out.get('top_pattern')} score={out.get('pattern_score')}", True
            if name == "extract_content":
                out = tb.extract_content(
                    args.get("input") or safe_text,
                    args.get("kind") or "text",
                    image_bytes=image_bytes,
                    media_type=media_type,
                )
                return out, f"source={out.get('source')}", bool(out.get("ok"))
            if name == "draft_report":
                out = tb.draft_report(args.get("analysis") or safe_text[:800],
                                      args.get("language") or lang, args.get("authority"))
                return out, f"source={out.get('source')}", bool(out.get("report"))
            if name == "generate_family_alert":
                out = tb.generate_family_alert(args.get("analysis") or safe_text[:800],
                                               args.get("language") or lang)
                return out, f"source={out.get('source')}", bool(out.get("alert"))
            if name == "create_micro_lesson":
                out = tb.create_micro_lesson(args.get("pattern") or "phishing_link",
                                             args.get("language") or lang, args.get("level") or "basic")
                return out, f"source={out.get('source')}", bool(out.get("lesson"))
            return {"error": f"unknown tool {name}"}, f"unknown tool {name}", False
        except Exception as exc:  # noqa: BLE001
            log.exception("tool %s failed", name)
            return {"error": f"{type(exc).__name__}: {exc}"[:300]}, f"error: {type(exc).__name__}", False

    # ------------------------------------------------------------------ local
    def _local_result(self, trace: ToolTrace, safe_text: str, kind: InputKind, lang: str, guess,
                      ml_pred, matches, p_score: float, url_results: list[dict],
                      url_score: float | None, pii, make_lesson: bool, make_report: bool,
                      make_family_alert: bool) -> AgentResult:
        # A submission that is nothing but a link has no message text to weigh against the
        # link, so the URL analyser's score *is* the risk score. Blending it with the
        # generic "this message contains a link" pattern only ever dilutes the evidence.
        link_only = bool(url_results) and len(TextCleaner.strip_urls(safe_text)) < 12
        if link_only and url_score is not None:
            matches = [m for m in matches if m.pattern_id != "phishing_link"]
            p_score = pattern_score(matches) if matches else 0.0

        signals = {"ml": ml_pred.score, "url": url_score, "pattern": p_score if p_score > 0 else None}
        if trace.llm_score is not None:
            signals["llm"] = trace.llm_score
        if link_only and url_score is not None:
            # the URL analyser decides; weights say so explicitly (see explain_breakdown)
            score = float(url_score)
            breakdown = {"url": 1.0}
            if signals.get("pattern"):
                breakdown["pattern"] = 0.0  # reported, but not allowed to dilute the link
        else:
            score, breakdown = ensemble.combine(signals, self._weights(url_present=url_score is not None))
        thresholds = self._thresholds()
        verdict = _verdict_str(ensemble.verdict_for(score, thresholds))
        confidence = ensemble.confidence_for(score, signals, thresholds)

        top = matches[0] if matches else None
        scam_type = top.pattern_id if top else ("legitimate" if verdict == "SAFE" else "unknown")
        type_label = (top.name.get(lang) or top.name.get("en", "")) if top else ""  # localised pattern name

        red_flags = self._red_flags(safe_text, matches, ml_pred, url_results)
        actionability = self._actionability(safe_text, [r["url"] for r in url_results], pii.entities)
        # Playbook override: the pattern library is human-curated ground truth for the
        # playbooks we have seen in the field. When a high-severity playbook matches
        # strongly AND the message asks the reader to send money / a code / a click, the
        # rule wins over the statistical score. The effect of this rule is measured on the
        # held-out test set by `ml/eval_ensemble.py` and published on the Benchmark tab.
        if self.settings.playbook_override_enabled and actionability["actionable"] and top is not None:
            strong_hits = [h for h in top.matched_keywords if h.lower() not in {
                w.lower() for w in (get_pattern(top.pattern_id) or {}).get("weak_keywords", [])
            }]
            if (
                top.severity >= ensemble.PLAYBOOK_MIN_SEVERITY
                and top.score >= ensemble.PLAYBOOK_MIN_PATTERN_SCORE
                and len(strong_hits) >= ensemble.PLAYBOOK_MIN_STRONG_KEYWORDS
            ):
                override = ensemble.PLAYBOOK_OVERRIDE_SCORE
                if score < override:
                    breakdown = {
                        **breakdown,
                        "playbook_override": override,
                        "playbook_override_pattern": top.pattern_id,
                    }
                    score = override
                    verdict = _verdict_str(ensemble.verdict_for(score, thresholds))

        # Band floor: a clear match on a curated, high-severity playbook keeps the result
        # out of the SAFE band. A known playbook is positive evidence, not the absence of
        # one, so it should never be averaged away by a low ML score on unfamiliar wording.
        if actionability["actionable"] and top is not None:
            strong_hits = [h for h in top.matched_keywords if h.lower() not in {
                w.lower() for w in (get_pattern(top.pattern_id) or {}).get("weak_keywords", [])
            }]
            if top.severity >= 0.85 and top.score >= 0.55 and strong_hits:
                floor = 0.40
                if score < floor:
                    breakdown = {**breakdown, "pattern_band_floor": floor}
                    score = floor
                    verdict = _verdict_str(ensemble.verdict_for(score, thresholds))

        cap = float(self.settings.non_actionable_risk_cap)
        # Keep the displayed score inside the SAFE band so the number and the verdict agree.
        cap = min(cap, round(float(thresholds["suspicious"]) - 0.02, 4))
        if not actionability["actionable"] and cap < 1.0 and (ml_pred.score or 0.0) < 0.85:
            if score > cap:
                actionability["cap_applied"] = True
                actionability["uncapped_score"] = round(score, 4)
                score = cap
                breakdown = {**breakdown}
                breakdown["non_actionable_cap"] = cap
            # A message that asks for nothing cannot be executed against the reader, so it is
            # never reported as a scam. The raw (uncapped) score is still shown in the evidence.
            verdict = _verdict_str(Verdict.SAFE)

        explanation = self._explanation(verdict, lang, top, ml_pred, url_score, score, confidence)
        actions = self._actions(verdict, lang, top, url_score)
        report = self._report_template(lang, verdict, top, safe_text, pii) if make_report and verdict != "SAFE" else None
        alert = self._family_alert_template(lang, safe_text, verdict) if make_family_alert and verdict != "SAFE" else None
        lesson = self._offline_lesson(top, lang) if make_lesson and top else None

        return AgentResult(
            verdict=Verdict(verdict),
            risk_score=int(round(score * 100)),
            confidence=confidence,
            language=lang if lang in i18n.SUPPORTED else "en",  # type: ignore[arg-type]
            scam_type=scam_type,
            scam_type_label=type_label,
            input_kind=kind,
            red_flags=red_flags,
            explanation=explanation,
            recommended_actions=actions,
            report_draft=report,
            family_alert=alert,
            lesson=lesson,
            evidence=Evidence(
                ml_score=ml_pred.score,
                ml_label=ml_pred.label,
                url_score=url_score,
                pattern_score=p_score if p_score > 0 else None,
                pattern_matches=[m.to_dict() for m in matches[:5]],
                ensemble_breakdown=ensemble.explain_breakdown(signals, breakdown, score),
                top_tokens=ml_pred.top_tokens,
                url_findings=[f for r in url_results for f in r["findings"]][:12],
                pii_found=[e.to_dict() for e in pii.entities],
                actionability=actionability,
            ),
        )

    def _merge_llm_result(self, local: AgentResult, llm_json: dict, trace: ToolTrace) -> AgentResult:
        """Validate the model JSON; keep local evidence; fill any missing field locally."""
        data = dict(llm_json)
        data.pop("llm_score", None)

        # Map the model output onto the strict schema, falling back to local values.
        merged = local.model_copy(deep=True)
        try:
            candidate = AgentResult.model_validate({**local.model_dump(), **{
                k: v for k, v in data.items()
                if k in {"verdict", "risk_score", "confidence", "language", "scam_type", "red_flags",
                         "explanation", "recommended_actions", "report_draft", "family_alert", "lesson"}
            }})
            merged = candidate
        except Exception as exc:
            log.warning("LLM JSON failed validation (%s) – keeping local fields where needed", exc)
            for key in ("explanation", "recommended_actions", "red_flags", "lesson", "report_draft", "family_alert"):
                value = data.get(key)
                if value:
                    try:
                        merged = AgentResult.model_validate({**merged.model_dump(), key: value})
                    except Exception:  # noqa: BLE001
                        pass

        # The ensemble decides the score/verdict; the model contributes the llm signal.
        local_signals = {
            "ml": merged.evidence.ml_score,
            "url": merged.evidence.url_score,
            "pattern": merged.evidence.pattern_score,
            "llm": trace.llm_score,
        }
        score, breakdown = ensemble.combine(
            local_signals, self._weights(url_present=local_signals.get("url") is not None))
        thresholds = self._thresholds()
        merged.risk_score = int(round(score * 100))
        merged.verdict = Verdict(_verdict_str(ensemble.verdict_for(score, thresholds)))
        merged.confidence = ensemble.confidence_for(score, local_signals, thresholds)
        merged.evidence.llm_score = trace.llm_score
        merged.evidence.ensemble_breakdown = ensemble.explain_breakdown(local_signals, breakdown, score)
        if trace.llm_verdict and trace.llm_verdict != merged.verdict.value:
            merged.evidence.ensemble_breakdown["model_disagreement"] = (
                f"AI judgement was {trace.llm_verdict}; the calibrated ensemble (which includes it) returned {merged.verdict.value}"
            )
        merged.evidence.llm_red_flags = [f.model_dump() for f in (merged.red_flags or [])][:8]
        return merged

    # ------------------------------------------------------------------ checks
    def _actionability(self, text: str, urls: list[str], pii_entities) -> dict:
        """Does the message actually ask the reader to do something?

        Fraud is an *ask*: money, a code, a click, an install, a callback or a reply.
        A message with none of those and no link/contact cannot be executed against the
        user, so its risk is capped (see Settings.non_actionable_risk_cap). This is
        reported in evidence.actionability so the reasoning stays visible.
        """
        lowered = text.lower()
        ask_hits: list[str] = []
        for rx in _REQUEST_RES:
            for match in rx.finditer(text):
                # Look both ways: "call the number printed on your card" only reads as
                # self-service advice once you see the words AFTER the request.
                start = max(0, match.start() - 40)
                end = min(len(lowered), match.end() + 60)
                context = lowered[start:end].lower()
                # defensive advice ("never share your OTP") is not a request
                if any(cue in context for cue in _NEGATION_CUES):
                    continue
                if any(cue in context for cue in SELF_SERVE_CUES):
                    continue
                ask_hits.append(match.group(0).strip())
        ask_hits = sorted(set(ask_hits))[:8]
        has_link = bool(urls)
        has_contact = any(e.kind in ("phone", "email") for e in pii_entities)
        # A request only counts as an *actionable* ask when the message gives the reader
        # somewhere to act (a link, a contact, or an explicit instruction to send/pay).
        actionable = has_link or has_contact or bool(ask_hits)
        return {
            "actionable": actionable,
            "ask_keywords": ask_hits[:8],
            "has_link": has_link,
            "has_contact": has_contact,
            "cap_applied": False,
            "explanation": (
                "A scam must request money, a code, a click, an install or a callback. "
                "None of those appear in this message, so its risk is capped."
                if not actionable else
                "The message does make a request, so the full ensemble score applies."
            ),
        }

    # ------------------------------------------------------------------ pieces
    def _weights(self, url_present: bool = False) -> dict[str, float]:
        """Tuned weights, with a floor on the URL signal when a link is actually present.

        Why: the weights are tuned on a text corpus in which almost no row contains a
        URL, so the tuned URL weight is ~0. Ignoring a submitted link would be wrong —
        a brand-look-alike domain is the single strongest piece of evidence in MFS
        phishing — so a present link gets ``URL_SIGNAL_FLOOR``.
        """
        metrics = self.ml.metadata().get("validation", {}) if self.ml.ready else {}
        tuned = dict((metrics or {}).get("ensemble_weights") or ensemble.DEFAULT_WEIGHTS)
        if url_present:
            tuned["url"] = max(float(tuned.get("url", 0.0)), float(self.settings.url_signal_floor))
        return tuned

    def _thresholds(self) -> dict[str, float]:
        metrics = self.ml.metadata().get("validation", {}) if self.ml.ready else {}
        tuned = (metrics or {}).get("ensemble_thresholds")
        return tuned or ensemble.DEFAULT_THRESHOLDS

    def _red_flags(self, text: str, matches, ml_pred, url_results: list[dict]) -> list[RedFlag]:
        flags: list[RedFlag] = []
        for span in highlight_spans(text, matches):
            pattern = get_pattern(span["pattern_id"]) or {}
            flags.append(RedFlag(
                text_span=span["text"][:200],
                reason=f"Known red flag for '{pattern.get('name', {}).get('en', span['pattern_id'])}'"
                       + (f" - {pattern.get('red_flag_hints', [''])[0]}" if pattern.get("red_flag_hints") else ""),
                severity=round(min(1.0, span["weight"]), 3),
            ))
        for token in ml_pred.top_tokens[:5]:
            if "text" not in token:
                continue
            flags.append(RedFlag(
                text_span=token["text"][:200],
                reason=f"The scam-detection model gives this phrase a high weight ({token['contribution']:.2f})",
                severity=round(min(0.9, 0.3 + token["contribution"] * 0.6), 3),
            ))
        for r in url_results:
            for finding in r["findings"][:3]:
                for suspicious in [r["url"]]:
                    flags.append(RedFlag(
                        text_span=suspicious[:200],
                        reason=f"{finding['detail']} (link risk {r['score']:.2f})",
                        severity=round(float(finding.get("severity", 0.5)), 3),
                    ))
        # dedupe by normalised span text
        seen, out = set(), []
        for f in sorted(flags, key=lambda x: x.severity, reverse=True):
            key = f.text_span.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(f)
        return out[:8]

    def _explanation(self, verdict: str, lang: str, top, ml_pred, url_score, score: float,
                     confidence: float) -> str:
        # Each fragment is a sentence and they are joined with the language's terminator
        # (Bangla and Hindi use "।", not "."). Without this the opener ran straight into the
        # next clause ("...signs of a scam This looks like:") or produced a stray "।.".
        terminator = i18n.SENTENCE_END.get(lang, ".")
        parts = [i18n.text(i18n.OPENERS, lang, verdict)]
        if top:
            name = top.name.get(lang) or top.name.get("en")
            parts.append(i18n.fmt(i18n.pick(i18n.PATTERN_SENTENCE, lang), pattern=name))
            # The curated, human-written explanation of this pattern in the user's
            # own language — better than anything we can template mechanically.
            summary = top.summary.get(lang) or top.summary.get("en")
            if summary and verdict != "SAFE":
                parts.append(summary)
        if url_score is not None and url_score >= 0.5:
            template = i18n.pick(i18n.URL_SENTENCE, lang)
            parts.append(i18n.fmt(template, score=f"{url_score * 100:.0f}"))
        if ml_pred.score is not None:
            parts.append(i18n.fmt(i18n.pick(i18n.ML_SENTENCE, lang), score=f"{ml_pred.score * 100:.0f}"))
        cleaned = [p.strip().rstrip(".\u0964\u06d4") for p in parts if p and p.strip()]
        return f"{terminator} ".join(cleaned) + terminator

    def _actions(self, verdict: str, lang: str, top, url_score) -> list[str]:
        actions = list(i18n.pick(i18n.BASE_ACTIONS, lang, verdict) or [])
        if top:
            category_action = i18n.pick(i18n.CATEGORY_ACTION, lang, top.category)
            if category_action:
                actions.insert(2, category_action)
        if url_score is not None and url_score >= 0.5:
            actions.insert(1, i18n.pick(i18n.CATEGORY_ACTION, lang, "phishing"))
        if verdict != "SAFE" and top:
            actions.append(i18n.pick(i18n.REPORT_PREFIX, lang) + top.safe_response)
        # de-dup while keeping order
        seen, out = set(), []
        for a in actions:
            if a and a not in seen:
                seen.add(a)
                out.append(a)
        return out[:7]

    def _report_template(self, lang: str, verdict: str, top, text: str, pii) -> str:
        type_name = (top.name.get("en") if top else "suspicious message")
        excerpt = _truncate(pii.redacted_text, 400)
        if lang == "bn":
            body = (
                "বিষয়: প্রতারণার অভিযোগ ও সহায়তার অনুরোধ\n\n"
                "জনাব,\nআমি একটি প্রতারণার চেষ্টার শিকার হয়েছি। নিচে বিস্তারিত দিচ্ছি।\n\n"
                f"১. প্রতারণার ধরন: {type_name}\n"
                f"২. যে মেসেজটি পেয়েছি: \"{excerpt}\"\n"
                "৩. আমি কোনো টাকা পাঠাইনি / পাঠিয়েছি (যেটি হয় লিখুন)।\n"
                "৪. অনুরোধ: অভিযুক্ত নাম্বার/অ্যাকাউন্টটি ব্লক করুন এবং আমার অভিযোগটি রেজিস্টার করুন।\n"
                "৫. প্রেরকের নাম্বার: [PHONE_1] (যদি থাকে)\n"
                "৬. তারিখ ও সময়: [DATE]\n\n"
                "ধন্যবাদ,\n[YOUR NAME]\n[YOUR PHONE]"
            )
        elif lang == "hi":
            body = (
                "विषय: धोखाधड़ी की शिकायत और सहायता का अनुरोध\n\n"
                "महोदय,\nमुझे धोखाधड़ी के प्रयास का सामना करना पड़ा। विवरण नीचे है।\n\n"
                f"1. ठगी का प्रकार: {type_name}\n"
                f"2. मिला संदेश: \"{excerpt}\"\n"
                "3. मैंने कोई पैसा नहीं भेजा / भेज दिया (जो सही हो लिखें)।\n"
                "4. अनुरोध: संबंधित नंबर/अकाउंट ब्लॉक करें और मेरी शिकायत दर्ज करें।\n"
                "5. भेजने वाले का नंबर: [PHONE_1]\n6. दिनांक: [DATE]\n\n"
                "धन्यवाद,\n[YOUR NAME]\n[YOUR PHONE]"
            )
        elif lang == "ur":
            body = (
                "موضوع: فراڈ کی شکایت اور مدد کی درخواست\n\n"
                "محترم،\nمجھے فراڈ کی کوشش کا سامنا ہوا۔ تفصیل درج ہے۔\n\n"
                f"1. فراڈ کی قسم: {type_name}\n"
                f"2. موصول پیغام: \"{excerpt}\"\n"
                "3. میں نے کوئی رقم نہیں بھیجی / بھیج دی (جو درست ہو لکھیں)۔\n"
                "4. درخواست: متعلقہ نمبر/اکاؤنٹ بلاک کریں اور میری شکایت درج کریں۔\n"
                "5. بھیجنے والے کا نمبر: [PHONE_1]\n6. تاریخ: [DATE]\n\n"
                "شکریہ،\n[YOUR NAME]\n[YOUR PHONE]"
            )
        else:
            body = (
                "Subject: Complaint about a fraud attempt and request for help\n\n"
                "Dear Sir/Madam,\nI have received a fraudulent message. Details below.\n\n"
                f"1. Type of fraud: {type_name}\n"
                f"2. Message received: \"{excerpt}\"\n"
                "3. I have NOT sent any money / I already sent money (keep the true one).\n"
                "4. Request: please block the reported number/account and register my complaint.\n"
                "5. Sender's number: [PHONE_1]\n6. Date and time: [DATE]\n\n"
                "Thank you,\n[YOUR NAME]\n[YOUR PHONE]"
            )
        return body

    def _family_alert_template(self, lang: str, text: str, verdict: str) -> str:
        return i18n.fmt(i18n.pick(i18n.FAMILY_ALERT, lang), preview=_truncate(text, 90))

    def _offline_lesson(self, top, lang: str) -> MicroLesson | None:
        if top is None:
            return None
        labels = {k: i18n.text(i18n.LESSON_LABELS, lang, k) for k in ("title", "flags", "tip", "quiz")}
        name = top.name.get(lang) or top.name.get("en", top.pattern_id)
        summary = top.summary.get(lang) or top.summary.get("en", "")

        quiz_templates = {
            "en": [
                {"question": "What should you never share, even with someone claiming to be from a bank?",
                 "options": ["OTP or PIN", "Your city name", "Today's date"], "answer_index": 0,
                 "explanation": "Banks and mobile-money services never ask for OTP or PIN."},
                {"question": "You are promised a prize but asked to pay a small fee first. What is it?",
                 "options": ["A normal process", "A scam", "A discount"], "answer_index": 1,
                 "explanation": "Real prizes never require a payment."},
                {"question": "A link in the message is short and you cannot see the real address. What is safest?",
                 "options": ["Tap it quickly", "Ask the sender for the PIN too", "Open the official app instead"],
                 "answer_index": 2, "explanation": "Never trust the link — use the official app or typed address."},
            ],
            "bn": [
                {"question": "ব্যাংক থেকে বললেও কখনো কাউকে কী দেবেন না?",
                 "options": ["ওটিপি বা পিন", "আপনার এলাকার নাম", "আজকের তারিখ"], "answer_index": 0,
                 "explanation": "ব্যাংক বা মোবাইল ব্যাংকিং কখনো ওটিপি-পিন চায় না।"},
                {"question": "পুরস্কার পেতে আগে ছোট ফি দিতে বললে সেটা কী?",
                 "options": ["স্বাভাবিক প্রক্রিয়া", "প্রতারণা", "ছাড়"], "answer_index": 1,
                 "explanation": "আসল পুরস্কারে টাকা দিতে হয় না।"},
                {"question": "মেসেজের ছোট লিংকে আসল ঠিকানা বোঝা যাচ্ছে না। নিরাপদ কী?",
                 "options": ["দ্রুত চাপ দিন", "প্রেরকের কাছে পিন চান", "নিজে অফিশিয়াল অ্যাপ খুলুন"],
                 "answer_index": 2, "explanation": "লিংক বাদ দিন — অফিশিয়াল অ্যাপ ব্যবহার করুন।"},
            ],
            "hi": [
                {"question": "बैंक से कहने पर भी किसी को क्या नहीं देना चाहिए?",
                 "options": ["ओटीपी या पिन", "अपने शहर का नाम", "आज की तारीख"], "answer_index": 0,
                 "explanation": "बैंक कभी ओटीपी-पिन नहीं मांगता।"},
                {"question": "इनाम के लिए पहले छोटी फीस मांगी जाए तो वह क्या है?",
                 "options": ["सामान्य प्रक्रिया", "धोखा", "छूट"], "answer_index": 1,
                 "explanation": "असली इनाम में पैसा नहीं देना पड़ता।"},
                {"question": "संदेश का छोटा लिंक असली पता नहीं दिखाता। क्या सुरक्षित है?",
                 "options": ["जल्दी टैप करें", "भेजने वाले से पिन मांगें", "खुद ऑफिशियल ऐप खोलें"],
                 "answer_index": 2, "explanation": "लिंक छोड़ें — ऑफिशियल ऐप इस्तेमाल करें।"},
            ],
            "ur": [
                {"question": "بینک کہنے پر بھی کسی کو کیا نہیں دینا چاہیے؟",
                 "options": ["او ٹی پی یا پن", "اپنے شہر کا نام", "آج کی تاریخ"], "answer_index": 0,
                 "explanation": "بینک کبھی او ٹی پی یا پن نہیں مانگتا۔"},
                {"question": "انعام کے لیے پہلے چھوٹی فیس مانگی جائے تو یہ کیا ہے؟",
                 "options": ["عام طریقہ", "فراڈ", "رعایت"], "answer_index": 1,
                 "explanation": "اصل انعام میں پیسے نہیں دینے پڑتے۔"},
                {"question": "پیغام کا چھوٹا لنک اصل پتہ نہیں دکھاتا۔ محفوظ کیا ہے؟",
                 "options": ["فوراً کھول لیں", "بھیجنے والے سے پن مانگیں", "خود آفیشل ایپ کھولیں"],
                 "answer_index": 2, "explanation": "لنک چھوڑیں — آفیشل ایپ استعمال کریں。"},
            ],
        }
        body = "\n".join([
            f"{name}",
            summary,
            "",
            f"{labels.get('flags', 'Red flags')}: " + "; ".join(top.red_flag_hints[:3]),
            f"{labels.get('tip', 'Golden rule')}: " + top.safe_response,
            "",
            i18n.pick(i18n.LOCKED_PATTERNS_NOTE, lang),
        ])
        return MicroLesson(
            title=f"{labels.get('title', '60-second lesson')}: {name}"[:200],
            pattern_id=top.pattern_id,
            language=lang if lang in i18n.SUPPORTED else "en",  # type: ignore[arg-type]
            level="basic",
            seconds=60,
            body=body,
            key_takeaways=(top.red_flag_hints[:3] or [top.safe_response])[:6],
            quiz=[{**q, "explanation": q.get("explanation", "")} for q in quiz_templates.get(lang, quiz_templates["en"])],
        )
