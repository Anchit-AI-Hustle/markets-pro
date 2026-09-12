"""Yahoo chart parsing and the live-cache round trip."""

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from autotrader.data.fetch import _prefer_fresher_series
from autotrader.data.universe import universe
from autotrader.data.yahoo import (
    DailyRow,
    FetchError,
    parse_chart,
    read_cache,
    write_cache,
)

IST_OFFSET = 19800  # NSE sessions live at UTC+5:30


def chart_payload(*, timestamps, opens, highs, lows, closes, volumes,
                  currency="INR", market_state="CLOSED", gmtoffset=IST_OFFSET):
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": currency,
                        "gmtoffset": gmtoffset,
                        "marketState": market_state,
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens,
                                "high": highs,
                                "low": lows,
                                "close": closes,
                                "volume": volumes,
                            }
                        ]
                    },
                }
            ]
        }
    }


def _ist_open_epoch(year: int, month: int, day: int) -> int:
    """09:15 IST on the given day, as a UTC epoch — how Yahoo stamps NSE bars."""
    return int(datetime(year, month, day, 3, 45, tzinfo=timezone.utc).timestamp())


DAY1 = _ist_open_epoch(2026, 7, 30)
DAY2 = _ist_open_epoch(2026, 7, 31)


class TestParseChart(unittest.TestCase):
    def test_parses_completed_sessions(self):
        payload = chart_payload(
            timestamps=[DAY1, DAY2],
            opens=[100.0, 102.0], highs=[103.0, 104.0],
            lows=[99.0, 101.0], closes=[102.0, 103.5],
            volumes=[1000, 1100],
        )
        rows, currency = parse_chart(payload, today=date(2026, 8, 2))
        self.assertEqual(currency, "INR")
        self.assertEqual([r.day for r in rows], [date(2026, 7, 30), date(2026, 7, 31)])
        self.assertEqual(rows[-1].close, "103.5000")
        self.assertEqual(rows[-1].volume, "1100")

    def test_null_rows_are_dropped(self):
        payload = chart_payload(
            timestamps=[DAY1, DAY2],
            opens=[100.0, None], highs=[103.0, None],
            lows=[99.0, None], closes=[102.0, None],
            volumes=[1000, None],
        )
        rows, _ = parse_chart(payload, today=date(2026, 8, 2))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].day, date(2026, 7, 30))

    def test_todays_bar_dropped_while_market_open(self):
        payload = chart_payload(
            timestamps=[DAY1, DAY2],
            opens=[100.0, 102.0], highs=[103.0, 104.0],
            lows=[99.0, 101.0], closes=[102.0, 103.5],
            volumes=[1000, 1100],
            market_state="REGULAR",
        )
        rows, _ = parse_chart(payload, today=date(2026, 7, 31))
        self.assertEqual([r.day for r in rows], [date(2026, 7, 30)])

    def test_todays_bar_kept_after_the_close(self):
        payload = chart_payload(
            timestamps=[DAY1, DAY2],
            opens=[100.0, 102.0], highs=[103.0, 104.0],
            lows=[99.0, 101.0], closes=[102.0, 103.5],
            volumes=[1000, 1100],
            market_state="CLOSED",
        )
        rows, _ = parse_chart(payload, today=date(2026, 7, 31))
        self.assertEqual(len(rows), 2)

    def test_malformed_payload_raises_fetch_error(self):
        with self.assertRaises(FetchError):
            parse_chart({"chart": {"result": []}}, today=date(2026, 8, 2))


class TestBenchmarkRefreshGuard(unittest.TestCase):
    def test_older_benchmark_response_keeps_previous_series(self):
        previous = {"days": ["2026-09-04", "2026-09-07"], "closes": ["100", "101"]}
        candidate = {"days": ["2026-09-04"], "closes": ["100"]}
        selected, regressed = _prefer_fresher_series(previous, candidate)
        self.assertTrue(regressed)
        self.assertIs(selected, previous)

    def test_same_day_benchmark_correction_is_allowed(self):
        previous = {"days": ["2026-09-07"], "closes": ["101"]}
        candidate = {"days": ["2026-09-07"], "closes": ["102"]}
        selected, regressed = _prefer_fresher_series(previous, candidate)
        self.assertFalse(regressed)
        self.assertIs(selected, candidate)


class TestCacheRoundTrip(unittest.TestCase):
    def test_write_then_read(self):
        entry = universe("india")[0]
        rows = [
            DailyRow(date(2026, 7, 30), "100.0000", "103.0000", "99.0000", "102.0000", "1000"),
            DailyRow(date(2026, 7, 31), "102.0000", "104.0000", "101.0000", "103.5000", "1100"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_cache(root, entry, rows, "INR")
            document = read_cache(root, entry)
        self.assertEqual(document["symbol"], entry.symbol)
        self.assertEqual(document["currency"], "INR")
        self.assertEqual(len(document["bars"]), 2)
        self.assertEqual(document["bars"][-1]["close"], "103.5000")

    def test_older_refresh_does_not_replace_newer_cache(self):
        entry = universe("india")[0]
        newer = [
            DailyRow(date(2026, 7, 31), "102.0000", "104.0000", "101.0000", "103.5000", "1100")
        ]
        older = [
            DailyRow(date(2026, 7, 30), "100.0000", "103.0000", "99.0000", "102.0000", "1000")
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_cache(root, entry, newer, "INR")
            with self.assertRaisesRegex(FetchError, "refusing to regress"):
                write_cache(root, entry, older, "INR")
            document = read_cache(root, entry)
        self.assertEqual(document["bars"][-1]["day"], "2026-07-31")
        self.assertEqual(document["bars"][-1]["close"], "103.5000")

    def test_same_day_provider_correction_is_allowed(self):
        entry = universe("india")[0]
        first = [
            DailyRow(date(2026, 7, 31), "102.0000", "104.0000", "101.0000", "103.5000", "1100")
        ]
        corrected = [
            DailyRow(date(2026, 7, 31), "102.0000", "104.0000", "101.0000", "103.7500", "1150")
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_cache(root, entry, first, "INR")
            write_cache(root, entry, corrected, "INR")
            document = read_cache(root, entry)
        self.assertEqual(document["bars"][-1]["close"], "103.7500")
        self.assertEqual(document["bars"][-1]["volume"], "1150")

    def test_missing_cache_raises(self):
        entry = universe("us")[0]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FetchError):
                read_cache(Path(tmp), entry)


if __name__ == "__main__":
    unittest.main()
