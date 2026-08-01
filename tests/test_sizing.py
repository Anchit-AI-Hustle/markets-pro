"""Position sizing and the constraint ladder."""

import unittest
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.money import Money
from autotrader.portfolio.sizing import (
    SizingConfig,
    apply_constraints,
    kelly_fraction,
    risk_based_quantity,
    size_order,
    volatility_target_quantity,
    weight_based_quantity,
)

STOCK = Instrument("AAPL", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), Decimal("1"))
LOT100 = Instrument("600519", "CN", AssetClass.EQUITY, "CNY", Decimal("0.01"), Decimal("100"))
FUTURE = Instrument(
    "ES", "US", AssetClass.FUTURE, "USD", Decimal("0.25"), Decimal("1"),
    multiplier=Decimal("50"),
)
CRYPTO = Instrument("BTC", "US", AssetClass.CRYPTO, "USD", Decimal("0.01"), Decimal("1"))

EQUITY = Decimal("100000")


class TestRiskBasedSizing(unittest.TestCase):
    def setUp(self):
        self.config = SizingConfig(risk_per_trade=Decimal("0.01"))   # risk 1,000

    def test_exact_risk_budget(self):
        # 1,000 risk / 5 per share = 200 shares
        qty = risk_based_quantity(STOCK, EQUITY, Decimal("100"), Decimal("95"), self.config)
        self.assertEqual(qty, Decimal("200"))

    def test_loss_at_stop_equals_the_risk_budget(self):
        qty = risk_based_quantity(STOCK, EQUITY, Decimal("100"), Decimal("95"), self.config)
        loss = (Decimal("100") - Decimal("95")) * qty
        self.assertEqual(loss, EQUITY * self.config.risk_per_trade)

    def test_wider_stop_gives_a_smaller_position(self):
        tight = risk_based_quantity(STOCK, EQUITY, Decimal("100"), Decimal("95"), self.config)
        wide = risk_based_quantity(STOCK, EQUITY, Decimal("100"), Decimal("90"), self.config)
        self.assertEqual(wide, tight / 2)

    def test_fractional_result_floors_to_a_whole_share(self):
        # 1,000 / 7 = 142.857 -> 142
        qty = risk_based_quantity(STOCK, EQUITY, Decimal("100"), Decimal("93"), self.config)
        self.assertEqual(qty, Decimal("142"))

    def test_board_lot_floors_to_a_multiple_of_one_hundred(self):
        qty = risk_based_quantity(LOT100, EQUITY, Decimal("100"), Decimal("93"), self.config)
        self.assertEqual(qty, Decimal("100"))

    def test_multiplier_reduces_contract_count(self):
        # 5 points * 50 multiplier = 250 risk per contract -> 4 contracts
        qty = risk_based_quantity(FUTURE, EQUITY, Decimal("100"), Decimal("95"), self.config)
        self.assertEqual(qty, Decimal("4"))

    def test_zero_stop_distance_gives_zero(self):
        qty = risk_based_quantity(STOCK, EQUITY, Decimal("100"), Decimal("100"), self.config)
        self.assertEqual(qty, Decimal("0"))

    def test_stop_above_entry_uses_absolute_distance(self):
        # Short trade: stop is above the entry.
        qty = risk_based_quantity(STOCK, EQUITY, Decimal("100"), Decimal("105"), self.config)
        self.assertEqual(qty, Decimal("200"))

    def test_crypto_keeps_fractional_units(self):
        qty = risk_based_quantity(CRYPTO, EQUITY, Decimal("100"), Decimal("93"), self.config)
        self.assertNotEqual(qty, qty.to_integral_value())


class TestVolatilityTargeting(unittest.TestCase):
    def test_known_value(self):
        # 1,000 budget / (ATR 2 * multiple 2) = 250 shares
        qty = volatility_target_quantity(
            STOCK, EQUITY, Decimal("100"), Decimal("2"), Decimal("0.01"), Decimal("2")
        )
        self.assertEqual(qty, Decimal("250"))

    def test_higher_volatility_gives_a_smaller_position(self):
        low = volatility_target_quantity(
            STOCK, EQUITY, Decimal("100"), Decimal("1"), Decimal("0.01")
        )
        high = volatility_target_quantity(
            STOCK, EQUITY, Decimal("100"), Decimal("4"), Decimal("0.01")
        )
        self.assertEqual(low, high * 4)

    def test_zero_atr_gives_zero(self):
        self.assertEqual(
            volatility_target_quantity(
                STOCK, EQUITY, Decimal("100"), Decimal("0"), Decimal("0.01")
            ),
            Decimal("0"),
        )


class TestWeightBasedSizing(unittest.TestCase):
    def test_known_value(self):
        # 10% of 100,000 = 10,000 / 50 = 200 shares
        qty = weight_based_quantity(STOCK, EQUITY, Decimal("50"), Decimal("0.10"))
        self.assertEqual(qty, Decimal("200"))

    def test_board_lot_rounding(self):
        qty = weight_based_quantity(LOT100, EQUITY, Decimal("37"), Decimal("0.10"))
        # 10,000 / 37 = 270.27 -> 200 (floor to a 100 lot)
        self.assertEqual(qty, Decimal("200"))

    def test_zero_or_negative_price_gives_zero(self):
        self.assertEqual(weight_based_quantity(STOCK, EQUITY, Decimal("0"), Decimal("0.1")),
                         Decimal("0"))

    def test_zero_weight_gives_zero(self):
        self.assertEqual(weight_based_quantity(STOCK, EQUITY, Decimal("50"), Decimal("0")),
                         Decimal("0"))


class TestKelly(unittest.TestCase):
    def test_formula(self):
        # p=0.6, R=2 -> f = 0.6 - 0.4/2 = 0.4
        self.assertAlmostEqual(kelly_fraction(0.6, 2.0, 1.0, cap=1.0), 0.4, places=10)

    def test_cap_binds_by_default(self):
        self.assertAlmostEqual(kelly_fraction(0.6, 2.0, 1.0), 0.25, places=10)

    def test_no_edge_gives_zero(self):
        self.assertEqual(kelly_fraction(0.4, 1.0, 1.0), 0.0)

    def test_break_even_gives_zero(self):
        self.assertAlmostEqual(kelly_fraction(0.5, 1.0, 1.0), 0.0, places=10)

    def test_zero_average_loss_gives_zero(self):
        self.assertEqual(kelly_fraction(0.9, 5.0, 0.0), 0.0)

    def test_never_exceeds_cap_even_with_a_huge_edge(self):
        self.assertEqual(kelly_fraction(0.99, 100.0, 1.0, cap=0.25), 0.25)

    def test_invalid_win_rate_rejected(self):
        for bad in (-0.1, 1.1):
            with self.assertRaises(ValueError):
                kelly_fraction(bad, 1.0, 1.0)


class TestConstraints(unittest.TestCase):
    def setUp(self):
        self.config = SizingConfig(
            risk_per_trade=Decimal("0.01"),
            max_position_weight=Decimal("0.10"),
            min_order_notional=Decimal("100"),
            max_cash_utilisation=Decimal("0.95"),
            max_volume_participation=Decimal("0.05"),
        )

    def test_position_weight_cap_binds(self):
        # 200 shares at 100 = 20,000 notional; 10% cap on 100,000 equity = 10,000.
        result = apply_constraints(
            STOCK, Decimal("200"), Decimal("100"), EQUITY, EQUITY, self.config
        )
        self.assertEqual(result.quantity, Decimal("100"))
        self.assertEqual(result.notional, Decimal("10000"))
        self.assertEqual(result.reason, "max_position_weight")

    def test_within_limits_passes_through_untouched(self):
        result = apply_constraints(
            STOCK, Decimal("50"), Decimal("100"), EQUITY, EQUITY, self.config
        )
        self.assertEqual(result.quantity, Decimal("50"))
        self.assertEqual(result.reason, "ok")

    def test_cash_constraint_binds(self):
        # Only 5,000 cash, 95% usable = 4,750 -> 47 shares at 100.
        result = apply_constraints(
            STOCK, Decimal("100"), Decimal("100"), EQUITY, Decimal("5000"), self.config
        )
        self.assertEqual(result.quantity, Decimal("47"))
        self.assertEqual(result.reason, "cash_constrained")

    def test_never_spends_more_than_available_cash(self):
        result = apply_constraints(
            STOCK, Decimal("100"), Decimal("100"), EQUITY, Decimal("5000"), self.config
        )
        self.assertLessEqual(result.notional, Decimal("5000"))

    def test_liquidity_cap_binds(self):
        # ADV 1,000 * 5% = 50 shares.
        result = apply_constraints(
            STOCK, Decimal("100"), Decimal("100"), EQUITY, EQUITY, self.config,
            average_volume=Decimal("1000"),
        )
        self.assertEqual(result.quantity, Decimal("50"))
        self.assertEqual(result.reason, "liquidity_capped")

    def test_below_minimum_notional_is_skipped(self):
        result = apply_constraints(
            STOCK, Decimal("1"), Decimal("50"), EQUITY, EQUITY, self.config
        )
        self.assertEqual(result.quantity, Decimal("0"))
        self.assertEqual(result.reason, "below_min_notional")
        self.assertFalse(result.is_tradable)

    def test_zero_quantity_input(self):
        result = apply_constraints(
            STOCK, Decimal("0"), Decimal("50"), EQUITY, EQUITY, self.config
        )
        self.assertEqual(result.reason, "zero_quantity")

    def test_tightest_constraint_wins(self):
        # Weight allows 100, cash allows 47, liquidity allows 20 -> 20.
        result = apply_constraints(
            STOCK, Decimal("200"), Decimal("100"), EQUITY, Decimal("5000"), self.config,
            average_volume=Decimal("400"),
        )
        self.assertEqual(result.quantity, Decimal("20"))

    def test_lot_size_respected_after_clamping(self):
        result = apply_constraints(
            LOT100, Decimal("1000"), Decimal("37"), EQUITY, EQUITY, self.config
        )
        self.assertEqual(result.quantity % Decimal("100"), Decimal("0"))

    def test_invalid_config_rejected(self):
        with self.assertRaises(ValueError):
            SizingConfig(risk_per_trade=Decimal("0"))
        with self.assertRaises(ValueError):
            SizingConfig(max_position_weight=Decimal("1.5"))


class TestSizeOrder(unittest.TestCase):
    def setUp(self):
        self.config = SizingConfig(
            risk_per_trade=Decimal("0.01"), max_position_weight=Decimal("1.0")
        )
        self.equity = Money(EQUITY, "USD")
        self.cash = Money(EQUITY, "USD")

    def test_stop_price_takes_precedence(self):
        result = size_order(
            STOCK, equity=self.equity, available_cash=self.cash, price=Decimal("100"),
            config=self.config, stop_price=Decimal("95"), target_weight=Decimal("0.5"),
        )
        self.assertEqual(result.quantity, Decimal("200"))    # risk-based, not weight

    def test_target_weight_used_when_no_stop(self):
        result = size_order(
            STOCK, equity=self.equity, available_cash=self.cash, price=Decimal("100"),
            config=self.config, target_weight=Decimal("0.10"),
        )
        self.assertEqual(result.quantity, Decimal("100"))

    def test_atr_used_as_a_last_resort(self):
        result = size_order(
            STOCK, equity=self.equity, available_cash=self.cash, price=Decimal("100"),
            config=self.config, atr_value=Decimal("2"),
        )
        self.assertEqual(result.quantity, Decimal("250"))

    def test_no_basis_returns_zero(self):
        result = size_order(
            STOCK, equity=self.equity, available_cash=self.cash, price=Decimal("100"),
            config=self.config,
        )
        self.assertEqual(result.reason, "no_sizing_basis")

    def test_conviction_scales_the_position(self):
        full = size_order(
            STOCK, equity=self.equity, available_cash=self.cash, price=Decimal("100"),
            config=self.config, stop_price=Decimal("95"), conviction=Decimal("1"),
        )
        half = size_order(
            STOCK, equity=self.equity, available_cash=self.cash, price=Decimal("100"),
            config=self.config, stop_price=Decimal("95"), conviction=Decimal("0.5"),
        )
        self.assertEqual(half.quantity, full.quantity / 2)

    def test_zero_equity_returns_zero(self):
        result = size_order(
            STOCK, equity=Money(Decimal("0"), "USD"), available_cash=self.cash,
            price=Decimal("100"), config=self.config, stop_price=Decimal("95"),
        )
        self.assertEqual(result.reason, "no_equity")


if __name__ == "__main__":
    unittest.main()
