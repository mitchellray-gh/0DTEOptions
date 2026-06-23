"""Tests for the trade settlement / P&L engine."""
from __future__ import annotations

import unittest

from backend.models import Opportunity, TradePlan
from backend.backtest.settlement import _intrinsic, settle_trade


def make_opp(ask: float, fair: float, *, ref_iv: float = 0.20,
             strike: float = 500.0, spot: float = 500.0,
             otype: str = "call", minutes: int = 390) -> Opportunity:
    edge_abs = fair - ask
    return Opportunity(
        symbol="SPY260623C00500000", underlying="SPY", underlying_price=spot,
        expiration="2026-06-23", strike=strike, option_type=otype,
        bid=round(ask - 0.02, 2), ask=ask, mid=round(ask - 0.01, 2),
        last=round(ask - 0.01, 2), volume=1000, open_interest=2000,
        market_iv=0.18, reference_iv=ref_iv, fair_value=fair,
        edge_abs=edge_abs, edge_pct=edge_abs / ask, delta=0.5, gamma=0.01,
        theta_per_day=-0.10, vega_per_volpt=0.05, minutes_to_expiry=minutes,
        score=20.0,
    )


def make_plan(opp: Opportunity, *, contracts: int = 1,
              target: float | None = None, stop: float | None = None) -> TradePlan:
    target = opp.ask + (opp.fair_value - opp.ask) * 0.5 if target is None else target
    stop = opp.ask * 0.5 if stop is None else stop
    return TradePlan(
        action="BUY_TO_OPEN", contract_symbol=opp.symbol, side_human="BUY",
        limit_price=opp.ask, suggested_contracts=contracts,
        cost_per_contract_usd=opp.ask * 100, total_cost_usd=opp.ask * 100 * contracts,
        max_loss_usd=opp.ask * 100 * contracts,
        breakeven_underlying_price=opp.strike + opp.ask,
        target_exit_price=target, target_profit_usd=(target - opp.ask) * 100 * contracts,
        stop_loss_price=stop, stop_loss_usd=(opp.ask - stop) * 100 * contracts,
        rationale="", steps=[],
    )


class TestIntrinsic(unittest.TestCase):
    def test_call_and_put(self):
        self.assertAlmostEqual(_intrinsic(510, 500, "call"), 10.0)
        self.assertEqual(_intrinsic(490, 500, "call"), 0.0)
        self.assertAlmostEqual(_intrinsic(490, 500, "put"), 10.0)
        self.assertEqual(_intrinsic(510, 500, "put"), 0.0)


class TestSettlement(unittest.TestCase):
    def test_take_profit_on_favorable_jump(self):
        """A call whose underlying jumps deep ITM should hit take-profit."""
        opp = make_opp(ask=1.00, fair=1.20)
        plan = make_plan(opp, contracts=1)
        # Underlying jumps from 500 to 515 immediately and holds.
        path = [500.0] + [515.0] * 26
        trade = settle_trade(opp, plan, path, date="2026-06-23",
                             risk_free=0.045, reversion_fraction=1.0,
                             minutes_to_expiry=390, commission_per_contract=0.0,
                             exit_slippage_pct=0.0)
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertAlmostEqual(trade.exit_price, plan.target_exit_price, places=4)
        self.assertGreater(trade.pnl_usd, 0.0)

    def test_stop_loss_on_decay(self):
        """An ATM call with no move and no reversion decays into the stop."""
        opp = make_opp(ask=1.00, fair=1.15)
        plan = make_plan(opp, contracts=1)
        path = [500.0] * 27          # flat underlying, full theta bleed
        trade = settle_trade(opp, plan, path, date="2026-06-23",
                             risk_free=0.045, reversion_fraction=0.0,
                             minutes_to_expiry=390, commission_per_contract=0.0,
                             exit_slippage_pct=0.0)
        self.assertEqual(trade.exit_reason, "stop_loss")
        self.assertAlmostEqual(trade.exit_price, plan.stop_loss_price, places=4)
        self.assertLess(trade.pnl_usd, 0.0)

    def test_expiry_settles_at_intrinsic_not_stop(self):
        """When neither TP nor SL trips, P&L is the real intrinsic value."""
        opp = make_opp(ask=1.00, fair=1.15)
        # Disable TP/SL so the trade must run to expiry.
        plan = make_plan(opp, contracts=1, target=9999.0, stop=0.0001)
        path = [500.0] * 26 + [500.0]   # expires exactly ATM -> worthless
        trade = settle_trade(opp, plan, path, date="2026-06-23",
                             risk_free=0.045, reversion_fraction=0.0,
                             minutes_to_expiry=390, commission_per_contract=0.0,
                             exit_slippage_pct=0.0)
        self.assertEqual(trade.exit_reason, "expiry")
        self.assertEqual(trade.exit_price, 0.0)
        self.assertAlmostEqual(trade.pnl_usd, -100.0, places=2)

    def test_commission_reduces_pnl(self):
        opp = make_opp(ask=1.00, fair=1.20)
        plan = make_plan(opp, contracts=3)
        path = [500.0] + [515.0] * 26
        no_comm = settle_trade(opp, plan, path, date="2026-06-23",
                               risk_free=0.045, reversion_fraction=1.0,
                               minutes_to_expiry=390, commission_per_contract=0.0)
        with_comm = settle_trade(opp, plan, path, date="2026-06-23",
                                 risk_free=0.045, reversion_fraction=1.0,
                                 minutes_to_expiry=390, commission_per_contract=0.65)
        # 3 contracts * $0.65 * 2 sides = $3.90 of commission.
        self.assertAlmostEqual(no_comm.pnl_usd - with_comm.pnl_usd, 3.90, places=2)


class TestAttribution(unittest.TestCase):
    def _attr_sum(self, t) -> float:
        return (t.pnl_underlying_usd + t.pnl_vol_usd
                + t.pnl_time_usd + t.pnl_execution_usd)

    def test_attribution_reconciles_take_profit(self):
        opp = make_opp(ask=1.00, fair=1.20)
        plan = make_plan(opp, contracts=2)
        path = [500.0] + [515.0] * 26
        t = settle_trade(opp, plan, path, date="2026-06-23", risk_free=0.045,
                         reversion_fraction=1.0, minutes_to_expiry=390,
                         commission_per_contract=0.0)
        self.assertEqual(t.exit_reason, "take_profit")
        # The four buckets must sum to gross P&L exactly (execution balances).
        self.assertAlmostEqual(self._attr_sum(t), t.gross_pnl_usd, places=2)

    def test_attribution_reconciles_stop_and_expiry(self):
        for rev, path, expect in [
            (0.0, [500.0] * 27, "stop_loss"),
            (0.0, [500.0] * 26 + [500.0], "expiry"),
        ]:
            opp = make_opp(ask=1.00, fair=1.15)
            plan = (make_plan(opp, contracts=1) if expect == "stop_loss"
                    else make_plan(opp, contracts=1, target=9999.0, stop=0.0001))
            t = settle_trade(opp, plan, path, date="2026-06-23", risk_free=0.045,
                             reversion_fraction=rev, minutes_to_expiry=390,
                             commission_per_contract=0.0)
            self.assertEqual(t.exit_reason, expect)
            self.assertAlmostEqual(self._attr_sum(t), t.gross_pnl_usd, places=2)

    def test_winning_trade_credits_underlying_move(self):
        """A pure directional win should attribute most P&L to the underlying."""
        opp = make_opp(ask=1.00, fair=1.05)          # tiny vol edge
        plan = make_plan(opp, contracts=1)
        path = [500.0] + [516.0] * 26                # big favorable move
        t = settle_trade(opp, plan, path, date="2026-06-23", risk_free=0.045,
                         reversion_fraction=0.0, minutes_to_expiry=390,
                         commission_per_contract=0.0)
        self.assertGreater(t.pnl_underlying_usd, 0.0)
        self.assertGreaterEqual(t.pnl_underlying_usd, t.pnl_vol_usd)

    def test_planned_targets_are_assigned_from_plan(self):
        opp = make_opp(ask=1.00, fair=1.20)
        plan = make_plan(opp, contracts=2)
        t = settle_trade(opp, plan, [500.0] + [515.0] * 26, date="2026-06-23",
                         risk_free=0.045, reversion_fraction=1.0,
                         minutes_to_expiry=390, commission_per_contract=0.0)
        self.assertAlmostEqual(t.planned_target_usd, round(plan.target_profit_usd, 2))
        self.assertAlmostEqual(t.planned_max_loss_usd, round(plan.max_loss_usd, 2))
        self.assertAlmostEqual(t.planned_rr,
                               round(plan.target_profit_usd / plan.max_loss_usd, 3),
                               places=3)

    def test_target_capture_sign_matches_outcome(self):
        # Winner vs a positive assigned target -> positive capture.
        win = make_opp(ask=1.00, fair=1.20)
        wplan = make_plan(win, contracts=1)
        wt = settle_trade(win, wplan, [500.0] + [515.0] * 26, date="2026-06-23",
                          risk_free=0.045, reversion_fraction=1.0,
                          minutes_to_expiry=390, commission_per_contract=0.0)
        self.assertGreater(wt.target_capture_pct, 0.0)
        # Total loss vs a positive assigned target -> negative capture.
        lose = make_opp(ask=1.00, fair=1.15)
        lplan = make_plan(lose, contracts=1, target=9999.0, stop=0.0001)
        lt = settle_trade(lose, lplan, [500.0] * 27, date="2026-06-23",
                          risk_free=0.045, reversion_fraction=0.0,
                          minutes_to_expiry=390, commission_per_contract=0.0)
        self.assertLess(lt.target_capture_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
