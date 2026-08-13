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
from .scanner import (
    DEFAULT_RISK_FREE_RATE,
    fetch_chains,
    fetch_filings,
    fetch_history,
    fetch_intraday_for_date,
    fetch_news,
    fetch_quotes,
    fetch_spreads,
)
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


_spreads_cache: dict[str, tuple[float, dict]] = {}
_SPREADS_CACHE_TTL_SECONDS = 20.0


@app.get("/api/spreads")
async def spreads_endpoint(
    tickers: Optional[str] = Query(None, description="Comma-separated tickers. Max 15."),
    account_size: float = Query(5_000.0, ge=100.0, le=10_000_000.0),
    risk_pct: float = Query(0.02, gt=0.0, le=1.0),
    min_pop: float = Query(0.85, ge=0.5, le=0.99),
    max_width: float = Query(5.0, gt=0.0, le=50.0),
    nocache: bool = Query(False),
) -> dict:
    """Ranked 0DTE defined-risk credit spreads (the high-win-rate strategy).

    Sells vertical credit spreads whose short strike has a low probability of
    finishing in the money — modeled win probability >= ``min_pop``.
    """
    parsed = _parse_tickers(tickers, 15)
    key = f"{','.join(parsed)}:{account_size}:{risk_pct}:{min_pop}:{max_width}"
    now = time.time()
    cached = _spreads_cache.get(key)
    if cached and not nocache and (now - cached[0]) < _SPREADS_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        loop = asyncio.get_event_loop()
        items, notes = await loop.run_in_executor(
            None,
            lambda: fetch_spreads(parsed, account_size, risk_pct, min_pop, max_width),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Spread fetch failed")
        raise HTTPException(500, f"Spread fetch failed: {exc}") from exc
    response = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spreads": items,
        "notes": notes,
        "disclaimer": (
            "Defined-risk credit spreads: max loss is capped at width − credit. "
            "Modeled win probability, not a guarantee. Educational use only."
        ),
    }
    _spreads_cache[key] = (time.time(), response)
    return response


def _parse_tickers(tickers: Optional[str], max_n: int) -> list[str]:
    parsed = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else []
    if not parsed:
        raise HTTPException(400, "Provide at least one ticker, e.g. ?tickers=SPY,QQQ")
    if len(parsed) > max_n:
        raise HTTPException(400, f"Too many tickers — limit to {max_n}.")
    # de-dup, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for t in parsed:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# Short caches for the polling endpoints so rapid front-end refreshes don't
# hammer Yahoo. Quotes move fast (short TTL); news changes slowly (longer TTL).
_quote_cache: dict[str, tuple[float, dict]] = {}
_QUOTE_CACHE_TTL_SECONDS = 8.0
_news_cache: dict[str, tuple[float, dict]] = {}
_NEWS_CACHE_TTL_SECONDS = 120.0
_history_cache: dict[str, tuple[float, dict]] = {}
_HISTORY_CACHE_TTL_SECONDS = 30.0


@app.get("/api/quote")
async def quote(
    tickers: Optional[str] = Query(None, description="Comma-separated tickers. Max 30."),
    nocache: bool = Query(False),
) -> dict:
    """Lightweight last-price snapshot for auto-refreshing the UI."""
    parsed = _parse_tickers(tickers, 30)
    key = ",".join(parsed)
    now = time.time()
    cached = _quote_cache.get(key)
    if cached and not nocache and (now - cached[0]) < _QUOTE_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        loop = asyncio.get_event_loop()
        quotes, notes = await loop.run_in_executor(None, lambda: fetch_quotes(parsed))
    except Exception as exc:  # noqa: BLE001
        log.exception("Quote fetch failed")
        raise HTTPException(500, f"Quote fetch failed: {exc}") from exc
    response = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quotes": quotes,
        "notes": notes,
    }
    _quote_cache[key] = (time.time(), response)
    return response


@app.get("/api/history")
async def history(
    ticker: str = Query(..., description="Single ticker, e.g. SPY"),
    range: str = Query("1d", description="1d, 5d, 1mo, 3mo, 6mo, 1y, ytd"),
) -> dict:
    """OHLC bars for the instrument price chart."""
    sym = ticker.strip().upper()
    if not sym:
        raise HTTPException(400, "Provide a ticker, e.g. ?ticker=SPY")
    key = f"{sym}:{range}"
    now = time.time()
    cached = _history_cache.get(key)
    if cached and (now - cached[0]) < _HISTORY_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: fetch_history(sym, range))
    except Exception as exc:  # noqa: BLE001
        log.exception("History fetch failed")
        raise HTTPException(500, f"History fetch failed: {exc}") from exc
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    _history_cache[key] = (time.time(), data)
    return data


@app.get("/api/news")
async def news(
    tickers: Optional[str] = Query(None, description="Comma-separated tickers. Max 15."),
    limit: int = Query(20, ge=1, le=50),
    nocache: bool = Query(False),
) -> dict:
    """Recent news headlines for the Discover feed."""
    parsed = _parse_tickers(tickers, 15)
    key = f"{','.join(parsed)}:{limit}"
    now = time.time()
    cached = _news_cache.get(key)
    if cached and not nocache and (now - cached[0]) < _NEWS_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        loop = asyncio.get_event_loop()
        items, notes = await loop.run_in_executor(None, lambda: fetch_news(parsed, limit))
    except Exception as exc:  # noqa: BLE001
        log.exception("News fetch failed")
        raise HTTPException(500, f"News fetch failed: {exc}") from exc
    response = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "notes": notes,
    }
    _news_cache[key] = (time.time(), response)
    return response


_filings_cache: dict[str, tuple[float, dict]] = {}
_FILINGS_CACHE_TTL_SECONDS = 900.0  # filings change slowly


@app.get("/api/filings")
async def filings(
    tickers: Optional[str] = Query(None, description="Comma-separated tickers. Max 15."),
    limit: int = Query(6, ge=1, le=20),
    nocache: bool = Query(False),
) -> dict:
    """Recent SEC EDGAR investor filings (10-K/10-Q/8-K/proxy/etc.) per ticker."""
    parsed = _parse_tickers(tickers, 15)
    key = f"{','.join(parsed)}:{limit}"
    now = time.time()
    cached = _filings_cache.get(key)
    if cached and not nocache and (now - cached[0]) < _FILINGS_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        loop = asyncio.get_event_loop()
        by_ticker, notes = await loop.run_in_executor(None, lambda: fetch_filings(parsed, limit))
    except Exception as exc:  # noqa: BLE001
        log.exception("Filings fetch failed")
        raise HTTPException(500, f"Filings fetch failed: {exc}") from exc
    response = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filings": by_ticker,
        "notes": notes,
    }
    _filings_cache[key] = (time.time(), response)
    return response


@app.get("/api/replay/day")
async def replay_day(
    ticker: str = Query(..., description="Single ticker, e.g. SPY"),
    date: str = Query(..., description="Past date YYYY-MM-DD (last ~30 days)"),
) -> dict:
    """Intraday bars for a single past date, driving the replay practice mode.

    The front-end steps a simulated clock through these underlying bars and
    generates SYNTHETIC 0DTE option chains around each price (real historical
    option quotes aren't freely available) so the user can practice trades.
    """
    sym = ticker.strip().upper()
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, "date must be YYYY-MM-DD") from exc
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: fetch_intraday_for_date(sym, date))
    except Exception as exc:  # noqa: BLE001
        log.exception("Replay fetch failed")
        raise HTTPException(500, f"Replay fetch failed: {exc}") from exc
    if not data.get("bars"):
        data["notes"] = [
            "No intraday bars for that date — Yahoo only serves intraday history "
            "for roughly the last 30 days, and markets are closed on "
            "weekends/holidays. Pick a recent weekday."
        ]
    data["disclaimer"] = (
        "Replay uses real underlying prices but SYNTHETIC option chains "
        "(historical option quotes aren't free). Practice only."
    )
    return data


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
