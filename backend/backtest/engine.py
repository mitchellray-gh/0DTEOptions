"""Backtest orchestrator.

Drives the full pipeline for every simulated trading day:

    simulator -> live scanner scoring -> live trade-plan -> settlement -> metrics

The scoring (:func:`backend.scanner._evaluate_contract`), fair-value anchor
(:func:`backend.scanner.compute_reference_iv`) and position sizing
(:func:`backend.scanner._build_plan`) are imported directly from the production
scanner, so the backtest exercises the *same* strategy code the live API runs.
"""
from __future__ import annotations

import numpy as np

from ..models import Opportunity
from ..scanner import (
    _ChainContext, _build_plan, _evaluate_contract, compute_reference_iv,
)
from .metrics import compute_metrics
from .models import BacktestConfig, BacktestResult, DayRecord
from .settlement import settle_trade

_YEAR_MINUTES = 60 * 24 * 365

DISCLAIMER = (
    "SIMULATION ONLY. These results come from a synthetic option-chain model "
    "(or a Brownian-bridge reconstruction of real daily bars), not from real "
    "historical intraday option quotes, which are not available for free. "
    "Returns are driven by the configured mispricing-reversion assumption and "
    "are NOT evidence of live profitability. 0DTE options can lose 100% of "
    "premium in minutes. Educational use only."
)


def _draw_reversion(rng: np.random.Generator, cfg: BacktestConfig) -> float:
    """Per-trade reversion fraction of the entry discount back toward ref IV."""
    if rng.random() > cfg.reversion_prob:
        return 0.0
    return float(np.clip(rng.normal(cfg.mean_reversion, cfg.reversion_sd), 0.0, 1.2))


def run_backtest(cfg: BacktestConfig) -> BacktestResult:
    """Run a full backtest and return trades, equity curve and metrics."""
    from .simulator import iter_days  # local import avoids a cycle at import time

    cfg = cfg.normalized()
    rng = np.random.default_rng(cfg.seed)

    trades = []
    day_records: list[DayRecord] = []
    daily_pnls: list[float] = []
    equity = float(cfg.account_size)
    equity_curve: list[tuple[str, float]] = []
    notes: list[str] = []
    minutes = cfg.session_minutes
    T = max(minutes, 1) / _YEAR_MINUTES

    for day in iter_days(cfg, rng):
        if day.calls.empty and day.puts.empty:
            continue
        ref_iv = compute_reference_iv(day.calls, day.puts, day.spot)
        if ref_iv is None:
            continue
        ctx = _ChainContext(
            underlying=day.underlying,
            spot=day.spot,
            expiry_iso=day.expiry_iso,
            minutes_to_expiry=minutes,
            T_years=T,
            reference_iv=ref_iv,
        )

        opps: list[Opportunity] = []
        for df, otype in ((day.calls, "call"), (day.puts, "put")):
            for _, row in df.iterrows():
                res = _evaluate_contract(row, otype, ctx, cfg.risk_free_rate)
                if isinstance(res, Opportunity):
                    opps.append(res)
        opps.sort(key=lambda o: o.score, reverse=True)
        chosen = opps[:cfg.max_trades_per_day]

        day_pnl = 0.0
        for opp in chosen:
            plan = _build_plan(opp, cfg.account_size, cfg.risk_per_trade_pct)
            trade = settle_trade(
                opp, plan, day.path,
                date=day.date,
                risk_free=cfg.risk_free_rate,
                reversion_fraction=_draw_reversion(rng, cfg),
                minutes_to_expiry=minutes,
                commission_per_contract=cfg.commission_per_contract,
                exit_slippage_pct=cfg.exit_slippage_pct,
            )
            trades.append(trade)
            day_pnl += trade.pnl_usd

        equity += day_pnl
        equity_curve.append((day.date, round(equity, 2)))
        daily_pnls.append(round(day_pnl, 2))
        day_records.append(DayRecord(
            date=day.date,
            underlying=day.underlying,
            spot_open=round(day.spot, 4),
            spot_close=round(float(day.path[-1]), 4),
            reference_iv=round(ref_iv, 4),
            n_opportunities=len(opps),
            n_trades=len(chosen),
            day_pnl=round(day_pnl, 2),
        ))

    if not day_records:
        notes.append("No tradable days were produced — check the data source, "
                     "ticker symbols, or date range.")

    metrics = compute_metrics(trades, equity_curve, cfg.account_size, daily_pnls)
    return BacktestResult(
        config=cfg.to_dict(),
        trades=trades,
        day_records=day_records,
        equity_curve=equity_curve,
        metrics=metrics,
        notes=notes,
        disclaimer=DISCLAIMER,
    )
