"""Pattern library, ensemble maths and end-to-end API behaviour."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.ensemble import combine, confidence_for, verdict_for
from app.services.patterns import get_pattern, highlight_spans, list_patterns, match_patterns, pattern_score

DEVICE = "testdevice123456"


class TestPatternLibrary:
    def test_at_least_fifteen_patterns_are_documented(self):
        patterns = list_patterns()
        assert len(patterns) >= 15
        assert len({p["id"] for p in patterns}) == len(patterns)

    def test_every_pattern_has_four_language_names_and_a_safe_response(self):
        for pattern in list_patterns():
            for lang in ("en", "bn", "hi", "ur"):
                assert pattern["name"].get(lang), f"{pattern['id']} missing {lang}"
                assert pattern["summary"].get(lang), f"{pattern['id']} missing {lang} summary"
            assert pattern["safe_response"]
            assert pattern["red_flag_hints"]

    def test_bangla_otp_scam_matches_the_right_pattern(self):
        text = "প্রিয় গ্রাহক, আপনার বিকাশ একাউন্ট বন্ধ হবে, ওটিপি ও পিন দিন এই নাম্বারে"
        matches = match_patterns(text, language="bn")
        assert matches
        assert matches[0].pattern_id == "fake_otp_mfs"
        assert matches[0].score > 0.4

    def test_hindi_police_threat_matches_authority_pattern(self):
        text = "मैं साइबर सेल से बोल रहा हूँ, आपके नाम पर FIR है, जुर्माना भरो वरना गिरफ्तारी होगी"
        matches = match_patterns(text, language="hi")
        assert matches[0].pattern_id == "fake_authority"

    def test_urdu_lottery_matches_prize_pattern(self):
        text = "مبارک ہو! آپ نے 10 لاکھ کا انعام جیتا ہے، فیس بھیجیں"
        matches = match_patterns(text, language="ur")
        assert matches[0].pattern_id == "prize_lottery"

    def test_ordinary_message_matches_nothing_strong(self):
        matches = match_patterns("Bhai kal office e dekha hobe, 5 tay. Report ta niye asho.", language="bn")
        assert pattern_score(matches) < 0.4

    def test_highlight_spans_point_into_the_original_text(self):
        text = "Your OTP is needed and the account will be blocked today"
        spans = highlight_spans(text, match_patterns(text))
        assert spans
        for span in spans:
            assert text[span["start"]:span["end"]].lower() == span["text"].lower()

    def test_shortener_tokens_are_not_treated_as_phishing_keywords_alone(self):
        matches = match_patterns("Please share the meeting link tomorrow", language="en")
        assert all(m.pattern_id != "phishing_link" for m in matches)

    def test_every_pattern_id_is_retrievable(self):
        for pattern in list_patterns():
            assert get_pattern(pattern["id"]) is not None


class TestEnsembleMaths:
    def test_missing_signals_are_renormalised_not_zeroed(self):
        score, weights = combine({"ml": 0.9, "url": None, "pattern": None, "llm": None})
        assert score == pytest.approx(0.9)
        assert weights == {"ml": 1.0}

    def test_all_signals_included_when_present(self):
        score, weights = combine({"ml": 0.8, "url": 0.6, "pattern": 0.4, "llm": 0.2})
        assert 0.4 < score < 0.8
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_score_is_bounded(self):
        score, _ = combine({"ml": 1.0, "url": 1.0, "pattern": 1.0, "llm": 1.0})
        assert score <= 1.0

    def test_no_signals_returns_zero(self):
        assert combine({"ml": None})[0] == 0.0

    def test_verdict_thresholds(self):
        assert verdict_for(0.1) == "SAFE"
        assert verdict_for(0.45) == "SUSPICIOUS"
        assert verdict_for(0.9) == "SCAM"

    def test_confidence_drops_when_signals_disagree(self):
        agree = confidence_for(0.8, {"ml": 0.82, "url": 0.78, "pattern": 0.8})
        disagree = confidence_for(0.8, {"ml": 0.99, "url": 0.10, "pattern": 0.05})
        assert disagree < agree
        assert 0.0 < disagree < 1.0


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


class TestApi:
    def test_health_reports_real_model_state(self, client):
        data = client.get("/api/health").json()
        assert data["status"] == "ok"
        assert "text_model" in data
        assert data["limits"]["max_text_chars"] > 0

    def test_bangla_scam_is_detected_and_explained(self, client):
        payload = {
            "device_id": DEVICE,
            "text": "প্রিয় গ্রাহক, আপনার বিকাশ একাউন্ট বন্ধ হয়ে যাবে। এখনই ওটিপি ও পিন দিন 01712345678 নাম্বারে।",
        }
        res = client.post("/api/analyze/text", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] in ("SCAM", "SUSPICIOUS")
        assert body["risk_score"] > 40
        assert body["language"] == "bn"
        assert body["scam_type"] == "fake_otp_mfs"
        assert body["red_flags"], "expected at least one red flag"
        assert body["recommended_actions"]
        assert body["analysis_id"]

    def test_pii_is_redacted_from_the_evidence(self, client):
        payload = {"device_id": DEVICE, "text": "Your OTP is 445566, send it to 01712345678 right now"}
        body = client.post("/api/analyze/text", json=payload).json()
        assert body["pii_redacted"] is True
        joined = " ".join(str(v) for v in body["evidence"].values())
        assert "01712345678" not in joined
        assert "445566" not in joined
        assert any("PHONE" in p["placeholder"] for p in body["evidence"]["pii_found"])

    def test_legitimate_message_is_not_labelled_a_scam(self, client):
        payload = {
            "device_id": DEVICE,
            "text": "Hi, this is Farhana from accounts. The invoice is attached, please review before tomorrow's meeting.",
        }
        body = client.post("/api/analyze/text", json=payload).json()
        assert body["verdict"] in ("SAFE", "SUSPICIOUS"), body["explanation"]
        assert body["risk_score"] < 60

    def test_benign_messages_with_no_ask_are_not_labelled_scams(self, client):
        """A scam must ask for something. These two messages mention money, hospitals and
        OTPs in passing but request nothing, so the actionability cap applies."""
        controls = [
            "মা, আমি হাসপাতালে দাদাকে দেখতে এসেছি। রিপোর্ট ভালো, বিকেলে বাসায় ফিরবো। তুমি খেয়ে নিও।",
            "Your account 4210 was debited 1,250 BDT on 14 Oct at 18:42 to a merchant payment. "
            "If this was not you, call the number printed on your card. Staff will never ask for your PIN or OTP.",
        ]
        for text in controls:
            body = client.post("/api/analyze/text", json={"device_id": DEVICE, "text": text}).json()
            assert body["verdict"] != "SCAM", (text[:40], body["verdict"], body["risk_score"])
            assert body["evidence"]["actionability"]["actionable"] is False

    def test_actionability_cap_does_not_rescue_a_real_scam(self, client):
        body = client.post(
            "/api/analyze/text",
            json={"device_id": DEVICE, "text": "অভিনন্দন! আপনি লটারি জিতেছেন, ৫০০ টাকা ফি বিকাশ করুন 01712345678"},
        ).json()
        assert body["verdict"] == "SCAM"
        assert body["evidence"]["actionability"]["actionable"] is True
        assert body["evidence"]["actionability"]["cap_applied"] is False

    def test_phishing_url_is_flagged_with_findings(self, client):
        body = client.post("/api/analyze/url", json={"device_id": DEVICE, "url": "http://bkash-verify-login.tk/account"}).json()
        assert body["verdict"] in ("SCAM", "SUSPICIOUS")
        assert body["evidence"]["url_score"] >= 0.5
        assert any(f["type"] for f in body["evidence"]["url_findings"])

    def test_link_only_submission_is_not_ignored_by_the_ensemble(self, client):
        """A bare look-alike domain must be reported as a scam: the URL analyser decides
        when the submission is nothing but a link, and the tuned text weights cannot dilute it."""
        body = client.post(
            "/api/analyze/url",
            json={"device_id": DEVICE, "url": "http://nagad-kyc-verify-customer.top/login"},
        ).json()
        assert body["risk_score"] >= 60, body["evidence"]["ensemble_breakdown"]
        assert body["verdict"] == "SCAM"
        breakdown = body["evidence"]["ensemble_breakdown"]
        weights = breakdown.get("effective_weights") or breakdown
        assert weights.get("url", 0) > 0, breakdown

    def test_all_four_languages_round_trip(self, client):
        samples = {
            "bn": "অভিনন্দন! আপনি লটারি জিতেছেন, ৫০০ টাকা ফি দিন।",
            "hi": "बधाई हो! आपने लॉटरी जीती है, 500 रुपये फीस भेजें।",
            "ur": "مبارک ہو! آپ نے لاٹری جیتی ہے، 500 روپے فیس بھیجیں۔",
            "en": "Congratulations! You won the lottery, pay a 500 fee to claim.",
        }
        for expected_lang, text in samples.items():
            body = client.post("/api/analyze/text", json={"device_id": DEVICE, "text": text}).json()
            assert body["language"] == expected_lang, (expected_lang, body["language"])
            assert body["explanation"]

    def test_oversized_input_is_rejected(self, client):
        res = client.post("/api/analyze/text", json={"device_id": DEVICE, "text": "x" * 6001})
        assert res.status_code in (413, 422)

    def test_blank_input_is_rejected(self, client):
        assert client.post("/api/analyze/text", json={"device_id": DEVICE, "text": "   "}).status_code == 422

    def test_redact_endpoint_matches_the_pipeline(self, client):
        body = client.post("/api/redact", json={"text": "call 01712345678 or mail a@b.com"}).json()
        assert body["count"] == 2
        assert "[PHONE_1]" in body["redacted_text"]

    def test_history_and_stats_are_device_scoped(self, client):
        history = client.get(f"/api/history?device_id={DEVICE}").json()
        assert history["total"] > 0
        other = client.get("/api/history?device_id=someotherdevice99").json()
        assert other["total"] == 0

    def test_delete_removes_every_row_for_the_device(self, client):
        client.post("/api/analyze/text", json={"device_id": "deleteme1234567", "text": "You won a prize, pay 500 fee"})
        assert client.get("/api/history?device_id=deleteme1234567").json()["total"] == 1
        client.delete("/api/data?device_id=deleteme1234567")
        assert client.get("/api/history?device_id=deleteme1234567").json()["total"] == 0

    def test_lesson_and_quiz_progress(self, client):
        lesson = client.get("/api/learn/lesson?pattern_id=fake_otp_mfs&language=bn").json()
        assert lesson["pattern_id"] == "fake_otp_mfs"
        assert len(lesson["quiz"]) >= 3
        iq = client.post(
            "/api/learn/quiz",
            json={"device_id": "quizdevice123456", "pattern_id": "fake_otp_mfs", "correct": 3, "total": 3},
        ).json()
        assert iq["score"] > 0
        assert any(b["id"] == "perfect_quiz" for b in iq["badges"])

    def test_benchmark_endpoint_reports_measured_metrics(self, client):
        body = client.get("/api/benchmark").json()
        assert body["available"] is True
        assert body["models"]["ml_only"]["f1"] > 0.8
        assert body["models"]["ensemble"]["confusion_matrix"]
        assert body["limitations"]

    def test_samples_endpoint_returns_demo_cases(self, client):
        body = client.get("/api/samples").json()
        assert len(body["samples"]) >= 8
        assert any(s["expected"] == "SAFE" for s in body["samples"])

    def test_security_headers_are_present(self, client):
        res = client.get("/api/health")
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "DENY"

    def test_bare_link_is_answered_in_english_by_default(self, client):
        """A URL carries no prose to detect a language from; romanised tokens inside it used
        to tip detection to Bangla, so a bare link came back with a Bangla verdict."""
        body = client.post(
            "/api/analyze/url",
            json={"device_id": DEVICE, "url": "http://bkash-verify-login.tk/account"},
        ).json()
        assert body["language"] == "en", body["language"]
        assert body["verdict"] == "SCAM"

    def test_bare_link_can_be_answered_in_a_requested_language(self, client):
        body = client.post(
            "/api/analyze/url",
            json={"device_id": DEVICE, "url": "http://bkash-verify-login.tk/account",
                  "language": "bn"},
        ).json()
        assert body["language"] == "bn", body["language"]

    def test_romanised_bangla_is_routed_to_the_bangla_patterns(self, client):
        """Real traffic mixes scripts: "registration fee 500 taka bKash korun 018...".
        Detection maps it to bn on purpose, and the romanised keywords must catch it."""
        text = ("Ghore boshe mobile diye kaj korun, mashe 30,000 taka income. Kono experience lagbe na, "
                "shudhu registration fee 500 taka bKash korun 01799887766 number e.")
        body = client.post("/api/analyze/text", json={"device_id": DEVICE, "text": text}).json()
        assert body["language"] == "bn"
        assert body["verdict"] == "SCAM", (body["risk_score"], body["scam_type"])
        assert body["scam_type"] == "fake_job", body["scam_type"]

    def test_rate_limiter_fires_after_the_burst_allowance(self, client):
        """The limiter must stay active in production — assert it here so that the
        conftest reset (which only affects the suite) cannot hide a regression."""
        statuses = []
        for _ in range(12):
            res = client.post("/api/analyze/text", json={"device_id": "burstdevice12345", "text": "hello friend"})
            statuses.append(res.status_code)
        assert 429 in statuses, statuses
        assert statuses.count(200) <= 9, statuses

    def test_unknown_pattern_returns_404(self, client):
        assert client.get("/api/learn/patterns/does-not-exist").status_code == 404
