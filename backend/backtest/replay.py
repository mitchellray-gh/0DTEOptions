"""Replay backtester for **real** recorded scans.

The simulator in :mod:`backend.backtest.simulator` is synthetic. To evaluate the
strategy against reality you need real option quotes, which Yahoo only exposes
for the *current* moment. The practical workaround is to periodically save the
web app's scan output to disk (the **Export snapshot** button writes a
replay-compatible JSON file), then -- once those contracts have expired --
settle each flagged trade against the underlying's actual closing price on the
expiration date.

This module does the settlement half. Because free historical *intraday* option
quotes do not exist, replay assumes a **hold-to-expiry** policy (intrinsic value
at the close); it cannot replay the live take-profit / stop-loss fills. That
makes it a conservative lower bound on the strategy that also exits early.

Collecting snapshots:

* In the web UI, scan your watchlist and click **Export snapshot** to download a
  ``snapshot-<timestamp>.json`` file. Drop it in a ``snapshots/`` folder.
* Repeat across several sessions to build a history.

Then later::

    python -m backend.backtest replay --snapshots snapshots/
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from .metrics import compute_metrics
from .models import BacktestResult
from .settlement import BacktestTrade

log = logging.getLogger(__name__)

REPLAY_DISCLAIMER = (
    "REPLAY of recorded live scans, settled at intrinsic value on the "
    "expiration date (hold-to-expiry). Take-profit / stop-loss exits are NOT "
    "modeled (no historical intraday option quotes), so this is a conservative "
    "estimate. Educational use only."
)


def _intrinsic(spot: float, strike: float, option_type: str) -> float:
    if option_type == "call":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def load_snapshots(path: str | Path) -> list[dict]:
    """Load one snapshot JSON file or every ``*.json`` in a directory."""
    p = Path(path)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    snapshots: list[dict] = []
    for f in files:
        try:
            snapshots.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            log.warning("Skipping unreadable snapshot %s: %s", f, exc)
    return snapshots


def _settlement_close(ticker: str, expiry_iso: str, cache: dict) -> float | None:
    """Underlying closing price on the expiration date (cached, via yfinance)."""
    key = (ticker, expiry_iso)
    if key in cache:
        return cache[key]
    import yfinance as yf
    from datetime import datetime, timedelta

    close_px: float | None = None
    try:
        start = datetime.strptime(expiry_iso, "%Y-%m-%d").date()
        end = start + timedelta(days=1)
        hist = yf.Ticker(ticker).history(start=start.isoformat(),
                                         end=end.isoformat(), interval="1d")
        hist = hist.dropna()
        if not hist.empty:
            close_px = float(hist["Close"].iloc[-1])
    except Exception as exc:  # noqa: BLE001
        log.warning("No settlement close for %s %s: %s", ticker, expiry_iso, exc)
    cache[key] = close_px
    return close_px


def settle_recorded(snapshots: Iterable[dict], *,
                    commission_per_contract: float = 0.65,
                    starting_equity: float | None = None) -> BacktestResult:
    """Settle every opportunity across the supplied snapshots at expiry."""
    close_cache: dict = {}
    raw_trades: list[tuple[str, BacktestTrade]] = []
    notes: list[str] = []
    skipped = 0

    snapshots = list(snapshots)
    snap_count = len(snapshots)
    for snap in snapshots:
        for item in snap.get("results", []):
            opp = item.get("opportunity", {})
            plan = item.get("plan", {})
            ticker = opp.get("underlying")
            expiry = opp.get("expiration")
            otype = opp.get("option_type")
            strike = opp.get("strike")
            entry = plan.get("limit_price", opp.get("ask"))
            contracts = int(plan.get("suggested_contracts", 1))
            if not all([ticker, expiry, otype, strike is not None, entry]):
                skipped += 1
                continue

            settle_px = _settlement_close(ticker, expiry, close_cache)
            if settle_px is None:
                skipped += 1
                continue

            exit_price = _intrinsic(settle_px, float(strike), otype)
            mult = 100.0 * contracts
            capital = float(entry) * mult
            gross = (exit_price - float(entry)) * mult
            commission = commission_per_contract * contracts * 2.0
            pnl = gross - commission

            # Hold-to-expiry attribution: the change in intrinsic value is the
            # underlying's contribution; the extrinsic (time value) paid at entry
            # decays fully to zero -> time decay. (No intraday quotes, so vol and
            # execution buckets are not separable here.)
            entry_underlying = float(opp.get("underlying_price", 0.0))
            entry_intrinsic = (_intrinsic(entry_underlying, float(strike), otype)
                               if entry_underlying > 0 else 0.0)
            gross_r = round(gross, 2)
            pnl_underlying = round((exit_price - entry_intrinsic) * mult, 2)
            pnl_time = round(gross_r - pnl_underlying, 2)   # balances exactly

            planned_target = float(plan.get("target_profit_usd", 0.0) or 0.0)
            planned_max_loss = float(plan.get("max_loss_usd", 0.0) or 0.0)
            planned_rr = (planned_target / planned_max_loss
                          if planned_max_loss > 0 else 0.0)
            target_capture = pnl / planned_target if planned_target > 0 else 0.0

            raw_trades.append((expiry, BacktestTrade(
                date=expiry,
                underlying=ticker,
                symbol=opp.get("symbol", ""),
                option_type=otype,
                strike=float(strike),
                entry_underlying=round(entry_underlying, 4),
                exit_underlying=round(settle_px, 4),
                entry_price=round(float(entry), 4),
                exit_price=round(exit_price, 4),
                contracts=contracts,
                fair_value=round(float(opp.get("fair_value", 0.0)), 4),
                reference_iv=round(float(opp.get("reference_iv", 0.0)), 4),
                entry_iv=round(float(opp.get("market_iv") or 0.0), 4),
                edge_pct=round(float(opp.get("edge_pct", 0.0)), 4),
                reversion_fraction=0.0,
                exit_reason="expiry",
                hold_minutes=int(opp.get("minutes_to_expiry", 0)),
                capital_usd=round(capital, 2),
                gross_pnl_usd=gross_r,
                commission_usd=round(commission, 2),
                pnl_usd=round(pnl, 2),
                return_pct=round(pnl / capital, 4) if capital > 0 else 0.0,
                planned_target_usd=round(planned_target, 2),
                planned_max_loss_usd=round(planned_max_loss, 2),
                planned_rr=round(planned_rr, 3),
                target_capture_pct=round(target_capture, 4),
                pnl_underlying_usd=pnl_underlying,
                pnl_vol_usd=0.0,
                pnl_time_usd=pnl_time,
                pnl_execution_usd=0.0,
            )))

    raw_trades.sort(key=lambda x: x[0])
    trades = [t for _, t in raw_trades]

    if starting_equity is None:
        starting_equity = sum(t.capital_usd for t in trades) or 10_000.0

    equity = float(starting_equity)
    equity_curve: list[tuple[str, float]] = []
    daily: dict[str, float] = {}
    for t in trades:
        equity += t.pnl_usd
        equity_curve.append((t.date, round(equity, 2)))
        daily[t.date] = daily.get(t.date, 0.0) + t.pnl_usd

    if skipped:
        notes.append(f"Skipped {skipped} opportunities with missing fields or "
                     f"no available settlement price.")
    if not trades:
        notes.append("No recorded opportunities could be settled. Make sure the "
                     "snapshots' contracts have already expired.")

    metrics = compute_metrics(trades, equity_curve, starting_equity,
                              list(daily.values()))
    return BacktestResult(
        config={"mode": "replay", "snapshots": snap_count,
                "commission_per_contract": commission_per_contract},
        trades=trades,
        day_records=[],
        equity_curve=equity_curve,
        metrics=metrics,
        notes=notes,
        disclaimer=REPLAY_DISCLAIMER,
    )


def run_replay(snapshots_path: str | Path, *,
               commission_per_contract: float = 0.65,
               starting_equity: float | None = None) -> BacktestResult:
    """Load snapshots from disk and settle them. Returns a BacktestResult."""
    snapshots = load_snapshots(snapshots_path)
    return settle_recorded(snapshots,
                           commission_per_contract=commission_per_contract,
                           starting_equity=starting_equity)
