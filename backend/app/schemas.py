"""Pydantic contracts for ScamLens.

Every agent response is validated against ``AgentResult`` before it leaves the
API. If the LLM returns malformed JSON, the service layer repairs or rejects it
and the deterministic local agent takes over (see services/agent.py).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Language = Literal["bn", "en", "hi", "ur", "unknown"]


class Verdict(str, Enum):
    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"
    SCAM = "SCAM"


class InputKind(str, Enum):
    TEXT = "text"
    URL = "url"
    IMAGE = "image"
    AUDIO_TRANSCRIPT = "audio_transcript"


# --------------------------------------------------------------------------- #
# Sub-models
# --------------------------------------------------------------------------- #
class RedFlag(BaseModel):
    """A suspicious span inside the user's own message, with a plain reason."""

    text_span: str = Field(..., min_length=1, max_length=400)
    reason: str = Field(..., min_length=1, max_length=400)
    severity: float = Field(0.5, ge=0.0, le=1.0)


class LessonQuizQuestion(BaseModel):
    question: str = Field(..., min_length=4)
    options: list[str] = Field(..., min_length=2, max_length=5)
    answer_index: int = Field(..., ge=0)
    explanation: str = Field("", max_length=400)

    @field_validator("answer_index")
    @classmethod
    def _answer_in_range(cls, v: int, info) -> int:
        opts = info.data.get("options")
        if opts and v >= len(opts):
            raise ValueError("answer_index out of range for options")
        return v


class MicroLesson(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    pattern_id: str = Field(..., min_length=2, max_length=80)
    language: Language = "en"
    level: Literal["basic", "intermediate"] = "basic"
    seconds: int = Field(60, ge=30, le=180)
    body: str = Field(..., min_length=10)
    key_takeaways: list[str] = Field(default_factory=list, max_length=6)
    quiz: list[LessonQuizQuestion] = Field(default_factory=list, max_length=5)


class Evidence(BaseModel):
    """Real, computed numbers that justify the verdict. No invented values."""

    ml_score: float | None = Field(None, ge=0.0, le=1.0)
    ml_label: str | None = None
    url_score: float | None = Field(None, ge=0.0, le=1.0)
    pattern_matches: list[dict[str, Any]] = Field(default_factory=list)
    pattern_score: float | None = Field(None, ge=0.0, le=1.0)
    llm_score: float | None = Field(None, ge=0.0, le=1.0)
    llm_verdict: str | None = None
    llm_red_flags: list[dict[str, Any]] = Field(default_factory=list)
    ensemble_breakdown: dict[str, Any] = Field(default_factory=dict)
    top_tokens: list[dict[str, Any]] = Field(default_factory=list)
    url_findings: list[dict[str, Any]] = Field(default_factory=list)
    pii_found: list[dict[str, Any]] = Field(default_factory=list)
    agent_steps: list[dict[str, Any]] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    actionability: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """The strict JSON contract returned by /api/analyze."""

    verdict: Verdict
    risk_score: int = Field(..., ge=0, le=100)
    confidence: float = Field(..., ge=0.0, le=1.0)
    language: Language = "en"
    scam_type: str = Field("unknown", max_length=80)
    scam_type_label: str = Field("", max_length=120)
    input_kind: InputKind = InputKind.TEXT
    red_flags: list[RedFlag] = Field(default_factory=list, max_length=12)
    explanation: str = Field(..., min_length=1)
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)
    report_draft: str | None = None
    family_alert: str | None = None
    lesson: MicroLesson | None = None
    evidence: Evidence = Field(default_factory=Evidence)
    pii_redacted: bool = False
    mode: Literal["agent", "local_fallback"] = "agent"
    degraded_reason: str | None = None
    analysis_id: str | None = None
    created_at: str | None = None


# --------------------------------------------------------------------------- #
# Requests / responses
# --------------------------------------------------------------------------- #
class AnalyzeTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=6000)
    kind: InputKind = InputKind.TEXT
    language: Language | None = None  # None => auto-detect
    device_id: str = Field(..., min_length=6, max_length=64)
    # The client redacts PII before upload; server redacts again defensively.
    client_redacted: bool = True
    make_lesson: bool = True
    make_report: bool = True
    make_family_alert: bool = True

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v


class AnalyzeUrlRequest(BaseModel):
    url: str = Field(..., min_length=4, max_length=2048)
    device_id: str = Field(..., min_length=6, max_length=64)
    # A link has no prose to detect a language from, so the client may state the language the
    # answer should be written in (the app sends the interface language).
    language: Language | None = None
    make_lesson: bool = True


class RedactRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=6000)


class RedactResponse(BaseModel):
    redacted_text: str
    entities: list[dict[str, Any]]
    count: int


class HistoryItem(BaseModel):
    id: str
    created_at: str
    verdict: str
    risk_score: int
    scam_type: str
    language: str
    input_kind: str
    preview: str


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int


class StatsResponse(BaseModel):
    total_scans: int
    scam_count: int
    suspicious_count: int
    safe_count: int
    by_type: list[dict[str, Any]]
    by_language: list[dict[str, Any]]
    last_7_days: list[dict[str, Any]]
    privacy_note: str


class QuizSubmission(BaseModel):
    device_id: str = Field(..., min_length=6, max_length=64)
    pattern_id: str
    correct: int = Field(..., ge=0, le=20)
    total: int = Field(..., ge=1, le=20)


class ScamIQ(BaseModel):
    score: int
    level: str
    streak_days: int
    lessons_completed: int
    quizzes_passed: int
    correct_answers: int
    total_answers: int
    badges: list[dict[str, Any]]


class BenchmarkResponse(BaseModel):
    available: bool
    generated_at: str | None = None
    dataset: dict[str, Any] | None = None
    models: dict[str, Any] | None = None
    url_model: dict[str, Any] | None = None
    ensemble_weights: dict[str, float] | None = None
    shipped_pipeline: dict[str, Any] | None = None
    limitations: list[str] = Field(default_factory=list)
    notes: str | None = None
