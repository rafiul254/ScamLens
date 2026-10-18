# ScamLens API reference

Base URL: `http://localhost:8000` (dev) — interactive docs at `/docs`.

All analysing endpoints are rate limited (30/min, burst 8, keyed by IP + device id) and
size limited (text ≤ 6,000 chars, image ≤ 5 MB, URL ≤ 2,048 chars). Errors are JSON:
`{"error": "...", "message": "..."}`.

## `GET /api/health`

```json
{
  "status": "ok",
  "version": "1.0.0",
  "llm_enabled": true,
  "llm_model": "gemini-3.8-flash",
  "agent_max_steps": 6,
  "text_model": { "available": true, "backend": "ml_tfidf", "version": "text-ml_tfidf-20261016" },
  "url_model": "trained",
  "url_probe_enabled": true,
  "limits": { "max_text_chars": 6000, "max_image_bytes": 5242880, "rate_limit_per_minute": 30 }
}
```

## `POST /api/analyze/text`

```json
{
  "text": "প্রিয় গ্রাহক, আপনার বিকাশ একাউন্ট বন্ধ হবে। ওটিপি ও পিন দিন 01712345678 নাম্বারে।",
  "kind": "text",
  "device_id": "a1b2c3d4e5f6a7b8",
  "language": null,
  "make_lesson": true,
  "make_report": true,
  "make_family_alert": true
}
```

`language: null` ⇒ auto-detect (script-based, with romanised-Banglish/Hinglish fallback).
Response: the full `AgentResult` contract (see README). Key fields:

| Field | Meaning |
|---|---|
| `verdict` | `SAFE` · `SUSPICIOUS` · `SCAM` — from the calibrated ensemble, not the LLM alone |
| `risk_score` | 0–100, the ensemble score |
| `confidence` | 0–1, blends decision margin with agreement between signals (capped at 0.96) |
| `language` | detected language of the submission |
| `scam_type` | pattern id (`fake_otp_mfs`, `prize_lottery`, `phishing_link`, …) or `legitimate` |
| `red_flags[]` | spans **from the user's own message** with a plain reason and severity |
| `explanation` | 6th-grade-level prose in the user's language |
| `recommended_actions[]` | ordered, concrete steps |
| `report_draft` | complaint text with the user's own PII restored; typed-text PII is masked before Gemini, but screenshot images are sent as uploaded |
| `family_alert` | short forwardable warning |
| `lesson` | 60-second lesson + 3-question quiz |
| `evidence` | every input to the decision, including the agent trace |
| `pii_redacted` | whether PII was found and removed |
| `mode` | `agent` (Gemini function-calling loop) or `local_fallback` (deterministic, with `degraded_reason`) |

## `POST /api/analyze/url`

```json
{ "url": "http://bkash-verify-login.tk/account", "device_id": "a1b2c3d4e5f6a7b8" }
```

`evidence.url_score` and `evidence.url_findings` carry the lexical findings:
brand impersonation, suspicious TLD, deep subdomain, `@` in host, punycode, sensitive
path tokens, dangerous extension, shortener, free host, plus any redirect-probe flags.
The page is never fetched, parsed or rendered.

## `POST /api/analyze/image`

`multipart/form-data`: `file` (PNG/JPEG/WEBP/GIF, ≤ 5 MB), `device_id`, optional `text`.

`503 vision_unavailable` is returned when no `GEMINI_API_KEY` is configured — with a message
telling the user to paste the text instead. Screenshots are sent to Gemini as uploaded for
vision analysis; crop or blur personal details first. The Gemini free tier may use submitted
content under Google's current data-use terms.

## `POST /api/analyze/audio`

Same body as `/text` with `kind: "audio_transcript"`. The transcript is produced on the
device by the Web Speech API and never leaves it except as this request.

## `POST /api/redact`

```json
{ "text": "call 01712345678, OTP 445566" }
→ { "redacted_text": "call [PHONE_1], OTP [OTP_1]", "entities": [{ "kind": "phone", "placeholder": "[PHONE_1]", "masked_preview": "01********78", "length": 11 }], "count": 2 }
```

## Learn endpoints

* `GET /api/learn/patterns` → all 22 patterns with 4-language names/summaries.
* `GET /api/learn/patterns/{id}` → one pattern including keyword lists.
* `GET /api/learn/lesson?pattern_id=fake_otp_mfs&language=bn&level=basic` → `MicroLesson`
  (written by Gemini when available, otherwise assembled from the curated library).
* `POST /api/learn/quiz` → updates Scam IQ, streak and badges.
* `GET /api/learn/scamiq?device_id=…` → score, level, streak, badges.

## Meta endpoints

* `GET /api/benchmark` → the real contents of `ml/artifacts/metrics.json`, or
  `{"available": false, "notes": "…run make train…"}`.
* `GET /api/samples` → the 12 Demo Mode samples (two of them legitimate control cases).
* `GET /api/history?device_id=…` → local scan history (this device only).
* `GET /api/stats?device_id=…` → anonymised, device-local counters.
* `DELETE /api/data?device_id=…` → deletes every row for that device.

## Status codes

| Code | When |
|---|---|
| 422 | validation error (blank/oversized text, bad device id) |
| 413 | payload too large (text or image) |
| 415 | unsupported image type |
| 429 | rate limited (`error: rate_limited` / `too_fast`) |
| 503 | `vision_unavailable` — screenshot submitted without a vision model configured |
| 500 | unexpected server error (message text is never logged) |

## cURL examples

```bash
# Bangla bKash scam
curl -s http://localhost:8000/api/analyze/text -H 'Content-Type: application/json' -d '{
  "device_id":"demo123456789", "text":"অভিনন্দন! আপনি ৫ লাখ টাকার লটারি জিতেছেন, ৫০০ টাকা ফি বিকাশ করুন 01712345678"
}' | python3 -m json.tool | head -30

# Look-alike link
curl -s http://localhost:8000/api/analyze/url -H 'Content-Type: application/json' \
  -d '{"device_id":"demo123456789","url":"http://bkash-verify-login.tk/account"}'

# Screenshot
curl -s http://localhost:8000/api/analyze/image -F file=@screenshot.png -F device_id=demo123456789

# Delete everything for this device
curl -s -X DELETE "http://localhost:8000/api/data?device_id=demo123456789"
```
