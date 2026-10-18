"""Score the local URL sanity set with the shipped bundle and publish the result.

This is the measurement that matters for users: does ScamLens label a real bank's deep
link as safe, and a look-alike of a mobile-money brand as fraud? The URLs live in
`ml/url_sanity_set.py` and are excluded from the URL training data.

Writes `url_sanity` into ml/artifacts/url_metrics.json so the Benchmark tab can show it.

Usage: python3 ml/eval_url_sanity.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ml"))

import joblib  # noqa: E402

from url_sanity_set import LEGIT, PHISH  # noqa: E402
from app.services.url_analyzer import analyze_url  # noqa: E402


def main() -> int:
    bundle_path = ROOT / "ml" / "artifacts" / "url_risk_model.joblib"
    bundle = joblib.load(bundle_path) if bundle_path.exists() else None
    print(f"model: {bundle.get('version') if bundle else 'rules only'}")

    rows, correct, false_alarms, misses = [], 0, [], []
    for label, items in ((0, LEGIT), (1, PHISH)):
        for url, note in items:
            res = analyze_url(url, model=bundle, probe=False)
            score = res["score"]
            predicted = 1 if score >= 0.5 else 0
            ok = predicted == label
            correct += ok
            if label == 0 and not ok:
                false_alarms.append({"url": url, "score": score, "note": note})
            if label == 1 and not ok:
                misses.append({"url": url, "score": score, "note": note})
            rows.append({
                "url": url, "expected": "legitimate" if label == 0 else "look-alike",
                "score": round(float(score), 4), "rule_score": res["rule_score"],
                "model_score": res["model_score"], "correct": ok, "note": note,
            })
            flag = "ok " if ok else "MISS"
            print(f"  {flag} {score:0.3f}  {url}")

    total = len(rows)
    summary = {
        "n": total,
        "correct": correct,
        "accuracy": round(correct / total, 4),
        "false_alarms_on_official_domains": false_alarms,
        "missed_look_alikes": misses,
        "model_version": bundle.get("version") if bundle else None,
        "note": (
            "Held-out from URL training. PhiUSIIL measures a global URL population; this set "
            "measures the URLs ScamLens users actually meet: official domains of the brands we "
            "defend versus look-alikes of those same brands."
        ),
    }

    path = ROOT / "ml" / "artifacts" / "url_metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    metrics["url_sanity"] = summary
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\naccuracy {correct}/{total} ({summary['accuracy']:.1%}) · "
          f"{len(false_alarms)} false alarm(s) · {len(misses)} missed look-alike(s)")
    print(f"merged url_sanity into {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
