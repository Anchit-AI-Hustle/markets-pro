"""FIFO lot matching, realized P&L, position flips and T+1 lock-up."""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.portfolio.position import Position

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
D3 = date(2024, 1, 4)

EQUITY = Instrument("TEST", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), Decimal("1"))
FUTURE = Instrument(
    "ES", "US", AssetClass.FUTURE, "USD", Decimal("0.25"), Decimal("1"),
    multiplier=Decimal("50"),
)


class TestOpeningPositions(unittest.TestCase):
    def test_new_long(self):
        pos = Position(EQUITY)
        result = pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        self.assertEqual(pos.quantity, Decimal("100"))
        self.assertTrue(pos.is_long)
        self.assertEqual(result.realized_pnl.amount, Decimal("0"))
        self.assertEqual(result.opened_quantity, Decimal("100"))

    def test_new_short(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("-50"), Decimal("20"), D1)
        self.assertEqual(pos.quantity, Decimal("-50"))
        self.assertTrue(pos.is_short)
        self.assertEqual(pos.abs_quantity, Decimal("50"))

    def test_flat_by_default(self):
        pos = Position(EQUITY)
        self.assertTrue(pos.is_flat)
        self.assertEqual(pos.quantity, Decimal("0"))
        self.assertEqual(pos.average_cost, Decimal("0"))
        self.assertIsNone(pos.opened_on)

    def test_zero_quantity_fill_is_a_no_op(self):
        pos = Position(EQUITY)
        result = pos.apply_fill(Decimal("0"), Decimal("10"), D1)
        self.assertTrue(pos.is_flat)
        self.assertEqual(result.closed_quantity, Decimal("0"))

    def test_non_positive_price_rejected(self):
        pos = Position(EQUITY)
        with self.assertRaises(ValueError):
            pos.apply_fill(Decimal("10"), Decimal("0"), D1)


class TestAveraging(unittest.TestCase):
    def test_average_cost_is_quantity_weighted(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("100"), Decimal("12"), D2)
        self.assertEqual(pos.quantity, Decimal("200"))
        self.assertEqual(pos.average_cost, Decimal("11"))

    def test_unequal_sizes(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("300"), Decimal("20"), D2)
        # (100*10 + 300*20) / 400 = 7000/400 = 17.5
        self.assertEqual(pos.average_cost, Decimal("17.5"))

    def test_opened_on_tracks_the_oldest_lot(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("100"), Decimal("12"), D2)
        self.assertEqual(pos.opened_on, D1)


class TestFIFORealization(unittest.TestCase):
    def test_fifo_matches_oldest_lot_first(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("100"), Decimal("12"), D2)
        result = pos.apply_fill(Decimal("-150"), Decimal("15"), D3)
        # FIFO: 100 @ 10 -> (15-10)*100 = 500 ; 50 @ 12 -> (15-12)*50 = 150
        self.assertEqual(result.realized_pnl.amount, Decimal("650"))
        self.assertEqual(result.closed_quantity, Decimal("150"))

    def test_remaining_lot_after_partial_close(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("100"), Decimal("12"), D2)
        pos.apply_fill(Decimal("-150"), Decimal("15"), D3)
        self.assertEqual(pos.quantity, Decimal("50"))
        self.assertEqual(pos.average_cost, Decimal("12"))
        self.assertEqual(len(pos.lots), 1)

    def test_fifo_differs_from_average_cost(self):
        # Proves FIFO is actually implemented: average cost would give a
        # different realized number on a partial close.
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("100"), Decimal("20"), D2)
        result = pos.apply_fill(Decimal("-100"), Decimal("30"), D3)
        self.assertEqual(result.realized_pnl.amount, Decimal("2000"))   # FIFO
        # Average-cost would have been (30 - 15) * 100 = 1500.
        self.assertNotEqual(result.realized_pnl.amount, Decimal("1500"))

    def test_full_close_returns_flat(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        result = pos.apply_fill(Decimal("-100"), Decimal("11"), D2)
        self.assertTrue(pos.is_flat)
        self.assertEqual(result.realized_pnl.amount, Decimal("100"))
        self.assertFalse(result.flipped)

    def test_realized_accumulates_on_the_position(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("-100"), Decimal("11"), D2)
        pos.apply_fill(Decimal("100"), Decimal("10"), D2)
        pos.apply_fill(Decimal("-100"), Decimal("12"), D3)
        self.assertEqual(pos.realized.amount, Decimal("300"))   # 100 + 200

    def test_loss_is_negative(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        result = pos.apply_fill(Decimal("-100"), Decimal("8"), D2)
        self.assertEqual(result.realized_pnl.amount, Decimal("-200"))


class TestShortSide(unittest.TestCase):
    def test_short_profits_when_price_falls(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("-100"), Decimal("20"), D1)
        result = pos.apply_fill(Decimal("100"), Decimal("18"), D2)
        self.assertEqual(result.realized_pnl.amount, Decimal("200"))

    def test_short_loses_when_price_rises(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("-100"), Decimal("20"), D1)
        result = pos.apply_fill(Decimal("100"), Decimal("23"), D2)
        self.assertEqual(result.realized_pnl.amount, Decimal("-300"))

    def test_short_unrealized(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("-100"), Decimal("20"), D1)
        self.assertEqual(pos.unrealized_pnl(Decimal("18")).amount, Decimal("200"))
        self.assertEqual(pos.unrealized_pnl(Decimal("22")).amount, Decimal("-200"))

    def test_short_market_value_is_negative(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("-100"), Decimal("20"), D1)
        self.assertEqual(pos.market_value(Decimal("20")).amount, Decimal("-2000"))
        self.assertEqual(pos.notional_exposure(Decimal("20")).amount, Decimal("2000"))


class TestFlips(unittest.TestCase):
    def test_long_to_short_flip(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        result = pos.apply_fill(Decimal("-150"), Decimal("12"), D2)
        self.assertTrue(result.flipped)
        self.assertEqual(result.realized_pnl.amount, Decimal("200"))   # (12-10)*100
        self.assertEqual(result.closed_quantity, Decimal("100"))
        self.assertEqual(result.opened_quantity, Decimal("50"))
        self.assertTrue(pos.is_short)
        self.assertEqual(pos.quantity, Decimal("-50"))
        self.assertEqual(pos.average_cost, Decimal("12"))

    def test_short_to_long_flip(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("-100"), Decimal("20"), D1)
        result = pos.apply_fill(Decimal("250"), Decimal("18"), D2)
        self.assertTrue(result.flipped)
        self.assertEqual(result.realized_pnl.amount, Decimal("200"))
        self.assertTrue(pos.is_long)
        self.assertEqual(pos.quantity, Decimal("150"))


class TestValuation(unittest.TestCase):
    def test_market_value(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        self.assertEqual(pos.market_value(Decimal("12")).amount, Decimal("1200"))

    def test_unrealized_pnl(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        self.assertEqual(pos.unrealized_pnl(Decimal("12")).amount, Decimal("200"))

    def test_unrealized_across_multiple_lots(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("100"), Decimal("12"), D2)
        # (15-10)*100 + (15-12)*100 = 500 + 300
        self.assertEqual(pos.unrealized_pnl(Decimal("15")).amount, Decimal("800"))

    def test_flat_position_has_no_unrealized(self):
        pos = Position(EQUITY)
        self.assertEqual(pos.unrealized_pnl(Decimal("100")).amount, Decimal("0"))

    def test_multiplier_applies_to_futures(self):
        pos = Position(FUTURE)
        pos.apply_fill(Decimal("2"), Decimal("4000"), D1)
        # 2 contracts * 50 multiplier * 4000 = 400,000
        self.assertEqual(pos.market_value(Decimal("4000")).amount, Decimal("400000"))
        # A 10-point move on 2 contracts at 50x = 1000
        self.assertEqual(pos.unrealized_pnl(Decimal("4010")).amount, Decimal("1000"))

    def test_multiplier_applies_to_realized(self):
        pos = Position(FUTURE)
        pos.apply_fill(Decimal("2"), Decimal("4000"), D1)
        result = pos.apply_fill(Decimal("-2"), Decimal("4010"), D2)
        self.assertEqual(result.realized_pnl.amount, Decimal("1000"))


class TestSettlementLock(unittest.TestCase):
    """T+1 markets (China A-shares) lock shares bought the same session."""

    def test_same_day_lot_is_not_sellable_under_t_plus_one(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        self.assertEqual(pos.sellable_quantity(D1, same_day_sell_allowed=False), Decimal("0"))

    def test_prior_day_lot_is_sellable(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        self.assertEqual(pos.sellable_quantity(D2, same_day_sell_allowed=False), Decimal("100"))

    def test_mixed_lots_only_the_older_is_sellable(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        pos.apply_fill(Decimal("100"), Decimal("12"), D2)
        self.assertEqual(pos.sellable_quantity(D2, same_day_sell_allowed=False), Decimal("100"))
        self.assertEqual(pos.sellable_quantity(D3, same_day_sell_allowed=False), Decimal("200"))

    def test_same_day_selling_allowed_returns_everything(self):
        pos = Position(EQUITY)
        pos.apply_fill(Decimal("100"), Decimal("10"), D1)
        self.assertEqual(pos.sellable_quantity(D1, same_day_sell_allowed=True), Decimal("100"))


class TestInstrumentValidation(unittest.TestCase):
    def test_non_positive_tick_rejected(self):
        with self.assertRaises(ValueError):
            Instrument("X", "US", tick_size=Decimal("0"))

    def test_non_positive_lot_rejected(self):
        with self.assertRaises(ValueError):
            Instrument("X", "US", lot_size=Decimal("0"))

    def test_key_format(self):
        self.assertEqual(Instrument("reliance", "in").key, "IN:RELIANCE")

    def test_price_rounds_to_tick(self):
        nse = Instrument("X", "IN", tick_size=Decimal("0.05"))
        self.assertEqual(nse.round_price(Decimal("100.03")), Decimal("100.05"))

    def test_crypto_is_fractional_and_equity_is_not(self):
        self.assertTrue(Instrument("BTC", "US", AssetClass.CRYPTO).is_fractional)
        self.assertFalse(EQUITY.is_fractional)

    def test_shortability(self):
        self.assertTrue(EQUITY.is_shortable)
        self.assertFalse(Instrument("B", "US", AssetClass.BOND).is_shortable)


if __name__ == "__main__":
    unittest.main()
