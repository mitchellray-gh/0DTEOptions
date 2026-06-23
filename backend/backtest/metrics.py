"""Performance metrics for a completed backtest."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Sequence

from .settlement import BacktestTrade


def _safe_mean(xs: Sequence[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else 0.0


def _max_drawdown(equity: Sequence[float]) -> tuple[float, float]:
    """Return (max_drawdown_usd, max_drawdown_pct) over an equity series."""
    peak = -math.inf
    max_dd = 0.0
    max_dd_pct = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
        if peak > 0:
            max_dd_pct = max(max_dd_pct, dd / peak)
    return float(max_dd), float(max_dd_pct)


def compute_metrics(
    trades: Sequence[BacktestTrade],
    equity_curve: Sequence[tuple[str, float]],
    starting_equity: float,
    daily_pnls: Sequence[float] | None = None,
) -> dict:
    """Aggregate trade-level and equity-level performance statistics."""
    n = len(trades)
    equity_values = [e for _, e in equity_curve] or [starting_equity]
    final_equity = equity_values[-1]
    max_dd, max_dd_pct = _max_drawdown([starting_equity, *equity_values])

    base = {
        "total_trades": n,
        "starting_equity": round(starting_equity, 2),
        "final_equity": round(final_equity, 2),
        "net_pnl": round(final_equity - starting_equity, 2),
        "total_return_pct": round((final_equity - starting_equity) / starting_equity, 4)
        if starting_equity else 0.0,
        "max_drawdown_usd": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 4),
    }

    if n == 0:
        base.update({
            "wins": 0, "losses": 0, "win_rate": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0, "profit_factor": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "expectancy": 0.0,
            "avg_return_pct": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
            "by_exit_reason": {}, "by_option_type": {}, "sharpe": 0.0,
            "gross_pnl": 0.0,
            "pnl_attribution": {"underlying": 0.0, "vol_reversion": 0.0,
                                "time_decay": 0.0, "execution": 0.0,
                                "commission": 0.0},
            "total_planned_profit": 0.0, "total_planned_max_loss": 0.0,
            "plan_capture_ratio": 0.0, "avg_target_capture_pct": 0.0,
            "avg_planned_rr": 0.0,
        })
        return base

    pnls = [t.pnl_usd for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = float(sum(wins))
    gross_loss = float(-sum(losses))

    by_exit: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for t in trades:
        cell = by_exit[t.exit_reason]
        cell["count"] += 1
        cell["pnl"] = round(cell["pnl"] + t.pnl_usd, 2)

    by_type: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for t in trades:
        cell = by_type[t.option_type]
        cell["count"] += 1
        cell["pnl"] = round(cell["pnl"] + t.pnl_usd, 2)

    # Sharpe from per-day P&L (annualized, ~252 trading days). Risk-free is
    # already small at the daily scale; we report the excess-of-zero Sharpe.
    sharpe = 0.0
    if daily_pnls and len(daily_pnls) > 1:
        mean_d = _safe_mean(daily_pnls)
        var_d = _safe_mean([(x - mean_d) ** 2 for x in daily_pnls])
        sd_d = math.sqrt(var_d)
        if sd_d > 1e-9:
            sharpe = (mean_d / sd_d) * math.sqrt(252)

    # P&L attribution -- realized profit assigned to its drivers. The four model
    # buckets sum to gross P&L exactly; adding commission yields net P&L (within
    # sub-cent rounding), so the attribution "aligns" with the headline result.
    attr_underlying = float(sum(t.pnl_underlying_usd for t in trades))
    attr_vol = float(sum(t.pnl_vol_usd for t in trades))
    attr_time = float(sum(t.pnl_time_usd for t in trades))
    attr_exec = float(sum(t.pnl_execution_usd for t in trades))
    total_commission = float(sum(t.commission_usd for t in trades))
    gross_pnl = attr_underlying + attr_vol + attr_time + attr_exec

    # Plan alignment -- realized result vs the targets the trade plan assigned.
    total_planned_profit = float(sum(t.planned_target_usd for t in trades))
    total_planned_max_loss = float(sum(t.planned_max_loss_usd for t in trades))
    net_pnl = final_equity - starting_equity
    plan_capture_ratio = (net_pnl / total_planned_profit
                          if total_planned_profit > 0 else 0.0)

    base.update({
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n, 4),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else math.inf,
        "avg_win": round(_safe_mean(wins), 2),
        "avg_loss": round(_safe_mean(losses), 2),
        "expectancy": round(_safe_mean(pnls), 2),
        "avg_return_pct": round(_safe_mean([t.return_pct for t in trades]), 4),
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
        "by_exit_reason": dict(by_exit),
        "by_option_type": dict(by_type),
        "sharpe": round(sharpe, 3),
        "gross_pnl": round(gross_pnl, 2),
        "pnl_attribution": {
            "underlying": round(attr_underlying, 2),
            "vol_reversion": round(attr_vol, 2),
            "time_decay": round(attr_time, 2),
            "execution": round(attr_exec, 2),
            "commission": round(-total_commission, 2),
        },
        "total_planned_profit": round(total_planned_profit, 2),
        "total_planned_max_loss": round(total_planned_max_loss, 2),
        "plan_capture_ratio": round(plan_capture_ratio, 4),
        "avg_target_capture_pct": round(_safe_mean([t.target_capture_pct for t in trades]), 4),
        "avg_planned_rr": round(_safe_mean([t.planned_rr for t in trades]), 3),
    })
    return base
