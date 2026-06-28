"""0DTE option-chain scanner.

Pipeline:
  1. For each ticker, fetch the option chain that expires today (0DTE).
     If today's chain is unavailable (weekend / holiday / non-weekly), fall
     back to the nearest expiry within the next ~3 days.
  2. Estimate a *reference* implied volatility for each chain by taking the
     volume-weighted IV of liquid, near-the-money options. This is the
     market's own consensus IV — we use it as our "fair value" anchor and
     then look for individual contracts whose ask is materially below the
     Black-Scholes price computed at that reference IV.
  3. Filter for liquidity (bid > 0, volume / OI minimums, sane spread) and
     rank by edge.

The web app calls :func:`fetch_chains` for raw chains and scores them in the
browser; the per-contract helpers here (:func:`compute_reference_iv`,
:func:`_evaluate_contract`, :func:`_build_plan`) are also reused by the
backtester in :mod:`backend.backtest`.
"""
from __future__ import annotations

import logging
import math
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from .models import Opportunity, RejectedContract, TradePlan
from .pricing import bs_greeks, bs_price, implied_vol
from .sp500 import fetch_sp500_tickers

log = logging.getLogger(__name__)

# Sentinel value — when the API receives "SP500" we expand to the full list.
SP500_SENTINEL = "SP500"

# Legacy short list kept for quick scans
DEFAULT_TICKERS: list[str] = [SP500_SENTINEL]

# How many tickers to fetch in parallel (kept low to avoid Yahoo rate limits)
_MAX_WORKERS = 4

# Minimum gap between any two Yahoo Finance request bursts (seconds).
# Each ticker triggers 2-3 HTTP calls so this effectively caps throughput.
_MIN_REQUEST_GAP_S = 0.5

# Retry settings for rate-limited requests
_MAX_RETRIES = 3
_RETRY_BASE_DELAY_S = 3.0

# Global throttle lock — ensures at most one ticker starts fetching at a time,
# with a mandatory gap between starts.
_throttle_lock = threading.Lock()
_last_request_ts: float = 0.0


class _RateLimited(Exception):
    """Raised when Yahoo Finance returns a 429 / rate-limit error."""
    pass


def _throttled_sleep():
    """Sleep if needed to maintain _MIN_REQUEST_GAP_S between request bursts."""
    global _last_request_ts
    with _throttle_lock:
        now = _time.monotonic()
        elapsed = now - _last_request_ts
        if elapsed < _MIN_REQUEST_GAP_S:
            _time.sleep(_MIN_REQUEST_GAP_S - elapsed)
        _last_request_ts = _time.monotonic()

# Treasury T-bill yield is a reasonable proxy; for 0DTE pricing the rate
# barely matters.
DEFAULT_RISK_FREE_RATE = 0.045

# Minimum-quality filters
MIN_VOLUME = 50
MIN_OPEN_INTEREST = 100
MIN_BID = 0.05
MAX_REL_SPREAD = 0.25       # (ask-bid)/mid
MAX_STRIKE_DISTANCE_PCT = 0.50  # reject strikes >50% away from spot (non-standard / post-split)
NEAR_THE_MONEY_PCT = 0.03   # +/-3% of spot for the reference IV calc


@dataclass
class _ChainContext:
    underlying: str
    spot: float
    expiry_iso: str
    minutes_to_expiry: int
    T_years: float
    reference_iv: float


def _today_utc_date() -> datetime:
    return datetime.now(timezone.utc)


def _pick_expiry(expirations: Iterable[str], today: datetime) -> str | None:
    """Choose the closest expiry that is today or within the next 3 days."""
    today_d = today.date()
    best: tuple[int, str] | None = None
    for exp in expirations:
        try:
            d = datetime.strptime(exp, "%Y-%m-%d").date()
        except ValueError:
            continue
        days = (d - today_d).days
        if days < 0 or days > 3:
            continue
        if best is None or days < best[0]:
            best = (days, exp)
    return best[1] if best else None


def _minutes_to_us_market_close(expiry_iso: str, now: datetime) -> int:
    """Time until 16:00 America/New_York on the expiry date, in minutes.

    We approximate without pytz by using UTC offsets. EDT = UTC-4, EST = UTC-5.
    For 0DTE this is good enough for ranking; the engine doesn't rely on
    sub-minute precision.
    """
    expiry_d = datetime.strptime(expiry_iso, "%Y-%m-%d").date()
    # Naive: assume EDT (UTC-4). Close 16:00 ET => 20:00 UTC.
    close_utc = datetime(expiry_d.year, expiry_d.month, expiry_d.day,
                         20, 0, 0, tzinfo=timezone.utc)
    delta = close_utc - now
    return max(int(delta.total_seconds() // 60), 1)


def _safe_mid(bid: float, ask: float, last: float) -> float:
    if bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2
    if last > 0:
        return last
    return max(bid, ask, 0.0)


def compute_reference_iv(calls: pd.DataFrame, puts: pd.DataFrame,
                         spot: float) -> float | None:
    """Chain consensus IV = volume-weighted IV of near-the-money contracts.

    Considers contracts within ``NEAR_THE_MONEY_PCT`` of ``spot`` that have a
    sane IV (1%-500%) and non-zero volume, and returns the volume-weighted mean
    of their implied volatilities. Falls back to the whole-chain median IV when
    nothing qualifies near the money, or ``None`` when the chain has no usable
    IVs at all.

    This is the single source of truth for the chain's "fair" IV anchor: both
    the live scanner and the backtester call it so they price fair value the
    same way.
    """
    lo, hi = spot * (1 - NEAR_THE_MONEY_PCT), spot * (1 + NEAR_THE_MONEY_PCT)
    near = pd.concat([
        calls.assign(_type="call"),
        puts.assign(_type="put"),
    ])
    near = near[(near["strike"] >= lo) & (near["strike"] <= hi)]
    near = near[(near["impliedVolatility"] > 0.01) & (near["impliedVolatility"] < 5)]
    near = near[near["volume"].fillna(0) > 0]

    if near.empty:
        # Fallback: median IV across the whole chain
        all_iv = pd.concat([calls["impliedVolatility"], puts["impliedVolatility"]])
        all_iv = all_iv[(all_iv > 0.01) & (all_iv < 5)]
        if all_iv.empty:
            return None
        return float(all_iv.median())

    weights = near["volume"].fillna(0).astype(float).clip(lower=1.0)
    return float(np.average(near["impliedVolatility"].astype(float), weights=weights))


def _build_chain_context_with_retry(ticker: str, risk_free: float,
                                     now: datetime) -> tuple[_ChainContext, pd.DataFrame, pd.DataFrame] | None:
    """Wrapper around _build_chain_context with rate-limit-aware retries.

    The first call (options list) is lightweight and doesn't need throttling.
    We only throttle before fetching the full chain + spot price.
    """
    # Quick check: does this ticker even have options expiring soon?
    try:
        t = yf.Ticker(ticker)
        expirations = t.options or []
    except Exception as exc:
        if _is_rate_limit_error(exc):
            _time.sleep(_RETRY_BASE_DELAY_S)
            return None
        log.warning("yfinance options() failed for %s: %s", ticker, exc)
        return None

    expiry = _pick_expiry(expirations, now)
    if expiry is None:
        log.info("No 0DTE/near-dated expiry for %s", ticker)
        return None  # skip fast — no throttle wasted

    # We have a valid expiry; now fetch the chain (heavier calls)
    for attempt in range(_MAX_RETRIES):
        try:
            _throttled_sleep()
            return _build_chain_context(ticker, risk_free, now, t, expiry)
        except _RateLimited:
            delay = _RETRY_BASE_DELAY_S * (2 ** attempt)
            log.info("Rate-limited on %s — retrying in %.0fs (attempt %d/%d)",
                     ticker, delay, attempt + 1, _MAX_RETRIES)
            _time.sleep(delay)
    log.warning("Gave up on %s after %d rate-limit retries", ticker, _MAX_RETRIES)
    return None


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a Yahoo Finance rate-limit error."""
    msg = str(exc).lower()
    return "rate limit" in msg or "too many request" in msg or "429" in msg


def _build_chain_context(ticker: str, risk_free: float,
                         now: datetime,
                         t: yf.Ticker | None = None,
                         expiry: str | None = None,
                         ) -> tuple[_ChainContext, pd.DataFrame, pd.DataFrame] | None:
    """Fetch the chain and compute the reference IV from near-the-money
    contracts. Returns (context, calls_df, puts_df) or None on failure.
    Raises _RateLimited on 429-type errors so the caller can retry.

    If *t* and *expiry* are supplied (pre-fetched by the retry wrapper),
    skip the options-list lookup to save a network round-trip.
    """
    if t is None:
        try:
            t = yf.Ticker(ticker)
            expirations = t.options or []
        except Exception as exc:
            if _is_rate_limit_error(exc):
                raise _RateLimited(str(exc)) from exc
            log.warning("yfinance options() failed for %s: %s", ticker, exc)
            return None
        expiry = _pick_expiry(expirations, now)
        if expiry is None:
            log.info("No 0DTE/near-dated expiry for %s", ticker)
            return None

    try:
        chain = t.option_chain(expiry)
    except Exception as exc:
        if _is_rate_limit_error(exc):
            raise _RateLimited(str(exc)) from exc
        log.warning("option_chain failed for %s %s: %s", ticker, expiry, exc)
        return None

    calls = chain.calls.copy()
    puts = chain.puts.copy()
    if calls.empty and puts.empty:
        return None

    # Spot price — try fast_info first (single HTTP call), fall back to
    # history() only if needed.  This saves ~1-2s per ticker.
    spot = None
    try:
        spot = float(t.fast_info["last_price"])
    except Exception:
        pass
    if spot is None or spot <= 0:
        try:
            hist = t.history(period="1d", interval="5m")
            spot = float(hist["Close"].dropna().iloc[-1])
        except Exception as exc:
            log.warning("Could not get spot for %s: %s", ticker, exc)
            return None

    minutes = _minutes_to_us_market_close(expiry, now)
    T = max(minutes, 1) / (60 * 24 * 365)

    # Reference IV: VWAP of yfinance-provided IVs for near-the-money contracts.
    ref_iv = compute_reference_iv(calls, puts, spot)
    if ref_iv is None:
        return None

    ctx = _ChainContext(
        underlying=ticker,
        spot=spot,
        expiry_iso=expiry,
        minutes_to_expiry=minutes,
        T_years=T,
        reference_iv=ref_iv,
    )
    return ctx, calls, puts


def _evaluate_contract(row: pd.Series, option_type: str,
                       ctx: _ChainContext, risk_free: float) -> Opportunity | RejectedContract:
    """Evaluate a single contract. Returns an Opportunity on success or a
    RejectedContract explaining why it was filtered out."""
    bid = float(row.get("bid") or 0.0) if not pd.isna(row.get("bid")) else 0.0
    ask = float(row.get("ask") or 0.0) if not pd.isna(row.get("ask")) else 0.0
    last = float(row.get("lastPrice") or 0.0) if not pd.isna(row.get("lastPrice")) else 0.0
    raw_vol = row.get("volume")
    volume = int(raw_vol) if raw_vol is not None and not pd.isna(raw_vol) else 0
    raw_oi = row.get("openInterest")
    oi = int(raw_oi) if raw_oi is not None and not pd.isna(raw_oi) else 0
    strike = float(row["strike"])
    symbol = str(row["contractSymbol"])

    def _reject(reason: str, detail: str, lesson: str) -> RejectedContract:
        return RejectedContract(
            symbol=symbol, underlying=ctx.underlying, strike=strike,
            option_type=option_type, bid=round(bid, 4), ask=round(ask, 4),
            volume=volume, open_interest=oi,
            rejection_reason=reason, rejection_detail=detail, lesson=lesson,
        )

    # Strike-distance gate — catches non-standard (post-split) contracts
    # whose strikes are wildly far from the current spot price.
    strike_distance = abs(strike - ctx.spot) / max(ctx.spot, 0.01)
    if strike_distance > MAX_STRIKE_DISTANCE_PCT:
        return _reject(
            "non_standard_strike",
            f"Strike ${strike:g} is {strike_distance:.0%} from spot "
            f"${ctx.spot:.2f} — exceeds {MAX_STRIKE_DISTANCE_PCT:.0%} limit.",
            "After a stock split, old option contracts keep their original "
            "strike prices but with adjusted deliverables (e.g. 10 shares "
            "instead of 100). These 'non-standard' contracts look wildly "
            "mispriced but they aren't — they just follow different rules. "
            "Our scanner skips any strike more than 50% from the current "
            "price to avoid these traps.",
        )

    # Liquidity gate
    if bid < MIN_BID or ask <= 0:
        return _reject(
            "low_bid_ask",
            f"Bid ${bid:.2f} < min ${MIN_BID} or ask ${ask:.2f} ≤ 0.",
            "A very low bid means market makers aren't willing to pay much for "
            "this contract. If you bought it, you'd have trouble selling it back "
            "at a fair price. Always look for contracts where both bid AND ask "
            "are meaningful — that indicates active two-sided interest.",
        )
    if volume < MIN_VOLUME or oi < MIN_OPEN_INTEREST:
        return _reject(
            "low_liquidity",
            f"Volume {volume:,} < {MIN_VOLUME:,} or OI {oi:,} < {MIN_OPEN_INTEREST:,}.",
            "Volume is how many contracts traded TODAY; Open Interest (OI) is how "
            "many contracts are currently outstanding. Low numbers mean few "
            "participants are trading this strike — you could get trapped in a "
            "position with no one willing to buy from you. For 0DTE, high "
            "liquidity is critical because you need to exit before expiration.",
        )
    mid = _safe_mid(bid, ask, last)
    if mid <= 0:
        return _reject(
            "no_valid_mid",
            "Could not compute a valid midpoint price.",
            "The midpoint ((bid + ask) / 2) is our best estimate of the "
            "'true' market price. If we can't compute one, something is "
            "wrong with the quotes — stale data, a halted underlying, etc.",
        )
    rel_spread = (ask - bid) / mid if mid > 0 else 1.0
    if rel_spread > MAX_REL_SPREAD:
        return _reject(
            "wide_spread",
            f"Relative spread {rel_spread:.1%} > max {MAX_REL_SPREAD:.0%} "
            f"(bid ${bid:.2f}, ask ${ask:.2f}, mid ${mid:.2f}).",
            "The bid-ask spread is the 'toll' you pay to enter and exit a trade. "
            "A wide spread (e.g. bid $0.10 / ask $0.20) means you'd instantly "
            "lose ~50% of your premium just from the spread. Tight spreads "
            "(< 25% of mid) indicate fair, efficient pricing.",
        )

    fair = bs_price(ctx.spot, strike, ctx.T_years, risk_free,
                    ctx.reference_iv, option_type)
    edge_abs = fair - ask
    if edge_abs <= 0:
        return _reject(
            "no_edge",
            f"Fair value ${fair:.2f} ≤ ask ${ask:.2f} — no positive edge.",
            "We compute each contract's 'fair value' using the Black-Scholes "
            "model with the chain's consensus implied volatility (IV). If the "
            "ask price is already AT or ABOVE fair value, you'd be paying full "
            "price or overpaying. We only want contracts where the market is "
            "under-pricing relative to the rest of the chain.",
        )
    edge_pct = edge_abs / ask
    # Require at least 5% edge to be worth highlighting
    if edge_pct < 0.05:
        return _reject(
            "insufficient_edge",
            f"Edge {edge_pct:.1%} < 5% minimum (fair ${fair:.2f} vs ask ${ask:.2f}).",
            "Even when a contract IS technically undervalued, a tiny edge "
            "(< 5%) gets eaten by commissions, slippage, and the bid-ask "
            "spread on exit. We set a 5% minimum to ensure the potential "
            "profit justifies the risk of a 0DTE trade, where you can lose "
            "100% of your premium in minutes.",
        )

    market_iv = implied_vol(mid, ctx.spot, strike, ctx.T_years, risk_free, option_type)
    greeks = bs_greeks(ctx.spot, strike, ctx.T_years, risk_free,
                       ctx.reference_iv, option_type)

    # Composite score: blend edge_pct, liquidity (log volume), and how
    # close to ATM we are (gamma-rich names get a small bump).
    liq_score = math.log10(max(volume, 1) + max(oi, 1))
    atm_score = 1.0 / (1.0 + abs(strike - ctx.spot) / max(ctx.spot * 0.01, 1e-6))
    score = edge_pct * 100 + liq_score + atm_score

    return Opportunity(
        symbol=symbol,
        underlying=ctx.underlying,
        underlying_price=round(ctx.spot, 4),
        expiration=ctx.expiry_iso,
        strike=strike,
        option_type=option_type,  # type: ignore[arg-type]
        bid=round(bid, 4),
        ask=round(ask, 4),
        mid=round(mid, 4),
        last=round(last, 4),
        volume=volume,
        open_interest=oi,
        market_iv=round(market_iv, 4) if market_iv else None,
        reference_iv=round(ctx.reference_iv, 4),
        fair_value=round(fair, 4),
        edge_abs=round(edge_abs, 4),
        edge_pct=round(edge_pct, 4),
        delta=round(greeks.delta, 4),
        gamma=round(greeks.gamma, 6),
        theta_per_day=round(greeks.theta / 365.0, 4),
        vega_per_volpt=round(greeks.vega / 100.0, 4),
        minutes_to_expiry=ctx.minutes_to_expiry,
        score=round(score, 3),
    )


def _build_plan(opp: Opportunity, account_size_usd: float = 5_000.0,
                risk_per_trade_pct: float = 0.02) -> TradePlan:
    """Construct an explicit, human-readable trade plan.

    Sizing rule: risk no more than `risk_per_trade_pct` of `account_size_usd`
    per trade, where the per-contract risk is the entire premium (a long
    option's worst case is a 100% loss).
    """
    cost_per_contract = opp.ask * 100.0
    risk_budget = account_size_usd * risk_per_trade_pct
    contracts = max(int(risk_budget // max(cost_per_contract, 0.01)), 1)
    total_cost = contracts * cost_per_contract

    # Take-profit: exit when market price reaches halfway between ask and
    # fair value (a conservative target that doesn't require the market to
    # fully close the gap).
    target_exit = opp.ask + (opp.fair_value - opp.ask) * 0.5
    target_profit = (target_exit - opp.ask) * 100.0 * contracts
    # Stop-loss: 50% of premium paid
    stop_price = opp.ask * 0.5
    stop_loss_usd = (opp.ask - stop_price) * 100.0 * contracts

    if opp.option_type == "call":
        breakeven = opp.strike + opp.ask
        side_human = f"BUY {contracts} {opp.underlying} {opp.expiration} ${opp.strike:g} CALL"
    else:
        breakeven = opp.strike - opp.ask
        side_human = f"BUY {contracts} {opp.underlying} {opp.expiration} ${opp.strike:g} PUT"

    rationale = (
        f"Black-Scholes fair value at the chain's volume-weighted IV "
        f"({opp.reference_iv:.1%}) is ${opp.fair_value:.2f}, but the contract "
        f"is offered at ${opp.ask:.2f} — an edge of "
        f"{opp.edge_pct:.1%} (${opp.edge_abs:.2f}/share). "
        f"With {opp.minutes_to_expiry} minutes to expiry, delta is "
        f"{opp.delta:+.2f} and theta is ${opp.theta_per_day:.2f}/day."
    )

    steps = [
        f"1. In your broker, open the options chain for {opp.underlying} expiring {opp.expiration}.",
        f"2. Select the ${opp.strike:g} {opp.option_type.upper()} contract ({opp.symbol}).",
        f"3. Place a LIMIT BUY-TO-OPEN order for {contracts} {opp.option_type.upper()} contract(s) at ${opp.ask:.2f} or better.",
        f"4. Immediately stage a LIMIT SELL-TO-CLOSE order on the same {opp.option_type.upper()} at ${target_exit:.2f} (take-profit).",
        f"5. Set a stop at ${stop_price:.2f} (≈50% of premium); SELL-TO-CLOSE manually if hit.",
        f"6. SELL-TO-CLOSE any remaining position by 15:45 ET to avoid pin / assignment risk.",
    ]

    return TradePlan(
        action="BUY_TO_OPEN",
        contract_symbol=opp.symbol,
        side_human=side_human,
        limit_price=round(opp.ask, 2),
        suggested_contracts=contracts,
        cost_per_contract_usd=round(cost_per_contract, 2),
        total_cost_usd=round(total_cost, 2),
        max_loss_usd=round(total_cost, 2),
        breakeven_underlying_price=round(breakeven, 2),
        target_exit_price=round(target_exit, 2),
        target_profit_usd=round(target_profit, 2),
        stop_loss_price=round(stop_price, 2),
        stop_loss_usd=round(stop_loss_usd, 2),
        rationale=rationale,
        steps=steps,
    )


# ── Thin data proxy ──────────────────────────────────────────────────────────
# The web app does all pricing/scoring in the browser (frontend/src/lib/*.js).
# These helpers expose just the raw Yahoo option chain — the one thing a browser
# can't fetch itself because of CORS.

def _row_float(v) -> float:
    try:
        if v is None or pd.isna(v):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _row_int(v) -> int:
    return int(round(_row_float(v)))


def _serialize_chain_rows(df: pd.DataFrame) -> list[dict]:
    """Convert a yfinance calls/puts DataFrame to plain JSON-able rows."""
    rows: list[dict] = []
    for _, r in df.iterrows():
        rows.append({
            "contractSymbol": str(r.get("contractSymbol", "")),
            "strike": _row_float(r.get("strike")),
            "bid": _row_float(r.get("bid")),
            "ask": _row_float(r.get("ask")),
            "lastPrice": _row_float(r.get("lastPrice")),
            "volume": _row_int(r.get("volume")),
            "openInterest": _row_int(r.get("openInterest")),
            "impliedVolatility": _row_float(r.get("impliedVolatility")),
        })
    return rows


def fetch_chains(tickers: list[str] | None = None,
                 risk_free: float = DEFAULT_RISK_FREE_RATE,
                 ) -> tuple[list[dict], list[str]]:
    """Fetch raw 0DTE/near-dated option chains for the given tickers.

    Returns ``(chains, notes)`` where each chain is::

        {underlying, spot, expiration, minutes_to_expiry, calls[], puts[]}

    All scoring (reference IV, edge, trade plan) is intentionally left to the
    client — this is just the data fetch. The ``SP500`` sentinel is expanded to
    the full S&P 500 constituent list.
    """
    raw_tickers = tickers or DEFAULT_TICKERS

    expanded: list[str] = []
    for t in raw_tickers:
        if t.upper() == SP500_SENTINEL:
            expanded.extend(fetch_sp500_tickers())
        else:
            expanded.append(t)
    seen: set[str] = set()
    unique_tickers: list[str] = []
    for t in expanded:
        up = t.upper()
        if up not in seen:
            seen.add(up)
            unique_tickers.append(up)

    now = _today_utc_date()
    chains: list[dict] = []
    notes: list[str] = []

    def _fetch_one(ticker: str):
        ctx_tuple = _build_chain_context_with_retry(ticker, risk_free, now)
        if ctx_tuple is None:
            return None, f"{ticker}: no usable 0DTE/near-dated chain"
        ctx, calls, puts = ctx_tuple
        chain = {
            "underlying": ctx.underlying,
            "spot": round(ctx.spot, 4),
            "expiration": ctx.expiry_iso,
            "minutes_to_expiry": ctx.minutes_to_expiry,
            "calls": _serialize_chain_rows(calls),
            "puts": _serialize_chain_rows(puts),
        }
        note = (f"{ctx.underlying}: spot=${ctx.spot:.2f}, expiry={ctx.expiry_iso}, "
                f"mins_left={ctx.minutes_to_expiry}")
        return chain, note

    workers = min(_MAX_WORKERS, max(len(unique_tickers), 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in unique_tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                chain, note = fut.result()
                if chain is not None:
                    chains.append(chain)
                notes.append(note)
            except Exception as exc:  # noqa: BLE001
                log.warning("Chain fetch for %s failed: %s", ticker, exc)
                notes.append(f"{ticker}: fetch error — {exc}")

    return chains, notes

