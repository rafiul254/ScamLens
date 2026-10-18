"""ML text classifier loader + inference + token-level explainability.

Two models are trained by ml/train_text_model.py and stored in ml/artifacts:

1. ``embedding``  – multilingual MiniLM sentence embeddings -> calibrated Logistic
   Regression. Primary scorer; handles Bangla/Hindi/Urdu/English text.
2. ``tfidf``      – TF-IDF char+word n-grams -> calibrated Logistic Regression.
   Always available (no torch download needed) and doubles as the token-level
   explainability surrogate, because embedding models are not directly
   attributable per token.

If the artifacts are missing the service degrades to rules only and reports
``ml_unavailable`` in the evidence, instead of inventing a score.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("scamlens.ml")

_TOKEN_RE = re.compile(r"[\w\u0600-\u06FF\u0900-\u097F\u0980-\u09FF]+", re.UNICODE)


@dataclass
class TextPrediction:
    available: bool
    score: float | None = None
    label: str | None = None
    top_tokens: list[dict[str, Any]] = field(default_factory=list)
    model_used: str = "none"
    version: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "score": self.score,
            "label": self.label,
            "top_tokens": self.top_tokens,
            "model_used": self.model_used,
            "version": self.version,
            "reason": self.reason,
        }


class TextClassifierService:
    """Thread-safe, lazy-loading wrapper around the trained artifacts."""

    def __init__(self, artifacts_dir: Path, model_file: str = "text_classifier.joblib",
                 embedder_name: str | None = None) -> None:
        self.artifacts_dir = Path(artifacts_dir)
        self.model_file = model_file
        self.embedder_name = embedder_name
        self._lock = threading.Lock()
        self._bundle: dict[str, Any] | None = None
        self._embedder = None
        self._load_attempted = False
        self._load_error: str | None = None

    # ---------------------------------------------------------------- loading
    def _load(self) -> None:
        if self._load_attempted:
            return
        with self._lock:
            if self._load_attempted:
                return
            self._load_attempted = True
            path = self.artifacts_dir / self.model_file
            if not path.exists():
                self._load_error = f"artifact missing: {path}"
                log.warning("Text classifier artifact not found at %s – running rules only", path)
                return
            try:
                import joblib

                self._bundle = joblib.load(path)
                log.info(
                    "Loaded text classifier %s (version=%s, backend=%s)",
                    path.name, self._bundle.get("version"), self._bundle.get("backend"),
                )
            except Exception as exc:  # pragma: no cover
                self._load_error = f"{type(exc).__name__}: {exc}"[:300]
                log.exception("Failed to load text classifier")

    def _get_embedder(self):
        if self._embedder is not None:
            return self._embedder
        name = (self._bundle or {}).get("embedder_name") or self.embedder_name
        if not name:
            return None
        try:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(name)
            log.info("Loaded embedder %s", name)
        except Exception as exc:
            log.warning("Embedding model unavailable (%s) – falling back to TF-IDF model", exc)
            self._embedder = None
        return self._embedder

    # -------------------------------------------------------------- inference
    @property
    def ready(self) -> bool:
        self._load()
        return self._bundle is not None

    def metadata(self) -> dict[str, Any]:
        self._load()
        if not self._bundle:
            return {"available": False, "reason": self._load_error}
        meta = self._bundle.get("metadata", {})
        return {
            "available": True,
            "version": self._bundle.get("version"),
            "backend": self._bundle.get("backend"),
            "embedder_name": self._bundle.get("embedder_name"),
            "trained_at": meta.get("trained_at"),
            # operating threshold baked into the bundle when the classifier was trained
            "threshold": self._bundle.get("threshold"),
            "validation": meta.get("validation", {}),
            "embedding_model_available": self._try_embedding_backend() is not None,
        }

    def preferred_backend(self) -> str:
        """'tfidf' | 'embedding' | 'auto', from settings or the trained bundle."""
        import os

        override = (os.getenv("TEXT_MODEL_BACKEND") or "").strip().lower()
        if override in ("tfidf", "embedding", "auto"):
            return override
        backend = (self._bundle or {}).get("backend") or "auto"
        return {"ml_tfidf": "tfidf", "ml_embedding": "embedding"}.get(backend, "auto")

    def _try_embedding_backend(self):
        if self._bundle and self._bundle.get("embedding_classifier") is not None:
            return self._bundle.get("embedding_classifier")
        return None

    def predict(self, text: str) -> TextPrediction:
        self._load()
        if not self._bundle:
            return TextPrediction(available=False, reason=self._load_error)

        version = self._bundle.get("version")
        backend = self.preferred_backend()
        emb_clf = self._try_embedding_backend() if backend in ("auto", "embedding") else None
        embedder = self._get_embedder() if emb_clf is not None else None
        tfidf_first = backend == "tfidf"

        # 0) TF-IDF is the production backend when it won on the validation split
        #    (see ml/artifacts/metrics.json). It is also the always-available path.
        if tfidf_first:
            tfidf = self._bundle.get("tfidf_classifier")
            if tfidf is not None:
                prob = float(tfidf.predict_proba([text])[0][1])
                return TextPrediction(
                    available=True, score=round(prob, 4),
                    label="scam" if prob >= 0.5 else "ham",
                    top_tokens=self.explain_tokens(text),
                    model_used="tfidf+logreg(calibrated)", version=version,
                )

        # 1) Multilingual embedding model (used when it scored better in training,
        #    or when TEXT_MODEL_BACKEND=embedding is set explicitly)
        if emb_clf is not None and embedder is not None:
            try:
                emb = embedder.encode([text], normalize_embeddings=True, show_progress_bar=False)
                prob = float(emb_clf.predict_proba(emb)[0][1])
                return TextPrediction(
                    available=True, score=round(prob, 4),
                    label="scam" if prob >= 0.5 else "ham",
                    top_tokens=self.explain_tokens(text),
                    model_used="embedding+logreg(calibrated)", version=version,
                )
            except Exception as exc:
                log.warning("Embedding inference failed (%s); using TF-IDF backend", exc)

        # 2) Always-available fallback: TF-IDF model trained on the same data
        tfidf = self._bundle.get("tfidf_classifier")
        if tfidf is not None:
            prob = float(tfidf.predict_proba([text])[0][1])
            return TextPrediction(
                available=True, score=round(prob, 4),
                label="scam" if prob >= 0.5 else "ham",
                top_tokens=self.explain_tokens(text),
                model_used="tfidf+logreg(calibrated)", version=version,
            )
        return TextPrediction(available=False, reason="no usable classifier backend")

    def explain_tokens(self, text: str, top_k: int = 8) -> list[dict[str, Any]]:
        """Token-level contributions via the linear TF-IDF surrogate.

        contribution = tfidf_value * coefficient  (documented approximation).
        Contributions are normalised so the largest absolute value maps to 1.0,
        which is what the UI uses for colour intensity.
        """
        self._load()
        if not self._bundle:
            return []
        tfidf = self._bundle.get("tfidf_classifier")
        vectorizer = self._bundle.get("explainer_vectorizer")
        if tfidf is None or vectorizer is None:
            return []
        try:
            X = vectorizer.transform([text])
            coefs = self._linear_coefficients(tfidf)
            if coefs is None:
                return []
            raw = X.multiply(coefs).tocsr()
            items = []
            for idx, value in zip(raw.indices, raw.data):
                if value <= 0:
                    continue
                feature = vectorizer.get_feature_names_out()[idx]
                items.append({"feature": str(feature), "contribution": float(value)})
            if not items:
                return []
            items.sort(key=lambda d: d["contribution"], reverse=True)
            top = items[:top_k]
            max_c = max(i["contribution"] for i in top) or 1.0
            out = [
                {
                    "token": i["feature"],
                    "contribution": round(i["contribution"] / max_c, 3),
                    "raw_score": round(i["contribution"], 5),
                    "source": "ml_token_attribution",
                }
                for i in top
            ]
            # Map n-gram features back onto real spans in the message when possible.
            for item in out:
                span = _find_span(text, item["token"])
                if span:
                    item["start"], item["end"] = span
                    item["text"] = text[span[0]:span[1]]
            return out
        except Exception as exc:  # pragma: no cover
            log.warning("Token explanation failed: %s", exc)
            return []

    @staticmethod
    def _linear_coefficients(clf):
        try:
            inner = clf
            for attr in ("calibrated_classifiers_",):
                if hasattr(inner, attr):
                    inner = inner.calibrated_classifiers_[0]
            for attr in ("estimator", "base_estimator"):
                if hasattr(inner, attr):
                    inner = getattr(inner, attr)
            return inner.coef_[0]
        except Exception:
            return None


def _find_span(text: str, needle: str) -> tuple[int, int] | None:
    """Find a feature (word or n-gram) inside the original text, loosely."""
    n = needle.strip()
    if not n:
        return None
    low, low_n = text.lower(), n.lower()
    pos = low.find(low_n)
    if pos >= 0:
        return pos, pos + len(low_n)
    # char/word n-grams may span punctuation: match on collapsed alphanumerics
    parts = [p for p in re.split(r"\W+", low_n) if p]
    if not parts:
        return None
    pattern = r"\W*".join(re.escape(p) for p in parts)
    m = re.search(pattern, low)
    return (m.start(), m.end()) if m else None


def load_metrics(artifacts_dir: Path, metrics_file: str = "metrics.json") -> dict[str, Any] | None:
    path = Path(artifacts_dir) / metrics_file
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None
