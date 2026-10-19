"""ScamLens backend configuration.

All secrets come from the environment. Nothing sensitive is ever sent to the
frontend. See /home/user/scamlens/.env.example for the full list.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    # --- App ---
    app_name: str = "ScamLens API"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # --- Google Gemini API (optional; local agent works without a key) ---
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_max_tokens: int = 2400
    gemini_timeout_seconds: float = 45.0
    # gemini-3.8-flash is a thinking model: thought tokens are billed against
    # max_output_tokens, so a low budget can yield HTTP 200 with finishReason
    # MAX_TOKENS and empty content. 0 disables thinking (recommended for the
    # short JSON/OCR replies here); -1 omits thinkingConfig so the model decides.
    gemini_thinking_budget: int = 0

    # --- Groq API (optional fallback when Gemini is rate-limited/unavailable) ---
    # OpenAI-compatible chat completions. Only used when Gemini cannot answer;
    # the deterministic local agent remains the last resort.
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: float = 25.0
    # After a 429 RESOURCE_EXHAUSTED the client stops calling the API for this
    # many seconds and serves the local agent instead (quota circuit breaker).
    llm_cooldown_seconds: float = 60.0
    agent_max_steps: int = 6
    # When the API key is missing or the API fails, ScamLens runs a fully
    # deterministic local agent (ML + rules + pattern library). The UI shows a
    # "degraded mode" banner so results are never silently different.
    enable_local_agent_fallback: bool = True

    # --- CORS: locked to the known frontend origins ---
    frontend_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173,"
        "http://localhost:8080,http://127.0.0.1:8080"
    )

    # --- Limits / safety ---
    max_text_chars: int = 6000
    max_image_bytes: int = 5 * 1024 * 1024
    max_url_length: int = 2048
    url_probe_timeout_seconds: float = 3.0
    url_probe_enabled: bool = True  # safe HEAD-only probe, never renders a page
    rate_limit_per_minute: int = 30
    rate_limit_burst: int = 8

    # --- Storage ---
    db_path: str = str(BACKEND_DIR / "scamlens.db")

    # --- Optional: serve the built PWA from this same origin (Docker image) ---
    frontend_dist: str | None = None

    # --- ML artifacts ---
    ml_artifacts_dir: str = str(REPO_ROOT / "ml" / "artifacts")
    ml_model_file: str = "text_classifier.joblib"
    url_model_file: str = "url_risk_model.joblib"
    metrics_file: str = "metrics.json"
    embedder_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # The ensemble weights are tuned on the text corpus, where almost no row contains a
    # URL, so the tuned URL weight collapses to 0. When a submission DOES contain a link,
    # that link is direct evidence and must not be ignored, so it gets this floor.
    url_signal_floor: float = 0.30
    # A scam has to ask for something: money, a code, a click, an install or a callback.
    # If a message contains no such ask and no link/contact, its risk is capped here so a
    # benign family or appointment message cannot be labelled a scam by a keyword alone.
    # The effective cap is additionally bounded by the tuned "suspicious" threshold so the
    # displayed number always agrees with the SAFE verdict. Set to 1.0 to disable; the check
    # is always reported in evidence.actionability.
    non_actionable_risk_cap: float = 0.30
    # The curated playbook override is a real product decision, so it can be switched off
    # and A/B measured on the held-out set (ml/eval_ensemble.py reports both rows).
    playbook_override_enabled: bool = True

    @field_validator("ml_artifacts_dir", mode="after")
    @classmethod
    def _resolve_artifacts_dir(cls, value: str) -> str:
        # .env ships a repo-relative path (ml/artifacts); the server may be
        # launched from backend/ (make dev-backend), so anchor it to the repo.
        path = Path(value)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return str(path)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
