"""Bar validation and the lookahead guard.

The tests in :class:`TestLookaheadGuard` are the most important in the suite. If
they fail, every performance number the engine produces is meaningless.
"""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.data.bars import (
    Bar,
    BarSeries,
    LookaheadError,
    MarketDataSet,
)


def make_bar(day, close, *, open_=None, high=None, low=None, volume=1000):
    close = Decimal(str(close))
    open_ = close if open_ is None else Decimal(str(open_))
    high = max(open_, close) if high is None else Decimal(str(high))
    low = min(open_, close) if low is None else Decimal(str(low))
    return Bar(day=day, open=open_, high=high, low=low, close=close, volume=Decimal(volume))


class TestBarValidation(unittest.TestCase):
    def test_valid_bar(self):
        bar = make_bar(date(2024, 1, 2), 100, open_=99, high=101, low=98)
        self.assertEqual(bar.close, Decimal("100"))

    def test_high_below_low_rejected(self):
        with self.assertRaises(ValueError):
            Bar(date(2024, 1, 2), Decimal("10"), Decimal("9"), Decimal("11"), Decimal("10"))

    def test_open_outside_range_rejected(self):
        with self.assertRaises(ValueError):
            Bar(date(2024, 1, 2), Decimal("50"), Decimal("11"), Decimal("9"), Decimal("10"))

    def test_close_outside_range_rejected(self):
        with self.assertRaises(ValueError):
            Bar(date(2024, 1, 2), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("50"))

    def test_negative_volume_rejected(self):
        with self.assertRaises(ValueError):
            Bar(
                date(2024, 1, 2), Decimal("10"), Decimal("11"),
                Decimal("9"), Decimal("10"), Decimal("-1"),
            )

    def test_typical_price(self):
        bar = make_bar(date(2024, 1, 2), 10, open_=10, high=12, low=9)
        self.assertEqual(bar.typical_price, (Decimal("12") + Decimal("9") + Decimal("10")) / 3)

    def test_range(self):
        bar = make_bar(date(2024, 1, 2), 10, open_=10, high=12, low=9)
        self.assertEqual(bar.range, Decimal("3"))


class TestBarSeries(unittest.TestCase):
    def setUp(self):
        self.days = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
        self.series = BarSeries("US:TEST", [make_bar(d, 100 + i) for i, d in enumerate(self.days)])

    def test_length_and_iteration(self):
        self.assertEqual(len(self.series), 5)
        self.assertEqual([b.day for b in self.series], self.days)

    def test_out_of_order_bars_rejected(self):
        with self.assertRaises(ValueError):
            BarSeries("X", [make_bar(date(2024, 1, 3), 1), make_bar(date(2024, 1, 2), 1)])

    def test_duplicate_dates_rejected(self):
        with self.assertRaises(ValueError):
            BarSeries("X", [make_bar(date(2024, 1, 3), 1), make_bar(date(2024, 1, 3), 2)])

    def test_bar_on_exact_date(self):
        self.assertEqual(self.series.bar_on(date(2024, 1, 4)).close, Decimal("102"))

    def test_bar_on_missing_date_is_none(self):
        self.assertIsNone(self.series.bar_on(date(2024, 1, 6)))

    def test_index_asof_finds_prior_bar(self):
        # 2024-01-06 is a Saturday; the last bar at or before it is the 5th.
        self.assertEqual(self.series.index_asof(date(2024, 1, 6)), 3)

    def test_index_asof_before_series_is_negative(self):
        self.assertEqual(self.series.index_asof(date(2023, 12, 31)), -1)

    def test_first_and_last_day(self):
        self.assertEqual(self.series.first_day, date(2024, 1, 2))
        self.assertEqual(self.series.last_day, date(2024, 1, 8))


class TestLookaheadGuard(unittest.TestCase):
    """A window must not expose data after its decision date. Ever."""

    def setUp(self):
        self.days = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
        self.closes = [100, 101, 102, 103, 104]
        self.series = BarSeries(
            "US:TEST", [make_bar(d, c) for d, c in zip(self.days, self.closes, strict=False)]
        )

    def test_window_stops_at_the_decision_date(self):
        window = self.series.window(date(2024, 1, 4))
        self.assertEqual(len(window), 3)
        self.assertEqual(window.latest.close, Decimal("102"))

    def test_window_cannot_see_tomorrow(self):
        window = self.series.window(date(2024, 1, 4))
        closes = window.closes()
        self.assertNotIn(Decimal("103"), closes)
        self.assertNotIn(Decimal("104"), closes)

    def test_negative_ago_raises_lookahead_error(self):
        window = self.series.window(date(2024, 1, 4))
        with self.assertRaises(LookaheadError):
            window.ago(-1)

    def test_ago_zero_is_the_decision_bar(self):
        window = self.series.window(date(2024, 1, 4))
        self.assertEqual(window.ago(0).close, Decimal("102"))

    def test_ago_walks_backwards(self):
        window = self.series.window(date(2024, 1, 4))
        self.assertEqual(window.ago(1).close, Decimal("101"))
        self.assertEqual(window.ago(2).close, Decimal("100"))

    def test_ago_beyond_history_raises_index_error(self):
        window = self.series.window(date(2024, 1, 4))
        with self.assertRaises(IndexError):
            window.ago(5)

    def test_window_on_a_non_session_uses_the_prior_bar(self):
        window = self.series.window(date(2024, 1, 6))   # Saturday
        self.assertEqual(window.latest.day, date(2024, 1, 5))

    def test_window_before_series_start_is_empty(self):
        window = self.series.window(date(2023, 1, 1))
        self.assertTrue(window.is_empty)
        self.assertIsNone(window.latest)
        self.assertEqual(window.closes(), [])

    def test_bars_count_limits_to_the_most_recent(self):
        window = self.series.window(date(2024, 1, 8))
        self.assertEqual([b.close for b in window.bars(2)], [Decimal("103"), Decimal("104")])

    def test_bars_are_chronological(self):
        window = self.series.window(date(2024, 1, 8))
        days = [b.day for b in window.bars()]
        self.assertEqual(days, sorted(days))

    def test_has_reports_available_history(self):
        window = self.series.window(date(2024, 1, 4))
        self.assertTrue(window.has(3))
        self.assertFalse(window.has(4))

    def test_every_window_is_a_prefix_of_the_full_series(self):
        # Property check across all dates: no window may contain a future close.
        for cutoff in self.days:
            window = self.series.window(cutoff)
            for bar in window.bars():
                self.assertLessEqual(bar.day, cutoff)

    def test_accessors_agree_on_length(self):
        window = self.series.window(date(2024, 1, 5))
        n = len(window)
        self.assertEqual(len(window.closes()), n)
        self.assertEqual(len(window.highs()), n)
        self.assertEqual(len(window.lows()), n)
        self.assertEqual(len(window.volumes()), n)


class TestMarketDataSet(unittest.TestCase):
    def setUp(self):
        self.data = MarketDataSet()
        self.data.add(
            "US:A", BarSeries("US:A", [make_bar(date(2024, 1, 2), 10), make_bar(date(2024, 1, 3), 11)])
        )
        self.data.add("IN:B", BarSeries("IN:B", [make_bar(date(2024, 1, 3), 20)]))

    def test_contains_and_len(self):
        self.assertIn("US:A", self.data)
        self.assertNotIn("US:Z", self.data)
        self.assertEqual(len(self.data), 2)

    def test_keys_sorted(self):
        self.assertEqual(self.data.keys, ["IN:B", "US:A"])

    def test_missing_key_returns_none(self):
        self.assertIsNone(self.data.get("US:Z"))
        self.assertIsNone(self.data.window("US:Z", date(2024, 1, 3)))
        self.assertIsNone(self.data.bar_on("US:Z", date(2024, 1, 3)))

    def test_all_days_is_the_sorted_union(self):
        self.assertEqual(self.data.all_days(), [date(2024, 1, 2), date(2024, 1, 3)])


if __name__ == "__main__":
    unittest.main()
