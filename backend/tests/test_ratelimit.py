"""Sliding-window limiter: client tracking stays bounded without weakening the limit."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import ratelimit
from app.api.ratelimit import SlidingWindowLimiter


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ratelimit, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_stale_clients_are_evicted_once_the_cap_is_passed(clock):
    limiter = SlidingWindowLimiter(lambda: 3, window_seconds=60.0)
    for i in range(ratelimit._MAX_TRACKED_CLIENTS):
        limiter.check(f"old-{i}")
    assert len(limiter._hits) == ratelimit._MAX_TRACKED_CLIENTS

    clock[0] += 61  # every earlier client is now outside the window
    for _ in range(3):
        limiter.check("active")
    limiter.check("newcomer")  # pushes the count past the cap and triggers the prune

    assert len(limiter._hits) <= 2
    with pytest.raises(HTTPException) as exc:
        limiter.check("active")
    assert exc.value.status_code == 429


def test_tracking_is_bounded_even_when_every_client_is_active(clock):
    limiter = SlidingWindowLimiter(lambda: 3, window_seconds=60.0)
    for _ in range(3):
        limiter.check("busy")
    for i in range(ratelimit._MAX_TRACKED_CLIENTS + 500):
        clock[0] += 0.001
        limiter.check(f"client-{i}")
    for _ in range(3):
        limiter.check("recent")

    assert len(limiter._hits) <= ratelimit._MAX_TRACKED_CLIENTS
    assert "recent" in limiter._hits
    with pytest.raises(HTTPException) as exc:
        limiter.check("recent")
    assert exc.value.status_code == 429
