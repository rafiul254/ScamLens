"""Analysis endpoints: text, link, screenshot, plus PII redaction preview."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from ..config import Settings, get_settings
from ..deps import get_agent, get_db, limiter
from ..schemas import (
    AgentResult, AnalyzeTextRequest, AnalyzeUrlRequest, InputKind,
    RedactRequest, RedactResponse,
)
from ..security import client_key, guard_image, guard_text
from ..services.pii import redact

log = logging.getLogger("scamlens.api")
router = APIRouter(prefix="/api", tags=["analysis"])


def _rate_limit(request: Request, device_id: str) -> None:
    limiter().check(client_key(request, device_id))


@router.post("/redact", response_model=RedactResponse)
def redact_endpoint(payload: RedactRequest, settings: Settings = Depends(get_settings)) -> RedactResponse:
    """Client-side+server-side PII redaction preview (also used by the UI badge)."""
    guard_text(payload.text, settings.max_text_chars)
    result = redact(payload.text)
    return RedactResponse(
        redacted_text=result.redacted_text,
        entities=[e.to_dict() for e in result.entities],
        count=result.count,
    )


@router.post("/analyze/text", response_model=AgentResult)
def analyze_text(payload: AnalyzeTextRequest, request: Request,
                 settings: Settings = Depends(get_settings)) -> AgentResult:
    _rate_limit(request, payload.device_id)
    guard_text(payload.text, settings.max_text_chars)
    agent = get_agent()
    result = agent.analyze(
        text=payload.text,
        kind=payload.kind,
        language=payload.language,
        device_id=payload.device_id,
        make_lesson=payload.make_lesson,
        make_report=payload.make_report,
        make_family_alert=payload.make_family_alert,
    )
    get_db().save_analysis(result.model_dump(), payload.device_id, payload.text)
    return result


@router.post("/analyze/url", response_model=AgentResult)
def analyze_url_endpoint(payload: AnalyzeUrlRequest, request: Request,
                         settings: Settings = Depends(get_settings)) -> AgentResult:
    _rate_limit(request, payload.device_id)
    guard_text(payload.url, settings.max_url_length)
    agent = get_agent()
    result = agent.analyze(
        text=payload.url,
        kind=InputKind.URL,
        language=payload.language,
        device_id=payload.device_id,
        make_lesson=payload.make_lesson,
        url_override=payload.url,
    )
    get_db().save_analysis(result.model_dump(), payload.device_id, payload.url)
    return result


@router.post("/analyze/image", response_model=AgentResult)
async def analyze_image(request: Request, file: UploadFile = File(...),
                        device_id: str = Form(...), text: str = Form(""),
                        language: str = Form(""), kind: str = Form("image"),
                        settings: Settings = Depends(get_settings)) -> AgentResult:
    """Screenshot analysis. OCR is done by Gemini vision; without a configured
    Gemini key the API asks the user to paste the text instead of guessing."""
    _rate_limit(request, device_id)
    data = await file.read()
    guard_image(data, settings.max_image_bytes, file.content_type)
    if len(device_id) < 6:
        raise HTTPException(status_code=422, detail={"error": "bad_device_id"})

    allowed_types = ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif")
    media_type = file.content_type if file.content_type in allowed_types else "image/png"

    agent = get_agent()
    if not agent.llm.available:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "vision_unavailable",
                "message": "Reading screenshots needs a configured Gemini API key on this server. "
                           "Paste the message text instead — every other feature still works.",
            },
        )
    result = agent.analyze(
        text=text or "[screenshot uploaded — transcript below]",
        kind=InputKind.IMAGE,
        language=language or None,
        device_id=device_id,
        image_bytes=data,
        media_type=media_type,
    )
    get_db().save_analysis(result.model_dump(), device_id, text or "[screenshot]")
    return result


@router.post("/analyze/audio", response_model=AgentResult)
def analyze_audio(payload: AnalyzeTextRequest, request: Request,
                  settings: Settings = Depends(get_settings)) -> AgentResult:
    """Voice notes are transcribed on the device with the Web Speech API; the
    transcript arrives here and is analysed like text."""
    _rate_limit(request, payload.device_id)
    guard_text(payload.text, settings.max_text_chars)
    agent = get_agent()
    result = agent.analyze(
        text=payload.text, kind=InputKind.AUDIO_TRANSCRIPT, language=payload.language,
        device_id=payload.device_id, make_lesson=payload.make_lesson,
        make_report=payload.make_report, make_family_alert=payload.make_family_alert,
    )
    get_db().save_analysis(result.model_dump(), payload.device_id, payload.text)
    return result
