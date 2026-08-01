"""Trading calendars, sessions and settlement."""

import unittest
from datetime import date

from autotrader.core.calendar import GlobalCalendar, TradingCalendar, merge_sessions
from autotrader.core.market import CHINA, INDIA, UNITED_STATES, with_holidays


class TestTradingCalendar(unittest.TestCase):
    def setUp(self):
        self.cal = TradingCalendar(UNITED_STATES)

    def test_weekday_is_a_session(self):
        self.assertTrue(self.cal.is_trading_day(date(2024, 1, 3)))   # Wednesday

    def test_weekend_is_not_a_session(self):
        self.assertFalse(self.cal.is_trading_day(date(2024, 1, 6)))  # Saturday
        self.assertFalse(self.cal.is_trading_day(date(2024, 1, 7)))  # Sunday

    def test_next_trading_day_skips_the_weekend(self):
        # Friday 2024-01-05 -> Monday 2024-01-08
        self.assertEqual(self.cal.next_trading_day(date(2024, 1, 5)), date(2024, 1, 8))

    def test_next_trading_day_is_strict_by_default(self):
        self.assertEqual(self.cal.next_trading_day(date(2024, 1, 3)), date(2024, 1, 4))

    def test_next_trading_day_inclusive(self):
        self.assertEqual(
            self.cal.next_trading_day(date(2024, 1, 3), inclusive=True), date(2024, 1, 3)
        )

    def test_previous_trading_day_skips_the_weekend(self):
        self.assertEqual(
            self.cal.previous_trading_day(date(2024, 1, 8)), date(2024, 1, 5)
        )

    def test_sessions_in_a_week(self):
        sessions = self.cal.sessions(date(2024, 1, 1), date(2024, 1, 7))
        self.assertEqual(len(sessions), 5)
        self.assertEqual(sessions[0], date(2024, 1, 1))
        self.assertEqual(sessions[-1], date(2024, 1, 5))

    def test_sessions_reversed_range_is_empty(self):
        self.assertEqual(self.cal.sessions(date(2024, 1, 5), date(2024, 1, 1)), [])

    def test_holidays_are_excluded(self):
        spec = with_holidays(UNITED_STATES, {date(2024, 1, 3)})
        cal = TradingCalendar(spec)
        self.assertFalse(cal.is_trading_day(date(2024, 1, 3)))
        self.assertEqual(cal.next_trading_day(date(2024, 1, 2)), date(2024, 1, 4))

    def test_add_sessions_forward(self):
        # Wed 3rd + 3 sessions -> Thu 4, Fri 5, Mon 8
        self.assertEqual(self.cal.add_sessions(date(2024, 1, 3), 3), date(2024, 1, 8))

    def test_add_sessions_backward(self):
        self.assertEqual(self.cal.add_sessions(date(2024, 1, 8), -1), date(2024, 1, 5))

    def test_add_zero_sessions_on_a_session(self):
        self.assertEqual(self.cal.add_sessions(date(2024, 1, 3), 0), date(2024, 1, 3))

    def test_add_zero_sessions_on_a_holiday_rolls_forward(self):
        self.assertEqual(self.cal.add_sessions(date(2024, 1, 6), 0), date(2024, 1, 8))

    def test_session_count(self):
        self.assertEqual(
            self.cal.session_count(date(2024, 1, 1), date(2024, 1, 31)), 23
        )

    def test_settlement_is_t_plus_one_across_a_weekend(self):
        # US settles T+1; a Friday trade settles Monday.
        self.assertEqual(self.cal.settlement_date(date(2024, 1, 5)), date(2024, 1, 8))

    def test_settlement_midweek(self):
        self.assertEqual(self.cal.settlement_date(date(2024, 1, 3)), date(2024, 1, 4))


class TestGlobalCalendar(unittest.TestCase):
    def setUp(self):
        self.india = with_holidays(INDIA, {date(2024, 1, 26)})    # Republic Day
        self.us = with_holidays(UNITED_STATES, {date(2024, 1, 15)})  # MLK Day
        self.cal = GlobalCalendar.from_specs([self.india, self.us, CHINA])

    def test_union_includes_a_day_only_one_venue_is_open(self):
        # US closed on MLK Day but India and China are open.
        self.assertTrue(self.cal.is_any_open(date(2024, 1, 15)))
        self.assertNotIn("US", self.cal.open_markets(date(2024, 1, 15)))
        self.assertIn("IN", self.cal.open_markets(date(2024, 1, 15)))

    def test_open_markets_on_a_normal_weekday(self):
        self.assertEqual(
            sorted(self.cal.open_markets(date(2024, 1, 3))), ["CN", "IN", "US"]
        )

    def test_no_market_open_on_a_weekend(self):
        self.assertFalse(self.cal.is_any_open(date(2024, 1, 6)))
        self.assertEqual(self.cal.open_markets(date(2024, 1, 6)), [])

    def test_union_sessions_count(self):
        # Every weekday in January 2024 has at least one venue open.
        sessions = self.cal.sessions(date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(len(sessions), 23)

    def test_for_region_lookup(self):
        self.assertIs(self.cal.for_region("in").spec, self.india)


class TestMergeSessions(unittest.TestCase):
    def test_dedupes_and_sorts(self):
        a = [date(2024, 1, 2), date(2024, 1, 3)]
        b = [date(2024, 1, 3), date(2024, 1, 1)]
        self.assertEqual(
            merge_sessions([a, b]),
            [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)],
        )

    def test_empty(self):
        self.assertEqual(merge_sessions([]), [])


class TestMarketSpecs(unittest.TestCase):
    def test_china_is_t_plus_one_no_same_day_sell(self):
        self.assertFalse(CHINA.same_day_sell_allowed)

    def test_india_and_us_allow_same_day_round_trips(self):
        self.assertTrue(INDIA.same_day_sell_allowed)
        self.assertTrue(UNITED_STATES.same_day_sell_allowed)

    def test_china_board_lot_is_one_hundred(self):
        self.assertEqual(CHINA.default_lot_size, 100)

    def test_india_tick_is_five_paise(self):
        self.assertEqual(str(INDIA.default_tick_size), "0.05")

    def test_china_price_limit_is_ten_percent(self):
        lower, upper = CHINA.price_limits(100)
        self.assertEqual(lower, 90)
        self.assertEqual(upper, 110)

    def test_price_limit_membership(self):
        self.assertTrue(CHINA.is_within_limits(109, 100))
        self.assertFalse(CHINA.is_within_limits(111, 100))
        self.assertFalse(CHINA.is_within_limits(89, 100))

    def test_us_has_no_fixed_daily_band(self):
        self.assertIsNone(UNITED_STATES.price_limits(100))
        self.assertTrue(UNITED_STATES.is_within_limits(1000, 100))


if __name__ == "__main__":
    unittest.main()
