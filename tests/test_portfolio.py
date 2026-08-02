"""Portfolio ledger: cash movement, multi-currency equity, accounting identity."""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.money import FXRates
from autotrader.execution.orders import Fill, Horizon, Side
from autotrader.portfolio.portfolio import InsufficientCash, Portfolio

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)

US = Instrument("AAPL", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), Decimal("1"))
IN = Instrument("RELIANCE", "IN", AssetClass.EQUITY, "INR", Decimal("0.05"), Decimal("1"))

FX = FXRates("USD", {"INR": Decimal("83")})


def fill(instrument, side, qty, price, day=D1, commission="0", taxes="0", fees="0",
         horizon=Horizon.LONG_TERM):
    return Fill(
        order_id=1,
        instrument=instrument,
        side=side,
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        day=day,
        horizon=horizon,
        commission=Decimal(commission),
        taxes=Decimal(taxes),
        fees=Decimal(fees),
        slippage_per_unit=Decimal("0"),
    )


class TestCashMovement(unittest.TestCase):
    def setUp(self):
        self.pf = Portfolio("USD", {"USD": Decimal("100000")})

    def test_buy_reduces_cash_by_notional_plus_costs(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50, commission="1"))
        self.assertEqual(self.pf.cash_in("USD").amount, Decimal("94999"))

    def test_sell_increases_cash_net_of_costs(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        self.pf.apply_fill(fill(US, Side.SELL, 100, 60, day=D2, commission="2"))
        # 100000 - 5000 + 6000 - 2
        self.assertEqual(self.pf.cash_in("USD").amount, Decimal("100998"))

    def test_realized_pnl_is_returned_and_tracked(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        realized = self.pf.apply_fill(fill(US, Side.SELL, 100, 60, day=D2))
        self.assertEqual(realized.amount, Decimal("1000"))
        self.assertEqual(self.pf.realized_pnl(FX).amount, Decimal("1000"))

    def test_costs_are_tracked_separately_from_pnl(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50, commission="3", taxes="2", fees="1"))
        self.assertEqual(self.pf.costs_paid(FX).amount, Decimal("6"))

    def test_insufficient_cash_raises(self):
        with self.assertRaises(InsufficientCash):
            self.pf.apply_fill(fill(US, Side.BUY, 10000, 50))

    def test_insufficient_cash_leaves_ledger_untouched(self):
        try:
            self.pf.apply_fill(fill(US, Side.BUY, 10000, 50))
        except InsufficientCash:
            pass
        self.assertEqual(self.pf.cash_in("USD").amount, Decimal("100000"))
        self.assertEqual(len(self.pf.fills), 0)
        self.assertFalse(self.pf.has_position(US.key))

    def test_margin_allows_negative_cash_when_enabled(self):
        pf = Portfolio("USD", {"USD": Decimal("1000")}, allow_margin=True)
        pf.apply_fill(fill(US, Side.BUY, 100, 50))
        self.assertEqual(pf.cash_in("USD").amount, Decimal("-4000"))

    def test_unknown_currency_balance_is_zero(self):
        self.assertEqual(self.pf.cash_in("EUR").amount, Decimal("0"))


class TestEquityIdentity(unittest.TestCase):
    """equity == initial cash + realized + unrealized - costs, exactly."""

    def setUp(self):
        self.pf = Portfolio("USD", {"USD": Decimal("100000")})

    def _check_identity(self, prices):
        equity = self.pf.total_equity(prices, FX).amount
        expected = (
            self.pf.initial_equity(FX).amount
            + self.pf.realized_pnl(FX).amount
            + self.pf.unrealized_pnl(prices, FX).amount
            - self.pf.costs_paid(FX).amount
        )
        self.assertEqual(equity, expected)

    def test_identity_holds_with_an_open_position(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50, commission="5"))
        self._check_identity({US.key: Decimal("55")})

    def test_identity_holds_after_a_closed_round_trip(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50, commission="5"))
        self.pf.apply_fill(fill(US, Side.SELL, 100, 60, day=D2, commission="5"))
        self._check_identity({US.key: Decimal("60")})

    def test_identity_holds_with_a_partial_close(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50, commission="5"))
        self.pf.apply_fill(fill(US, Side.SELL, 40, 60, day=D2, commission="2"))
        self._check_identity({US.key: Decimal("58")})

    def test_identity_holds_across_currencies(self):
        pf = Portfolio("USD", {"USD": Decimal("50000"), "INR": Decimal("4150000")})
        pf.apply_fill(fill(US, Side.BUY, 100, 50, commission="5"))
        pf.apply_fill(fill(IN, Side.BUY, 100, 2500, commission="100"))
        prices = {US.key: Decimal("52"), IN.key: Decimal("2600")}
        equity = pf.total_equity(prices, FX).amount
        expected = (
            pf.initial_equity(FX).amount
            + pf.realized_pnl(FX).amount
            + pf.unrealized_pnl(prices, FX).amount
            - pf.costs_paid(FX).amount
        )
        self.assertEqual(equity, expected)

    def test_cost_free_round_trip_at_entry_price_is_flat(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        self.pf.apply_fill(fill(US, Side.SELL, 100, 50, day=D2))
        self.assertEqual(self.pf.total_equity({US.key: Decimal("50")}, FX).amount,
                         Decimal("100000"))


class TestMultiCurrency(unittest.TestCase):
    def setUp(self):
        self.pf = Portfolio("USD", {"USD": Decimal("1000"), "INR": Decimal("83000")})

    def test_cash_balances_are_held_separately(self):
        self.assertEqual(self.pf.cash_in("USD").amount, Decimal("1000"))
        self.assertEqual(self.pf.cash_in("INR").amount, Decimal("83000"))

    def test_total_cash_converts_at_the_daily_rate(self):
        # 83,000 INR / 83 = 1,000 USD, plus 1,000 USD = 2,000 USD
        self.assertEqual(self.pf.total_cash(FX).amount, Decimal("2000"))

    def test_a_weaker_rupee_reduces_base_equity(self):
        weak = FXRates("USD", {"INR": Decimal("100")})
        self.assertEqual(self.pf.total_cash(weak).amount, Decimal("1830"))

    def test_buying_in_inr_only_moves_the_inr_balance(self):
        self.pf.apply_fill(fill(IN, Side.BUY, 10, 2500))
        self.assertEqual(self.pf.cash_in("USD").amount, Decimal("1000"))
        self.assertEqual(self.pf.cash_in("INR").amount, Decimal("58000"))

    def test_position_value_converts_to_base(self):
        self.pf.apply_fill(fill(IN, Side.BUY, 10, 2500))
        value = self.pf.positions_value({IN.key: Decimal("2500")}, FX)
        self.assertEqual(value.amount, Decimal("25000") / Decimal("83"))


class TestExposure(unittest.TestCase):
    def setUp(self):
        self.pf = Portfolio("USD", {"USD": Decimal("100000")}, allow_margin=True)

    def test_gross_exposure_sums_absolute_values(self):
        other = Instrument("MSFT", "US", currency="USD")
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        self.pf.apply_fill(fill(other, Side.SELL, 100, 30))
        prices = {US.key: Decimal("50"), other.key: Decimal("30")}
        self.assertEqual(self.pf.gross_exposure(prices, FX).amount, Decimal("8000"))

    def test_net_exposure_nets_long_against_short(self):
        other = Instrument("MSFT", "US", currency="USD")
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        self.pf.apply_fill(fill(other, Side.SELL, 100, 30))
        prices = {US.key: Decimal("50"), other.key: Decimal("30")}
        self.assertEqual(self.pf.positions_value(prices, FX).amount, Decimal("2000"))

    def test_missing_mark_price_raises(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        with self.assertRaises(KeyError):
            self.pf.positions_value({}, FX)


class TestPositionTracking(unittest.TestCase):
    def setUp(self):
        self.pf = Portfolio("USD", {"USD": Decimal("100000")})

    def test_open_positions_excludes_flat(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        self.assertEqual(len(self.pf.open_positions()), 1)
        self.pf.apply_fill(fill(US, Side.SELL, 100, 50, day=D2))
        self.assertEqual(len(self.pf.open_positions()), 0)

    def test_get_position_returns_none_when_flat(self):
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        self.pf.apply_fill(fill(US, Side.SELL, 100, 50, day=D2))
        self.assertIsNone(self.pf.get_position(US.key))

    def test_has_position(self):
        self.assertFalse(self.pf.has_position(US.key))
        self.pf.apply_fill(fill(US, Side.BUY, 100, 50))
        self.assertTrue(self.pf.has_position(US.key))


class TestEquityCurve(unittest.TestCase):
    def test_record_equity_appends_a_point(self):
        pf = Portfolio("USD", {"USD": Decimal("100000")})
        pf.apply_fill(fill(US, Side.BUY, 100, 50, commission="5"))
        point = pf.record_equity(D1, {US.key: Decimal("55")}, FX)
        self.assertEqual(len(pf.equity_curve), 1)
        self.assertEqual(point.open_positions, 1)
        self.assertEqual(point.cash, Decimal("94995"))
        self.assertEqual(point.positions_value, Decimal("5500"))
        self.assertEqual(point.equity, Decimal("100495"))
        self.assertEqual(point.costs_paid, Decimal("5"))

    def test_leverage_is_gross_over_equity(self):
        pf = Portfolio("USD", {"USD": Decimal("10000")})
        pf.apply_fill(fill(US, Side.BUY, 100, 50))
        point = pf.record_equity(D1, {US.key: Decimal("50")}, FX)
        self.assertAlmostEqual(point.leverage, 0.5, places=10)


class TestSnapshots(unittest.TestCase):
    def test_snapshot_weights_sum_to_invested_fraction(self):
        pf = Portfolio("USD", {"USD": Decimal("100000")})
        pf.apply_fill(fill(US, Side.BUY, 100, 50))
        snaps = pf.snapshots({US.key: Decimal("50")}, FX)
        self.assertEqual(len(snaps), 1)
        self.assertAlmostEqual(snaps[0].weight, 0.05, places=10)
        self.assertEqual(snaps[0].quantity, Decimal("100"))
        self.assertEqual(snaps[0].region, "US")


if __name__ == "__main__":
    unittest.main()
