"""Weighted ensemble of the four real signals.

risk_score = w_ml*ml + w_url*url + w_pattern*pattern + w_llm*llm

* Weights come from ml/artifacts/metrics.json (tuned on the validation split by
  ml/train_text_model.py, which grid-searches weights to maximise F1 of the
  combined score on held-out validation data).
* When a signal is missing (e.g. no URL in the message, or Gemini is unavailable),
  the remaining weights are renormalised instead of treating the missing signal
  as 0 - that would silently deflate risk.
* Thresholds (SAFE/SUSPICIOUS/SCAM) also come from the tuned metrics, with
  documented defaults.
"""
from __future__ import annotations

from typing import Any

# --- curated playbook override -------------------------------------------------------
# These constants define when a hand-curated, high-severity scam playbook outranks the
# statistical score, and where it lands on the 0-100 scale. They are deliberately
# conservative (severity >= 0.85 means MFS / OTP / authority fraud — the playbooks that do
# real damage in South Asia) and their effect is measured, not assumed: ml/eval_ensemble.py
# reports precision / recall / F1 with and without the rule on the held-out test set.
PLAYBOOK_MIN_SEVERITY = 0.85
PLAYBOOK_MIN_PATTERN_SCORE = 0.60
PLAYBOOK_MIN_STRONG_KEYWORDS = 2
PLAYBOOK_OVERRIDE_SCORE = 0.70  # 70/100 -> inside the SCAM band, below the strongest cases

DEFAULT_WEIGHTS = {"ml": 0.34, "url": 0.22, "pattern": 0.26, "llm": 0.18}
DEFAULT_THRESHOLDS = {"scam": 0.68, "suspicious": 0.34}


def combine(signals: dict[str, float | None],
            weights: dict[str, float] | None = None) -> tuple[float, dict[str, float]]:
    """Return (risk_score_0_1, weighted_breakdown_used)."""
    w = dict(weights or DEFAULT_WEIGHTS)
    available = {k: v for k, v in signals.items() if v is not None and k in w}
    if not available:
        return 0.0, {}
    total_w = sum(w[k] for k in available)
    if total_w <= 0:
        return 0.0, {}
    breakdown = {k: round(w[k] / total_w, 4) for k in available}
    score = sum(float(v) * (w[k] / total_w) for k, v in available.items())
    return round(min(1.0, max(0.0, score)), 4), breakdown


def verdict_for(score: float, thresholds: dict[str, float] | None = None) -> str:
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if score >= t["scam"]:
        return "SCAM"
    if score >= t["suspicious"]:
        return "SUSPICIOUS"
    return "SAFE"


def confidence_for(score: float, signals: dict[str, float | None],
                   thresholds: dict[str, float] | None = None) -> float:
    """Confidence blends decision margin with agreement between signals.

    * margin: how far the score sits from the nearest decision boundary
    * agreement: 1 - spread of the available signals (disagreeing signals => lower confidence)
    """
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    boundaries = [t["suspicious"], t["scam"]]
    margin = min(abs(score - b) for b in boundaries) / 0.5
    margin = min(1.0, margin)

    vals = [float(v) for v in signals.values() if v is not None]
    if len(vals) >= 2:
        mean = sum(vals) / len(vals)
        spread = (max(vals) - min(vals))
        agreement = max(0.0, 1.0 - spread)
    else:
        mean = vals[0] if vals else 0.5
        agreement = 0.6 if vals else 0.4

    conf = 0.55 * margin + 0.45 * agreement
    # Never claim near-certainty; published ML is imperfect.
    return round(min(0.96, max(0.35, conf)), 3)


def explain_breakdown(signals: dict[str, float | None], breakdown: dict[str, float],
                      score: float) -> dict[str, Any]:
    return {
        "signals": {k: (round(float(v), 4) if v is not None else None) for k, v in signals.items()},
        "effective_weights": breakdown,
        "final_score": round(score, 4),
        "formula": "risk = Σ wᵢ·sᵢ over available signals (weights renormalised), tuned on the validation split",
    }
