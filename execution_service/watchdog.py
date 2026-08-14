"""Risk watchdog with dead-man's-switch (scaffold).

Satisfies the infra-audit requirement: risk must be held SERVER-SIDE, independent
of any UI/browser. The watchdog:
  * Flattens all positions if the market-data feed goes stale (dead-man's-switch)
    — you never want an open 0DTE condor running blind through a data outage.
  * Enforces a hard "flatten by HH:MM ET" cutoff (no overnight / no pin risk).
  * Enforces a daily max-loss kill switch.

It is deliberately independent of the strategy loop: even if the strategy process
hangs, the watchdog can still flatten.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

log = logging.getLogger("exec.watchdog")


class Watchdog:
    def __init__(self, broker, *, feed_stale_s: float = 20.0,
                 flatten_after_utc: str = "19:55",   # 15:55 ET
                 daily_max_loss: float = 0.03,        # 3% of equity
                 poll_s: float = 1.0):
        self.broker = broker
        self.feed_stale_s = feed_stale_s
        self.flatten_after_utc = flatten_after_utc
        self.daily_max_loss = daily_max_loss
        self.poll_s = poll_s
        self._last_feed = asyncio.get_event_loop().time()
        self._flattened = False
        self._stop = asyncio.Event()

    def heartbeat(self) -> None:
        """Call on every inbound market-data message to keep the switch armed."""
        self._last_feed = asyncio.get_event_loop().time()

    async def run(self, *, start_equity: float, get_equity) -> None:
        """Main loop. `get_equity()` -> current account equity (float)."""
        while not self._stop.is_set():
            await asyncio.sleep(self.poll_s)
            now = asyncio.get_event_loop().time()

            # 1) Dead-man's-switch: feed went silent -> flatten.
            if now - self._last_feed > self.feed_stale_s and not self._flattened:
                log.error("FEED STALE %.0fs — flattening all positions",
                          now - self._last_feed)
                await self._flatten("feed_stale")
                continue

            # 2) Hard time cutoff (no overnight holds).
            hm = dt.datetime.now(dt.timezone.utc).strftime("%H:%M")
            if hm >= self.flatten_after_utc and not self._flattened:
                log.info("time cutoff %s reached — flattening", self.flatten_after_utc)
                await self._flatten("time_cutoff")
                continue

            # 3) Daily max-loss kill switch.
            eq = get_equity()
            if eq <= start_equity * (1 - self.daily_max_loss) and not self._flattened:
                log.error("daily max loss hit (equity %.2f) — flattening + halting", eq)
                await self._flatten("max_loss")
                self.stop()

    async def _flatten(self, reason: str) -> None:
        try:
            await self.broker.flatten_all()   # adapter: market-close every position
            self._flattened = True
            log.warning("FLATTENED all positions (reason=%s)", reason)
        except Exception:  # noqa: BLE001 - flatten must be retried, never silent
            log.exception("flatten FAILED — retrying next tick (reason=%s)", reason)

    def reset_daily(self) -> None:
        self._flattened = False

    def stop(self) -> None:
        self._stop.set()
