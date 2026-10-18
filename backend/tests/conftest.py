"""Shared test fixtures.

The API is rate limited (on purpose). The suite makes many requests in a row, so
each test starts with a clean limiter window — and one test asserts the limiter
itself still fires, so we are not silencing the behaviour we ship.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.main import reset_rate_limiter

    reset_rate_limiter()
    yield
    reset_rate_limiter()
