"""PII detection + redaction.

Design (privacy engineering, see README "Ethics & privacy"):

* The browser redacts PII *before* the text is uploaded (frontend/src/lib/pii.ts).
* The server redacts again defensively before any text reaches the LLM. So the
  model never receives a phone number, account number, OTP or email.
* Placeholders are stable and typed (``[PHONE_1]``), which keeps the sentence
  readable for the LLM and lets the API restore the user's *own* values into the
  returned report draft (never sent back to the model).

Detection runs on a digit-normalised copy of the text so Bangla (০-৯),
Devanagari (०-९) and Urdu/Arabic-Indic (۰-۹) numerals are caught too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Digit normalisation
# --------------------------------------------------------------------------- #
_DIGIT_RANGES = [
    (0x0660, 0x0669),  # Arabic-Indic
    (0x06F0, 0x06F9),  # Extended Arabic-Indic (Urdu)
    (0x0966, 0x096F),  # Devanagari
    (0x09E6, 0x09EF),  # Bengali
    (0x0A66, 0x0A6F),  # Gurmukhi
    (0x0BE6, 0x0BEF),  # Tamil
]
_DIGIT_MAP: dict[int, str] = {}
for _start, _end in _DIGIT_RANGES:
    for _i in range(10):
        _DIGIT_MAP[_start + _i] = str(_i)

# Unicode invisibles used to smuggle text past filters.
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)


def normalize_digits(text: str) -> str:
    """Map every supported numeral script to ASCII digits (same length)."""
    return "".join(_DIGIT_MAP.get(ord(ch), ch) for ch in text)


# --------------------------------------------------------------------------- #
# Patterns (run against the normalised text)
# --------------------------------------------------------------------------- #
# South Asia first, then generic international.
_PHONE = re.compile(
    r"(?<![\d])("
    r"\+\s?\d{1,3}[\s.\-]?\d{2,5}[\s.\-]?\d{3,5}(?:[\s.\-]?\d{2,4})?"  # +880 1712 345678
    r"|0\d{2}[\s.\-]?\d{6,8}"          # 01712 345678 style
    r"|0\d{9,10}"                      # 01712345678 (BD) / 09811122233 (IN)
    r"|03\d{2}[\s.\-]?\d{7}"           # 0300-1234567 (PK)
    r")(?![\d])"
)

_EMAIL = re.compile(r"(?<![\w.])([\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{2,63}){1,3})")

# 13-19 digits with optional separators; validated with Luhn below.
_CARD_CANDIDATE = re.compile(r"(?<![\d])((?:\d[ -]?){13,19})(?![\d])")

_ACCOUNT = re.compile(r"(?<![\d])(\d{8,18})(?![\d])")

_OTP_CONTEXT = re.compile(
    r"(?:otp|o\.t\.p|one[\s-]?time[\s-]?(?:password|code|pin)|verification code|"
    r"security code|login code|code is|pin code|একবার|ওটিপি|পিন|কোড|"
    r"ओटीपी|कोड|पिन|او\s?ٹی\s?پی|کوڈ|پن)"
    r"[^0-9]{0,24}(?:is|:|hain|hai|হলো|है|ہے)?[^0-9]{0,8}(\d{4,8})(?![\d])",
    re.IGNORECASE,
)

_NID_CONTEXT = re.compile(
    r"(?:nid|national id|aadhaar|aadhar|আইডি|এনআইডি|आधार|شناختی کارڈ)[^0-9]{0,16}(\d{10,17})(?![\d])",
    re.IGNORECASE,
)

_PWD_HINT = re.compile(
    r"(?:password|passcode|pin|পাসওয়ার্ড|পিন|पासवर्ड|पिन|پاس\s?ورڈ)[\s:=\-—]{0,4}(?:is\s+)?([0-9A-Za-z@#$%!]{4,20})(?![0-9A-Za-z])",
    re.IGNORECASE,
)

_TYPE_LABEL = {
    "phone": "PHONE",
    "email": "EMAIL",
    "otp": "OTP",
    "card": "CARD",
    "account": "ACCOUNT",
    "nid": "NID",
    "password": "PASSWORD",
}


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


@dataclass
class PIIEntity:
    kind: str
    value: str
    start: int
    end: int
    placeholder: str = ""

    def masked(self) -> str:
        v = self.value
        if len(v) <= 4:
            return "*" * len(v)
        return f"{v[:2]}{'*' * (len(v) - 4)}{v[-2:]}"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "placeholder": self.placeholder,
            "masked_preview": self.masked(),
            "length": len(self.value),
        }


@dataclass
class RedactionResult:
    original: str
    redacted_text: str
    entities: list[PIIEntity] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.entities)


def _find(pattern: re.Pattern, norm: str, kind: str, group: int = 1) -> list[PIIEntity]:
    out: list[PIIEntity] = []
    for m in pattern.finditer(norm):
        if m.group(group) is None:
            continue
        start, end = m.span(group)
        out.append(PIIEntity(kind=kind, value=norm[start:end], start=start, end=end))
    return out


def detect_pii(text: str) -> list[PIIEntity]:
    """Find PII spans in ``text`` (positions map back to the original string)."""
    clean = text.translate(_INVISIBLE)
    norm = normalize_digits(clean)
    found: list[PIIEntity] = []

    found += _find(_EMAIL, norm, "email")

    for m in _CARD_CANDIDATE.finditer(norm):
        raw = m.group(1)
        digits = re.sub(r"\D", "", raw)
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            found.append(PIIEntity("card", raw, m.start(1), m.end(1)))

    found += _find(_OTP_CONTEXT, norm, "otp")
    found += _find(_NID_CONTEXT, norm, "nid")
    found += _find(_PWD_HINT, norm, "password")
    found += _find(_PHONE, norm, "phone")

    # Any remaining bare 8-18 digit run is treated as an account / reference no.
    for m in _ACCOUNT.finditer(norm):
        found.append(PIIEntity("account", m.group(1), m.start(1), m.end(1)))

    return _resolve_overlaps(found)


def _resolve_overlaps(entities: list[PIIEntity]) -> list[PIIEntity]:
    """Keep the most specific entity when spans overlap.

    Priority: card > otp > nid > email > password > phone > account.
    """
    priority = {"card": 0, "otp": 1, "nid": 2, "email": 3, "password": 4, "phone": 5, "account": 6}
    ordered = sorted(entities, key=lambda e: (e.start, priority[e.kind], -(e.end - e.start)))
    kept: list[PIIEntity] = []
    last_end = -1
    for ent in ordered:
        if ent.start >= last_end:
            kept.append(ent)
            last_end = ent.end
        else:
            # Overlaps a kept span: replace only if strictly more specific and contained.
            prev = kept[-1]
            if priority[ent.kind] < priority[prev.kind] and ent.end <= prev.end and ent.start >= prev.start:
                kept[-1] = ent
                last_end = max(last_end, ent.end)
    return kept


def redact(text: str, entities: list[PIIEntity] | None = None) -> RedactionResult:
    """Replace every PII span with a typed placeholder."""
    ents = detect_pii(text) if entities is None else entities
    counters: dict[str, int] = {}
    for ent in ents:
        counters[ent.kind] = counters.get(ent.kind, 0) + 1
        ent.placeholder = f"[{_TYPE_LABEL[ent.kind]}_{counters[ent.kind]}]"

    out, cursor = [], 0
    for ent in sorted(ents, key=lambda e: e.start):
        out.append(text[cursor:ent.start])
        out.append(ent.placeholder)
        cursor = ent.end
    out.append(text[cursor:])
    return RedactionResult(original=text, redacted_text="".join(out), entities=ents)


def restore(text: str, entities: list[PIIEntity]) -> str:
    """Put the user's own values back (used only for the returned, user-facing draft).

    The restored text is never sent back to the model.
    """
    for ent in entities:
        if ent.placeholder:
            text = text.replace(ent.placeholder, ent.value)
    return text


def redact_for_model(text: str) -> RedactionResult:
    """Convenience wrapper used by the agent before every LLM call."""
    return redact(text)
