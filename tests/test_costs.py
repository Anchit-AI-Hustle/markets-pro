"""Region-specific cost and slippage models.

Expected totals are computed by hand from each venue's published fee structure
and written out line by line, so a rate change shows up as an obvious diff
rather than a mysterious number.
"""

import unittest
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.execution.costs import (
    ChinaCostModel,
    CostBreakdown,
    FlatBpsCostModel,
    IndiaCostModel,
    RussiaCostModel,
    SlippageModel,
    USCostModel,
    ZERO_SLIPPAGE,
    get_cost_model,
    register_cost_model,
)
from autotrader.execution.orders import Side

IN_STOCK = Instrument("RELIANCE", "IN", AssetClass.EQUITY, "INR", Decimal("0.05"))
US_STOCK = Instrument("AAPL", "US", AssetClass.EQUITY, "USD", Decimal("0.01"))
CN_STOCK = Instrument("600519", "CN", AssetClass.EQUITY, "CNY", Decimal("0.01"), Decimal("100"))
RU_STOCK = Instrument("GAZP", "RU", AssetClass.EQUITY, "RUB", Decimal("0.01"))


class TestIndiaCosts(unittest.TestCase):
    """NSE cash equity. Turnover for every case below is 100,000 INR."""

    def setUp(self):
        self.model = IndiaCostModel()
        self.qty = Decimal("100")
        self.price = Decimal("1000")

    def test_delivery_buy(self):
        c = self.model.compute(IN_STOCK, Side.BUY, self.qty, self.price, intraday=False)
        self.assertEqual(c.commission, Decimal("0"))          # free delivery
        self.assertEqual(c.securities_tax, Decimal("100"))    # STT 0.1% both legs
        self.assertEqual(c.exchange_fee, Decimal("2.97"))     # 0.00297%
        self.assertEqual(c.regulatory_fee, Decimal("0.1"))    # SEBI Rs 10/crore
        self.assertEqual(c.stamp_duty, Decimal("15"))         # 0.015% buy only
        self.assertEqual(c.gst, Decimal("0.5526"))            # 18% of (0 + 2.97 + 0.1)
        self.assertEqual(c.total, Decimal("118.6226"))

    def test_delivery_sell_has_no_stamp_duty(self):
        c = self.model.compute(IN_STOCK, Side.SELL, self.qty, self.price, intraday=False)
        self.assertEqual(c.stamp_duty, Decimal("0"))
        self.assertEqual(c.securities_tax, Decimal("100"))    # STT still charged
        self.assertEqual(c.total, Decimal("103.6226"))

    def test_intraday_sell_pays_reduced_stt(self):
        c = self.model.compute(IN_STOCK, Side.SELL, self.qty, self.price, intraday=True)
        self.assertEqual(c.commission, Decimal("20"))         # Rs 20 cap beats 0.03%
        self.assertEqual(c.securities_tax, Decimal("25"))     # 0.025% sell only
        self.assertEqual(c.stamp_duty, Decimal("0"))
        self.assertEqual(c.gst, Decimal("4.1526"))            # 18% of (20 + 2.97 + 0.1)
        self.assertEqual(c.total, Decimal("52.2226"))

    def test_intraday_buy_pays_no_stt(self):
        c = self.model.compute(IN_STOCK, Side.BUY, self.qty, self.price, intraday=True)
        self.assertEqual(c.securities_tax, Decimal("0"))
        self.assertEqual(c.stamp_duty, Decimal("3"))          # 0.003% intraday buy
        self.assertEqual(c.total, Decimal("30.2226"))

    def test_delivery_costs_more_than_intraday_on_the_sell_leg(self):
        delivery = self.model.compute(IN_STOCK, Side.SELL, self.qty, self.price, intraday=False)
        intraday = self.model.compute(IN_STOCK, Side.SELL, self.qty, self.price, intraday=True)
        self.assertGreater(delivery.total, intraday.total)

    def test_brokerage_cap_binds_on_large_orders(self):
        c = self.model.compute(IN_STOCK, Side.BUY, Decimal("10000"), self.price, intraday=True)
        self.assertEqual(c.commission, Decimal("20"))         # capped, not 0.03%

    def test_gst_excludes_stt_and_stamp_duty(self):
        c = self.model.compute(IN_STOCK, Side.BUY, self.qty, self.price, intraday=False)
        taxable = c.commission + c.exchange_fee + c.regulatory_fee
        self.assertEqual(c.gst, taxable * Decimal("0.18"))


class TestUSCosts(unittest.TestCase):
    def setUp(self):
        self.model = USCostModel()

    def test_buy_is_free_by_default(self):
        c = self.model.compute(US_STOCK, Side.BUY, Decimal("100"), Decimal("50"))
        self.assertEqual(c.total, Decimal("0"))

    def test_sell_pays_sec_and_finra_fees(self):
        c = self.model.compute(US_STOCK, Side.SELL, Decimal("100"), Decimal("50"))
        # SEC: 5000 * 0.0000278 = 0.139 ; TAF: 100 * 0.000166 = 0.0166
        self.assertEqual(c.regulatory_fee, Decimal("0.1556"))
        self.assertEqual(c.total, Decimal("0.1556"))

    def test_finra_taf_is_capped(self):
        c = self.model.compute(US_STOCK, Side.SELL, Decimal("100000"), Decimal("1"))
        # Raw TAF would be 16.60; the cap is 8.30. SEC on 100,000 notional = 2.78.
        self.assertEqual(c.regulatory_fee, Decimal("8.30") + Decimal("2.78"))

    def test_per_share_commission(self):
        model = USCostModel(commission_per_share=Decimal("0.005"))
        c = model.compute(US_STOCK, Side.BUY, Decimal("100"), Decimal("50"))
        self.assertEqual(c.commission, Decimal("0.5"))

    def test_commission_minimum_applies(self):
        model = USCostModel(commission_per_share=Decimal("0.005"), commission_minimum=Decimal("1"))
        c = model.compute(US_STOCK, Side.BUY, Decimal("10"), Decimal("50"))
        self.assertEqual(c.commission, Decimal("1"))

    def test_sells_cost_more_than_buys(self):
        buy = self.model.compute(US_STOCK, Side.BUY, Decimal("100"), Decimal("50"))
        sell = self.model.compute(US_STOCK, Side.SELL, Decimal("100"), Decimal("50"))
        self.assertGreater(sell.total, buy.total)


class TestChinaCosts(unittest.TestCase):
    def setUp(self):
        self.model = ChinaCostModel()

    def test_buy_pays_no_stamp_duty(self):
        c = self.model.compute(CN_STOCK, Side.BUY, Decimal("100"), Decimal("10"))
        self.assertEqual(c.stamp_duty, Decimal("0"))
        # commission floor of CNY 5 dominates on a 1,000 turnover
        self.assertEqual(c.commission, Decimal("5"))
        self.assertEqual(c.total, Decimal("5.0441"))

    def test_sell_pays_stamp_duty(self):
        c = self.model.compute(CN_STOCK, Side.SELL, Decimal("100"), Decimal("10"))
        self.assertEqual(c.stamp_duty, Decimal("0.5"))       # 0.05% sell only
        self.assertEqual(c.total, Decimal("5.5441"))

    def test_commission_minimum_makes_small_orders_expensive(self):
        c = self.model.compute(CN_STOCK, Side.BUY, Decimal("100"), Decimal("1"))
        # Turnover 100; commission floor of 5 is 5% of the trade.
        self.assertEqual(c.commission, Decimal("5"))
        self.assertGreater(c.total / Decimal("100"), Decimal("0.05"))

    def test_large_order_uses_the_rate_not_the_floor(self):
        c = self.model.compute(CN_STOCK, Side.SELL, Decimal("10000"), Decimal("100"))
        self.assertEqual(c.commission, Decimal("250"))       # 0.025% of 1,000,000
        self.assertEqual(c.stamp_duty, Decimal("500"))
        self.assertEqual(c.total, Decimal("794.1"))


class TestRussiaCosts(unittest.TestCase):
    def test_symmetric_costs_on_both_sides(self):
        model = RussiaCostModel()
        buy = model.compute(RU_STOCK, Side.BUY, Decimal("100"), Decimal("200"))
        sell = model.compute(RU_STOCK, Side.SELL, Decimal("100"), Decimal("200"))
        self.assertEqual(buy.commission, Decimal("10"))      # 0.05% of 20,000
        self.assertEqual(buy.exchange_fee, Decimal("2"))     # 0.01%
        self.assertEqual(buy.total, Decimal("12"))
        self.assertEqual(buy.total, sell.total)


class TestFlatBpsAndRegistry(unittest.TestCase):
    def test_flat_bps(self):
        model = FlatBpsCostModel(rate_bps=Decimal("10"))
        c = model.compute(US_STOCK, Side.BUY, Decimal("100"), Decimal("100"))
        self.assertEqual(c.commission, Decimal("10"))        # 10 bps of 10,000

    def test_registry_returns_the_right_model(self):
        self.assertIsInstance(get_cost_model("IN"), IndiaCostModel)
        self.assertIsInstance(get_cost_model("us"), USCostModel)
        self.assertIsInstance(get_cost_model("CN"), ChinaCostModel)
        self.assertIsInstance(get_cost_model("RU"), RussiaCostModel)

    def test_unknown_region_falls_back(self):
        self.assertIsInstance(get_cost_model("ZZ"), FlatBpsCostModel)

    def test_registration_overrides(self):
        custom = FlatBpsCostModel(region="QQ", rate_bps=Decimal("50"))
        register_cost_model("QQ", custom)
        self.assertIs(get_cost_model("QQ"), custom)


class TestCostBreakdown(unittest.TestCase):
    def test_addition_is_componentwise(self):
        a = CostBreakdown(commission=Decimal("1"), securities_tax=Decimal("2"))
        b = CostBreakdown(commission=Decimal("3"), gst=Decimal("4"))
        total = a + b
        self.assertEqual(total.commission, Decimal("4"))
        self.assertEqual(total.securities_tax, Decimal("2"))
        self.assertEqual(total.gst, Decimal("4"))
        self.assertEqual(total.total, Decimal("10"))

    def test_totals_partition_correctly(self):
        c = CostBreakdown(
            commission=Decimal("1"), securities_tax=Decimal("2"),
            exchange_fee=Decimal("3"), regulatory_fee=Decimal("4"),
            stamp_duty=Decimal("5"), gst=Decimal("6"),
        )
        self.assertEqual(c.taxes, Decimal("13"))     # 2 + 5 + 6
        self.assertEqual(c.fees, Decimal("7"))       # 3 + 4
        self.assertEqual(c.total, Decimal("21"))


class TestSlippage(unittest.TestCase):
    def setUp(self):
        self.model = SlippageModel(
            half_spread_bps=Decimal("2"), impact_coefficient=Decimal("0")
        )

    def test_buys_pay_up(self):
        price = self.model.apply(Decimal("100"), Side.BUY, Decimal("1"), Decimal("0"))
        self.assertEqual(price, Decimal("100.02"))

    def test_sells_receive_less(self):
        price = self.model.apply(Decimal("100"), Side.SELL, Decimal("1"), Decimal("0"))
        self.assertEqual(price, Decimal("99.98"))

    def test_slippage_always_moves_against_the_order(self):
        for side, cmp_ in ((Side.BUY, self.assertGreater), (Side.SELL, self.assertLess)):
            price = self.model.apply(Decimal("50"), side, Decimal("10"), Decimal("1000"))
            cmp_(price, Decimal("50"))

    def test_impact_scales_with_square_root_of_participation(self):
        model = SlippageModel(half_spread_bps=Decimal("2"), impact_coefficient=Decimal("10"))
        # participation = 1000/100000 = 0.01 ; sqrt = 0.1 ; impact = 1 bp
        self.assertEqual(model.slippage_bps(Decimal("1000"), Decimal("100000")), Decimal("3"))

    def test_larger_orders_slip_more(self):
        model = SlippageModel(half_spread_bps=Decimal("2"), impact_coefficient=Decimal("10"))
        small = model.slippage_bps(Decimal("100"), Decimal("100000"))
        large = model.slippage_bps(Decimal("10000"), Decimal("100000"))
        self.assertGreater(large, small)

    def test_slippage_is_clamped(self):
        model = SlippageModel(
            half_spread_bps=Decimal("2"),
            impact_coefficient=Decimal("100000"),
            max_slippage_bps=Decimal("200"),
        )
        self.assertEqual(model.slippage_bps(Decimal("1000"), Decimal("1000")), Decimal("200"))

    def test_zero_volume_uses_spread_only(self):
        model = SlippageModel(half_spread_bps=Decimal("5"), impact_coefficient=Decimal("10"))
        self.assertEqual(model.slippage_bps(Decimal("100"), Decimal("0")), Decimal("5"))

    def test_zero_slippage_model_is_a_no_op(self):
        self.assertEqual(
            ZERO_SLIPPAGE.apply(Decimal("100"), Side.BUY, Decimal("50"), Decimal("1000")),
            Decimal("100"),
        )


if __name__ == "__main__":
    unittest.main()
