"""Small security helpers: rate limiting + input guards.

No external dependencies (no redis) because ScamLens is a single-instance demo
deployment; the limiter is in-process and documented as such.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    def __init__(self, per_minute: int = 30, burst: int = 8) -> None:
        self.per_minute = per_minute
        self.burst = burst
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.time()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "rate_limited", "message": "Too many requests. Please wait a minute and try again."},
            )
        # burst guard (per 5 seconds)
        recent = [t for t in window if now - t < 5]
        if len(recent) >= self.burst:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "too_fast", "message": "You are scanning very fast — take a short break."},
            )
        window.append(now)

    def reset(self) -> None:
        self._hits.clear()


def client_key(request: Request, device_id: str | None = None) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{(device_id or '')[:32]}"


def guard_text(text: str, max_chars: int) -> str:
    if len(text) > max_chars:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": "text_too_long", "message": f"Message is too long (max {max_chars} characters)."},
        )
    return text


def guard_image(data: bytes, max_bytes: int, content_type: str | None) -> None:
    if not data:
        raise HTTPException(status_code=400, detail={"error": "empty_image", "message": "No image data received."})
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={"error": "image_too_large", "message": f"Image is too large (max {max_bytes // (1024 * 1024)} MB)."},
        )
    allowed = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
    if content_type and content_type.lower() not in allowed:
        raise HTTPException(
            status_code=415,
            detail={"error": "unsupported_image", "message": "Please upload a PNG, JPEG, WEBP or GIF screenshot."},
        )
