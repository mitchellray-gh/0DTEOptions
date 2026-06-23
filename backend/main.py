"""FastAPI entry point for the 0DTE scanner."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .backtest import BacktestConfig, run_backtest
from .scanner import DEFAULT_RISK_FREE_RATE, fetch_chains
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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# Short-lived cache for the raw-chain proxy (quotes move fast; this only
# de-duplicates rapid repeat requests for the same watchlist).
_chain_cache: dict[str, tuple[float, dict]] = {}
_CHAIN_CACHE_TTL_SECONDS = 20.0


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/chain")
async def chain(
    tickers: Optional[str] = Query(
        None, description="Comma-separated tickers (e.g. SPY,QQQ). Max 25."),
    nocache: bool = Query(False),
) -> dict:
    """Thin data proxy: return raw 0DTE option chains for the given tickers.

    The browser can't call Yahoo directly (CORS), so this endpoint does only the
    fetch. All pricing, edge ranking and trade plans run client-side in
    ``frontend/src/lib/`` — this server intentionally does no scoring here.
    """
    parsed = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else []
    if not parsed:
        raise HTTPException(400, "Provide at least one ticker, e.g. ?tickers=SPY,QQQ")
    if len(parsed) > 25:
        raise HTTPException(400, "Too many tickers — limit a watchlist to 25.")

    cache_key = ",".join(parsed)
    now = time.time()
    cached = _chain_cache.get(cache_key)
    if cached and not nocache and (now - cached[0]) < _CHAIN_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        loop = asyncio.get_event_loop()
        chains, notes = await loop.run_in_executor(None, lambda: fetch_chains(parsed))
    except Exception as exc:  # noqa: BLE001
        log.exception("Chain fetch failed")
        raise HTTPException(500, f"Chain fetch failed: {exc}") from exc

    response = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chains": chains,
        "notes": notes,
    }
    _chain_cache[cache_key] = (time.time(), response)
    return response


@app.get("/api/sp500")
def sp500_tickers() -> dict:
    """Return the current S&P 500 ticker list."""
    tickers = fetch_sp500_tickers()
    return {"count": len(tickers), "tickers": tickers}


class BacktestRequest(BaseModel):
    """Parameters for a strategy backtest.

    Defaults run an offline, deterministic synthetic simulation (``gbm``). Set
    ``source='yfinance'`` to drive the simulation off real historical daily
    bars. Results are a SIMULATION, not proof of live profitability.
    """
    source: Literal["gbm", "yfinance"] = "gbm"
    tickers: list[str] = Field(default_factory=lambda: ["SPY"], max_length=10)
    days: int = Field(60, ge=5, le=252)
    seed: int = 42
    account_size: float = Field(5_000.0, ge=100.0, le=10_000_000.0)
    risk_per_trade_pct: float = Field(0.02, gt=0.0, le=1.0)
    risk_free_rate: float = Field(DEFAULT_RISK_FREE_RATE, ge=0.0, le=0.25)
    max_trades_per_day: int = Field(3, ge=1, le=20)
    base_iv: float = Field(0.20, gt=0.0, le=3.0)
    iv_noise: float = Field(0.03, ge=0.0, le=1.0)
    mean_reversion: float = Field(0.6, ge=0.0, le=1.2)
    reversion_prob: float = Field(0.55, ge=0.0, le=1.0)
    commission_per_contract: float = Field(0.65, ge=0.0, le=10.0)
    start: Optional[str] = Field(None, description="yfinance start date YYYY-MM-DD")
    end: Optional[str] = Field(None, description="yfinance end date YYYY-MM-DD")


@app.post("/api/backtest")
async def backtest(req: BacktestRequest) -> dict:
    """Backtest the 0DTE scanner strategy and return trades + metrics.

    The response includes a ``disclaimer`` describing the simulation's
    assumptions. The trade list is capped at the most recent 500 entries; the
    ``metrics`` reflect every trade.
    """
    tickers = tuple(t.strip().upper() for t in req.tickers if t.strip()) or ("SPY",)
    cfg = BacktestConfig(
        source=req.source,
        tickers=tickers,
        days=req.days,
        start=req.start,
        end=req.end,
        seed=req.seed,
        account_size=req.account_size,
        risk_per_trade_pct=req.risk_per_trade_pct,
        risk_free_rate=req.risk_free_rate,
        max_trades_per_day=req.max_trades_per_day,
        base_iv=req.base_iv,
        iv_noise=req.iv_noise,
        mean_reversion=req.mean_reversion,
        reversion_prob=req.reversion_prob,
        commission_per_contract=req.commission_per_contract,
    )
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: run_backtest(cfg))
    except Exception as exc:  # noqa: BLE001
        log.exception("Backtest failed")
        raise HTTPException(500, f"Backtest failed: {exc}") from exc

    payload = result.to_dict()
    # Keep the JSON response bounded and strictly valid (no Infinity).
    pf = payload["metrics"].get("profit_factor")
    if isinstance(pf, float) and math.isinf(pf):
        payload["metrics"]["profit_factor"] = None
    if len(payload["trades"]) > 500:
        payload["notes"].append(
            f"Trade list truncated to the most recent 500 of "
            f"{len(payload['trades'])} total (metrics cover all trades)."
        )
        payload["trades"] = payload["trades"][-500:]
    return payload
