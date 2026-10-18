"""ScamLens FastAPI application."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .deps import init_state, limiter
from .routers import analyze, learn, meta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("scamlens")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_state(settings)
    if not settings.llm_enabled:
        log.warning(
            "Neither GEMINI_API_KEY nor GROQ_API_KEY is set – ScamLens runs the deterministic "
            "local agent (ML + URL rules + pattern library). The API reports mode='local_fallback'."
        )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "ScamLens — an explainable anti-scam agent for Bangla, English, Hindi and Urdu speakers. "
        "Analyses messages, links, screenshots and voice notes, explains the evidence, drafts a complaint "
        "and teaches the scam pattern. Everything in /api/benchmark comes from real training runs."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Device-Id"],
    max_age=600,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.0f}"
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Some fields were missing or invalid.",
            # exc.errors() can contain exception objects in "ctx" — keep it JSON-safe
            "details": [
                {"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
                for e in exc.errors()[:5]
            ],
        },
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):  # pragma: no cover
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error",
                 "message": "Something went wrong on our side. Your message was not stored."},
    )


app.include_router(meta.router)
app.include_router(analyze.router)
app.include_router(learn.router)


def _api_index() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "endpoints": [
            "GET  /api/health",
            "POST /api/analyze/text",
            "POST /api/analyze/url",
            "POST /api/analyze/image",
            "POST /api/analyze/audio",
            "POST /api/redact",
            "GET  /api/learn/patterns",
            "GET  /api/learn/lesson",
            "POST /api/learn/quiz",
            "GET  /api/learn/scamiq",
            "GET  /api/benchmark",
            "GET  /api/samples",
            "GET  /api/history",
            "GET  /api/stats",
            "DELETE /api/data",
        ],
        "privacy": "No accounts. Anonymous device id only. Delete everything with DELETE /api/data.",
    }


# The Docker image bakes the built PWA in and serves it from this same origin,
# which also removes any need for CORS in production. In local development the
# Vite dev server serves the UI instead and this block is skipped.
_dist = Path(settings.frontend_dist) if settings.frontend_dist else None
if _dist and _dist.exists():
    from fastapi.staticfiles import StaticFiles

    log.info("Serving built frontend from %s", _dist)
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="spa")
else:
    app.get("/", tags=["meta"])(_api_index)


# Backwards-compatible alias used by the CLI smoke test.
def reset_rate_limiter() -> None:
    limiter().reset()
