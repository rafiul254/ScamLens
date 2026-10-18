"""PII redaction + strict result-schema tests."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import AgentResult, Evidence, MicroLesson, RedFlag, Verdict
from app.services.pii import detect_pii, redact, restore


class TestPiiDetection:
    def test_bangladeshi_mobile(self):
        ents = detect_pii("Call 01712345678 now")
        assert [e.kind for e in ents] == ["phone"]

    def test_international_formats(self):
        ents = detect_pii("Reach me on +880 1712-345678 or +91 98111 22222")
        assert len(ents) == 2
        assert all(e.kind == "phone" for e in ents)

    def test_pakistani_mobile(self):
        ents = detect_pii("Bhejein 0300-1234567 par")
        assert ents and ents[0].kind == "phone"

    def test_bangla_digits(self):
        ents = detect_pii("আমার নাম্বার ০১৭১১২২৩৩৪৪")
        assert len(ents) == 1
        assert ents[0].kind == "phone"

    def test_devanagari_digits(self):
        ents = detect_pii("ओटीपी है ४८३९२०")
        assert any(e.kind == "otp" for e in ents)

    def test_otp_with_keyword(self):
        ents = detect_pii("Your verification code is 918273")
        assert any(e.kind == "otp" and "918273" in e.value for e in ents)

    def test_email(self):
        assert detect_pii("write to scammer@fraud-corp.co.uk")[0].kind == "email"

    def test_card_number_requires_luhn(self):
        # 4111 1111 1111 1111 is a valid Luhn test number
        kinds = [e.kind for e in detect_pii("card 4111 1111 1111 1111")]
        assert "card" in kinds
        # a random 16-digit run that fails Luhn is still private, but typed as account
        kinds2 = [e.kind for e in detect_pii("ref 1234 5678 9012 3456")]
        assert "card" not in kinds2

    def test_account_number(self):
        assert any(e.kind == "account" for e in detect_pii("account 1234567890123"))

    def test_keyword_does_not_swallow_a_following_phone_number(self):
        """Regression: 'পিন দিন 01712345678' must be a phone, not a password."""
        ents = detect_pii("এখনই ওটিপি ও পিন দিন 01712345678 নাম্বারে")
        assert [e.kind for e in ents] == ["phone"]
        assert ents[0].value.endswith("01712345678") or ents[0].value == "01712345678"
        assert not any(e.kind == "otp" for e in ents)

    def test_password_after_keyword_is_still_caught(self):
        assert detect_pii("your password is Abc12345")[0].kind == "password"

    def test_nid_context(self):
        assert any(e.kind == "nid" for e in detect_pii("Aadhaar 123456789012"))

    def test_clean_text_has_no_entities(self):
        assert detect_pii("Bhai kal office e dekha hobe, 5 tay") == []


class TestRedaction:
    def test_placeholders_are_typed_and_numbered(self):
        res = redact("Send to 01712345678 or 01812345678, email a@b.com")
        assert "[PHONE_1]" in res.redacted_text
        assert "[PHONE_2]" in res.redacted_text
        assert "[EMAIL_1]" in res.redacted_text
        assert "01712345678" not in res.redacted_text
        assert res.count == 3

    def test_round_trip_restore(self):
        original = "Call 01712345678, OTP 445566"
        res = redact(original)
        assert restore(res.redacted_text, res.entities) == original

    def test_masked_preview_hides_middle(self):
        res = redact("01712345678")
        assert res.entities[0].masked().startswith("01")
        assert "*" in res.entities[0].masked()

    def test_original_text_is_preserved(self):
        text = "hello 01712345678"
        assert redact(text).original == text

    def test_urls_are_not_mistaken_for_pii(self):
        res = redact("visit https://bkash-verify.xyz/login")
        assert res.count == 0


class TestAgentResultSchema:
    def _valid(self, **overrides):
        base = dict(
            verdict=Verdict.SCAM,
            risk_score=88,
            confidence=0.9,
            language="bn",
            scam_type="fake_otp_mfs",
            explanation="এটি একটি প্রতারণা।",
            recommended_actions=["Do not share the OTP"],
            red_flags=[RedFlag(text_span="OTP", reason="OTP is never requested", severity=0.9)],
            evidence=Evidence(ml_score=0.93, ensemble_breakdown={"final_score": 0.88}),
        )
        base.update(overrides)
        return base

    def test_valid_payload_passes(self):
        result = AgentResult.model_validate(self._valid())
        assert result.verdict is Verdict.SCAM
        assert result.risk_score == 88

    def test_risk_score_is_bounded(self):
        with pytest.raises(ValidationError):
            AgentResult.model_validate(self._valid(risk_score=101))
        with pytest.raises(ValidationError):
            AgentResult.model_validate(self._valid(risk_score=-1))

    def test_verdict_must_be_known(self):
        with pytest.raises(ValidationError):
            AgentResult.model_validate(self._valid(verdict="MAYBE"))

    def test_confidence_is_bounded(self):
        with pytest.raises(ValidationError):
            AgentResult.model_validate(self._valid(confidence=1.4))

    def test_red_flag_needs_a_span_and_reason(self):
        with pytest.raises(ValidationError):
            AgentResult.model_validate(self._valid(red_flags=[{"text_span": "", "reason": "x"}]))

    def test_quiz_answer_index_must_exist(self):
        with pytest.raises(ValidationError):
            MicroLesson(
                title="t", pattern_id="p", body="b" * 20,
                quiz=[{"question": "why?", "options": ["a", "b"], "answer_index": 5}],
            )

    def test_default_mode_is_agent_and_optional_fields_are_null(self):
        result = AgentResult.model_validate(self._valid())
        assert result.mode == "agent"
        assert result.report_draft is None
        assert result.lesson is None
