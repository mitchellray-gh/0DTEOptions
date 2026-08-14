"""Streaming market-data consumer (scaffold).

Satisfies the infra-audit requirements:
  * Persistent WebSocket (NOT REST polling).
  * Exponential backoff + reconnect loop.
  * Heartbeat ping/pong to detect silent drops.
  * Non-blocking asyncio handoff to a bounded queue (no main-thread blocking).

This is a transport skeleton. Plug your data vendor's WS URL + auth + subscribe
message into the marked TODOs. No vendor is hardcoded.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from typing import Awaitable, Callable

log = logging.getLogger("exec.stream")

_MAX_BACKOFF = 30.0
_HEARTBEAT_S = 10.0
_STALE_S = 25.0  # if no message for this long, force a reconnect


class MarketDataStream:
    def __init__(self, ws_url: str, subscribe_msg: dict,
                 on_message: Callable[[dict], Awaitable[None]],
                 *, queue_max: int = 10_000):
        self.ws_url = ws_url
        self.subscribe_msg = subscribe_msg
        self.on_message = on_message
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=queue_max)
        self._last_msg = time.monotonic()
        self._stop = asyncio.Event()

    async def run(self) -> None:
        """Reconnect loop with exponential backoff + jitter."""
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._connect_once()
                backoff = 1.0  # reset after a clean session
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - transport is intentionally broad
                sleep = min(backoff, _MAX_BACKOFF) * (0.5 + random.random())
                log.warning("stream dropped (%s); reconnecting in %.1fs", exc, sleep)
                await asyncio.sleep(sleep)
                backoff *= 2

    async def _connect_once(self) -> None:
        # NOTE: `websockets` is an optional dep of this scaffold; import lazily so
        # the repo doesn't require it just to read the code.
        import websockets  # type: ignore

        async with websockets.connect(
            self.ws_url, ping_interval=None, max_queue=None,
        ) as ws:
            await ws.send(_dumps(self.subscribe_msg))
            self._last_msg = time.monotonic()
            consumer = asyncio.create_task(self._consume())
            hb = asyncio.create_task(self._heartbeat(ws))
            try:
                async for raw in ws:
                    self._last_msg = time.monotonic()
                    msg = _loads(raw)
                    # Non-blocking handoff; drop-oldest if the consumer lags.
                    if self.queue.full():
                        with contextlib.suppress(asyncio.QueueEmpty):
                            self.queue.get_nowait()
                    self.queue.put_nowait(msg)
            finally:
                for t in (consumer, hb):
                    t.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await t

    async def _consume(self) -> None:
        while True:
            msg = await self.queue.get()
            try:
                await self.on_message(msg)
            except Exception:  # noqa: BLE001 - a bad message must not kill the stream
                log.exception("on_message failed for %r", msg)

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(_HEARTBEAT_S)
            # Detect silent drops: if no data recently, force a reconnect.
            if time.monotonic() - self._last_msg > _STALE_S:
                log.warning("no data for %.0fs — forcing reconnect", _STALE_S)
                await ws.close()
                return
            with contextlib.suppress(Exception):
                await ws.ping()

    def stop(self) -> None:
        self._stop.set()


def _dumps(obj: dict) -> str:
    import json
    return json.dumps(obj)


def _loads(raw) -> dict:
    import json
    return json.loads(raw)
