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
            for key in [k for k, v in self._hits.items() if not v][:1000]:
                del self._hits[key]


def _env_limit() -> int:
    try:
        return int(os.getenv("LLM_RATE_LIMIT_PER_MINUTE", "20"))
    except ValueError:
        return 20


llm_limiter = SlidingWindowLimiter(_env_limit)


async def llm_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    llm_limiter.check(client)
