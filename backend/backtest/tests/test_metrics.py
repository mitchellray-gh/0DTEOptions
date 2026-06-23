"""Tests for the performance-metrics aggregation."""
from __future__ import annotations

import math
import unittest

from backend.backtest.metrics import compute_metrics
from backend.backtest.settlement import BacktestTrade


def make_trade(pnl: float, *, reason: str = "expiry", otype: str = "call",
               capital: float = 100.0, underlying: float = 0.0, vol: float = 0.0,
               time: float = 0.0, execution: float | None = None,
               planned_target: float = 0.0, planned_max_loss: float = 0.0,
               planned_rr: float = 0.0, target_capture: float = 0.0) -> BacktestTrade:
    # Default attribution: assign the whole gross to the execution bucket so the
    # four buckets always reconcile to gross P&L.
    if execution is None:
        execution = pnl - (underlying + vol + time)
    return BacktestTrade(
        date="2026-06-23", underlying="SPY", symbol="SPY...C", option_type=otype,
        strike=500.0, entry_underlying=500.0, exit_underlying=500.0,
        entry_price=1.0, exit_price=1.0, contracts=1, fair_value=1.1,
        reference_iv=0.2, entry_iv=0.18, edge_pct=0.1, reversion_fraction=0.0,
        exit_reason=reason, hold_minutes=100, capital_usd=capital,
        gross_pnl_usd=pnl, commission_usd=0.0, pnl_usd=pnl,
        return_pct=pnl / capital,
        planned_target_usd=planned_target, planned_max_loss_usd=planned_max_loss,
        planned_rr=planned_rr, target_capture_pct=target_capture,
        pnl_underlying_usd=underlying, pnl_vol_usd=vol, pnl_time_usd=time,
        pnl_execution_usd=execution,
    )


class TestMetrics(unittest.TestCase):
    def test_empty(self):
        m = compute_metrics([], [], 5000.0)
        self.assertEqual(m["total_trades"], 0)
        self.assertEqual(m["net_pnl"], 0.0)
        self.assertEqual(m["win_rate"], 0.0)

    def test_basic_stats(self):
        trades = [make_trade(100), make_trade(-50), make_trade(50), make_trade(-100)]
        # equity: 1000 -> 1100 -> 1050 -> 1100 -> 1000
        curve = [("d1", 1100.0), ("d2", 1050.0), ("d3", 1100.0), ("d4", 1000.0)]
        m = compute_metrics(trades, curve, 1000.0)
        self.assertEqual(m["total_trades"], 4)
        self.assertEqual(m["wins"], 2)
        self.assertEqual(m["losses"], 2)
        self.assertAlmostEqual(m["win_rate"], 0.5)
        self.assertAlmostEqual(m["gross_profit"], 150.0)
        self.assertAlmostEqual(m["gross_loss"], 150.0)
        self.assertAlmostEqual(m["profit_factor"], 1.0)
        self.assertAlmostEqual(m["expectancy"], 0.0)
        self.assertEqual(m["net_pnl"], 0.0)
        self.assertEqual(m["best_trade"], 100.0)
        self.assertEqual(m["worst_trade"], -100.0)

    def test_max_drawdown(self):
        trades = [make_trade(100), make_trade(-300)]
        # equity: 1000 -> 1100 -> 800 ; peak 1100, trough 800 -> dd 300 (27.3%)
        curve = [("d1", 1100.0), ("d2", 800.0)]
        m = compute_metrics(trades, curve, 1000.0)
        self.assertAlmostEqual(m["max_drawdown_usd"], 300.0)
        self.assertAlmostEqual(m["max_drawdown_pct"], 300.0 / 1100.0, places=4)

    def test_profit_factor_infinite_when_no_losses(self):
        trades = [make_trade(10), make_trade(20)]
        curve = [("d1", 1010.0), ("d2", 1030.0)]
        m = compute_metrics(trades, curve, 1000.0)
        self.assertEqual(m["profit_factor"], math.inf)

    def test_exit_reason_and_type_breakdown(self):
        trades = [
            make_trade(10, reason="take_profit", otype="call"),
            make_trade(-5, reason="stop_loss", otype="put"),
            make_trade(-3, reason="expiry", otype="call"),
        ]
        curve = [("d1", 1010.0), ("d2", 1005.0), ("d3", 1002.0)]
        m = compute_metrics(trades, curve, 1000.0)
        self.assertEqual(m["by_exit_reason"]["take_profit"]["count"], 1)
        self.assertEqual(m["by_exit_reason"]["stop_loss"]["count"], 1)
        self.assertEqual(m["by_option_type"]["call"]["count"], 2)
        self.assertEqual(m["by_option_type"]["put"]["count"], 1)

    def test_pnl_attribution_aggregates_and_reconciles(self):
        trades = [
            make_trade(100, underlying=80, vol=30, time=-15, execution=5,
                       planned_target=50, planned_max_loss=100, planned_rr=0.5),
            make_trade(-40, underlying=-30, vol=-5, time=-10, execution=5,
                       planned_target=20, planned_max_loss=80, planned_rr=0.25),
        ]
        curve = [("d1", 1100.0), ("d2", 1060.0)]   # net = +60
        m = compute_metrics(trades, curve, 1000.0)
        attr = m["pnl_attribution"]
        self.assertAlmostEqual(attr["underlying"], 50.0)
        self.assertAlmostEqual(attr["vol_reversion"], 25.0)
        self.assertAlmostEqual(attr["time_decay"], -25.0)
        self.assertAlmostEqual(attr["execution"], 10.0)
        self.assertAlmostEqual(attr["commission"], 0.0)
        # The four model buckets reconcile to gross P&L exactly...
        self.assertAlmostEqual(
            attr["underlying"] + attr["vol_reversion"]
            + attr["time_decay"] + attr["execution"], m["gross_pnl"])
        # ...and adding commission reconciles to net P&L.
        self.assertAlmostEqual(m["gross_pnl"] + attr["commission"], m["net_pnl"])

    def test_plan_alignment_metrics(self):
        trades = [
            make_trade(100, planned_target=50, planned_max_loss=100, planned_rr=0.5),
            make_trade(-40, planned_target=20, planned_max_loss=80, planned_rr=0.25),
        ]
        curve = [("d1", 1100.0), ("d2", 1060.0)]   # net = +60
        m = compute_metrics(trades, curve, 1000.0)
        self.assertAlmostEqual(m["total_planned_profit"], 70.0)
        self.assertAlmostEqual(m["total_planned_max_loss"], 180.0)
        # plan capture = realized net / total assigned target = 60 / 70.
        self.assertAlmostEqual(m["plan_capture_ratio"], 60.0 / 70.0, places=4)
        self.assertAlmostEqual(m["avg_planned_rr"], 0.375, places=3)


if __name__ == "__main__":
    unittest.main()
