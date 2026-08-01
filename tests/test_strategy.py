"""Strategy signal generation."""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.data.synthetic import (
    business_days,
    generate_oscillating_series,
    generate_trending_series,
)
from autotrader.execution.orders import Horizon
from autotrader.strategy.base import (
    Direction,
    Signal,
    StrategyContext,
    is_month_boundary,
    is_week_boundary,
)
from autotrader.strategy.long_term import LongTermConfig, LongTermStrategy
from autotrader.strategy.short_term import ShortTermConfig, ShortTermStrategy

DAYS = business_days(date(2022, 1, 3), 420)
US_A = Instrument("AAA", "US", AssetClass.EQUITY, "USD", Decimal("0.01"))
US_B = Instrument("BBB", "US", AssetClass.EQUITY, "USD", Decimal("0.01"))
US_C = Instrument("CCC", "US", AssetClass.EQUITY, "USD", Decimal("0.01"))


def context(day, equity="1000000", open_keys=(), halted=False):
    return StrategyContext(
        day=day, equity=Decimal(equity),
        open_keys=frozenset(open_keys), entries_halted=halted,
    )


class TestBoundaryHelpers(unittest.TestCase):
    def test_month_boundary(self):
        self.assertTrue(is_month_boundary(date(2024, 2, 1), date(2024, 1, 31)))
        self.assertFalse(is_month_boundary(date(2024, 1, 31), date(2024, 1, 30)))

    def test_no_previous_day_is_a_boundary(self):
        self.assertTrue(is_month_boundary(date(2024, 1, 5), None))

    def test_year_change_is_a_month_boundary(self):
        self.assertTrue(is_month_boundary(date(2025, 1, 2), date(2024, 12, 31)))

    def test_week_boundary(self):
        # Fri 2024-01-05 -> Mon 2024-01-08 crosses ISO weeks.
        self.assertTrue(is_week_boundary(date(2024, 1, 8), date(2024, 1, 5)))
        self.assertFalse(is_week_boundary(date(2024, 1, 4), date(2024, 1, 3)))


class TestSignalValidation(unittest.TestCase):
    def test_strength_must_be_a_fraction(self):
        with self.assertRaises(ValueError):
            Signal(US_A, Direction.LONG, Horizon.SHORT_TERM, strength=1.5)

    def test_entry_and_exit_flags(self):
        entry = Signal(US_A, Direction.LONG, Horizon.SHORT_TERM)
        exit_ = Signal(US_A, Direction.FLAT, Horizon.SHORT_TERM)
        self.assertTrue(entry.is_entry)
        self.assertFalse(entry.is_exit)
        self.assertTrue(exit_.is_exit)


class TestLongTermStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = LongTermStrategy(LongTermConfig(max_holdings=2))
        self.up = generate_trending_series("US:AAA", DAYS, daily_drift=0.0025, seed=1)
        self.up2 = generate_trending_series("US:BBB", DAYS, daily_drift=0.0015, seed=2)
        self.down = generate_trending_series("US:CCC", DAYS, daily_drift=-0.002, seed=3)
        self.day = DAYS[-1]
        self.instruments = {"US:AAA": US_A, "US:BBB": US_B, "US:CCC": US_C}

    def windows(self, *series):
        return {s.key: s.window(self.day) for s in series}

    def test_rebalances_only_on_a_month_boundary(self):
        ctx = context(self.day)
        self.assertTrue(self.strategy.should_run(self.day, ctx))
        self.strategy.generate(self.day, self.windows(self.up), self.instruments, ctx)
        # Same month, one day later -> no rebalance.
        self.assertFalse(self.strategy.should_run(self.day, ctx))

    def test_uptrending_name_is_selected(self):
        signals = self.strategy.generate(
            self.day, self.windows(self.up), self.instruments, context(self.day)
        )
        longs = [s for s in signals if s.direction is Direction.LONG]
        self.assertEqual(len(longs), 1)
        self.assertEqual(longs[0].instrument.key, "US:AAA")

    def test_downtrending_name_is_filtered_out(self):
        signals = self.strategy.generate(
            self.day, self.windows(self.down), self.instruments, context(self.day)
        )
        self.assertEqual([s for s in signals if s.direction is Direction.LONG], [])

    def test_selection_is_capped_at_max_holdings(self):
        strategy = LongTermStrategy(LongTermConfig(max_holdings=1))
        signals = strategy.generate(
            self.day, self.windows(self.up, self.up2), self.instruments, context(self.day)
        )
        self.assertEqual(len([s for s in signals if s.direction is Direction.LONG]), 1)

    def test_target_weights_sum_to_the_allocation(self):
        config = LongTermConfig(max_holdings=2, total_allocation=Decimal("0.60"))
        strategy = LongTermStrategy(config)
        signals = strategy.generate(
            self.day, self.windows(self.up, self.up2), self.instruments, context(self.day)
        )
        longs = [s for s in signals if s.direction is Direction.LONG]
        total = sum(s.target_weight for s in longs)
        self.assertAlmostEqual(float(total), 0.60, places=8)

    def test_weights_are_positive_and_bounded(self):
        signals = self.strategy.generate(
            self.day, self.windows(self.up, self.up2), self.instruments, context(self.day)
        )
        for signal in signals:
            if signal.direction is Direction.LONG:
                self.assertGreater(signal.target_weight, 0)
                self.assertLessEqual(signal.target_weight, Decimal("1"))

    def test_inverse_volatility_favours_the_calmer_name(self):
        calm = generate_trending_series("US:AAA", DAYS, daily_drift=0.002, noise=0.002, seed=5)
        wild = generate_trending_series("US:BBB", DAYS, daily_drift=0.002, noise=0.020, seed=6)
        strategy = LongTermStrategy(LongTermConfig(max_holdings=2))
        signals = strategy.generate(
            self.day, self.windows(calm, wild), self.instruments, context(self.day)
        )
        weights = {
            s.instrument.key: s.target_weight
            for s in signals if s.direction is Direction.LONG
        }
        if len(weights) == 2:
            self.assertGreater(weights["US:AAA"], weights["US:BBB"])

    def test_held_name_that_drops_out_is_exited(self):
        signals = self.strategy.generate(
            self.day, self.windows(self.up), self.instruments,
            context(self.day, open_keys=["US:CCC"]),
        )
        exits = [s for s in signals if s.direction is Direction.FLAT]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].instrument.key, "US:CCC")

    def test_selected_name_is_not_exited(self):
        signals = self.strategy.generate(
            self.day, self.windows(self.up), self.instruments,
            context(self.day, open_keys=["US:AAA"]),
        )
        self.assertEqual([s for s in signals if s.direction is Direction.FLAT], [])

    def test_insufficient_history_produces_nothing(self):
        short_days = business_days(date(2023, 1, 2), 50)
        short = generate_trending_series("US:AAA", short_days, seed=4)
        day = short_days[-1]
        signals = self.strategy.generate(
            day, {"US:AAA": short.window(day)}, self.instruments, context(day)
        )
        self.assertEqual([s for s in signals if s.direction is Direction.LONG], [])

    def test_signals_carry_diagnostics(self):
        signals = self.strategy.generate(
            self.day, self.windows(self.up), self.instruments, context(self.day)
        )
        longs = [s for s in signals if s.direction is Direction.LONG]
        self.assertIn("momentum", longs[0].diagnostics)
        self.assertIn("adx", longs[0].diagnostics)
        self.assertTrue(longs[0].reason)

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            LongTermConfig(fast_ma=200, slow_ma=50)
        with self.assertRaises(ValueError):
            LongTermConfig(max_holdings=0)


class TestShortTermStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = ShortTermStrategy(ShortTermConfig())
        self.series = generate_oscillating_series(
            "US:AAA", DAYS, amplitude=0.10, period=30, drift=0.0012, seed=21
        )
        self.instruments = {"US:AAA": US_A}

    def _find_entry_day(self):
        """First session on which the strategy produces an entry."""
        for day in DAYS[300:]:
            windows = {"US:AAA": self.series.window(day)}
            signals = self.strategy.generate(day, windows, self.instruments, context(day))
            entries = [s for s in signals if s.direction is Direction.LONG]
            if entries:
                return day, entries[0]
        return None, None

    def test_produces_an_entry_somewhere_in_the_oscillation(self):
        day, signal = self._find_entry_day()
        self.assertIsNotNone(signal, "expected at least one entry on an oscillating series")

    def test_entry_carries_a_stop_below_and_a_target_above(self):
        day, signal = self._find_entry_day()
        price = self.series.bar_on(day).close
        self.assertLess(signal.stop_loss, price)
        self.assertGreater(signal.take_profit, price)

    def test_entry_reward_risk_matches_the_config(self):
        day, signal = self._find_entry_day()
        price = self.series.bar_on(day).close
        risk = price - signal.stop_loss
        reward = signal.take_profit - price
        self.assertAlmostEqual(float(reward / risk), 2.0, places=6)

    def test_entry_carries_a_time_limit(self):
        day, signal = self._find_entry_day()
        self.assertEqual(signal.max_holding_days, self.strategy.config.max_holding_days)

    def test_entry_is_short_term_horizon(self):
        day, signal = self._find_entry_day()
        self.assertIs(signal.horizon, Horizon.SHORT_TERM)

    def test_no_entries_while_halted(self):
        for day in DAYS[300:330]:
            windows = {"US:AAA": self.series.window(day)}
            signals = self.strategy.generate(
                day, windows, self.instruments, context(day, halted=True)
            )
            self.assertEqual([s for s in signals if s.direction is Direction.LONG], [])

    def test_concurrency_cap_is_respected(self):
        strategy = ShortTermStrategy(ShortTermConfig(max_concurrent=1))
        day = DAYS[-1]
        windows = {"US:AAA": self.series.window(day)}
        signals = strategy.generate(
            day, windows, self.instruments, context(day, open_keys=["US:ZZZ"])
        )
        self.assertEqual([s for s in signals if s.direction is Direction.LONG], [])

    def test_downtrend_produces_no_pullback_entry(self):
        # The pullback setup requires price above the long moving average.
        down = generate_trending_series("US:AAA", DAYS, daily_drift=-0.002, seed=31)
        strategy = ShortTermStrategy(ShortTermConfig(enable_breakout=False))
        for day in DAYS[300:340]:
            signals = strategy.generate(
                day, {"US:AAA": down.window(day)}, self.instruments, context(day)
            )
            self.assertEqual([s for s in signals if s.direction is Direction.LONG], [])

    def test_insufficient_history_produces_nothing(self):
        short_days = business_days(date(2023, 1, 2), 30)
        short = generate_oscillating_series("US:AAA", short_days, seed=41)
        day = short_days[-1]
        signals = self.strategy.generate(
            day, {"US:AAA": short.window(day)}, self.instruments, context(day)
        )
        self.assertEqual(signals, [])

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            ShortTermConfig(max_holding_days=0)
        with self.assertRaises(ValueError):
            ShortTermConfig(reward_risk_ratio=Decimal("0"))
        with self.assertRaises(ValueError):
            ShortTermConfig(signal_exit_min_r=Decimal("-1"))


class TestRMultiple(unittest.TestCase):
    def ctx(self, entry, stop):
        return StrategyContext(
            day=date(2024, 1, 5), equity=Decimal("100000"),
            open_keys=frozenset({"US:AAA"}),
            entry_prices={"US:AAA": Decimal(entry)},
            stop_levels={"US:AAA": Decimal(stop)},
        )

    def test_at_entry_is_zero_r(self):
        self.assertEqual(self.ctx("100", "95").r_multiple("US:AAA", Decimal("100")), 0)

    def test_one_risk_unit_of_profit_is_one_r(self):
        self.assertEqual(self.ctx("100", "95").r_multiple("US:AAA", Decimal("105")), 1)

    def test_at_the_stop_is_minus_one_r(self):
        self.assertEqual(self.ctx("100", "95").r_multiple("US:AAA", Decimal("95")), -1)

    def test_half_a_risk_unit(self):
        # Entry 100, stop 90 -> 10 of risk; a move to 105 is 5/10 = 0.5R.
        self.assertEqual(
            self.ctx("100", "90").r_multiple("US:AAA", Decimal("105")), Decimal("0.5")
        )

    def test_wider_stop_lowers_the_r_multiple_for_the_same_gain(self):
        tight = self.ctx("100", "95").r_multiple("US:AAA", Decimal("105"))
        wide = self.ctx("100", "90").r_multiple("US:AAA", Decimal("105"))
        self.assertGreater(tight, wide)

    def test_unknown_position_returns_none(self):
        self.assertIsNone(self.ctx("100", "95").r_multiple("US:ZZZ", Decimal("100")))

    def test_zero_risk_returns_none(self):
        self.assertIsNone(self.ctx("100", "100").r_multiple("US:AAA", Decimal("105")))

    def test_missing_stop_returns_none(self):
        ctx = StrategyContext(
            day=date(2024, 1, 5), equity=Decimal("100000"),
            entry_prices={"US:AAA": Decimal("100")},
        )
        self.assertIsNone(ctx.r_multiple("US:AAA", Decimal("105")))


class TestSignalExitGate(unittest.TestCase):
    """The RSI exit must not fire before the trade has paid for its own risk.

    Without this gate the signal exit is strictly faster than the profit target,
    so winners are cut at a fraction of 1R while losers run the full stop
    distance — a built-in negative skew that loses money regardless of entry
    quality.
    """

    def setUp(self):
        self.series = generate_oscillating_series(
            "US:AAA", DAYS, amplitude=0.10, period=30, drift=0.0012, seed=51
        )
        self.instruments = {"US:AAA": US_A}

    def _exit_days(self, min_r):
        """Sessions on which a flat signal is produced for a held position."""
        strategy = ShortTermStrategy(ShortTermConfig(signal_exit_min_r=min_r))
        found = []
        for day in DAYS[300:380]:
            bar = self.series.bar_on(day)
            if bar is None:
                continue
            # Entry 6% below the current price with a stop 3% below entry, so the
            # position is comfortably more than 1R onside.
            entry = bar.close * Decimal("0.94")
            ctx = StrategyContext(
                day=day, equity=Decimal("1000000"),
                open_keys=frozenset({"US:AAA"}),
                entry_prices={"US:AAA": entry},
                stop_levels={"US:AAA": entry * Decimal("0.97")},
            )
            signals = strategy.generate(
                day, {"US:AAA": self.series.window(day)}, self.instruments, ctx
            )
            if any(s.direction is Direction.FLAT for s in signals):
                found.append(day)
        return found

    def test_profitable_position_may_exit_on_signal(self):
        self.assertGreater(len(self._exit_days(Decimal("1.0"))), 0)

    def test_gate_blocks_the_exit_when_the_trade_is_barely_onside(self):
        strategy = ShortTermStrategy(ShortTermConfig(signal_exit_min_r=Decimal("1.0")))
        blocked = 0
        for day in DAYS[300:380]:
            bar = self.series.bar_on(day)
            if bar is None:
                continue
            # Entry just below price, stop far away -> well under 1R of profit.
            entry = bar.close * Decimal("0.999")
            ctx = StrategyContext(
                day=day, equity=Decimal("1000000"),
                open_keys=frozenset({"US:AAA"}),
                entry_prices={"US:AAA": entry},
                stop_levels={"US:AAA": entry * Decimal("0.90")},
            )
            signals = strategy.generate(
                day, {"US:AAA": self.series.window(day)}, self.instruments, ctx
            )
            if not any(s.direction is Direction.FLAT for s in signals):
                blocked += 1
        self.assertGreater(blocked, 0)

    def test_disabling_the_gate_restores_unconditional_exits(self):
        gated = len(self._exit_days(Decimal("5.0")))
        ungated = len(self._exit_days(Decimal("0")))
        self.assertGreaterEqual(ungated, gated)

    def test_unknown_entry_price_does_not_block_the_exit(self):
        # With no position context the gate cannot evaluate, and must not
        # silently trap the position with no way out.
        strategy = ShortTermStrategy(ShortTermConfig(signal_exit_min_r=Decimal("1.0")))
        exits = 0
        for day in DAYS[300:380]:
            ctx = context(day, open_keys=["US:AAA"])
            signals = strategy.generate(
                day, {"US:AAA": self.series.window(day)}, self.instruments, ctx
            )
            exits += sum(1 for s in signals if s.direction is Direction.FLAT)
        self.assertGreater(exits, 0)


if __name__ == "__main__":
    unittest.main()
