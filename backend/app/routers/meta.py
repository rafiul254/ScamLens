"""Health, benchmark, demo samples, history and privacy endpoints."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings, get_settings
from ..deps import get_agent, get_db, get_url_model
from ..schemas import BenchmarkResponse, HistoryResponse, StatsResponse
from ..services.ml_classifier import load_metrics

router = APIRouter(prefix="/api", tags=["meta"])
REPO_ROOT = Path(__file__).resolve().parents[3]


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    agent = get_agent()
    ml_meta = agent.ml.metadata()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "llm_enabled": agent.llm.available,
        "llm_model": agent.llm.model if agent.llm.available else None,
        "llm_cooldown_seconds": agent.llm.cooldown_remaining or None,
        "agent_max_steps": settings.agent_max_steps,
        "text_model": ml_meta,
        "url_model": "trained" if get_url_model() else "rule_based",
        "url_probe_enabled": settings.url_probe_enabled,
        "limits": {
            "max_text_chars": settings.max_text_chars,
            "max_image_bytes": settings.max_image_bytes,
            "rate_limit_per_minute": settings.rate_limit_per_minute,
        },
    }


@router.get("/benchmark", response_model=BenchmarkResponse)
def benchmark(settings: Settings = Depends(get_settings)) -> BenchmarkResponse:
    """Real metrics produced by ml/train_text_model.py + ml/train_url_model.py.

    Nothing here is hard-coded: if the artifacts are missing the API says so.
    """
    metrics = load_metrics(Path(settings.ml_artifacts_dir), settings.metrics_file)
    if not metrics:
        return BenchmarkResponse(
            available=False,
            notes="No training metrics found. Run `make train` (ml/train_text_model.py) to generate ml/artifacts/metrics.json.",
        )
    return BenchmarkResponse(
        available=True,
        generated_at=metrics.get("generated_at"),
        dataset=metrics.get("dataset"),
        models=metrics.get("models"),
        url_model=metrics.get("url_model"),
        ensemble_weights=metrics.get("ensemble_weights"),
        shipped_pipeline=metrics.get("shipped_pipeline_eval"),
        limitations=metrics.get("limitations", []),
        notes=metrics.get("notes"),
    )


@router.get("/samples")
def samples() -> dict:
    """Demo-mode carousel: 10 realistic, synthetic scam examples."""
    path = REPO_ROOT / "data" / "demo_samples.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail={"error": "samples_missing"})
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/history", response_model=HistoryResponse)
def history(device_id: str = Query(..., min_length=6, max_length=64),
            limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> HistoryResponse:
    db = get_db()
    items = db.list_analyses(device_id, limit=limit, offset=offset)
    return HistoryResponse(items=items, total=db.count_analyses(device_id))


@router.get("/history/{analysis_id}")
def history_item(analysis_id: str, device_id: str = Query(..., min_length=6, max_length=64)) -> dict:
    item = get_db().get_analysis(device_id, analysis_id)
    if not item:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return item


@router.get("/stats", response_model=StatsResponse)
def stats(device_id: str = Query(..., min_length=6, max_length=64)) -> StatsResponse:
    return StatsResponse(**get_db().community_stats(device_id))


@router.delete("/data")
def delete_all(device_id: str = Query(..., min_length=6, max_length=64)) -> dict:
    """Privacy-first: wipes every row this device ever created."""
    removed = get_db().delete_device_data(device_id)
    return {"deleted": True, "removed": removed,
            "message": "All scans, lessons and Scam IQ progress for this device were deleted."}
