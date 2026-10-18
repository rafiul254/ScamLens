#!/usr/bin/env python3
"""Score the LLM-only column of the benchmark — honestly, on the same test split.

The Benchmark page shows "LLM-only: not evaluated" until you run this with a real
API key. That is deliberate: we would rather show an empty cell than a made-up
number. Running it uses one Gemini request per sampled test message and consumes API quota. PII is redacted before each request; Google free-tier data-use terms still apply.

Usage:
    export GEMINI_API_KEY=...
    python ml/eval_llm.py --sample 200
    # writes the llm_only block into ml/artifacts/metrics.json (keeps everything else)

The prompt is the same classification task the agent performs, minus tool use, so
this measures "the model alone" rather than the full agent.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "ml" / "artifacts"
PROCESSED = REPO / "data" / "processed"
sys.path.insert(0, str(REPO / "backend"))

SYSTEM = (
    "You are a fraud-detection classifier for South Asian SMS and messaging traffic. "
    "Given one message, decide whether it is a scam. Answer with a single number between 0 and 1 "
    "(0 = clearly legitimate, 1 = clearly a scam) and nothing else."
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=int(os.getenv("SCAMLENS_EVAL_SAMPLE", "200")))
    ap.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    ap.add_argument("--sleep", type=float, default=0.4, help="pause between calls for rate limits")
    args = ap.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("Set GEMINI_API_KEY first — this script calls the real API and may consume free-tier quota.")

    test_path = PROCESSED / "test.csv"
    if not test_path.exists():
        raise SystemExit("Run `python ml/build_text_dataset.py` first.")

    test = pd.read_csv(test_path)
    rng = random.Random(20261017)
    # Take every multilingual row available, then fill with English, so the
    # comparison is not silently English-only.
    multilingual = test[test.language.isin(["bn", "hi", "ur"])]
    english = test[test.language == "en"]
    n_ml = len(multilingual)
    keep_ml = multilingual
    keep_en = english.sample(min(len(english), max(0, args.sample - n_ml)), random_state=20261017)
    sample = pd.concat([keep_ml, keep_en]).sample(frac=1, random_state=20261017)
    print(f"Scoring {len(sample)} test messages ({n_ml} multilingual) with {args.model}")

    from app.services.llm import GeminiClient, LLMUnavailable
    from app.services.pii import redact

    client = GeminiClient(os.environ["GEMINI_API_KEY"], args.model, max_tokens=12, timeout=30)

    scores, failures = [], 0
    for i, row in enumerate(sample.itertuples(), 1):
        try:
            safe_text = redact(str(row.text)).redacted_text
            resp = client.messages_create(
                system=SYSTEM,
                messages=[{"role": "user", "content": f"Message:\n{safe_text}\n\nScore:"}],
                max_tokens=12,
                temperature=0.0,
            )
            value = float("".join(ch for ch in resp.text if ch.isdigit() or ch == ".")[:5] or "nan")
            scores.append(min(1.0, max(0.0, value)))
        except (LLMUnavailable, ValueError) as exc:
            failures += 1
            scores.append(np.nan)
            if failures <= 3:
                print(f"  ! {type(exc).__name__}: {exc}")
        if i % 25 == 0:
            print(f"  {i}/{len(sample)} …")
        time.sleep(args.sleep)

    y_true = sample.label.to_numpy()
    y_prob = np.asarray(scores, dtype=float)
    mask = ~np.isnan(y_prob)
    if mask.sum() < 20:
        raise SystemExit(f"Too many failures ({failures}) — not writing metrics.")

    from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                                 precision_score, recall_score, roc_auc_score, roc_curve)

    threshold = 0.5
    y_pred = (y_prob[mask] >= threshold).astype(int)
    fpr, tpr, _ = roc_curve(y_true[mask], y_prob[mask])
    idx = np.linspace(0, len(fpr) - 1, min(60, len(fpr))).astype(int)

    llm_only = {
        "label": f"{args.model}, zero-shot, single call per message",
        "threshold": threshold,
        "precision": round(float(precision_score(y_true[mask], y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true[mask], y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true[mask], y_pred, zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(y_true[mask], y_pred)), 4),
        "roc_auc": round(float(roc_auc_score(y_true[mask], y_prob[mask])), 4),
        "confusion_matrix": confusion_matrix(y_true[mask], y_pred).tolist(),
        "roc_curve": {"fpr": [round(float(v), 4) for v in fpr[idx]],
                      "tpr": [round(float(v), 4) for v in tpr[idx]]},
        "n": int(mask.sum()),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "failed_calls": int(failures),
    }

    metrics_path = ARTIFACTS / "metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    metrics["llm_only"] = llm_only
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(llm_only, indent=2))
    print(f"\nUpdated {metrics_path} — the Benchmark page now shows the LLM-only column.")


if __name__ == "__main__":
    main()
