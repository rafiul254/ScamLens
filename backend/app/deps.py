"""Process-wide singletons (models, DB, limiter) built once at startup."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .security import SlidingWindowLimiter
from .services.agent import ScamLensAgent
from .services.db import Database
from .services.ml_classifier import TextClassifierService

log = logging.getLogger("scamlens")

_state: dict[str, Any] = {}


def _load_url_model(settings: Settings) -> dict | None:
    path = Path(settings.ml_artifacts_dir) / settings.url_model_file
    if not path.exists():
        log.warning("URL risk model not found at %s – using transparent rule score", path)
        return None
    try:
        import joblib

        bundle = joblib.load(path)
        log.info("Loaded URL risk model %s (version=%s)", path.name, bundle.get("version"))
        return bundle
    except Exception as exc:  # pragma: no cover
        log.exception("Could not load URL model: %s", exc)
        return None


def build_agent(settings: Settings) -> ScamLensAgent:
    """Construct a fresh agent (its own model handles) without touching the process cache.

    Used by offline tooling such as ml/eval_ensemble.py, which needs to run the pipeline
    with different settings in the same interpreter.
    """
    ml = TextClassifierService(Path(settings.ml_artifacts_dir), settings.ml_model_file, settings.embedder_name)
    return ScamLensAgent(settings, ml, _load_url_model(settings))


def init_state(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if _state.get("ready"):
        return _state
    ml = TextClassifierService(Path(settings.ml_artifacts_dir), settings.ml_model_file, settings.embedder_name)
    url_model = _load_url_model(settings)
    _state.update({
        "settings": settings,
        "ml": ml,
        "url_model": url_model,
        "agent": ScamLensAgent(settings, ml, url_model),
        "db": Database(settings.db_path),
        "limiter": SlidingWindowLimiter(settings.rate_limit_per_minute, settings.rate_limit_burst),
        "ready": True,
    })
    if settings.gemini_api_key and settings.groq_api_key:
        llm_label = f"gemini:{settings.gemini_model}->groq:{settings.groq_model}"
    elif settings.gemini_api_key:
        llm_label = f"gemini:{settings.gemini_model}"
    elif settings.groq_api_key:
        llm_label = f"groq:{settings.groq_model}"
    else:
        llm_label = "local-fallback"
    log.info(
        "ScamLens ready | llm=%s | text_model=%s | url_model=%s | db=%s",
        llm_label,
        "loaded" if ml.ready else "rules-only",
        "loaded" if url_model else "rules-only",
        settings.db_path,
    )
    return _state


def get_agent() -> ScamLensAgent:
    return init_state()["agent"]


def get_db() -> Database:
    return init_state()["db"]


def get_url_model():
    return init_state()["url_model"]


def limiter() -> SlidingWindowLimiter:
    return init_state()["limiter"]
