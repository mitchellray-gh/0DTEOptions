"""FastAPI entry point for the 0DTE scanner."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import ScanResponse
from .scanner import DEFAULT_RISK_FREE_RATE, DEFAULT_TICKERS, SP500_SENTINEL, scan_tickers
from .sp500 import fetch_sp500_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("zdte")

app = FastAPI(
    title="0DTE Options Scanner",
    description="Identify undervalued zero-days-to-expiration options and "
                "produce explicit trade instructions.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # local dev tool
    allow_methods=["GET"],
    allow_headers=["*"],
)


# Cache — longer TTL for large S&P 500 scans.
_cache: dict[str, tuple[float, ScanResponse]] = {}
_CACHE_TTL_SECONDS = 300.0

# One lock per cache_key to prevent duplicate concurrent scans.
_scan_locks: dict[str, asyncio.Lock] = {}
_global_lock = threading.Lock()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/sp500")
def sp500_tickers() -> dict:
    """Return the current S&P 500 ticker list."""
    tickers = fetch_sp500_tickers()
    return {"count": len(tickers), "tickers": tickers}


@app.get("/api/opportunities", response_model=ScanResponse)
async def opportunities(
    tickers: Optional[str] = Query(
        None,
        description="Comma-separated tickers, or 'SP500' to scan the full "
                    "S&P 500. Defaults to SP500.",
    ),
    account_size: float = Query(5000.0, ge=100.0, le=10_000_000.0),
    risk_per_trade_pct: float = Query(0.02, gt=0.0, le=1.0),
    risk_free_rate: float = Query(DEFAULT_RISK_FREE_RATE, ge=0.0, le=0.25),
    max_results: int = Query(50, ge=1, le=500),
    nocache: bool = Query(False),
) -> ScanResponse:
    parsed = (
        [t.strip().upper() for t in tickers.split(",") if t.strip()]
        if tickers else list(DEFAULT_TICKERS)
    )
    if not parsed:
        raise HTTPException(400, "No valid tickers provided")

    cache_key = (
        f"{','.join(parsed)}|{account_size}|{risk_per_trade_pct}|"
        f"{risk_free_rate}|{max_results}"
    )
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and not nocache and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    # Get or create an async lock for this cache_key so duplicate
    # requests wait instead of spawning parallel scans.
    with _global_lock:
        if cache_key not in _scan_locks:
            _scan_locks[cache_key] = asyncio.Lock()
        key_lock = _scan_locks[cache_key]

    async with key_lock:
        # Re-check cache — another coroutine may have just finished.
        cached = _cache.get(cache_key)
        if cached and not nocache and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

        try:
            loop = asyncio.get_event_loop()
            results, notes, rejection_summary = await loop.run_in_executor(
                None,
                lambda: scan_tickers(
                    tickers=parsed,
                    risk_free=risk_free_rate,
                    account_size_usd=account_size,
                    risk_per_trade_pct=risk_per_trade_pct,
                    max_results=max_results,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Scan failed")
            raise HTTPException(500, f"Scan failed: {exc}") from exc

        display_tickers = []
        for t in parsed:
            if t == SP500_SENTINEL:
                display_tickers.append(f"S&P 500 ({len(fetch_sp500_tickers())} stocks)")
            else:
                display_tickers.append(t)

        response = ScanResponse(
            generated_at=datetime.now(timezone.utc).isoformat(),
            risk_free_rate=risk_free_rate,
            tickers_scanned=display_tickers,
            count=len(results),
            results=results,
            notes=notes,
            rejection_summary=rejection_summary,
        )
        _cache[cache_key] = (time.time(), response)
        return response
