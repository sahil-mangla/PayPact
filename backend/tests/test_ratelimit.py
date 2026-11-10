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


def _request(xff=None, host="10.0.0.1"):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))


def test_forwarded_header_is_ignored_by_default(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    assert ratelimit.client_key(_request("6.6.6.6")) == "10.0.0.1"


def test_spoofed_leading_entries_do_not_change_the_client(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    real = _request("1.1.1.1, 203.0.113.9")
    spoof = _request("2.2.2.2, 203.0.113.9")
    assert ratelimit.client_key(real) == ratelimit.client_key(spoof) == "203.0.113.9"


def test_falls_back_to_the_peer_when_the_header_is_shorter_than_the_hops(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    assert ratelimit.client_key(_request("203.0.113.9")) == "10.0.0.1"


def test_polling_has_its_own_bucket_so_it_cannot_starve_approvals():
    from app.api.ratelimit import poll_limiter, token_limiter

    token_limiter.reset()
    poll_limiter.reset()
    for _ in range(100):
        poll_limiter.check("owner")
    token_limiter.check("owner")  # still has its full allowance
