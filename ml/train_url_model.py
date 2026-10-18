#!/usr/bin/env python3
"""Train + calibrate the lexical URL risk model.

Model: standardised lexical features -> Logistic Regression (calibrated with
CalibratedClassifierCV, sigmoid) and, when xgboost is installed, an XGBoost
comparison. The better F1 on the validation split is saved as the production
model (ml/artifacts/url_risk_model.joblib) together with its test metrics.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "backend"))

from app.services.url_analyzer import (  # noqa: E402
    FEATURE_ORDER_SOURCE,
    FEATURE_ORDER_VERSION,
    HOST_LEVEL_FEATURES,
    extract_features,
)

ARTIFACTS = REPO / "ml" / "artifacts"


def metrics_for(y_true, y_pred, y_prob) -> dict:
    from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                                 precision_score, recall_score, roc_auc_score, roc_curve,
                                 average_precision_score)
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    idx = np.linspace(0, len(fpr) - 1, min(60, len(fpr))).astype(int)
    return {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "pr_auc": round(float(average_precision_score(y_true, y_prob)), 4),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "roc_curve": {"fpr": [round(float(v), 4) for v in fpr[idx]],
                      "tpr": [round(float(v), 4) for v in tpr[idx]]},
        "test_size": int(len(y_true)),
        "positive_rate": round(float(np.mean(y_true)), 4),
    }


def best_threshold(y_true, y_prob) -> float:
    from sklearn.metrics import f1_score
    best, best_f1 = 0.5, -1.0
    for t in np.arange(0.2, 0.85, 0.02):
        f1 = f1_score(y_true, (y_prob >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best, best_f1 = float(t), f1
    return round(best, 3)


def sanity_rows(host_only: bool) -> tuple[np.ndarray, list[int]]:
    """Feature matrix + labels for the held-out local sanity set."""
    from url_sanity_set import LEGIT, PHISH

    order = list(HOST_LEVEL_FEATURES) if host_only else list(FEATURE_ORDER_SOURCE)
    rows, labels = [], []
    for label, items in ((0, LEGIT), (1, PHISH)):
        for url, _note in items:
            feats = extract_features(url).features
            rows.append([float(feats.get(k, 0.0)) for k in order])
            labels.append(label)
    return np.asarray(rows, dtype=float), labels


def sanity_scores(candidates: dict, host_idx: list[int] | None) -> dict:
    """Score every candidate on the local sanity set (0.5 decision threshold)."""
    out = {}
    for name in candidates:
        host_only = name.endswith("host_only") and host_idx is not None
        X, y = sanity_rows(host_only)
        prob = candidates[name].predict_proba(X)[:, 1]
        pred = (prob >= 0.5).astype(int)
        false_alarms = int(sum(1 for p, t in zip(pred, y) if t == 0 and p == 1))
        missed = int(sum(1 for p, t in zip(pred, y) if t == 1 and p == 0))
        out[name] = {
            "accuracy": round(float((pred == np.asarray(y)).mean()), 4),
            "false_alarms": false_alarms,
            "missed_look_alikes": missed,
            "n": len(y),
        }
        print(f"  local sanity [{name}]: {out[name]['accuracy']:.1%} correct, "
              f"{false_alarms} false alarm(s), {missed} missed look-alike(s)")
    return out


def main() -> dict:
    import joblib
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    data = {}
    for split in ("train", "val", "test"):
        path = ARTIFACTS / f"url_features_{split}.npz"
        if not path.exists():
            raise SystemExit("Run `python ml/build_url_dataset.py` first (missing %s)" % path)
        d = np.load(path)
        data[split] = (d["X"], d["y"])
    Xtr, ytr = data["train"]
    Xva, yva = data["val"]
    Xte, yte = data["test"]
    print(f"train={Xtr.shape} val={Xva.shape} test={Xte.shape}")

    candidates: dict[str, Pipeline] = {}

    lr = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", CalibratedClassifierCV(LogisticRegression(max_iter=2000, class_weight="balanced"), cv=3, method="sigmoid")),
    ])
    lr.fit(Xtr, ytr)
    candidates["logreg_calibrated"] = lr

    # Host-level subset: see HOST_LEVEL_FEATURES in url_analyzer.py for why the path-level
    # features are excluded from the shipped model.
    host_idx = [list(FEATURE_ORDER_SOURCE).index(k) for k in HOST_LEVEL_FEATURES]
    lr_host = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", CalibratedClassifierCV(LogisticRegression(max_iter=2000, class_weight="balanced"), cv=3, method="sigmoid")),
    ])
    lr_host.fit(Xtr[:, host_idx], ytr)
    candidates["logreg_host_only"] = lr_host

    try:
        from xgboost import XGBClassifier  # type: ignore

        xgb = Pipeline([
            ("clf", XGBClassifier(
                n_estimators=300, max_depth=5, learning_rate=0.1, subsample=0.9,
                colsample_bytree=0.9, eval_metric="logloss", n_jobs=2,
            )),
        ])
        xgb.fit(Xtr, ytr)
        candidates["xgboost"] = xgb
        print("xgboost trained")
    except Exception as exc:  # xgboost is optional
        print(f"xgboost not used ({type(exc).__name__}: {exc})")

    # The local sanity set: does the model label our users' URLs correctly? A model can win
    # on PhiUSIIL and still be unusable (the full-feature model did exactly that).
    sanity = sanity_scores(candidates, host_idx if "logreg_host_only" in candidates else None)

    results, best = {}, None
    for name, model in candidates.items():
        # host-only candidates are scored on their own feature subset
        use_host = name.endswith("host_only")
        Xva_i = Xva[:, host_idx] if use_host else Xva
        Xte_i = Xte[:, host_idx] if use_host else Xte
        prob_val = model.predict_proba(Xva_i)[:, 1]
        thr = best_threshold(yva, prob_val)
        val_pred = (prob_val >= thr).astype(int)
        from sklearn.metrics import f1_score
        val_f1 = f1_score(yva, val_pred, zero_division=0)
        prob_test = model.predict_proba(Xte_i)[:, 1]
        test_m = metrics_for(yte, (prob_test >= thr).astype(int), prob_test)
        results[name] = {
            "validation_threshold": thr,
            "validation_f1": round(float(val_f1), 4),
            **test_m,
            "local_sanity_accuracy": sanity.get(name, {}).get("accuracy"),
            "local_sanity_false_alarms": sanity.get(name, {}).get("false_alarms"),
        }
        if best is None or val_f1 > best[1]:
            best = (name, val_f1)

    # Which model ships? The backend's requirements.txt intentionally excludes xgboost
    # (~100 MB) because the URL model must unpickle on a small free-tier instance. A model
    # whose library is not installed there would silently fail to load, so the bundle only
    # considers candidates whose dependencies the backend actually pins. Any optional model
    # that scores higher (xgboost usually does) is still trained, measured and reported in
    # url_metrics.json as a comparison row.
    SHIPPABLE = {"logreg_calibrated", "logreg_host_only"}
    shippable_best = None
    for name in SHIPPABLE & set(results):
        row = results[name]
        # Two conditions, both measured: loadable with the backend's pinned dependencies,
        # and no false alarm on official domains in the held-out local sanity set.
        if (row.get("local_sanity_false_alarms") or 0) > 0:
            print(f"  {name}: excluded from shipping — "
                  f"{row['local_sanity_false_alarms']} false alarm(s) on the local sanity set")
            continue
        score = row["validation_f1"]
        if shippable_best is None or score > shippable_best[1]:
            shippable_best = (name, score)
    # If nothing passes the gate the bundle is still saved — as a research artefact, with
    # `authoritative: False`, so the rule layer keeps deciding in production and the
    # measurements stay on record. A model only becomes authoritative by passing the gate.
    authoritative = shippable_best is not None
    if shippable_best is not None:
        chosen = shippable_best[0]
    else:
        # Nothing passed the gate: save the best candidate whose library the backend pins,
        # so the artefact can at least be loaded and reported (a non-deployable winner like
        # xgboost would fail to unpickle on the deployed instance). Its metrics stay in JSON.
        deployable = {n: r["validation_f1"] for n, r in results.items() if n in SHIPPABLE}
        chosen = max(deployable, key=deployable.get) if deployable else best[0]
    if not authoritative:
        print(
            "  no candidate passed the sanity gate: saving the best model as a NON-authoritative "
            "artefact. The transparent rule layer decides URL risk in production; this model's "
            "scores are reported for research (see ml/artifacts/url_metrics.json)."
        )
    if best[0] != chosen:
        print(
            f"note: {best[0]} scored higher on validation (F1={best[1]:.4f}) but needs an optional "
            f"library the backend does not ship; deploying {chosen} "
            f"(F1={results[chosen]['validation_f1']:.4f}). Both are reported in url_metrics.json."
        )
    bundle = {
        "pipeline": candidates[chosen],
        "feature_order": list(HOST_LEVEL_FEATURES) if chosen.endswith("host_only") else list(FEATURE_ORDER_SOURCE),
        "feature_order_version": FEATURE_ORDER_VERSION,
        "threshold": results[chosen]["validation_threshold"],
        "authoritative": authoritative,
        "local_sanity": sanity.get(chosen),
        "version": f"url-{chosen}-{FEATURE_ORDER_VERSION}",
        "metrics": {k: {kk: vv for kk, vv in v.items() if kk != "roc_curve"} for k, v in results.items()},
    }
    joblib.dump(bundle, ARTIFACTS / "url_risk_model.joblib")
    print(f"Saved URL model: {chosen} (test F1={results[chosen]['f1']}, "
          f"AUC={results[chosen]['roc_auc']}, authoritative={authoritative})")

    from datetime import datetime, timezone
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chosen_model": chosen,
        "authoritative": authoritative,
        "local_sanity": sanity,
        "selection_rule": (
            "ship the deployable candidate (dependencies pinned in backend/requirements.txt) "
            "with the highest validation F1 among those with zero false alarms on the "
            "held-out local sanity set (ml/url_sanity_set.py)"
        ),
        "chosen_because": (
            "highest validation F1 among models whose dependencies are pinned in "
            "backend/requirements.txt (deployable on a free-tier instance without xgboost)"
        ),
        "best_overall_on_validation": best[0],
        "feature_order_version": FEATURE_ORDER_VERSION,
        "n_features": len(FEATURE_ORDER_SOURCE),
        "dataset": {
            "name": "PhiUSIIL Phishing URL Dataset (UCI #967)",
            "license": "CC BY 4.0",
            "train": int(len(ytr)), "validation": int(len(yva)), "test": int(len(yte)),
        },
        "models": results,
    }
    (ARTIFACTS / "url_metrics.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("Wrote ml/artifacts/url_metrics.json")
    return out


if __name__ == "__main__":
    main()
