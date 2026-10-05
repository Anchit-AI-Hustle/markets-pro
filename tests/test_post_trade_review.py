"""Post-trade thesis/decision/outcome review tests."""

import unittest
from decimal import Decimal

from autotrader.governance.review import (
    ThesisOutcome,
    TradeOutcome,
    review_trade,
)
from autotrader.governance.trade_plan import Side, TradePlan


class PostTradeReviewTest(unittest.TestCase):
    def setUp(self):
        self.plan = TradePlan(
            "AAPL",
            Side.LONG,
            Decimal("100"),
            Decimal("95"),
            Decimal("110"),
            10,
            Decimal("0.8"),
            "trend and catalyst align",
        )

    def test_review_preserves_original_thesis_and_plan(self):
        review = review_trade(
            self.plan,
            TradeOutcome(Decimal("101"), Decimal("110"), 10),
        )
        self.assertEqual(review.thesis, self.plan.thesis)
        self.assertEqual(review.planned_entry, Decimal("100"))
        self.assertEqual(review.planned_stop, Decimal("95"))
        self.assertEqual(review.planned_target, Decimal("110"))

    def test_review_calculates_net_pnl_and_r_multiple(self):
        review = review_trade(
            self.plan,
            TradeOutcome(
                Decimal("101"),
                Decimal("111"),
                10,
                fees=Decimal("2"),
                thesis_outcome=ThesisOutcome.CONFIRMED,
            ),
        )
        self.assertEqual(review.gross_pnl, Decimal("100"))
        self.assertEqual(review.net_pnl, Decimal("98"))
        self.assertEqual(review.r_multiple, Decimal("1.96"))
        self.assertEqual(review.thesis_outcome, ThesisOutcome.CONFIRMED)

    def test_adverse_entry_slippage_is_positive(self):
        review = review_trade(
            self.plan,
            TradeOutcome(Decimal("101"), Decimal("105"), 10),
        )
        self.assertEqual(review.entry_slippage, Decimal("1"))

    def test_oversize_execution_is_flagged(self):
        review = review_trade(
            self.plan,
            TradeOutcome(Decimal("100"), Decimal("105"), 11),
        )
        self.assertTrue(review.size_violation)

    def test_short_trade_pnl_direction_is_correct(self):
        plan = TradePlan(
            "XYZ", Side.SHORT, Decimal("100"), Decimal("105"), Decimal("90"),
            5, Decimal("0.8"), "breakdown",
        )
        review = review_trade(
            plan,
            TradeOutcome(Decimal("99"), Decimal("90"), 5, fees=Decimal("1")),
        )
        self.assertEqual(review.gross_pnl, Decimal("45"))
        self.assertEqual(review.net_pnl, Decimal("44"))

    def test_invalid_actual_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            review_trade(
                self.plan,
                TradeOutcome(Decimal("100"), Decimal("105"), 0),
            )


if __name__ == "__main__":
    unittest.main()
