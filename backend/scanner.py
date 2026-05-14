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

The output is a list of `OpportunityWithPlan` items ready for the UI.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from .models import Opportunity, OpportunityWithPlan, TradePlan
from .pricing import bs_greeks, bs_price, implied_vol

log = logging.getLogger(__name__)

# Liquid US-listed underlyings that have daily-expiring options.
DEFAULT_TICKERS: list[str] = ["SPY", "QQQ", "IWM", "DIA", "SPX", "NDX"]

# Treasury T-bill yield is a reasonable proxy; for 0DTE pricing the rate
# barely matters.
DEFAULT_RISK_FREE_RATE = 0.045

# Minimum-quality filters
MIN_VOLUME = 50
MIN_OPEN_INTEREST = 100
MIN_BID = 0.05
MAX_REL_SPREAD = 0.25       # (ask-bid)/mid
NEAR_THE_MONEY_PCT = 0.03   # +/-3% of spot for the reference IV calc
MAX_RESULTS = 50


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


def _build_chain_context(ticker: str, risk_free: float,
                         now: datetime) -> tuple[_ChainContext, pd.DataFrame, pd.DataFrame] | None:
    """Fetch the chain and compute the reference IV from near-the-money
    contracts. Returns (context, calls_df, puts_df) or None on failure."""
    try:
        t = yf.Ticker(ticker)
        expirations = t.options or []
    except Exception as exc:
        log.warning("yfinance options() failed for %s: %s", ticker, exc)
        return None

    expiry = _pick_expiry(expirations, now)
    if expiry is None:
        log.info("No 0DTE/near-dated expiry for %s", ticker)
        return None

    try:
        chain = t.option_chain(expiry)
    except Exception as exc:
        log.warning("option_chain failed for %s %s: %s", ticker, expiry, exc)
        return None

    calls = chain.calls.copy()
    puts = chain.puts.copy()
    if calls.empty and puts.empty:
        return None

    # Spot price
    try:
        hist = t.history(period="1d", interval="1m")
        spot = float(hist["Close"].dropna().iloc[-1])
    except Exception:
        try:
            spot = float(t.fast_info["last_price"])
        except Exception as exc:
            log.warning("Could not get spot for %s: %s", ticker, exc)
            return None

    minutes = _minutes_to_us_market_close(expiry, now)
    T = max(minutes, 1) / (60 * 24 * 365)

    # Reference IV: VWAP of yfinance-provided IVs for near-the-money contracts.
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
        ref_iv = float(all_iv.median())
    else:
        weights = near["volume"].fillna(0).astype(float).clip(lower=1.0)
        ref_iv = float(np.average(near["impliedVolatility"].astype(float),
                                  weights=weights))

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
                       ctx: _ChainContext, risk_free: float) -> Opportunity | None:
    bid = float(row.get("bid") or 0.0)
    ask = float(row.get("ask") or 0.0)
    last = float(row.get("lastPrice") or 0.0)
    volume = int(row.get("volume") or 0)
    oi = int(row.get("openInterest") or 0)
    strike = float(row["strike"])
    symbol = str(row["contractSymbol"])

    # Liquidity gate
    if bid < MIN_BID or ask <= 0:
        return None
    if volume < MIN_VOLUME or oi < MIN_OPEN_INTEREST:
        return None
    mid = _safe_mid(bid, ask, last)
    if mid <= 0:
        return None
    rel_spread = (ask - bid) / mid if mid > 0 else 1.0
    if rel_spread > MAX_REL_SPREAD:
        return None

    fair = bs_price(ctx.spot, strike, ctx.T_years, risk_free,
                    ctx.reference_iv, option_type)
    edge_abs = fair - ask
    if edge_abs <= 0:
        return None
    edge_pct = edge_abs / ask
    # Require at least 5% edge to be worth highlighting
    if edge_pct < 0.05:
        return None

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
        f"3. Place a LIMIT BUY-TO-OPEN order for {contracts} contract(s) at ${opp.ask:.2f} or better.",
        f"4. Immediately stage a LIMIT SELL-TO-CLOSE at ${target_exit:.2f} (take-profit).",
        f"5. Set a mental/alert stop at ${stop_price:.2f} (≈50% of premium); close manually if hit.",
        f"6. Plan to flatten any remaining position by 15:45 ET to avoid pin / assignment risk.",
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


def scan_tickers(tickers: list[str] | None = None,
                 risk_free: float = DEFAULT_RISK_FREE_RATE,
                 account_size_usd: float = 5_000.0,
                 risk_per_trade_pct: float = 0.02,
                 max_results: int = MAX_RESULTS,
                 ) -> tuple[list[OpportunityWithPlan], list[str]]:
    """Top-level scan. Returns (results, notes)."""
    tickers = tickers or DEFAULT_TICKERS
    now = _today_utc_date()
    notes: list[str] = []
    opportunities: list[Opportunity] = []

    for ticker in tickers:
        ctx_tuple = _build_chain_context(ticker, risk_free, now)
        if ctx_tuple is None:
            notes.append(f"{ticker}: no usable 0DTE/near-dated chain")
            continue
        ctx, calls, puts = ctx_tuple
        notes.append(
            f"{ticker}: spot=${ctx.spot:.2f}, expiry={ctx.expiry_iso}, "
            f"ref_IV={ctx.reference_iv:.1%}, mins_left={ctx.minutes_to_expiry}"
        )
        for _, row in calls.iterrows():
            opp = _evaluate_contract(row, "call", ctx, risk_free)
            if opp is not None:
                opportunities.append(opp)
        for _, row in puts.iterrows():
            opp = _evaluate_contract(row, "put", ctx, risk_free)
            if opp is not None:
                opportunities.append(opp)

    opportunities.sort(key=lambda o: o.score, reverse=True)
    opportunities = opportunities[:max_results]

    results = [
        OpportunityWithPlan(
            opportunity=o,
            plan=_build_plan(o, account_size_usd, risk_per_trade_pct),
        )
        for o in opportunities
    ]
    return results, notes
