"""Research -> decision -> strict-plan gate tests."""

import unittest
from decimal import Decimal

from autotrader.governance.trade_plan import (
    Decision,
    Side,
    TradePlan,
    TradePlanGate,
)


def long_plan(**overrides):
    values = {
        "symbol": "AAPL",
        "side": Side.LONG,
        "entry": Decimal("100"),
        "stop": Decimal("95"),
        "target": Decimal("110"),
        "quantity": 10,
        "confidence": Decimal("0.80"),
        "thesis": "trend and catalyst align",
    }
    values.update(overrides)
    return TradePlan(**values)


class TradePlanGateTest(unittest.TestCase):
    def setUp(self):
        self.gate = TradePlanGate()

    def test_both_components_must_agree_to_trade(self):
        result = self.gate.evaluate(
            long_plan(),
            research_decision=Decision.TRADE,
            independent_decision=Decision.WAIT,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.action, Decision.WAIT)

    def test_low_confidence_means_no_trade(self):
        result = self.gate.evaluate(
            long_plan(confidence=Decimal("0.69")),
            research_decision=Decision.TRADE,
            independent_decision=Decision.TRADE,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "low_confidence")

    def test_high_confidence_does_not_change_maximum_loss(self):
        normal = self.gate.evaluate(
            long_plan(confidence=Decimal("0.80")),
            research_decision=Decision.TRADE,
            independent_decision=Decision.TRADE,
        )
        high = self.gate.evaluate(
            long_plan(confidence=Decimal("1.00")),
            research_decision=Decision.TRADE,
            independent_decision=Decision.TRADE,
        )
        self.assertEqual(normal.maximum_planned_loss, high.maximum_planned_loss)

    def test_entry_stop_target_must_be_logical(self):
        result = self.gate.evaluate(
            long_plan(stop=Decimal("105")),
            research_decision=Decision.TRADE,
            independent_decision=Decision.TRADE,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "invalid_trade_plan")

    def test_reward_risk_floor_is_enforced(self):
        result = self.gate.evaluate(
            long_plan(target=Decimal("106")),
            research_decision=Decision.TRADE,
            independent_decision=Decision.TRADE,
        )
        self.assertFalse(result.allowed)

    def test_valid_plan_calculates_loss_before_execution(self):
        result = self.gate.evaluate(
            long_plan(),
            research_decision=Decision.TRADE,
            independent_decision=Decision.TRADE,
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.maximum_planned_loss, Decimal("50"))
        self.assertEqual(result.reward_risk, Decimal("2"))

    def test_short_plan_uses_inverse_price_order(self):
        plan = TradePlan(
            "XYZ", Side.SHORT, Decimal("100"), Decimal("105"), Decimal("90"),
            4, Decimal("0.8"), "breakdown",
        )
        result = self.gate.evaluate(
            plan,
            research_decision=Decision.TRADE,
            independent_decision=Decision.TRADE,
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.maximum_planned_loss, Decimal("20"))


if __name__ == "__main__":
    unittest.main()
