"""Broker execution planning: eligibility, the daily cap, and the journal."""

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from autotrader.broker.kite import (
    append_journal,
    eligible_orders,
    plan,
    read_spent,
)


def order(symbol="RELIANCE", *, region="india", side="BUY", fresh=True, notional="10000"):
    return {
        "symbol": symbol,
        "region": region,
        "side": side,
        "fresh": fresh,
        "notional": notional,
        "quantity": "10",
        "reference_price": "1000",
        "kite": {"tradingsymbol": symbol, "exchange": "NSE", "transaction_type": side,
                 "quantity": 10, "order_type": "MARKET", "product": "CNC"},
    }


class TestEligibility(unittest.TestCase):
    def test_only_fresh_india_buys_are_eligible(self):
        snapshot = {
            "orders": [
                order("RELIANCE"),
                order("AAPL", region="us"),
                order("TCS", side="SELL"),
                order("INFY", fresh=False),
            ]
        }
        symbols = [o["symbol"] for o in eligible_orders(snapshot)]
        self.assertEqual(symbols, ["RELIANCE"])


class TestPlan(unittest.TestCase):
    def test_orders_fit_under_the_cap_in_priority_order(self):
        snapshot = {"orders": [order("A", notional="8000"), order("B", notional="8000"),
                               order("C", notional="3000")]}
        accepted, skipped = plan(snapshot, Decimal("12000"), Decimal("0"))
        self.assertEqual([o["symbol"] for o in accepted], ["A", "C"])
        self.assertEqual(len(skipped), 1)
        self.assertIn("B", skipped[0])

    def test_prior_spend_counts_against_the_cap(self):
        snapshot = {"orders": [order("A", notional="8000")]}
        accepted, skipped = plan(snapshot, Decimal("12000"), Decimal("6000"))
        self.assertEqual(accepted, [])
        self.assertEqual(len(skipped), 1)

    def test_zero_notional_is_never_accepted(self):
        snapshot = {"orders": [order("A", notional="0")]}
        accepted, skipped = plan(snapshot, Decimal("12000"), Decimal("0"))
        self.assertEqual(accepted, [])
        self.assertIn("no reference notional", skipped[0])


class TestJournal(unittest.TestCase):
    def test_spend_survives_process_restarts(self):
        day = date(2026, 8, 3)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(read_spent(root, day), Decimal("0"))
            append_journal(root, day, {"order_id": "1", "symbol": "A", "quantity": "10",
                                       "notional": "8000", "reference_price": "800"})
            append_journal(root, day, {"order_id": "2", "symbol": "B", "quantity": "5",
                                       "notional": "2500", "reference_price": "500"})
            self.assertEqual(read_spent(root, day), Decimal("10500"))
            self.assertEqual(read_spent(root, date(2026, 8, 4)), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
