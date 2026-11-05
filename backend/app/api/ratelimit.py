"""Small in-memory per-client rate limiter for the endpoints that spend LLM quota."""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Callable, Deque, Dict

from fastapi import HTTPException, Request

_MAX_TRACKED_CLIENTS = 5000


class SlidingWindowLimiter:
    def __init__(self, limit: Callable[[], int], window_seconds: float = 60.0):
        self._limit = limit
        self._window = window_seconds
        self._hits: Dict[str, Deque[float]] = {}

    def reset(self) -> None:
        self._hits.clear()

    def check(self, client: str) -> None:
        limit = self._limit()
        if limit <= 0:
            return  # 0 disables limiting
        now = time.monotonic()
        hits = self._hits.setdefault(client, deque())
        while hits and now - hits[0] > self._window:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(self._window - (now - hits[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please slow down and retry shortly.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        if len(self._hits) > _MAX_TRACKED_CLIENTS:
            self._evict(now)

    def _evict(self, now: float) -> None:
        # A client whose newest hit is outside the window has nothing left to limit.
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self._window]:
            del self._hits[key]
        # Still over the cap: every client is active, so drop the least recently seen.
        excess = len(self._hits) - _MAX_TRACKED_CLIENTS
        if excess > 0:
            for key in sorted(self._hits, key=lambda k: self._hits[k][-1])[:excess]:
                del self._hits[key]


def _env_limit() -> int:
    try:
        return int(os.getenv("LLM_RATE_LIMIT_PER_MINUTE", "30"))
    except ValueError:
        return 30


llm_limiter = SlidingWindowLimiter(_env_limit)


def _token_env_limit() -> int:
    try:
        return int(os.getenv("TOKEN_RATE_LIMIT_PER_MINUTE", "60"))
    except ValueError:
        return 60


# Owner-token and approval-link endpoints: bounds guessing and audit-ledger spam.
token_limiter = SlidingWindowLimiter(_token_env_limit)


def client_key(request: Request) -> str:
    """Address to rate-limit on.

    X-Forwarded-For is client-controlled except for the entries our own proxies append, so it is
    only read when TRUSTED_PROXY_HOPS says how many proxies sit in front of the app, and then only
    the entry that many hops from the right. By default the header is ignored.
    """
    try:
        hops = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
    except ValueError:
        hops = 0
    if hops > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


def _poll_env_limit() -> int:
    try:
        return int(os.getenv("POLL_RATE_LIMIT_PER_MINUTE", "240"))
    except ValueError:
        return 240


# The dashboard polls the owner's checkout list; a separate bucket keeps polling from starving
# the owner's own approve and revoke clicks, while still bounding token guessing on that route.
poll_limiter = SlidingWindowLimiter(_poll_env_limit)


async def llm_rate_limit(request: Request) -> None:
    llm_limiter.check(client_key(request))


async def token_rate_limit(request: Request) -> None:
    token_limiter.check(client_key(request))


async def poll_rate_limit(request: Request) -> None:
    poll_limiter.check(client_key(request))
