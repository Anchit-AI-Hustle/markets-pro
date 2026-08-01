"""Pre-trade risk checks and portfolio kill-switches."""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.market import CHINA, INDIA, RUSSIA, UNITED_STATES
from autotrader.core.money import FXRates
from autotrader.execution.orders import Fill, Horizon, Order, Side
from autotrader.portfolio.portfolio import Portfolio
from autotrader.risk.limits import RiskConfig, RiskManager

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
FX = FXRates("USD", {"INR": Decimal("83"), "CNY": Decimal("7"), "RUB": Decimal("90")})

US_A = Instrument("AAPL", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), sector="tech")
US_B = Instrument("MSFT", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), sector="tech")
US_C = Instrument("XOM", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), sector="energy")
IN_A = Instrument("RELIANCE", "IN", AssetClass.EQUITY, "INR", Decimal("0.05"), sector="energy")
CN_A = Instrument("600519", "CN", AssetClass.EQUITY, "CNY", Decimal("0.01"), Decimal("100"))
RU_A = Instrument("GAZP", "RU", AssetClass.EQUITY, "RUB", Decimal("0.01"), sector="energy")


def cfg(**overrides):
    """A permissive baseline so each test isolates exactly one limit.

    The shipped :class:`RiskConfig` defaults are deliberately strict, which means
    several of them bind at once on a test portfolio. Starting from "everything
    open" and tightening one dial keeps each test's failure attributable.
    """
    base = dict(
        max_open_positions=100,
        max_positions_per_region=100,
        max_region_weight=Decimal("10"),
        max_sector_weight=Decimal("10"),
        max_gross_leverage=Decimal("10"),
        max_net_exposure=Decimal("10"),
        max_drawdown_halt=Decimal("0.99"),
        daily_loss_limit=Decimal("0.99"),
        max_portfolio_heat=Decimal("10"),
        allow_short=False,
    )
    base.update(overrides)
    return RiskConfig(**base)


def make_fill(instrument, side, qty, price, day=D1):
    return Fill(
        order_id=1, instrument=instrument, side=side, quantity=Decimal(str(qty)),
        price=Decimal(str(price)), day=day, horizon=Horizon.LONG_TERM,
        commission=Decimal("0"), taxes=Decimal("0"), fees=Decimal("0"),
        slippage_per_unit=Decimal("0"),
    )


class RiskTestCase(unittest.TestCase):
    def setUp(self):
        self.portfolio = Portfolio("USD", {"USD": Decimal("100000")}, allow_margin=True)
        self.prices = {}

    def buy(self, instrument, qty, price, day=D1):
        self.portfolio.apply_fill(make_fill(instrument, Side.BUY, qty, price, day))
        self.prices[instrument.key] = Decimal(str(price))

    def check(self, manager, order, market, price, day=D2, is_exit=False):
        return manager.check(
            order, day=day, portfolio=self.portfolio, market=market,
            price=Decimal(str(price)), prices=self.prices, fx=FX, is_exit=is_exit,
        )


class TestPositionCountLimits(RiskTestCase):
    def test_max_open_positions_blocks_a_new_name(self):
        manager = RiskManager(cfg(max_open_positions=2, max_gross_leverage=Decimal("10")))
        self.buy(US_A, 10, 100)
        self.buy(US_B, 10, 100)
        order = Order(instrument=US_C, side=Side.BUY, quantity=Decimal("10"))
        decision = self.check(manager, order, UNITED_STATES, 100)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "max_positions")

    def test_adding_to_an_existing_name_is_allowed_at_the_cap(self):
        manager = RiskManager(cfg(max_open_positions=2, max_gross_leverage=Decimal("10")))
        self.buy(US_A, 10, 100)
        self.buy(US_B, 10, 100)
        order = Order(instrument=US_A, side=Side.BUY, quantity=Decimal("10"))
        self.assertTrue(self.check(manager, order, UNITED_STATES, 100).allowed)

    def test_per_region_cap(self):
        manager = RiskManager(
            cfg(max_positions_per_region=1, max_gross_leverage=Decimal("10"))
        )
        self.buy(US_A, 10, 100)
        order = Order(instrument=US_B, side=Side.BUY, quantity=Decimal("10"))
        decision = self.check(manager, order, UNITED_STATES, 100)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "max_region_positions")

    def test_a_different_region_is_unaffected_by_another_regions_cap(self):
        manager = RiskManager(
            cfg(max_positions_per_region=1, max_gross_leverage=Decimal("10"))
        )
        self.buy(US_A, 10, 100)
        order = Order(instrument=IN_A, side=Side.BUY, quantity=Decimal("10"))
        self.assertTrue(self.check(manager, order, INDIA, 2000).allowed)


class TestConcentrationLimits(RiskTestCase):
    def test_region_weight_cap(self):
        manager = RiskManager(
            cfg(max_region_weight=Decimal("0.50"), max_gross_leverage=Decimal("10"))
        )
        self.buy(US_A, 400, 100)          # 40,000 of 100,000 equity
        order = Order(instrument=US_B, side=Side.BUY, quantity=Decimal("200"))
        decision = self.check(manager, order, UNITED_STATES, 100)   # +20,000 -> 60%
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "max_region_weight")

    def test_region_weight_within_limit_passes(self):
        manager = RiskManager(
            cfg(max_region_weight=Decimal("0.50"), max_gross_leverage=Decimal("10"))
        )
        self.buy(US_A, 400, 100)
        order = Order(instrument=US_B, side=Side.BUY, quantity=Decimal("50"))
        self.assertTrue(self.check(manager, order, UNITED_STATES, 100).allowed)

    def test_sector_weight_cap(self):
        manager = RiskManager(
            cfg(
                max_sector_weight=Decimal("0.30"),
                max_region_weight=Decimal("1.0"),
                max_gross_leverage=Decimal("10"),
            )
        )
        self.buy(US_A, 250, 100)          # 25,000 in tech
        order = Order(instrument=US_B, side=Side.BUY, quantity=Decimal("100"))
        decision = self.check(manager, order, UNITED_STATES, 100)   # +10,000 -> 35%
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "max_sector_weight")

    def test_unknown_sector_is_not_aggregated(self):
        plain = Instrument("PLAIN", "US", AssetClass.EQUITY, "USD", Decimal("0.01"))
        manager = RiskManager(
            cfg(
                max_sector_weight=Decimal("0.01"),
                max_region_weight=Decimal("1.0"),
                max_gross_leverage=Decimal("10"),
            )
        )
        order = Order(instrument=plain, side=Side.BUY, quantity=Decimal("100"))
        self.assertTrue(self.check(manager, order, UNITED_STATES, 100).allowed)

    def test_gross_leverage_cap(self):
        manager = RiskManager(cfg(max_gross_leverage=Decimal("1.0")))
        order = Order(instrument=US_A, side=Side.BUY, quantity=Decimal("1500"))
        decision = self.check(manager, order, UNITED_STATES, 100)   # 150,000 on 100,000
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "max_leverage")

    def test_fully_invested_is_allowed_at_exactly_one_times(self):
        manager = RiskManager(cfg(max_gross_leverage=Decimal("1.0")))
        order = Order(instrument=US_A, side=Side.BUY, quantity=Decimal("1000"))
        self.assertTrue(self.check(manager, order, UNITED_STATES, 100).allowed)


class TestShortSelling(RiskTestCase):
    def test_venue_that_forbids_shorting_blocks_the_order(self):
        manager = RiskManager(cfg(allow_short=True, max_gross_leverage=Decimal("10")))
        order = Order(instrument=RU_A, side=Side.SELL, quantity=Decimal("100"))
        decision = self.check(manager, order, RUSSIA, 200)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "short_not_allowed")

    def test_config_can_disable_shorting_on_a_venue_that_permits_it(self):
        manager = RiskManager(cfg(allow_short=False, max_gross_leverage=Decimal("10")))
        order = Order(instrument=US_A, side=Side.SELL, quantity=Decimal("100"))
        decision = self.check(manager, order, UNITED_STATES, 100)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "short_disabled")

    def test_shorting_allowed_when_both_permit(self):
        manager = RiskManager(cfg(allow_short=True, max_gross_leverage=Decimal("10")))
        order = Order(instrument=US_A, side=Side.SELL, quantity=Decimal("100"))
        self.assertTrue(self.check(manager, order, UNITED_STATES, 100).allowed)

    def test_selling_what_you_hold_is_not_a_short(self):
        manager = RiskManager(cfg(allow_short=False, max_gross_leverage=Decimal("10")))
        self.buy(US_A, 100, 100)
        order = Order(instrument=US_A, side=Side.SELL, quantity=Decimal("100"))
        self.assertTrue(self.check(manager, order, UNITED_STATES, 100).allowed)

    def test_selling_more_than_held_is_a_short(self):
        manager = RiskManager(cfg(allow_short=False, max_gross_leverage=Decimal("10")))
        self.buy(US_A, 100, 100)
        order = Order(instrument=US_A, side=Side.SELL, quantity=Decimal("150"))
        self.assertFalse(self.check(manager, order, UNITED_STATES, 100).allowed)

    def test_non_shortable_asset_class(self):
        bond = Instrument("TBOND", "US", AssetClass.BOND, "USD", Decimal("0.01"))
        manager = RiskManager(cfg(allow_short=True, max_gross_leverage=Decimal("10")))
        order = Order(instrument=bond, side=Side.SELL, quantity=Decimal("100"))
        decision = self.check(manager, order, UNITED_STATES, 100)
        self.assertEqual(decision.code, "not_shortable")


class TestSettlementRules(RiskTestCase):
    def test_china_blocks_a_same_session_sell(self):
        manager = RiskManager(cfg(max_gross_leverage=Decimal("10")))
        self.buy(CN_A, 100, 100, day=D1)
        order = Order(instrument=CN_A, side=Side.SELL, quantity=Decimal("100"))
        decision = self.check(manager, order, CHINA, 100, day=D1)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "t_plus_one")

    def test_china_allows_the_sell_on_the_next_session(self):
        manager = RiskManager(cfg(max_gross_leverage=Decimal("10")))
        self.buy(CN_A, 100, 100, day=D1)
        order = Order(instrument=CN_A, side=Side.SELL, quantity=Decimal("100"))
        self.assertTrue(self.check(manager, order, CHINA, 100, day=D2).allowed)

    def test_india_permits_a_same_session_round_trip(self):
        manager = RiskManager(cfg(max_gross_leverage=Decimal("10")))
        self.buy(IN_A, 100, 2000, day=D1)
        order = Order(instrument=IN_A, side=Side.SELL, quantity=Decimal("100"))
        self.assertTrue(self.check(manager, order, INDIA, 2000, day=D1).allowed)

    def test_t_plus_one_applies_to_exits_too(self):
        # Exits skip entry limits, but they cannot break exchange rules.
        manager = RiskManager(cfg(max_gross_leverage=Decimal("10")))
        self.buy(CN_A, 100, 100, day=D1)
        order = Order(instrument=CN_A, side=Side.SELL, quantity=Decimal("100"))
        decision = self.check(manager, order, CHINA, 100, day=D1, is_exit=True)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "t_plus_one")


class TestKillSwitches(RiskTestCase):
    def test_drawdown_halt_trips(self):
        manager = RiskManager(cfg(max_drawdown_halt=Decimal("0.20")))
        manager.start_day(Decimal("100000"))
        manager.update_equity(Decimal("75000"))      # -25%
        self.assertTrue(manager.entries_halted)
        self.assertEqual(manager.state.halt_reason, "max_drawdown_halt")

    def test_drawdown_within_tolerance_does_not_halt(self):
        manager = RiskManager(cfg(max_drawdown_halt=Decimal("0.20")))
        manager.start_day(Decimal("100000"))
        manager.update_equity(Decimal("85000"))      # -15%
        self.assertFalse(manager.entries_halted)

    def test_daily_loss_limit_trips(self):
        manager = RiskManager(
            cfg(daily_loss_limit=Decimal("0.05"), max_drawdown_halt=Decimal("0.90"))
        )
        manager.start_day(Decimal("100000"))
        manager.update_equity(Decimal("94000"))      # -6% on the day
        self.assertTrue(manager.entries_halted)
        self.assertEqual(manager.state.halt_reason, "daily_loss_limit")

    def test_a_new_day_clears_the_daily_loss_halt(self):
        manager = RiskManager(
            cfg(daily_loss_limit=Decimal("0.05"), max_drawdown_halt=Decimal("0.90"))
        )
        manager.start_day(Decimal("100000"))
        manager.update_equity(Decimal("94000"))
        manager.start_day(Decimal("94000"))
        self.assertFalse(manager.entries_halted)

    def test_a_new_day_does_not_clear_the_drawdown_halt(self):
        manager = RiskManager(cfg(max_drawdown_halt=Decimal("0.20")))
        manager.start_day(Decimal("100000"))
        manager.update_equity(Decimal("75000"))
        manager.start_day(Decimal("75000"))
        self.assertTrue(manager.entries_halted)

    def test_equity_peak_only_rises(self):
        manager = RiskManager(cfg())
        manager.start_day(Decimal("100000"))
        manager.update_equity(Decimal("120000"))
        manager.update_equity(Decimal("90000"))
        self.assertEqual(manager.state.equity_peak, Decimal("120000"))
        self.assertEqual(manager.state.drawdown, Decimal("0.25"))

    def test_halted_entries_are_blocked(self):
        manager = RiskManager(cfg(max_drawdown_halt=Decimal("0.20")))
        manager.start_day(Decimal("100000"))
        manager.update_equity(Decimal("75000"))
        order = Order(instrument=US_A, side=Side.BUY, quantity=Decimal("10"))
        decision = self.check(manager, order, UNITED_STATES, 100)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "halted")

    def test_exits_are_allowed_while_halted(self):
        manager = RiskManager(cfg(max_drawdown_halt=Decimal("0.20")))
        self.buy(US_A, 100, 100)
        manager.start_day(Decimal("100000"))
        manager.update_equity(Decimal("75000"))
        order = Order(instrument=US_A, side=Side.SELL, quantity=Decimal("100"))
        self.assertTrue(self.check(manager, order, UNITED_STATES, 100, is_exit=True).allowed)


class TestRejectionLogging(RiskTestCase):
    def test_rejections_are_recorded_with_a_reason(self):
        manager = RiskManager(cfg(max_gross_leverage=Decimal("0.5")))
        order = Order(instrument=US_A, side=Side.BUY, quantity=Decimal("1000"))
        self.check(manager, order, UNITED_STATES, 100)
        self.assertEqual(len(manager.state.rejections), 1)
        day, key, code, detail = manager.state.rejections[0]
        self.assertEqual(key, "US:AAPL")
        self.assertEqual(code, "max_leverage")
        self.assertTrue(detail)

    def test_allowed_orders_are_not_recorded(self):
        manager = RiskManager(cfg(max_gross_leverage=Decimal("10")))
        order = Order(instrument=US_A, side=Side.BUY, quantity=Decimal("10"))
        self.check(manager, order, UNITED_STATES, 100)
        self.assertEqual(len(manager.state.rejections), 0)


class TestPortfolioHeat(RiskTestCase):
    def test_heat_is_the_sum_of_stop_distances(self):
        manager = RiskManager(cfg())
        self.buy(US_A, 100, 100)
        heat = manager.portfolio_heat(
            self.portfolio, {US_A.key: Decimal("95")}, self.prices, FX
        )
        # 100 shares * 5 = 500 at risk on 100,000 equity
        self.assertEqual(heat, Decimal("0.005"))

    def test_heat_ignores_positions_without_stops(self):
        manager = RiskManager(cfg())
        self.buy(US_A, 100, 100)
        self.assertEqual(manager.portfolio_heat(self.portfolio, {}, self.prices, FX),
                         Decimal("0"))

    def test_heat_aggregates_across_positions(self):
        manager = RiskManager(cfg())
        self.buy(US_A, 100, 100)
        self.buy(US_B, 100, 100)
        stops = {US_A.key: Decimal("95"), US_B.key: Decimal("90")}
        heat = manager.portfolio_heat(self.portfolio, stops, self.prices, FX)
        self.assertEqual(heat, Decimal("0.015"))     # (500 + 1000) / 100,000


class TestConfigValidation(unittest.TestCase):
    def test_max_open_positions_must_be_positive(self):
        with self.assertRaises(ValueError):
            RiskConfig(max_open_positions=0)


if __name__ == "__main__":
    unittest.main()
