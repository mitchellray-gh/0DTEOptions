"""Tests for the Robinhood-MCP order builder."""
import unittest

from backend.robinhood import ROBINHOOD_MCP_ENDPOINT, build_robinhood_order


class BuildRobinhoodOrderTests(unittest.TestCase):
    def setUp(self):
        self.opp = {
            "symbol": "SPY260514C00525000",
            "underlying": "SPY",
            "option_type": "call",
            "expiration": "2026-05-14",
            "strike": 525.0,
            "ask": 0.45,
            "minutes_to_expiry": 95,
        }
        self.plan = {
            "contract_symbol": "SPY260514C00525000",
            "suggested_contracts": 2,
            "limit_price": 0.45,
            "total_cost_usd": 90.0,
            "max_loss_usd": 90.0,
            "target_exit_price": 0.52,
            "target_profit_usd": 14.0,
            "stop_loss_price": 0.23,
        }

    def test_entry_order_fields(self):
        order = build_robinhood_order(self.opp, self.plan)
        entry = order["entry"]
        self.assertEqual(order["endpoint"], ROBINHOOD_MCP_ENDPOINT)
        self.assertEqual(entry["side"], "buy")
        self.assertEqual(entry["position_effect"], "open")
        self.assertEqual(entry["order_type"], "limit")
        self.assertEqual(entry["option_type"], "call")
        self.assertEqual(entry["quantity"], 2)
        self.assertEqual(entry["limit_price"], 0.45)
        self.assertEqual(entry["time_in_force"], "day")
        self.assertEqual(entry["option_symbol"], "SPY260514C00525000")

    def test_exit_orders_are_sell_to_close(self):
        order = build_robinhood_order(self.opp, self.plan)
        tp, sl = order["exit"]
        self.assertEqual(tp["side"], "sell")
        self.assertEqual(tp["position_effect"], "close")
        self.assertEqual(tp["limit_price"], 0.52)
        self.assertEqual(sl["order_type"], "stop")
        self.assertEqual(sl["stop_price"], 0.23)
        self.assertIsNone(sl["limit_price"])

    def test_instruction_is_natural_language(self):
        order = build_robinhood_order(self.opp, self.plan)
        text = order["instruction"]
        self.assertIn(ROBINHOOD_MCP_ENDPOINT, text)
        self.assertIn("BUY-TO-OPEN", text)
        self.assertIn("SPY 2026-05-14 $525 CALL", text)
        self.assertIn("SPY260514C00525000", text)
        self.assertIn("$0.45", text)
        self.assertIn("$0.52", text)  # take-profit
        self.assertIn("$0.23", text)  # stop-loss

    def test_accepts_pydantic_models(self):
        from backend.models import Opportunity, TradePlan

        opp = Opportunity(
            symbol="QQQ260514P00400000", underlying="QQQ", underlying_price=401.0,
            expiration="2026-05-14", strike=400.0, option_type="put",
            bid=0.50, ask=0.55, mid=0.525, last=0.52, volume=300, open_interest=500,
            reference_iv=0.18, fair_value=0.70, edge_abs=0.15, edge_pct=0.27,
            delta=-0.40, gamma=0.01, theta_per_day=-0.05, vega_per_volpt=0.02,
            minutes_to_expiry=120, score=20.0,
        )
        plan = TradePlan(
            action="BUY_TO_OPEN", contract_symbol="QQQ260514P00400000",
            side_human="BUY 1 QQQ 2026-05-14 $400 PUT", limit_price=0.55,
            suggested_contracts=1, cost_per_contract_usd=55.0, total_cost_usd=55.0,
            max_loss_usd=55.0, breakeven_underlying_price=399.45, target_exit_price=0.63,
            target_profit_usd=8.0, stop_loss_price=0.28, stop_loss_usd=27.0,
            rationale="x", steps=["1."],
        )
        order = build_robinhood_order(opp, plan)
        self.assertEqual(order["entry"]["option_type"], "put")
        self.assertEqual(order["entry"]["quantity"], 1)
        self.assertIn("QQQ 2026-05-14 $400 PUT", order["instruction"])

    def test_time_in_force_override(self):
        order = build_robinhood_order(self.opp, self.plan, time_in_force="gtc")
        self.assertEqual(order["entry"]["time_in_force"], "gtc")
        self.assertIn("GTC", order["instruction"])


if __name__ == "__main__":
    unittest.main()
