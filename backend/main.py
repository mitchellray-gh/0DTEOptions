"""FastAPI entry point for the 0DTE scanner."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import ScanResponse
from .scanner import DEFAULT_RISK_FREE_RATE, DEFAULT_TICKERS, scan_tickers

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


# Tiny in-memory cache to keep yfinance load reasonable (it's slow).
_cache: dict[str, tuple[float, ScanResponse]] = {}
_CACHE_TTL_SECONDS = 30.0


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/opportunities", response_model=ScanResponse)
def opportunities(
    tickers: Optional[str] = Query(
        None,
        description="Comma-separated tickers, e.g. SPY,QQQ. Defaults to a "
                    "curated set of liquid daily-expiry underlyings.",
    ),
    account_size: float = Query(5000.0, ge=100.0, le=10_000_000.0),
    risk_per_trade_pct: float = Query(0.02, gt=0.0, le=1.0),
    risk_free_rate: float = Query(DEFAULT_RISK_FREE_RATE, ge=0.0, le=0.25),
    max_results: int = Query(50, ge=1, le=200),
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

    try:
        results, notes = scan_tickers(
            tickers=parsed,
            risk_free=risk_free_rate,
            account_size_usd=account_size,
            risk_per_trade_pct=risk_per_trade_pct,
            max_results=max_results,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Scan failed")
        raise HTTPException(500, f"Scan failed: {exc}") from exc

    response = ScanResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        risk_free_rate=risk_free_rate,
        tickers_scanned=parsed,
        count=len(results),
        results=results,
        notes=notes,
    )
    _cache[cache_key] = (now, response)
    return response
