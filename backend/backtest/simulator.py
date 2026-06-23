"""Synthetic 0DTE option-chain and price-path simulator.

Two underlying data sources:

* ``gbm``      -- geometric Brownian motion. Fully offline and deterministic
  given a seed; ideal for CI and parameter sweeps.
* ``yfinance`` -- real historical *daily* OHLC bars from Yahoo. Realistic
  underlying moves; the intraday path between open and close is reconstructed
  with a Brownian bridge that respects the day's high and low.

For each trading day the simulator:

1. Produces an OHLC bar plus a fine-grained intraday path for the underlying.
2. Builds a synthetic option chain at the open (the scan moment): a strike grid
   around spot, each contract priced with Black-Scholes at a per-contract IV of
   ``base_iv * (1 + smile) + noise``. The noise is what creates the mispricings
   the scanner hunts -- contracts whose quoted IV sits below the chain reference
   become "undervalued".

.. important::
   This is a **simulation**, not a replay of real historical option quotes
   (those are not available for free from Yahoo). Use it to stress-test the
   strategy's logic and parameters, not as proof of live profitability. For a
   real-data evaluation, collect live scan snapshots and use
   :mod:`backend.backtest.replay`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..pricing import bs_price
from .models import BacktestConfig

_YEAR_MINUTES = 60 * 24 * 365


@dataclass
class DaySim:
    """One simulated trading day handed to the engine."""
    date: str
    underlying: str
    spot: float
    expiry_iso: str
    calls: pd.DataFrame
    puts: pd.DataFrame
    path: np.ndarray


def _occ_symbol(underlying: str, date_iso: str, option_type: str,
                strike: float) -> str:
    yymmdd = date_iso[2:4] + date_iso[5:7] + date_iso[8:10]
    cp = "C" if option_type == "call" else "P"
    return f"{underlying}{yymmdd}{cp}{int(round(strike * 1000)):08d}"


def _strike_increment(spot: float) -> float:
    if spot < 25:
        return 0.5
    if spot < 100:
        return 1.0
    if spot < 250:
        return 2.5
    return 5.0


def build_chain(underlying: str, spot: float, date_iso: str,
                minutes_to_expiry: int, cfg: BacktestConfig,
                rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construct a synthetic call/put chain (yfinance column shape)."""
    r = cfg.risk_free_rate
    T = max(minutes_to_expiry, 1) / _YEAR_MINUTES
    inc = _strike_increment(spot)
    lo, hi = spot * (1 - cfg.strike_width_pct), spot * (1 + cfg.strike_width_pct)

    strikes: list[float] = []
    k = math.floor(lo / inc) * inc
    while k <= hi + 1e-9:
        if k > 0:
            strikes.append(round(k, 2))
        k += inc

    calls_rows: list[dict] = []
    puts_rows: list[dict] = []
    for K in strikes:
        moneyness = (K - spot) / spot
        for otype, rows in (("call", calls_rows), ("put", puts_rows)):
            smile = cfg.smile_coef * moneyness * moneyness
            iv_true = cfg.base_iv * (1.0 + smile)
            quote_iv = max(0.02, iv_true + float(rng.normal(0.0, cfg.iv_noise)))
            mid = bs_price(spot, K, T, r, quote_iv, otype)
            if mid < 0.02:                       # effectively worthless far OTM
                continue
            spread_frac = cfg.base_spread_pct + 0.4 * abs(moneyness) + 0.01 / max(mid, 0.05)
            spread_frac = min(max(spread_frac, 0.01), 0.6)
            half = mid * spread_frac / 2.0
            bid = max(round(mid - half, 2), 0.0)
            ask = round(mid + half, 2)
            if ask <= 0:
                continue
            liq = math.exp(-((moneyness / 0.03) ** 2))
            volume = int(cfg.base_volume * liq * float(rng.lognormal(0.0, 0.4)))
            oi = int(volume * float(rng.uniform(2.0, 6.0)))
            rows.append({
                "contractSymbol": _occ_symbol(underlying, date_iso, otype, K),
                "strike": float(K),
                "bid": float(bid),
                "ask": float(ask),
                "lastPrice": float(round(mid, 2)),
                "volume": int(volume),
                "openInterest": int(oi),
                "impliedVolatility": float(quote_iv),
            })

    return pd.DataFrame(calls_rows), pd.DataFrame(puts_rows)


def _gbm_day_path(prev_close: float, cfg: BacktestConfig,
                  rng: np.random.Generator) -> np.ndarray:
    steps = cfg.intraday_steps
    open_px = prev_close * math.exp(float(rng.normal(0.0, cfg.gbm_overnight_gap_vol)))
    dt = (1.0 / 252.0) / steps
    vol, drift = cfg.gbm_annual_vol, cfg.gbm_annual_drift
    shocks = rng.standard_normal(steps)
    logrets = (drift - 0.5 * vol * vol) * dt + vol * math.sqrt(dt) * shocks
    path = np.empty(steps + 1)
    path[0] = open_px
    path[1:] = open_px * np.exp(np.cumsum(logrets))
    return path


def _bridge_path(o: float, h: float, l: float, c: float, steps: int,
                 rng: np.random.Generator) -> np.ndarray:
    """Reconstruct an intraday path from a daily OHLC bar via a Brownian bridge.

    The bridge is pinned to the open and close, scaled to roughly the day's
    range, and forced to touch the actual high and low at two interior points so
    take-profit / stop-loss checks see the day's true extremes.
    """
    n = steps
    frac = np.arange(n + 1) / n
    w = np.concatenate([[0.0], np.cumsum(rng.standard_normal(n))])
    bridge = w - frac * w[-1]
    span = float(np.max(bridge) - np.min(bridge))
    if span > 1e-9:
        bridge = bridge / span
    path = o + (c - o) * frac + bridge * (h - l) * 0.7
    if n >= 4:
        j_hi, j_lo = sorted(rng.choice(range(1, n), size=2, replace=False).tolist())
        path[j_hi] = h
        path[j_lo] = l
    path[0] = o
    path[-1] = c
    return np.clip(path, min(l, float(path.min())), max(h, float(path.max())))


def _iter_gbm(cfg: BacktestConfig, rng: np.random.Generator):
    end = cfg.end or datetime.now(timezone.utc).date().isoformat()
    dates = pd.bdate_range(end=end, periods=cfg.days).strftime("%Y-%m-%d").tolist()
    for ticker in cfg.tickers:
        prev = cfg.gbm_start_price
        for d in dates:
            path = _gbm_day_path(prev, cfg, rng)
            calls, puts = build_chain(ticker, float(path[0]), d,
                                      cfg.session_minutes, cfg, rng)
            yield DaySim(d, ticker, float(path[0]), d, calls, puts, path)
            prev = float(path[-1])


def _iter_yfinance(cfg: BacktestConfig, rng: np.random.Generator):
    import yfinance as yf  # local import: keeps offline GBM runs network-free

    for ticker in cfg.tickers:
        t = yf.Ticker(ticker)
        if cfg.start:
            hist = t.history(start=cfg.start, end=cfg.end, interval="1d")
        else:
            hist = t.history(period=f"{max(cfg.days + 5, 10)}d", interval="1d")
        hist = hist.dropna()
        if hist.empty:
            continue
        hist = hist.tail(cfg.days)
        for idx, bar in hist.iterrows():
            d = idx.strftime("%Y-%m-%d")
            o, h, l, c = (float(bar["Open"]), float(bar["High"]),
                          float(bar["Low"]), float(bar["Close"]))
            if o <= 0:
                continue
            path = _bridge_path(o, h, l, c, cfg.intraday_steps, rng)
            calls, puts = build_chain(ticker, o, d, cfg.session_minutes, cfg, rng)
            yield DaySim(d, ticker, o, d, calls, puts, path)


def iter_days(cfg: BacktestConfig, rng: np.random.Generator):
    """Yield :class:`DaySim` objects for every simulated trading day."""
    cfg = cfg.normalized()
    if cfg.source == "gbm":
        yield from _iter_gbm(cfg, rng)
    elif cfg.source == "yfinance":
        yield from _iter_yfinance(cfg, rng)
    else:  # pragma: no cover - guarded by config typing
        raise ValueError(f"Unknown data source: {cfg.source!r}")
