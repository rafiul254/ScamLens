#!/usr/bin/env python3
"""Live smoke test for a running ScamLens instance.

Checks the real HTTP surface end to end — the same calls the PWA makes — and prints a
PASS/FAIL table. Run it against a local or deployed backend:

    python3 scripts/smoke_test.py                        # http://localhost:8000
    python3 scripts/smoke_test.py https://your.app       # a deployment

Exit code is 0 only when everything passes, so it doubles as a post-deploy check.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
results: list[tuple[str, bool, str]] = []


def call(method: str, path: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode()
            return res.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200]}


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, bool(condition), detail))


def device() -> str:
    """A fresh anonymous device id keeps the rate limiter out of the way."""
    return uuid.uuid4().hex


def main() -> int:
    print(f"ScamLens smoke test → {BASE}\n")

    # ---- meta ----
    status, health = call("GET", "/api/health")
    check("GET /api/health", status == 200 and health.get("status") == "ok", f"{status} {health.get('status')}")

    status, samples = call("GET", "/api/samples")
    n_samples = len(samples.get("samples", []))
    check("GET /api/samples", status == 200 and n_samples >= 8, f"{n_samples} samples")

    status, bench = call("GET", "/api/benchmark")
    shipped = (bench.get("shipped_pipeline") or {}).get("results", {}).get("ensemble_override", {})
    check(
        "GET /api/benchmark",
        status == 200 and bench.get("available") and shipped.get("f1"),
        f"ML-only F1 {(bench.get('models') or {}).get('ml_only', {}).get('f1')}, "
        f"shipped F1 {shipped.get('f1')}",
    )

    # ---- text analysis ----
    cases = [
        ("Bangla bKash OTP scam", "bn", "SCAM",
         "প্রিয় গ্রাহক, আপনার বিকাশ একাউন্ট সাময়িকভাবে বন্ধ করা হয়েছে। "
         "চালু রাখতে এই ওটিপি 445566 সহায়ক কর্মকর্তাকে জানান।"),
        ("Urdu prize scam", "ur", "SCAM",
         "مبارک ہو! آپ نے 5 لاکھ روپے کا انعام جیتا ہے۔ فیس 500 روپے بھیجیں 03001234567 پر۔"),
        ("Hindi police threat", "hi", "SCAM",
         "आपके नाम पर केस दर्ज है। जुर्माना 10,000 रुपये इस नंबर पर भेजें वरना गिरफ्तारी होगी।"),
        # Romanised Bangla ("kaj korun", "bKash korun") is deliberately mapped to the Bangla
        # path — the pattern library carries romanised keywords for exactly this traffic.
        ("Romanised job-fee scam", "bn", "SCAM",
         "Ghore boshe mobile diye kaj korun, mashe 30,000 taka income. Registration fee 500 taka "
         "bKash korun 01799887766 number e."),
        ("English bank alert (benign)", "en", "SAFE",
         "Your account 4210 was debited 1,250 BDT on 14 Oct at 18:42 to a merchant payment. "
         "If this was not you, call the number printed on your card. Staff will never ask for your PIN."),
    ]
    for name, lang, expected, text in cases:
        status, body = call("POST", "/api/analyze/text", {"device_id": device(), "text": text})
        ok = status == 200 and body.get("verdict") == expected and body.get("language") == lang
        check(f"analyze/text · {name}", ok,
              f"{body.get('verdict')} {body.get('risk_score')}/100 · {body.get('language')} · "
              f"{body.get('scam_type')}")

    # ---- PII protection ----
    status, body = call("POST", "/api/analyze/text", {
        "device_id": device(),
        "text": "আমার পিন দিন 01712345678 নাম্বারে এবং এই ওটিপি 445566 পাঠান",
    })
    kinds = [p["kind"] for p in body.get("evidence", {}).get("pii_found", [])]
    check("PII redaction (phone + otp)", status == 200 and "phone" in kinds and "otp" in kinds,
          f"{kinds}")

    # ---- URL analysis ----
    url_cases = [
        ("phishing URL", "http://bkash-verify-login.tk/account", lambda b: b["verdict"] == "SCAM"),
        ("official domain", "https://www.bkash.com/terms", lambda b: b["verdict"] == "SAFE"),
    ]
    for name, url, predicate in url_cases:
        status, body = call("POST", "/api/analyze/url", {"device_id": device(), "url": url})
        check(f"analyze/url · {name}", status == 200 and predicate(body),
              f"{body.get('verdict')} {body.get('risk_score')}/100 · {len(body.get('evidence', {}) or {})} evidence blocks")

    # ---- learn + history ----
    status, patterns = call("GET", "/api/learn/patterns")
    check("GET /api/learn/patterns", status == 200 and len(patterns.get("patterns", [])) >= 20,
          f"{len(patterns.get('patterns', []))} patterns")

    dev = device()
    call("POST", "/api/analyze/text", {"device_id": dev, "text": "Congratulations! You won a 50,000 prize. Pay 500 fee to claim."})
    status, history = call("GET", f"/api/history?device_id={dev}")
    check("history records the scan then deletes it",
          status == 200 and history.get("total", 0) >= 1
          and call("DELETE", f"/api/data?device_id={dev}")[0] == 200
          and call("GET", f"/api/history?device_id={dev}")[1].get("total") == 0,
          f"total {history.get('total')} → 0 after delete")

    status, stats = call("GET", f"/api/stats?device_id={device()}")
    check("GET /api/stats (community stats)", status == 200, str(stats)[:60])

    # ---- graceful behaviour without an API key ----
    status, body = call("POST", "/api/analyze/image", {"device_id": device(), "image_base64": "aGVsbG8="})
    check("image endpoint degrades gracefully without a key",
          status in (200, 503) and body.get("detail", {}).get("error") in ("vision_unavailable", None)
          or status == 422,
          f"{status} {str(body)[:70]}")

    # ---- limits ----
    status, body = call("POST", "/api/analyze/text", {"device_id": device(), "text": "x" * 9000})
    check("oversized input rejected", status in (413, 422), f"{status}")

    burst_dev = device()
    # Fire concurrently: with the LLM agent loop each request can take >5 s, and
    # sequential calls would never land inside the limiter's 5-second burst window.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(
            lambda _: call("POST", "/api/analyze/text", {"device_id": burst_dev, "text": "hello"})[0],
            range(12),
        ))
    check("rate limiter returns 429 on burst", 429 in statuses, f"{statuses.count(200)}×200, {statuses.count(429)}×429")

    # ---- report ----
    width = max(len(name) for name, _, _ in results) + 2
    print(f"{'CHECK'.ljust(width)}{'RESULT':8}DETAIL")
    for name, ok, detail in results:
        print(f"{name.ljust(width)}{'PASS' if ok else 'FAIL':8}{detail}")
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
