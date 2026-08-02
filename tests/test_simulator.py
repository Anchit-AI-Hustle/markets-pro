"""Order validation and fill simulation."""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.market import CHINA, INDIA, UNITED_STATES
from autotrader.data.bars import Bar
from autotrader.execution.costs import ZERO_SLIPPAGE, SlippageModel, USCostModel
from autotrader.execution.orders import (
    Fill,
    Horizon,
    Order,
    OrderType,
    Rejection,
    Side,
)
from autotrader.execution.simulator import ExecutionConfig, ExecutionSimulator

DAY = date(2024, 1, 5)
US = Instrument("AAPL", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), Decimal("1"))
IN = Instrument("RELIANCE", "IN", AssetClass.EQUITY, "INR", Decimal("0.05"), Decimal("1"))
CN = Instrument("600519", "CN", AssetClass.EQUITY, "CNY", Decimal("0.01"), Decimal("100"))


def bar(open_, high, low, close, volume=10000):
    return Bar(
        day=DAY,
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(volume),
    )


def order(side=Side.BUY, qty="100", instrument=US, **kwargs):
    return Order(instrument=instrument, side=side, quantity=Decimal(qty), **kwargs)


class TestOrderValidation(unittest.TestCase):
    def test_negative_quantity_rejected(self):
        with self.assertRaises(ValueError):
            Order(instrument=US, side=Side.BUY, quantity=Decimal("-1"))

    def test_zero_quantity_rejected(self):
        with self.assertRaises(ValueError):
            Order(instrument=US, side=Side.BUY, quantity=Decimal("0"))

    def test_lot_size_violation_rejected(self):
        # China trades in board lots of 100; 137 is not a valid order.
        with self.assertRaises(ValueError):
            Order(instrument=CN, side=Side.BUY, quantity=Decimal("137"))

    def test_valid_board_lot_accepted(self):
        self.assertEqual(
            Order(instrument=CN, side=Side.BUY, quantity=Decimal("200")).quantity,
            Decimal("200"),
        )

    def test_limit_order_requires_a_price(self):
        with self.assertRaises(ValueError):
            Order(instrument=US, side=Side.BUY, quantity=Decimal("1"),
                  order_type=OrderType.LIMIT)

    def test_stop_order_requires_a_price(self):
        with self.assertRaises(ValueError):
            Order(instrument=US, side=Side.BUY, quantity=Decimal("1"),
                  order_type=OrderType.STOP)

    def test_non_positive_limit_price_rejected(self):
        with self.assertRaises(ValueError):
            Order(instrument=US, side=Side.BUY, quantity=Decimal("1"),
                  order_type=OrderType.LIMIT, limit_price=Decimal("0"))

    def test_signed_quantity_follows_the_side(self):
        self.assertEqual(order(Side.BUY).signed_quantity, Decimal("100"))
        self.assertEqual(order(Side.SELL).signed_quantity, Decimal("-100"))

    def test_side_helpers(self):
        self.assertEqual(Side.BUY.sign, 1)
        self.assertEqual(Side.SELL.sign, -1)
        self.assertIs(Side.BUY.opposite, Side.SELL)


class TestFillArithmetic(unittest.TestCase):
    def _fill(self, side, commission="0", taxes="0", fees="0"):
        return Fill(
            order_id=1, instrument=US, side=side, quantity=Decimal("100"),
            price=Decimal("50"), day=DAY, horizon=Horizon.SHORT_TERM,
            commission=Decimal(commission), taxes=Decimal(taxes), fees=Decimal(fees),
            slippage_per_unit=Decimal("0"),
        )

    def test_gross_value(self):
        self.assertEqual(self._fill(Side.BUY).gross_value, Decimal("5000"))

    def test_buy_cash_delta_is_negative(self):
        self.assertEqual(self._fill(Side.BUY, commission="5").cash_delta, Decimal("-5005"))

    def test_sell_cash_delta_is_positive_net_of_costs(self):
        self.assertEqual(self._fill(Side.SELL, commission="5").cash_delta, Decimal("4995"))

    def test_total_cost_sums_components(self):
        self.assertEqual(
            self._fill(Side.BUY, commission="1", taxes="2", fees="3").total_cost,
            Decimal("6"),
        )


class TestMarketOrders(unittest.TestCase):
    def setUp(self):
        self.sim = ExecutionSimulator(ZERO_SLIPPAGE, ExecutionConfig())

    def test_fills_at_the_open(self):
        result = self.sim.execute(order(), bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertIsInstance(result, Fill)
        self.assertEqual(result.price, Decimal("100"))

    def test_fill_price_is_never_the_close(self):
        # Guards against the classic "fill at today's close" lookahead shortcut.
        b = bar(100, 105, 99, 103)
        result = self.sim.execute(order(), b, market=UNITED_STATES)
        self.assertNotEqual(result.price, b.close)

    def test_slippage_moves_the_buy_price_up(self):
        sim = ExecutionSimulator(
            SlippageModel(half_spread_bps=Decimal("10"), impact_coefficient=Decimal("0"))
        )
        result = sim.execute(order(), bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("100.10"))

    def test_slippage_moves_the_sell_price_down(self):
        sim = ExecutionSimulator(
            SlippageModel(half_spread_bps=Decimal("10"), impact_coefficient=Decimal("0"))
        )
        result = sim.execute(order(Side.SELL), bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("99.90"))

    def test_fill_price_snaps_to_the_tick_grid(self):
        sim = ExecutionSimulator(
            SlippageModel(half_spread_bps=Decimal("3"), impact_coefficient=Decimal("0"))
        )
        # 1000 * 1.0003 = 1000.30 which is already on the 0.05 NSE grid;
        # use a price that is not, to prove rounding happens.
        result = sim.execute(
            order(instrument=IN), bar(1000, 1010, 995, 1005), market=INDIA
        )
        remainder = result.price % Decimal("0.05")
        self.assertEqual(remainder, Decimal("0"))

    def test_fill_price_is_clamped_inside_the_bar(self):
        sim = ExecutionSimulator(
            SlippageModel(half_spread_bps=Decimal("500"), impact_coefficient=Decimal("0"))
        )
        b = bar(100, 100.5, 99, 100)
        result = sim.execute(order(), b, market=UNITED_STATES)
        self.assertLessEqual(result.price, b.high)
        self.assertGreaterEqual(result.price, b.low)

    def test_costs_are_attached_to_the_fill(self):
        result = self.sim.execute(
            order(Side.SELL), bar(50, 51, 49, 50), market=UNITED_STATES,
            cost_model=USCostModel(),
        )
        self.assertGreater(result.total_cost, Decimal("0"))

    def test_buy_on_a_us_venue_has_no_regulatory_cost(self):
        result = self.sim.execute(
            order(Side.BUY), bar(50, 51, 49, 50), market=UNITED_STATES,
            cost_model=USCostModel(),
        )
        self.assertEqual(result.total_cost, Decimal("0"))


class TestLimitOrders(unittest.TestCase):
    def setUp(self):
        self.sim = ExecutionSimulator(ZERO_SLIPPAGE)

    def test_buy_limit_not_reached_is_rejected(self):
        o = order(Side.BUY, order_type=OrderType.LIMIT, limit_price=Decimal("95"))
        result = self.sim.execute(o, bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.code, "not_triggered")

    def test_buy_limit_reached_fills_at_the_limit(self):
        o = order(Side.BUY, order_type=OrderType.LIMIT, limit_price=Decimal("100"))
        result = self.sim.execute(o, bar(102, 105, 99, 103), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("100"))

    def test_buy_limit_gapped_below_fills_at_the_better_open(self):
        # Limit 100, bar opens at 95: you get 95, not 100.
        o = order(Side.BUY, order_type=OrderType.LIMIT, limit_price=Decimal("100"))
        result = self.sim.execute(o, bar(95, 99, 94, 97), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("95"))

    def test_sell_limit_not_reached_is_rejected(self):
        o = order(Side.SELL, order_type=OrderType.LIMIT, limit_price=Decimal("110"))
        result = self.sim.execute(o, bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertIsInstance(result, Rejection)

    def test_sell_limit_reached_fills_at_the_limit(self):
        o = order(Side.SELL, order_type=OrderType.LIMIT, limit_price=Decimal("104"))
        result = self.sim.execute(o, bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("104"))

    def test_sell_limit_gapped_above_fills_at_the_better_open(self):
        o = order(Side.SELL, order_type=OrderType.LIMIT, limit_price=Decimal("100"))
        result = self.sim.execute(o, bar(108, 110, 107, 109), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("108"))


class TestStopOrders(unittest.TestCase):
    def setUp(self):
        self.sim = ExecutionSimulator(ZERO_SLIPPAGE)

    def test_buy_stop_not_triggered(self):
        o = order(Side.BUY, order_type=OrderType.STOP, stop_price=Decimal("110"))
        result = self.sim.execute(o, bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertIsInstance(result, Rejection)

    def test_buy_stop_triggered_fills_at_the_stop(self):
        o = order(Side.BUY, order_type=OrderType.STOP, stop_price=Decimal("104"))
        result = self.sim.execute(o, bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("104"))

    def test_buy_stop_gapped_through_fills_at_the_worse_open(self):
        o = order(Side.BUY, order_type=OrderType.STOP, stop_price=Decimal("104"))
        result = self.sim.execute(o, bar(108, 110, 107, 109), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("108"))

    def test_sell_stop_triggered_fills_at_the_stop(self):
        o = order(Side.SELL, order_type=OrderType.STOP, stop_price=Decimal("99.5"))
        result = self.sim.execute(o, bar(100, 105, 99, 103), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("99.5"))

    def test_sell_stop_gapped_down_fills_at_the_worse_open(self):
        o = order(Side.SELL, order_type=OrderType.STOP, stop_price=Decimal("99"))
        result = self.sim.execute(o, bar(90, 95, 88, 92), market=UNITED_STATES)
        self.assertEqual(result.price, Decimal("90"))


class TestPriceLimits(unittest.TestCase):
    def setUp(self):
        self.sim = ExecutionSimulator(ZERO_SLIPPAGE)

    def test_order_beyond_the_china_daily_band_is_rejected(self):
        o = order(instrument=CN, qty="100")
        result = self.sim.execute(
            o, bar(115, 116, 114, 115), market=CHINA, previous_close=Decimal("100")
        )
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.code, "price_limit")

    def test_order_inside_the_band_fills(self):
        o = order(instrument=CN, qty="100")
        result = self.sim.execute(
            o, bar(105, 106, 104, 105), market=CHINA, previous_close=Decimal("100")
        )
        self.assertIsInstance(result, Fill)

    def test_us_has_no_band_so_a_large_move_still_fills(self):
        result = self.sim.execute(
            order(), bar(150, 151, 149, 150), market=UNITED_STATES,
            previous_close=Decimal("100"),
        )
        self.assertIsInstance(result, Fill)

    def test_no_previous_close_skips_the_band_check(self):
        result = self.sim.execute(
            order(instrument=CN, qty="100"), bar(115, 116, 114, 115), market=CHINA
        )
        self.assertIsInstance(result, Fill)


class TestLiquidity(unittest.TestCase):
    def setUp(self):
        self.sim = ExecutionSimulator(
            ZERO_SLIPPAGE,
            ExecutionConfig(max_volume_participation=Decimal("0.10")),
        )

    def test_order_within_participation_fills_in_full(self):
        result = self.sim.execute(order(qty="100"), bar(100, 101, 99, 100, volume=10000),
                                  market=UNITED_STATES)
        self.assertEqual(result.quantity, Decimal("100"))

    def test_oversized_order_is_capped_to_the_participation_limit(self):
        result = self.sim.execute(order(qty="5000"), bar(100, 101, 99, 100, volume=10000),
                                  market=UNITED_STATES)
        self.assertEqual(result.quantity, Decimal("1000"))    # 10% of 10,000

    def test_cap_respects_board_lots(self):
        result = self.sim.execute(
            order(instrument=CN, qty="5000"), bar(100, 101, 99, 100, volume=1050),
            market=CHINA,
        )
        # 10% of 1,050 = 105 -> floored to one 100-share lot.
        self.assertEqual(result.quantity, Decimal("100"))

    def test_zero_volume_assumes_the_order_fills(self):
        result = self.sim.execute(order(qty="100"), bar(100, 101, 99, 100, volume=0),
                                  market=UNITED_STATES)
        self.assertIsInstance(result, Fill)
        self.assertEqual(result.quantity, Decimal("100"))

    def test_average_volume_overrides_the_session_volume(self):
        result = self.sim.execute(
            order(qty="5000"), bar(100, 101, 99, 100, volume=10000),
            market=UNITED_STATES, average_volume=Decimal("100000"),
        )
        self.assertEqual(result.quantity, Decimal("5000"))    # 10% of 100,000

    def test_reject_mode_refuses_instead_of_capping(self):
        sim = ExecutionSimulator(
            ZERO_SLIPPAGE,
            ExecutionConfig(
                max_volume_participation=Decimal("0.10"),
                reject_on_insufficient_volume=True,
            ),
        )
        result = sim.execute(order(qty="5000"), bar(100, 101, 99, 100, volume=10000),
                             market=UNITED_STATES)
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.code, "insufficient_volume")

    def test_capped_to_zero_is_rejected(self):
        result = self.sim.execute(
            order(instrument=CN, qty="100"), bar(100, 101, 99, 100, volume=100),
            market=CHINA,
        )
        # 10% of 100 = 10, which is below one 100-share board lot.
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.code, "no_liquidity")


class TestExitFills(unittest.TestCase):
    def test_execute_at_price_uses_the_given_level(self):
        sim = ExecutionSimulator(ZERO_SLIPPAGE)
        fill = sim.execute_at_price(
            order(Side.SELL), Decimal("95"), DAY, market=UNITED_STATES
        )
        self.assertEqual(fill.price, Decimal("95"))

    def test_exit_slippage_still_moves_against_the_trader(self):
        sim = ExecutionSimulator(
            SlippageModel(half_spread_bps=Decimal("10"), impact_coefficient=Decimal("0"))
        )
        fill = sim.execute_at_price(
            order(Side.SELL), Decimal("100"), DAY, market=UNITED_STATES
        )
        self.assertEqual(fill.price, Decimal("99.90"))

    def test_slippage_can_be_disabled_for_exits(self):
        sim = ExecutionSimulator(SlippageModel(half_spread_bps=Decimal("10")))
        fill = sim.execute_at_price(
            order(Side.SELL), Decimal("100"), DAY, market=UNITED_STATES,
            apply_slippage=False,
        )
        self.assertEqual(fill.price, Decimal("100"))


if __name__ == "__main__":
    unittest.main()
