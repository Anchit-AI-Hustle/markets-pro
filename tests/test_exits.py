"""Exit logic: stops, targets, gaps, trailing stops, time limits.

The gap and ambiguity tests matter most. Both are places where a backtest can
quietly award itself a better price than the market would have given.
"""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.data.bars import Bar
from autotrader.execution.orders import Horizon
from autotrader.portfolio.portfolio import OpenTrade
from autotrader.risk.exits import (
    ExitReason,
    compute_stop_and_target,
    effective_stop,
    evaluate_exit,
    update_trailing,
)

DAY = date(2024, 1, 5)


def bar(open_, high, low, close, volume=1000):
    return Bar(
        day=DAY,
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(volume),
    )


def long_trade(stop="95", target="110", max_days=None, trail=None, held=0):
    return OpenTrade(
        key="US:TEST",
        horizon=Horizon.SHORT_TERM,
        entry_price=Decimal("100"),
        entry_day=date(2024, 1, 2),
        stop_loss=Decimal(stop) if stop else None,
        take_profit=Decimal(target) if target else None,
        max_holding_days=max_days,
        trailing_stop_pct=Decimal(trail) if trail else None,
        high_water_mark=Decimal("100"),
        bars_held=held,
    )


def short_trade(stop="105", target="90", max_days=None, trail=None, held=0):
    return OpenTrade(
        key="US:TEST",
        horizon=Horizon.SHORT_TERM,
        entry_price=Decimal("100"),
        entry_day=date(2024, 1, 2),
        stop_loss=Decimal(stop) if stop else None,
        take_profit=Decimal(target) if target else None,
        max_holding_days=max_days,
        trailing_stop_pct=Decimal(trail) if trail else None,
        high_water_mark=Decimal("100"),
        bars_held=held,
    )


class TestLongExits(unittest.TestCase):
    def test_no_exit_when_bar_stays_between_levels(self):
        self.assertIsNone(evaluate_exit(long_trade(), bar(100, 105, 97, 102), True))

    def test_stop_fills_at_the_stop_price(self):
        signal = evaluate_exit(long_trade(), bar(100, 102, 94, 96), True)
        self.assertEqual(signal.reason, ExitReason.STOP_LOSS)
        self.assertEqual(signal.price, Decimal("95"))
        self.assertTrue(signal.is_loss_exit)

    def test_stop_triggers_on_an_exact_touch(self):
        signal = evaluate_exit(long_trade(), bar(100, 102, 95, 96), True)
        self.assertEqual(signal.reason, ExitReason.STOP_LOSS)

    def test_target_fills_at_the_target_price(self):
        signal = evaluate_exit(long_trade(), bar(100, 111, 99, 108), True)
        self.assertEqual(signal.reason, ExitReason.TAKE_PROFIT)
        self.assertEqual(signal.price, Decimal("110"))
        self.assertFalse(signal.is_loss_exit)

    def test_gap_below_stop_fills_at_the_open_not_the_stop(self):
        # This is the honest-drawdown case: opening at 90 means you got 90.
        signal = evaluate_exit(long_trade(), bar(90, 92, 88, 91), True)
        self.assertEqual(signal.reason, ExitReason.GAP_THROUGH_STOP)
        self.assertEqual(signal.price, Decimal("90"))

    def test_gap_above_target_fills_at_the_open(self):
        signal = evaluate_exit(long_trade(), bar(115, 118, 114, 117), True)
        self.assertEqual(signal.reason, ExitReason.GAP_THROUGH_TARGET)
        self.assertEqual(signal.price, Decimal("115"))

    def test_ambiguous_bar_resolves_to_the_stop(self):
        # The bar pierced the stop AND reached the target. We cannot know the
        # order, so the pessimistic outcome is assumed.
        signal = evaluate_exit(long_trade(), bar(100, 111, 94, 105), True)
        self.assertEqual(signal.reason, ExitReason.STOP_LOSS)
        self.assertEqual(signal.price, Decimal("95"))

    def test_time_exit_fills_at_the_close(self):
        signal = evaluate_exit(long_trade(max_days=5, held=5), bar(100, 105, 97, 103), True)
        self.assertEqual(signal.reason, ExitReason.TIME_EXIT)
        self.assertEqual(signal.price, Decimal("103"))

    def test_time_exit_does_not_fire_early(self):
        self.assertIsNone(
            evaluate_exit(long_trade(max_days=5, held=4), bar(100, 105, 97, 103), True)
        )

    def test_price_exits_take_precedence_over_the_time_limit(self):
        signal = evaluate_exit(long_trade(max_days=5, held=5), bar(100, 102, 94, 96), True)
        self.assertEqual(signal.reason, ExitReason.STOP_LOSS)

    def test_sessions_held_override(self):
        signal = evaluate_exit(
            long_trade(max_days=3, held=0), bar(100, 105, 97, 103), True, sessions_held=3
        )
        self.assertEqual(signal.reason, ExitReason.TIME_EXIT)

    def test_no_stop_or_target_means_no_price_exit(self):
        trade = long_trade(stop=None, target=None)
        self.assertIsNone(evaluate_exit(trade, bar(100, 200, 1, 150), True))


class TestShortExits(unittest.TestCase):
    def test_stop_above_triggers(self):
        signal = evaluate_exit(short_trade(), bar(100, 106, 98, 104), False)
        self.assertEqual(signal.reason, ExitReason.STOP_LOSS)
        self.assertEqual(signal.price, Decimal("105"))

    def test_target_below_triggers(self):
        signal = evaluate_exit(short_trade(), bar(100, 101, 89, 92), False)
        self.assertEqual(signal.reason, ExitReason.TAKE_PROFIT)
        self.assertEqual(signal.price, Decimal("90"))

    def test_gap_up_through_stop_fills_at_the_open(self):
        signal = evaluate_exit(short_trade(), bar(110, 112, 108, 111), False)
        self.assertEqual(signal.reason, ExitReason.GAP_THROUGH_STOP)
        self.assertEqual(signal.price, Decimal("110"))

    def test_ambiguous_bar_resolves_to_the_stop(self):
        signal = evaluate_exit(short_trade(), bar(100, 106, 89, 95), False)
        self.assertEqual(signal.reason, ExitReason.STOP_LOSS)

    def test_no_exit_inside_the_band(self):
        self.assertIsNone(evaluate_exit(short_trade(), bar(100, 103, 96, 98), False))


class TestTrailingStop(unittest.TestCase):
    def test_high_water_mark_advances_on_a_long(self):
        trade = long_trade(trail="0.10")
        update_trailing(trade, bar(100, 120, 99, 118), True)
        self.assertEqual(trade.high_water_mark, Decimal("120"))

    def test_high_water_mark_never_retreats(self):
        trade = long_trade(trail="0.10")
        update_trailing(trade, bar(100, 120, 99, 118), True)
        update_trailing(trade, bar(118, 119, 110, 112), True)
        self.assertEqual(trade.high_water_mark, Decimal("120"))

    def test_effective_stop_is_the_tighter_of_hard_and_trailing(self):
        trade = long_trade(stop="95", trail="0.10")
        trade.high_water_mark = Decimal("120")
        # Trailing stop = 120 * 0.9 = 108, which is tighter than the hard stop 95.
        self.assertEqual(effective_stop(trade, True), Decimal("108.0"))

    def test_hard_stop_wins_while_it_is_still_tighter(self):
        trade = long_trade(stop="95", trail="0.50")
        trade.high_water_mark = Decimal("100")
        # Trailing = 50, hard = 95 -> hard is tighter for a long.
        self.assertEqual(effective_stop(trade, True), Decimal("95"))

    def test_trailing_exit_is_reported_as_trailing(self):
        # Target is set far away so the trailing stop is the only live exit; a
        # 110 target would already have filled on the way up to a 120 high.
        trade = long_trade(stop="95", target="200", trail="0.10")
        trade.high_water_mark = Decimal("120")
        signal = evaluate_exit(trade, bar(115, 116, 107, 108), True)
        self.assertEqual(signal.reason, ExitReason.TRAILING_STOP)
        self.assertEqual(signal.price, Decimal("108.0"))

    def test_trailing_stop_locks_in_a_profit_above_the_entry(self):
        trade = long_trade(stop="95", target="200", trail="0.10")
        trade.high_water_mark = Decimal("120")
        signal = evaluate_exit(trade, bar(115, 116, 107, 108), True)
        self.assertGreater(signal.price, trade.entry_price)

    def test_short_trailing_tracks_the_low(self):
        trade = short_trade(trail="0.10")
        trade.high_water_mark = Decimal("100")
        update_trailing(trade, bar(100, 101, 80, 82), False)
        self.assertEqual(trade.high_water_mark, Decimal("80"))
        # Short trailing stop sits above the low water mark: 80 * 1.1 = 88.
        self.assertEqual(effective_stop(trade, False), Decimal("88.0"))

    def test_no_trailing_returns_the_hard_stop(self):
        self.assertEqual(effective_stop(long_trade(stop="95"), True), Decimal("95"))


class TestStopAndTargetDerivation(unittest.TestCase):
    def test_long_levels(self):
        stop, target = compute_stop_and_target(
            Decimal("100"), Decimal("2"), is_long=True,
            stop_atr_multiple=Decimal("2"), reward_risk_ratio=Decimal("2"),
        )
        self.assertEqual(stop, Decimal("96"))     # 100 - 2*2
        self.assertEqual(target, Decimal("108"))  # 100 + (4 * 2)

    def test_reward_risk_ratio_is_respected(self):
        entry = Decimal("100")
        stop, target = compute_stop_and_target(
            entry, Decimal("2"), is_long=True, reward_risk_ratio=Decimal("3")
        )
        self.assertEqual((target - entry) / (entry - stop), Decimal("3"))

    def test_short_levels_are_mirrored(self):
        stop, target = compute_stop_and_target(
            Decimal("100"), Decimal("2"), is_long=False,
            stop_atr_multiple=Decimal("2"), reward_risk_ratio=Decimal("2"),
        )
        self.assertEqual(stop, Decimal("104"))
        self.assertEqual(target, Decimal("92"))

    def test_wider_atr_gives_a_wider_stop(self):
        narrow, _ = compute_stop_and_target(Decimal("100"), Decimal("1"), is_long=True)
        wide, _ = compute_stop_and_target(Decimal("100"), Decimal("5"), is_long=True)
        self.assertGreater(narrow, wide)

    def test_zero_atr_rejected(self):
        with self.assertRaises(ValueError):
            compute_stop_and_target(Decimal("100"), Decimal("0"), is_long=True)

    def test_atr_wider_than_price_rejected(self):
        # A stop at or below zero is not a stop.
        with self.assertRaises(ValueError):
            compute_stop_and_target(Decimal("10"), Decimal("20"), is_long=True)


if __name__ == "__main__":
    unittest.main()
