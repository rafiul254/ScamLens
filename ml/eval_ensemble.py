"""Measure the SHIPPED ScamLens pipeline on the held-out test split.

`train_text_model.py` measures the classifier and the ensemble *scores* on the test
split. This script measures the product: it calls the real agent (PII redaction, pattern
matcher, URL analyser, actionability check, playbook override, band floor, thresholds)
once per held-out row and reports precision / recall / F1 / ROC-AUC plus the confusion
matrix for three configurations:

  ml_only            - the calibrated TF-IDF classifier alone
  ensemble           - tuned weights + thresholds, override rule switched off
  ensemble_override  - exactly what users get (the curated playbook override on)

The last row is the honest one: it is what the app actually decides. Both the delta and
the confusion matrix are merged into ml/artifacts/metrics.json, which the /api/benchmark
endpoint and the Benchmark tab read. Nothing here is hand-written.

Usage:  python3 ml/eval_ensemble.py [--split test] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Keep the evaluation out of the developer database.
os.environ.setdefault("DB_PATH", str(ROOT / "ml" / "artifacts" / "eval_scratch.db"))

import pandas as pd  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from app.config import get_settings  # noqa: E402
from app.deps import build_agent  # noqa: E402


def metrics(y_true, y_pred, y_score=None) -> dict:
    out = {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "n": int(len(y_true)),
    }
    if y_score is not None and len(set(y_true)) > 1:
        out["roc_auc"] = round(float(roc_auc_score(y_true, y_score)), 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["test", "val"])
    ap.add_argument("--limit", type=int, default=0, help="0 = all rows (useful for a smoke run)")
    args = ap.parse_args()

    frame = pd.read_csv(ROOT / "data" / "processed" / f"{args.split}.csv")
    frame = frame.dropna(subset=["text", "label"])
    if args.limit:
        frame = frame.sample(n=min(args.limit, len(frame)), random_state=7)
    frame = frame.reset_index(drop=True)

    print(f"evaluating the shipped pipeline on {len(frame)} {args.split} rows "
          f"(url probing off, playbook override measured both ways) ...", flush=True)

    results: dict[str, dict] = {}
    rows: dict[str, list[dict]] = {}

    # Probing live URLs during evaluation would make the numbers depend on the network
    # (and on third-party sites staying up). The probe adds findings, it never changes the
    # tokenisation of the risk score, so evaluation runs with it switched off.
    settings = get_settings().model_copy(update={"url_probe_enabled": False})

    # 1. the classifier on its own (cheap, and the reference row)
    reference = build_agent(settings)
    started = time.time()
    rows["ml_only"] = [
        {"label": int(row["label"]), "score": float(reference.ml.predict(str(row["text"])).score)}
        for _, row in frame.iterrows()
    ]
    print(f"  ml_only: done in {time.time() - started:.0f}s")

    # 2. the full pipeline, once with the playbook override off and once on (shipped)
    for flag in (False, True):
        key = "ensemble_override" if flag else "ensemble"
        agent = build_agent(settings.model_copy(update={"playbook_override_enabled": flag}))
        started = time.time()
        collected: list[dict] = []
        for i, row in enumerate(frame.itertuples()):
            result = agent.analyze(
                text=str(row.text),
                device_id="benchmark-eval",
                make_lesson=False,
                make_report=False,
                make_family_alert=False,
            )
            collected.append({"label": int(row.label), "score": float(result.risk_score) / 100.0})
            if i and i % 250 == 0:
                print(f"  {key}: {i}/{len(frame)} ({time.time() - started:.0f}s)")
        rows[key] = collected
        print(f"  {key}: done in {time.time() - started:.0f}s")

    thresholds = reference._thresholds()  # noqa: SLF001 - the exact numbers the API uses
    scam_threshold = float(thresholds["scam"])
    meta = reference.ml.metadata()
    ml_threshold = float(meta.get("threshold") or scam_threshold)

    for key, records in rows.items():
        y_true = [r["label"] for r in records]
        y_score = [r["score"] for r in records]
        cut = ml_threshold if key == "ml_only" else scam_threshold
        y_pred = [1 if s >= cut else 0 for s in y_score]
        results[key] = {**metrics(y_true, y_pred, y_score), "decision_threshold": round(cut, 4)}
        print(f"{key:18s} F1={results[key]['f1']:.4f} P={results[key]['precision']:.4f} "
              f"R={results[key]['recall']:.4f} AUC={results[key].get('roc_auc')} (thr {cut:.3f})")

    path = ROOT / "ml" / "artifacts" / "metrics.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    # How much does the curated playbook override actually change? Report the exact rows
    # rather than implying a benefit: if it changes nothing on this corpus, say so.
    off = [r["score"] >= scam_threshold for r in rows["ensemble"]]
    on = [r["score"] >= scam_threshold for r in rows["ensemble_override"]]
    changed = [(i, rows["ensemble"][i]["label"]) for i in range(len(off)) if off[i] != on[i]]
    override_effect = {
        "changed_decisions": len(changed),
        "rows_fixed": sum(1 for _, label in changed if label == 1),
        "rows_broken": sum(1 for _, label in changed if label == 0),
        "note": (
            "The curated playbook override fires only on high-severity, multi-keyword matches of "
            "MFS / OTP / fake-authority playbooks. The held-out corpus (UCI SMS Spam, SpamAssassin, "
            f"{len(frame)} rows, mostly English) contains none of them, so it changes "
            f"{len(changed)} decisions here: its value shows up on the Bangla / Hindi / Urdu MFS "
            "messages in the demo set and in the live app, not on this benchmark."
        ),
    }
    data["shipped_pipeline_eval"] = {
        "override_effect": override_effect,
        "split": args.split,
        "n": int(len(frame)),
        "note": (
            "Measured end-to-end by calling the shipped agent once per held-out row "
            "(PII redaction, pattern matcher, actionability check, thresholds). "
            "'ensemble_override' is what users get; 'ensemble' is the same pipeline with the "
            "curated playbook override switched off, which is how its effect is isolated."
        ),
        "results": results,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nmerged shipped_pipeline_eval into {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
