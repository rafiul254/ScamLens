"""Learn tab: pattern library, micro-lessons, quizzes, Scam IQ."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..deps import get_agent, get_db, limiter
from ..schemas import MicroLesson, QuizSubmission, ScamIQ
from ..security import client_key
from ..services.db import iq_level
from ..services.patterns import get_pattern, list_patterns

router = APIRouter(prefix="/api/learn", tags=["learn"])


@router.get("/patterns")
def patterns() -> dict:
    items = list_patterns()
    return {"count": len(items), "patterns": items}


@router.get("/patterns/{pattern_id}")
def pattern_detail(pattern_id: str) -> dict:
    p = get_pattern(pattern_id)
    if not p:
        raise HTTPException(status_code=404, detail={"error": "pattern_not_found", "pattern_id": pattern_id})
    return {
        "id": p["id"],
        "category": p["category"],
        "severity": p["severity"],
        "name": p["name"],
        "summary": p["summary"],
        "psychology": p.get("psychology", []),
        "safe_response": p.get("safe_response", ""),
        "red_flag_hints": p.get("red_flag_hints", []),
        "keywords": p.get("keywords", {}),
    }


@router.get("/lesson", response_model=MicroLesson)
def lesson(pattern_id: str = Query(..., min_length=2, max_length=60),
           language: str = Query("en"), level: str = Query("basic")) -> MicroLesson:
    if not get_pattern(pattern_id):
        raise HTTPException(status_code=404, detail={"error": "pattern_not_found", "pattern_id": pattern_id})
    agent = get_agent()
    out = agent.toolbox.create_micro_lesson(pattern_id, language, level)
    if not out.get("lesson"):
        # Deterministic offline lesson from the curated pattern library.
        from ..services.patterns import match_patterns

        p = get_pattern(pattern_id)
        match = next((m for m in match_patterns(" ".join(
            sum(p.get("keywords", {}).values(), [])[:12]), language=language)), None)
        if match is None:
            from ..services.patterns import PatternMatch

            match = PatternMatch(pattern_id=p["id"], name=p["name"], category=p["category"],
                                 severity=float(p["severity"]), score=float(p["severity"]),
                                 red_flag_hints=p.get("red_flag_hints", []),
                                 psychology=p.get("psychology", []),
                                 safe_response=p.get("safe_response", ""))
        lesson_obj = agent._offline_lesson(match, language)
        if lesson_obj is None:
            raise HTTPException(status_code=500, detail={"error": "lesson_unavailable"})
        return lesson_obj
    payload = out["lesson"]
    payload.setdefault("title", pattern_id)
    payload.setdefault("body", "")
    return MicroLesson.model_validate(payload)


@router.post("/quiz", response_model=ScamIQ)
def submit_quiz(payload: QuizSubmission, request: Request) -> ScamIQ:
    limiter().check(client_key(request, payload.device_id))
    if not get_pattern(payload.pattern_id):
        raise HTTPException(status_code=404, detail={"error": "pattern_not_found"})
    updated = get_db().record_lesson(payload.device_id, payload.pattern_id, payload.correct, payload.total)
    updated["level"] = iq_level(int(updated.get("score", 0)))
    badges = updated.get("badges") or []
    if isinstance(badges, str):
        import json

        badges = json.loads(badges)
    return ScamIQ(
        score=int(updated.get("score", 0)),
        level=updated["level"],
        streak_days=int(updated.get("streak_days", 0)),
        lessons_completed=int(updated.get("lessons_completed", 0)),
        quizzes_passed=int(updated.get("quizzes_passed", 0)),
        correct_answers=int(updated.get("correct_answers", 0)),
        total_answers=int(updated.get("total_answers", 0)),
        badges=badges,
    )


@router.get("/scamiq", response_model=ScamIQ)
def scam_iq(device_id: str = Query(..., min_length=6, max_length=64)) -> ScamIQ:
    iq = get_db().get_scam_iq(device_id)
    badges = iq.get("badges") or []
    if isinstance(badges, str):
        import json

        badges = json.loads(badges)
    return ScamIQ(
        score=int(iq.get("score", 0)),
        level=iq_level(int(iq.get("score", 0))),
        streak_days=int(iq.get("streak_days", 0)),
        lessons_completed=int(iq.get("lessons_completed", 0)),
        quizzes_passed=int(iq.get("quizzes_passed", 0)),
        correct_answers=int(iq.get("correct_answers", 0)),
        total_answers=int(iq.get("total_answers", 0)),
        badges=badges,
    )
