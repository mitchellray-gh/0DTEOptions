"""Token-bucket rate limiter + 429/418 backoff (scaffold).

Satisfies the infra-audit requirement: broker/data APIs must never be hammered
with per-contract REST calls, and 429 (Too Many Requests) / 418 responses must
trigger jittered exponential backoff — not a tight retry loop or an IP ban.

Design rule enforced by the accompanying README: subscribe to market data by
UNDERLYING over the WebSocket and compute greeks locally; use REST only for
order actions, gated through this limiter.
"""
from __future__ import annotations

import asyncio
import random
import time


class TokenBucket:
    """Async token bucket. `rate` tokens/sec, burst up to `capacity`."""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity,
                                   self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                await asyncio.sleep(deficit / self.rate)


class RateLimitedClient:
    """Wraps an async HTTP call with a token bucket + 429/418 backoff."""

    def __init__(self, bucket: TokenBucket, *, max_retries: int = 6):
        self.bucket = bucket
        self.max_retries = max_retries

    async def call(self, coro_factory):
        """`coro_factory()` -> awaitable returning an object with `.status`.

        Retries on 429/418 with jittered exponential backoff, honoring a
        Retry-After header when present.
        """
        backoff = 1.0
        for attempt in range(self.max_retries):
            await self.bucket.acquire()
            resp = await coro_factory()
            status = getattr(resp, "status", 200)
            if status not in (429, 418):
                return resp
            retry_after = _retry_after(resp)
            sleep = retry_after if retry_after is not None else \
                min(backoff, 30.0) * (0.5 + random.random())
            await asyncio.sleep(sleep)
            backoff *= 2
        raise RuntimeError("rate limit: exhausted retries")


def _retry_after(resp) -> float | None:
    try:
        headers = getattr(resp, "headers", {}) or {}
        val = headers.get("Retry-After")
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
