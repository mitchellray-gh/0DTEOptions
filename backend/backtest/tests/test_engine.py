"""End-to-end tests for the backtest engine and simulator (offline GBM)."""
from __future__ import annotations

import unittest

import numpy as np

from backend.backtest import BacktestConfig, run_backtest
from backend.backtest.simulator import build_chain, iter_days
from backend.scanner import compute_reference_iv


class TestSimulator(unittest.TestCase):
    def test_build_chain_shapes(self):
        rng = np.random.default_rng(0)
        cfg = BacktestConfig(source="gbm")
        calls, puts = build_chain("SPY", 500.0, "2026-06-23", 390, cfg, rng)
        self.assertFalse(calls.empty)
        self.assertFalse(puts.empty)
        for col in ("strike", "bid", "ask", "lastPrice", "volume",
                    "openInterest", "impliedVolatility", "contractSymbol"):
            self.assertIn(col, calls.columns)
        # asks strictly above bids; IVs positive
        self.assertTrue((calls["ask"] >= calls["bid"]).all())
        self.assertTrue((calls["impliedVolatility"] > 0).all())

    def test_reference_iv_is_finite(self):
        rng = np.random.default_rng(1)
        cfg = BacktestConfig(source="gbm")
        calls, puts = build_chain("SPY", 500.0, "2026-06-23", 390, cfg, rng)
        ref = compute_reference_iv(calls, puts, 500.0)
        self.assertIsNotNone(ref)
        self.assertTrue(0.0 < ref < 5.0)

    def test_iter_days_count(self):
        cfg = BacktestConfig(source="gbm", days=10, tickers=("SPY",))
        rng = np.random.default_rng(2)
        days = list(iter_days(cfg, rng))
        self.assertEqual(len(days), 10)
        self.assertEqual(len(days[0].path), cfg.intraday_steps + 1)


class TestEngine(unittest.TestCase):
    def test_runs_and_reports(self):
        cfg = BacktestConfig(source="gbm", days=30, seed=123)
        result = run_backtest(cfg)
        self.assertEqual(len(result.day_records), 30)
        self.assertEqual(len(result.equity_curve), 30)
        self.assertIn("net_pnl", result.metrics)
        self.assertIn("win_rate", result.metrics)
        self.assertTrue(result.disclaimer)
        # Every trade is attributed to a known exit reason.
        for t in result.trades:
            self.assertIn(t.exit_reason, ("take_profit", "stop_loss", "expiry"))

    def test_deterministic_with_seed(self):
        cfg = BacktestConfig(source="gbm", days=40, seed=999)
        r1 = run_backtest(cfg)
        r2 = run_backtest(cfg)
        self.assertEqual(r1.metrics["net_pnl"], r2.metrics["net_pnl"])
        self.assertEqual(len(r1.trades), len(r2.trades))

    def test_different_seeds_differ(self):
        a = run_backtest(BacktestConfig(source="gbm", days=40, seed=1))
        b = run_backtest(BacktestConfig(source="gbm", days=40, seed=2))
        # Extremely unlikely to match exactly across independent seeds.
        self.assertNotEqual(a.metrics["net_pnl"], b.metrics["net_pnl"])

    def test_zero_commission_higher_pnl(self):
        base = BacktestConfig(source="gbm", days=40, seed=7)
        costly = BacktestConfig(source="gbm", days=40, seed=7,
                                commission_per_contract=2.0)
        cheap = BacktestConfig(source="gbm", days=40, seed=7,
                               commission_per_contract=0.0)
        self.assertGreater(run_backtest(cheap).metrics["net_pnl"],
                           run_backtest(costly).metrics["net_pnl"])

    def test_attribution_reconciles_to_net_pnl(self):
        result = run_backtest(BacktestConfig(source="gbm", days=60, seed=7))
        m = result.metrics
        attr = m["pnl_attribution"]
        # Four model buckets sum to gross P&L (exact, per-trade balanced).
        model = (attr["underlying"] + attr["vol_reversion"]
                 + attr["time_decay"] + attr["execution"])
        self.assertAlmostEqual(model, m["gross_pnl"], places=2)
        # Buckets + commission reconcile to net P&L within rounding.
        n = max(m["total_trades"], 1)
        self.assertLessEqual(abs(m["gross_pnl"] + attr["commission"] - m["net_pnl"]),
                             max(0.5, 0.02 * n))
        # Every trade's own attribution reconciles to its gross.
        for t in result.trades:
            s = (t.pnl_underlying_usd + t.pnl_vol_usd
                 + t.pnl_time_usd + t.pnl_execution_usd)
            self.assertAlmostEqual(s, t.gross_pnl_usd, places=2)

    def test_plan_targets_assigned(self):
        result = run_backtest(BacktestConfig(source="gbm", days=30, seed=3))
        m = result.metrics
        self.assertIn("plan_capture_ratio", m)
        self.assertGreater(m["total_planned_profit"], 0.0)
        self.assertGreater(m["total_planned_max_loss"], 0.0)
        for t in result.trades:
            self.assertGreater(t.planned_target_usd, 0.0)
            self.assertGreater(t.planned_max_loss_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
