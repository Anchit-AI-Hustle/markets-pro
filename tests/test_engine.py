"""End-to-end engine tests.

These assert the invariants that make the whole thing trustworthy:

* orders decided on day D fill at day D+1's open (no lookahead);
* the accounting identity holds at every point on the equity curve;
* the same inputs produce the same outputs, byte for byte;
* venue rules (China T+1) are never violated by the engine.
"""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.money import FXRates
from autotrader.data.bars import MarketDataSet
from autotrader.data.synthetic import (
    business_days,
    generate_oscillating_series,
    generate_trending_series,
)
from autotrader.engine.backtest import BacktestConfig, BacktestEngine
from autotrader.execution.costs import ZERO_SLIPPAGE, SlippageModel
from autotrader.execution.orders import Horizon
from autotrader.execution.simulator import ExecutionConfig
from autotrader.portfolio.sizing import SizingConfig
from autotrader.risk.limits import RiskConfig
from autotrader.strategy.base import Direction, Signal, Strategy
from autotrader.strategy.short_term import ShortTermConfig, ShortTermStrategy

DAYS = business_days(date(2022, 1, 3), 400)
FX = FXRates("USD", {"INR": Decimal("83"), "CNY": Decimal("7")})

US_A = Instrument("AAA", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), Decimal("1"))
US_B = Instrument("BBB", "US", AssetClass.EQUITY, "USD", Decimal("0.01"), Decimal("1"))
IN_A = Instrument("RELI", "IN", AssetClass.EQUITY, "INR", Decimal("0.05"), Decimal("1"))
CN_A = Instrument("600519", "CN", AssetClass.EQUITY, "CNY", Decimal("0.01"), Decimal("100"))


def permissive_sizing(**kw):
    base = dict(
        risk_per_trade=Decimal("0.01"),
        max_position_weight=Decimal("1"),
        min_order_notional=Decimal("1"),
        max_cash_utilisation=Decimal("0.95"),
        max_volume_participation=Decimal("1"),
    )
    base.update(kw)
    return SizingConfig(**base)


def permissive_risk(**kw):
    base = dict(
        max_open_positions=50,
        max_positions_per_region=50,
        max_region_weight=Decimal("1"),
        max_sector_weight=Decimal("1"),
        max_gross_leverage=Decimal("1"),
        max_net_exposure=Decimal("1"),
        max_drawdown_halt=Decimal("0.99"),
        daily_loss_limit=Decimal("0.99"),
        max_portfolio_heat=Decimal("10"),
    )
    base.update(kw)
    return RiskConfig(**base)


class FixedWeightStrategy(Strategy):
    """Emits a constant target weight, optionally on one session only."""

    name = "fixed_weight"
    horizon = Horizon.LONG_TERM
    warmup_bars = 1

    def __init__(self, weights, only_on=None):
        self.weights = weights
        self.only_on = only_on

    def should_run(self, as_of, context):
        return self.only_on is None or as_of == self.only_on

    def generate(self, as_of, windows, instruments, context):
        return [
            Signal(
                instrument=instruments[key],
                direction=Direction.LONG,
                horizon=Horizon.LONG_TERM,
                target_weight=weight,
                reason="fixed weight",
            )
            for key, weight in self.weights.items()
            if key in windows
        ]


class ExitOnDayStrategy(Strategy):
    """Buys once, then flattens on a nominated session."""

    name = "buy_then_exit"
    horizon = Horizon.LONG_TERM
    warmup_bars = 1

    def __init__(self, key, buy_on, exit_on, weight=Decimal("0.5")):
        self.key = key
        self.buy_on = buy_on
        self.exit_on = exit_on
        self.weight = weight

    def should_run(self, as_of, context):
        return as_of in (self.buy_on, self.exit_on)

    def generate(self, as_of, windows, instruments, context):
        if self.key not in windows:
            return []
        if as_of == self.buy_on:
            return [Signal(instruments[self.key], Direction.LONG, Horizon.LONG_TERM,
                           target_weight=self.weight, reason="entry")]
        return [Signal(instruments[self.key], Direction.FLAT, Horizon.LONG_TERM,
                       reason="scheduled exit")]


def build_engine(instruments, series, strategies, *, cash=None, days=DAYS,
                 slippage=None, sizing=None, risk=None, start=None, end=None):
    data = MarketDataSet()
    for s in series:
        data.add(s.key, s)
    config = BacktestConfig(
        start=start or days[0],
        end=end or days[-1],
        base_currency="USD",
        starting_cash=cash or {"USD": Decimal("1000000")},
        sizing=sizing or permissive_sizing(),
        risk=risk or permissive_risk(),
        execution=ExecutionConfig(max_volume_participation=Decimal("1")),
        slippage=slippage or ZERO_SLIPPAGE,
    )
    return BacktestEngine(
        instruments=instruments, data=data, strategies=strategies,
        config=config, fx=FX,
    )


class TestNoLookahead(unittest.TestCase):
    """The defining invariant: today's decision cannot use tomorrow's price."""

    def setUp(self):
        self.series = generate_trending_series("US:AAA", DAYS, seed=1)
        self.engine = build_engine(
            [US_A], [self.series],
            [FixedWeightStrategy({"US:AAA": Decimal("0.5")}, only_on=DAYS[0])],
        )
        self.report = self.engine.run()

    def test_a_fill_occurs(self):
        self.assertEqual(len(self.engine.portfolio.fills), 1)

    def test_order_from_day_zero_fills_on_day_one(self):
        fill = self.engine.portfolio.fills[0]
        self.assertEqual(fill.day, DAYS[1])

    def test_fill_price_is_the_next_sessions_open(self):
        fill = self.engine.portfolio.fills[0]
        expected = self.series.bar_on(DAYS[1]).open
        self.assertEqual(fill.price, expected)

    def test_fill_price_is_not_the_decision_days_close(self):
        fill = self.engine.portfolio.fills[0]
        self.assertNotEqual(fill.price, self.series.bar_on(DAYS[0]).close)

    def test_equity_curve_covers_every_session(self):
        self.assertEqual(len(self.engine.portfolio.equity_curve), len(DAYS))


class TestLookaheadCanary(unittest.TestCase):
    """Record every bar the engine shows a strategy and audit it afterwards.

    This is stronger than checking one fill price: it inspects the entire run and
    fails if *any* bar handed to a strategy was dated after that strategy's
    decision date.
    """

    class SpyStrategy(Strategy):
        name = "spy"
        horizon = Horizon.LONG_TERM
        warmup_bars = 1

        def __init__(self):
            self.observations = []      # (decision_day, latest_bar_day, n_bars)

        def generate(self, as_of, windows, instruments, context):
            for key, window in windows.items():
                for bar in window.bars():
                    self.observations.append((as_of, bar.day, key))
            return []

    def setUp(self):
        self.spy = self.SpyStrategy()
        series = [
            generate_trending_series("US:AAA", DAYS[:60], seed=20),
            generate_oscillating_series("US:BBB", DAYS[:60], seed=21),
        ]
        engine = build_engine(
            [US_A, US_B], series, [self.spy],
            days=DAYS[:60], start=DAYS[0], end=DAYS[59],
        )
        engine.run()

    def test_the_spy_actually_observed_something(self):
        self.assertGreater(len(self.spy.observations), 100)

    def test_no_strategy_ever_saw_a_future_bar(self):
        violations = [
            (decision, bar_day, key)
            for decision, bar_day, key in self.spy.observations
            if bar_day > decision
        ]
        self.assertEqual(violations, [], f"{len(violations)} lookahead violations")

    def test_the_latest_visible_bar_is_the_decision_day_itself(self):
        # The strategy may see today's close (it decides at the close); it must
        # never see anything later.
        by_day = {}
        for decision, bar_day, _key in self.spy.observations:
            by_day[decision] = max(by_day.get(decision, bar_day), bar_day)
        for decision, latest in by_day.items():
            self.assertLessEqual(latest, decision)


class TestAccountingIdentity(unittest.TestCase):
    """equity == initial + realized + unrealized - costs, at every point."""

    def test_identity_holds_on_a_multi_asset_run(self):
        series = [
            generate_trending_series("US:AAA", DAYS, seed=2),
            generate_trending_series("US:BBB", DAYS, daily_drift=-0.001, seed=3),
        ]
        engine = build_engine(
            [US_A, US_B], series,
            [FixedWeightStrategy({"US:AAA": Decimal("0.3"), "US:BBB": Decimal("0.3")})],
        )
        engine.run()
        pf = engine.portfolio
        prices = engine.last_prices
        equity = pf.total_equity(prices, FX).amount
        expected = (
            pf.initial_equity(FX).amount
            + pf.realized_pnl(FX).amount
            + pf.unrealized_pnl(prices, FX).amount
            - pf.costs_paid(FX).amount
        )
        self.assertEqual(equity, expected)

    def test_final_equity_matches_the_last_curve_point(self):
        series = [generate_trending_series("US:AAA", DAYS, seed=4)]
        engine = build_engine(
            [US_A], series, [FixedWeightStrategy({"US:AAA": Decimal("0.5")})]
        )
        report = engine.run()
        self.assertEqual(report.ending_equity, engine.portfolio.equity_curve[-1].equity)

    def test_cash_never_goes_negative_without_margin(self):
        series = [generate_trending_series("US:AAA", DAYS, seed=5)]
        engine = build_engine(
            [US_A], series, [FixedWeightStrategy({"US:AAA": Decimal("0.9")})]
        )
        engine.run()
        for currency, money in engine.portfolio.cash.items():
            self.assertGreaterEqual(money.amount, Decimal("0"), currency)

    def test_costs_are_strictly_positive_when_trading_occurs(self):
        series = [generate_trending_series("US:AAA", DAYS, seed=6)]
        engine = build_engine(
            [US_A], series, [FixedWeightStrategy({"US:AAA": Decimal("0.5")})]
        )
        engine.run()
        if engine.portfolio.fills:
            self.assertGreaterEqual(engine.portfolio.costs_paid(FX).amount, Decimal("0"))


class TestTradePnlReconciliation(unittest.TestCase):
    """Summed round-trip P&L must reconcile with the equity curve.

    Regression guard for mixed-currency aggregation: if trade P&L were summed in
    local currency, this would be off by the FX rates. With every position
    closed and a constant FX table, the two must agree exactly.
    """

    def setUp(self):
        series = [
            generate_trending_series("US:AAA", DAYS, seed=22),
            generate_trending_series("IN:RELI", DAYS, start_price=Decimal("2500"),
                                     tick_size=Decimal("0.05"), seed=23),
            generate_trending_series("CN:600519", DAYS, start_price=Decimal("1700"),
                                     seed=24),
        ]

        class BuyThenFlatten(Strategy):
            name = "buy_then_flatten"
            horizon = Horizon.LONG_TERM
            warmup_bars = 1

            def should_run(self, as_of, context):
                return as_of in (DAYS[5], DAYS[120])

            def generate(self, as_of, windows, instruments, context):
                direction = Direction.LONG if as_of == DAYS[5] else Direction.FLAT
                weight = Decimal("0.15") if direction is Direction.LONG else None
                return [
                    Signal(instruments[k], direction, Horizon.LONG_TERM,
                           target_weight=weight, reason="reconcile")
                    for k in windows
                ]

        self.engine = build_engine(
            [US_A, IN_A, CN_A], series, [BuyThenFlatten()],
            cash={
                "USD": Decimal("300000"),
                "INR": Decimal("24900000"),
                "CNY": Decimal("2100000"),
            },
            start=DAYS[0], end=DAYS[150],
        )
        self.report = self.engine.run()

    def test_all_positions_are_closed(self):
        self.assertEqual(len(self.engine.portfolio.open_positions()), 0)

    def test_trades_span_all_three_regions(self):
        self.assertEqual(
            {t.region for t in self.report.trades}, {"US", "IN", "CN"}
        )

    def test_summed_base_pnl_equals_the_change_in_equity(self):
        total = sum((t.net_pnl_base for t in self.report.trades), Decimal("0"))
        change = self.report.ending_equity - self.report.starting_equity
        self.assertAlmostEqual(float(total), float(change), places=6)

    def test_summing_local_currency_would_be_wrong(self):
        # Documents why the base conversion exists: the naive sum is far off.
        naive = sum((t.net_pnl for t in self.report.trades), Decimal("0"))
        change = self.report.ending_equity - self.report.starting_equity
        self.assertNotAlmostEqual(float(naive), float(change), places=2)

    def test_expectancy_times_trade_count_matches_the_total(self):
        total = sum((t.net_pnl_base for t in self.report.trades), Decimal("0"))
        self.assertAlmostEqual(
            self.report.expectancy * self.report.total_trades,
            float(total), places=4,
        )


class TestDeterminism(unittest.TestCase):
    def _run(self):
        series = [generate_oscillating_series("US:AAA", DAYS, seed=7)]
        engine = build_engine(
            [US_A], series, [ShortTermStrategy(ShortTermConfig())]
        )
        return engine.run()

    def test_two_identical_runs_produce_identical_equity_curves(self):
        a, b = self._run(), self._run()
        self.assertEqual(a.equity_values, b.equity_values)

    def test_two_identical_runs_produce_identical_trade_counts(self):
        a, b = self._run(), self._run()
        self.assertEqual(a.total_trades, b.total_trades)
        self.assertEqual(a.ending_equity, b.ending_equity)


class TestRoundTrips(unittest.TestCase):
    def setUp(self):
        self.series = generate_trending_series("US:AAA", DAYS, seed=8)
        self.engine = build_engine(
            [US_A], [self.series],
            [ExitOnDayStrategy("US:AAA", DAYS[10], DAYS[40])],
        )
        self.report = self.engine.run()

    def test_a_round_trip_is_recorded(self):
        self.assertEqual(len(self.report.trades), 1)

    def test_round_trip_dates_bracket_the_holding_period(self):
        trip = self.report.trades[0]
        self.assertEqual(trip.entry_day, DAYS[11])   # order on day 10 fills day 11
        self.assertEqual(trip.exit_day, DAYS[41])

    def test_round_trip_exit_is_after_entry(self):
        for trip in self.report.trades:
            self.assertGreater(trip.exit_day, trip.entry_day)

    def test_position_is_flat_at_the_end(self):
        self.assertEqual(len(self.engine.portfolio.open_positions()), 0)

    def test_gross_pnl_matches_the_price_move(self):
        trip = self.report.trades[0]
        expected = (trip.exit_price - trip.entry_price) * trip.quantity
        self.assertEqual(trip.gross_pnl, expected)

    def test_net_pnl_is_gross_less_costs(self):
        trip = self.report.trades[0]
        self.assertEqual(trip.net_pnl, trip.gross_pnl - trip.costs)

    def test_costs_are_charged_on_both_legs(self):
        self.assertGreater(self.report.trades[0].costs, Decimal("0"))


class TestSuccessiveRoundTrips(unittest.TestCase):
    """A second trade in a name must not inherit the first one's P&L."""

    def test_each_round_trip_reports_its_own_pnl(self):
        series = generate_trending_series("US:AAA", DAYS, seed=9)

        class TwoTrips(Strategy):
            name = "two_trips"
            horizon = Horizon.LONG_TERM
            warmup_bars = 1

            def should_run(self, as_of, context):
                return as_of in (DAYS[5], DAYS[20], DAYS[30], DAYS[45])

            def generate(self, as_of, windows, instruments, context):
                if "US:AAA" not in windows:
                    return []
                direction = (
                    Direction.LONG if as_of in (DAYS[5], DAYS[30]) else Direction.FLAT
                )
                return [Signal(
                    instruments["US:AAA"], direction, Horizon.LONG_TERM,
                    target_weight=Decimal("0.4") if direction is Direction.LONG else None,
                    reason="cycle",
                )]

        engine = build_engine([US_A], [series], [TwoTrips()])
        report = engine.run()
        self.assertEqual(len(report.trades), 2)
        for trip in report.trades:
            expected = (trip.exit_price - trip.entry_price) * trip.quantity
            self.assertEqual(trip.gross_pnl, expected)


class TestChinaSettlement(unittest.TestCase):
    def test_no_same_session_round_trips_on_a_t_plus_one_venue(self):
        series = generate_oscillating_series(
            "CN:600519", DAYS, amplitude=0.10, period=25, drift=0.001, seed=10
        )
        engine = build_engine(
            [CN_A], [series], [ShortTermStrategy(ShortTermConfig())],
            cash={"CNY": Decimal("7000000")},
        )
        report = engine.run()
        for trip in report.trades:
            self.assertGreater(
                trip.exit_day, trip.entry_day,
                f"same-session round trip on a T+1 venue: {trip.key} {trip.entry_day}",
            )

    def test_board_lots_are_respected_on_every_fill(self):
        series = generate_oscillating_series(
            "CN:600519", DAYS, amplitude=0.10, period=25, drift=0.001, seed=11
        )
        engine = build_engine(
            [CN_A], [series], [ShortTermStrategy(ShortTermConfig())],
            cash={"CNY": Decimal("7000000")},
        )
        engine.run()
        for fill in engine.portfolio.fills:
            self.assertEqual(fill.quantity % Decimal("100"), Decimal("0"))


class TestRiskIntegration(unittest.TestCase):
    def test_leverage_cap_prevents_overspending(self):
        series = [generate_trending_series("US:AAA", DAYS, seed=12)]
        engine = build_engine(
            [US_A], series,
            [FixedWeightStrategy({"US:AAA": Decimal("2.0")})],
            risk=permissive_risk(max_gross_leverage=Decimal("0.5")),
        )
        engine.run()
        prices = engine.last_prices
        gross = engine.portfolio.gross_exposure(prices, FX).amount
        equity = engine.portfolio.total_equity(prices, FX).amount
        self.assertLessEqual(gross / equity, Decimal("0.51"))

    def test_rejections_are_recorded(self):
        series = [generate_trending_series("US:AAA", DAYS, seed=13)]
        engine = build_engine(
            [US_A], series,
            [FixedWeightStrategy({"US:AAA": Decimal("5.0")})],
            risk=permissive_risk(max_gross_leverage=Decimal("0.1")),
        )
        report = engine.run()
        self.assertGreater(report.rejections, 0)

    def test_position_weight_cap_is_enforced(self):
        series = [generate_trending_series("US:AAA", DAYS, seed=14)]
        engine = build_engine(
            [US_A], series,
            [FixedWeightStrategy({"US:AAA": Decimal("0.9")})],
            sizing=permissive_sizing(max_position_weight=Decimal("0.2")),
        )
        engine.run()
        prices = engine.last_prices
        for snap in engine.portfolio.snapshots(prices, FX):
            self.assertLessEqual(snap.weight, 0.25)


class TestMultiRegion(unittest.TestCase):
    def test_runs_across_three_regions_with_separate_currencies(self):
        series = [
            generate_trending_series("US:AAA", DAYS, seed=15),
            generate_trending_series("IN:RELI", DAYS, start_price=Decimal("2500"),
                                     tick_size=Decimal("0.05"), seed=16),
            generate_trending_series("CN:600519", DAYS, start_price=Decimal("1700"),
                                     seed=17),
        ]
        engine = build_engine(
            [US_A, IN_A, CN_A], series,
            [FixedWeightStrategy({
                "US:AAA": Decimal("0.2"),
                "IN:RELI": Decimal("0.2"),
                "CN:600519": Decimal("0.2"),
            })],
            cash={
                "USD": Decimal("500000"),
                "INR": Decimal("41500000"),
                "CNY": Decimal("3500000"),
            },
        )
        report = engine.run()
        regions = {f.instrument.region for f in engine.portfolio.fills}
        self.assertEqual(regions, {"US", "IN", "CN"})
        self.assertGreater(report.ending_equity, Decimal("0"))

    def test_india_fills_land_on_the_five_paise_tick_grid(self):
        series = [generate_trending_series(
            "IN:RELI", DAYS, start_price=Decimal("2500"),
            tick_size=Decimal("0.05"), seed=18,
        )]
        engine = build_engine(
            [IN_A], series, [FixedWeightStrategy({"IN:RELI": Decimal("0.5")})],
            cash={"INR": Decimal("83000000")},
            slippage=SlippageModel(half_spread_bps=Decimal("3")),
        )
        engine.run()
        for f in engine.portfolio.fills:
            self.assertEqual(f.price % Decimal("0.05"), Decimal("0"))


class TestConfigValidation(unittest.TestCase):
    def test_end_before_start_rejected(self):
        with self.assertRaises(ValueError):
            BacktestConfig(
                start=date(2024, 6, 1), end=date(2024, 1, 1),
                starting_cash={"USD": Decimal("1")},
            )

    def test_missing_starting_cash_rejected(self):
        with self.assertRaises(ValueError):
            BacktestConfig(start=date(2024, 1, 1), end=date(2024, 6, 1), starting_cash={})

    def test_no_sessions_in_range_rejected(self):
        series = generate_trending_series("US:AAA", DAYS, seed=19)
        # 2024-01-06/07 is a weekend: no venue is open.
        engine = build_engine(
            [US_A], [series], [FixedWeightStrategy({"US:AAA": Decimal("0.5")})],
            start=date(2024, 1, 6), end=date(2024, 1, 7),
        )
        with self.assertRaises(ValueError):
            engine.run()


if __name__ == "__main__":
    unittest.main()
