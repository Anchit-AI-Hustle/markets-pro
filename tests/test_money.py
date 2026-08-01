"""Money, FX and rounding — the accounting primitives."""

import unittest
from decimal import Decimal

from autotrader.core.money import (
    CurrencyMismatch,
    FXRates,
    Money,
    floor_to_increment,
    round_to_increment,
    sum_money,
    to_decimal,
)


class TestDecimalCoercion(unittest.TestCase):
    def test_float_converts_without_binary_error(self):
        # The whole reason money is not float: 0.1 must be exactly 0.1.
        self.assertEqual(to_decimal(0.1), Decimal("0.1"))
        self.assertEqual(to_decimal(0.2), Decimal("0.2"))

    def test_int_and_str(self):
        self.assertEqual(to_decimal(5), Decimal("5"))
        self.assertEqual(to_decimal("1.25"), Decimal("1.25"))

    def test_rejects_unsupported_type(self):
        with self.assertRaises(TypeError):
            to_decimal([1])


class TestMoneyArithmetic(unittest.TestCase):
    def test_addition_is_exact(self):
        a = Money(Decimal("0.1"), "USD")
        b = Money(Decimal("0.2"), "USD")
        self.assertEqual((a + b).amount, Decimal("0.3"))

    def test_subtraction_and_negation(self):
        a = Money(Decimal("10"), "USD")
        b = Money(Decimal("3"), "USD")
        self.assertEqual((a - b).amount, Decimal("7"))
        self.assertEqual((-a).amount, Decimal("-10"))
        self.assertEqual(abs(Money(Decimal("-4"), "USD")).amount, Decimal("4"))

    def test_multiplication_and_division(self):
        a = Money(Decimal("100"), "USD")
        self.assertEqual((a * 3).amount, Decimal("300"))
        self.assertEqual((3 * a).amount, Decimal("300"))
        self.assertEqual((a / 4).amount, Decimal("25"))

    def test_division_by_zero_raises(self):
        with self.assertRaises(ZeroDivisionError):
            Money(Decimal("1"), "USD") / 0

    def test_currency_mismatch_is_rejected(self):
        usd = Money(Decimal("1"), "USD")
        inr = Money(Decimal("1"), "INR")
        for op in (
            lambda: usd + inr,
            lambda: usd - inr,
            lambda: usd < inr,
            lambda: usd >= inr,
        ):
            with self.assertRaises(CurrencyMismatch):
                op()

    def test_comparison(self):
        self.assertTrue(Money(1, "USD") < Money(2, "USD"))
        self.assertTrue(Money(2, "USD") > Money(1, "USD"))
        self.assertTrue(Money(2, "USD") >= Money(2, "USD"))
        self.assertTrue(Money(2, "USD") <= Money(2, "USD"))

    def test_unknown_currency_rejected(self):
        with self.assertRaises(ValueError):
            Money(Decimal("1"), "XYZ")

    def test_quantize_half_up(self):
        self.assertEqual(Money(Decimal("1.005"), "USD").quantized().amount, Decimal("1.01"))
        self.assertEqual(Money(Decimal("1.004"), "USD").quantized().amount, Decimal("1.00"))
        # JPY has zero minor units.
        self.assertEqual(Money(Decimal("1.5"), "JPY").quantized().amount, Decimal("2"))

    def test_sum_money_empty_returns_zero(self):
        self.assertEqual(sum_money([], "INR").amount, Decimal("0"))
        self.assertEqual(sum_money([], "INR").currency, "INR")

    def test_sum_money(self):
        items = [Money(1, "USD"), Money(2, "USD"), Money(3, "USD")]
        self.assertEqual(sum_money(items, "USD").amount, Decimal("6"))


class TestFXRates(unittest.TestCase):
    def setUp(self):
        # Rates are "units of X per 1 USD".
        self.fx = FXRates("USD", {"INR": Decimal("83"), "EUR": Decimal("0.92")})

    def test_identity_rate(self):
        self.assertEqual(self.fx.rate("USD", "USD"), Decimal("1"))
        self.assertEqual(self.fx.rate("INR", "INR"), Decimal("1"))

    def test_base_to_quote(self):
        self.assertEqual(self.fx.rate("USD", "INR"), Decimal("83"))

    def test_inverse_is_derived(self):
        rate = self.fx.rate("INR", "USD")
        self.assertAlmostEqual(float(rate), 1 / 83, places=10)

    def test_cross_rate(self):
        # INR -> EUR must route through the base: 0.92 / 83.
        expected = Decimal("0.92") / Decimal("83")
        self.assertAlmostEqual(float(self.fx.rate("INR", "EUR")), float(expected), places=12)

    def test_convert(self):
        converted = self.fx.convert(Money(Decimal("100"), "USD"), "INR")
        self.assertEqual(converted.amount, Decimal("8300"))
        self.assertEqual(converted.currency, "INR")

    def test_round_trip_conversion_preserves_value(self):
        original = Money(Decimal("1000"), "USD")
        there = self.fx.convert(original, "INR")
        back = self.fx.convert(there, "USD")
        self.assertAlmostEqual(float(back.amount), 1000.0, places=8)

    def test_non_positive_rate_rejected(self):
        with self.assertRaises(ValueError):
            FXRates("USD", {"INR": Decimal("0")})

    def test_unknown_currency_rejected(self):
        with self.assertRaises(ValueError):
            FXRates("USD", {"ZZZ": Decimal("1")})


class TestRounding(unittest.TestCase):
    def test_round_to_tick_half_up(self):
        # NSE ticks are 0.05: 100.03 -> 100.05, 100.02 -> 100.00.
        self.assertEqual(round_to_increment(Decimal("100.03"), Decimal("0.05")), Decimal("100.05"))
        self.assertEqual(round_to_increment(Decimal("100.02"), Decimal("0.05")), Decimal("100.00"))

    def test_round_exact_multiple_unchanged(self):
        self.assertEqual(round_to_increment(Decimal("100.05"), Decimal("0.05")), Decimal("100.05"))

    def test_zero_increment_is_no_op(self):
        self.assertEqual(round_to_increment(Decimal("1.2345"), Decimal("0")), Decimal("1.2345"))

    def test_floor_never_rounds_up(self):
        # China board lots of 100: 137 shares is not a valid order.
        self.assertEqual(floor_to_increment(Decimal("137"), Decimal("100")), Decimal("100"))
        self.assertEqual(floor_to_increment(Decimal("199.99"), Decimal("100")), Decimal("100"))
        self.assertEqual(floor_to_increment(Decimal("200"), Decimal("100")), Decimal("200"))

    def test_floor_to_single_lot(self):
        self.assertEqual(floor_to_increment(Decimal("142.86"), Decimal("1")), Decimal("142"))


if __name__ == "__main__":
    unittest.main()
