"""Protected-capital governance tests."""

import unittest
from decimal import Decimal

from autotrader.governance.floor import CapitalFloorConfig, CapitalFloorKernel


class CapitalFloorTest(unittest.TestCase):
    def setUp(self):
        self.kernel = CapitalFloorKernel(
            CapitalFloorConfig(
                protected_floor=Decimal("100000"),
                max_risk_sleeve_fraction=Decimal("0.05"),
                profit_lock_fraction=Decimal("0.75"),
            )
        )

    def test_floor_must_already_be_funded(self):
        decision = self.kernel.capacity(
            nav=Decimal("105000"),
            protected_value=Decimal("99000"),
            proposed_loss=Decimal("1"),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "floor_underfunded")

    def test_only_surplus_above_protected_value_is_riskable(self):
        decision = self.kernel.capacity(
            nav=Decimal("105000"),
            protected_value=Decimal("100000"),
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.free_surplus, Decimal("5000"))
        self.assertEqual(decision.available_risk, Decimal("5000"))

    def test_nav_fraction_can_be_tighter_than_surplus(self):
        decision = self.kernel.capacity(
            nav=Decimal("120000"),
            protected_value=Decimal("100000"),
        )
        self.assertEqual(decision.free_surplus, Decimal("20000"))
        self.assertEqual(decision.sleeve_cap, Decimal("6000.00"))
        self.assertEqual(decision.available_risk, Decimal("6000.00"))

    def test_committed_risk_is_deducted_before_new_trade(self):
        decision = self.kernel.capacity(
            nav=Decimal("120000"),
            protected_value=Decimal("100000"),
            committed_risk=Decimal("5000"),
            proposed_loss=Decimal("1500"),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "risk_budget_exceeded")
        self.assertEqual(decision.available_risk, Decimal("1000.00"))

    def test_exact_remaining_budget_is_allowed(self):
        decision = self.kernel.capacity(
            nav=Decimal("120000"),
            protected_value=Decimal("100000"),
            committed_risk=Decimal("5000"),
            proposed_loss=Decimal("1000"),
        )
        self.assertTrue(decision.allowed)

    def test_protected_value_cannot_exceed_nav(self):
        decision = self.kernel.capacity(
            nav=Decimal("90000"),
            protected_value=Decimal("100000"),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "invalid_state")

    def test_realised_profit_is_one_way_split(self):
        split = self.kernel.split_realised_profit(Decimal("20000"))
        self.assertEqual(split.locked, Decimal("15000.00"))
        self.assertEqual(split.recycled, Decimal("5000.00"))

    def test_a_loss_cannot_be_relabelled_as_recyclable_profit(self):
        with self.assertRaises(ValueError):
            self.kernel.split_realised_profit(Decimal("-1"))


class CapitalFloorConfigTest(unittest.TestCase):
    def test_invalid_fractions_are_rejected(self):
        with self.assertRaises(ValueError):
            CapitalFloorConfig(Decimal("1"), max_risk_sleeve_fraction=Decimal("1.1"))
        with self.assertRaises(ValueError):
            CapitalFloorConfig(Decimal("1"), profit_lock_fraction=Decimal("-0.1"))


if __name__ == "__main__":
    unittest.main()
