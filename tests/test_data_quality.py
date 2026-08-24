"""Data-quality checks: freshness and sanity of the live cache."""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.money import FXRates
from autotrader.data.bars import Bar, BarSeries, MarketDataSet
from autotrader.data.livefeed import LiveFeed
from autotrader.data.quality import (
    HARD_FAILURE_KINDS,
    QualityIssue,
    check_freshness,
    check_sanity,
    format_issues,
    verify_livefeed,
)
from autotrader.data.universe import UniverseEntry


def _entry(symbol: str = "TESTCO", region: str = "india") -> UniverseEntry:
    return UniverseEntry(
        symbol=symbol,
        yahoo=f"{symbol}.NS" if region == "india" else symbol,
        exchange="NSE" if region == "india" else "NASDAQ",
        region=region,
        currency="INR" if region == "india" else "USD",
        kind="equity",
        sector="tech",
        name=symbol,
    )


def _series(entry: UniverseEntry, rows: list[tuple[date, float, int]]) -> BarSeries:
    bars = [
        Bar(
            day=d,
            open=Decimal(str(p)),
            high=Decimal(str(p + 1)),
            low=Decimal(str(max(p - 1, 0.01))),
            close=Decimal(str(p)),
            volume=Decimal(str(v)),
        )
        for d, p, v in rows
    ]
    return BarSeries(entry.key, bars)


class TestCheckFreshness(unittest.TestCase):
    def test_current_data_has_no_issue(self):
        entry = _entry()
        as_of = date(2026, 8, 19)  # Wednesday
        series = _series(entry, [(date(2026, 8, 18), 100, 1000)])  # Tuesday, 1 session back
        self.assertIsNone(check_freshness(entry, series, as_of=as_of))

    def test_no_data_flags_hard_failure(self):
        entry = _entry()
        issue = check_freshness(entry, None, as_of=date(2026, 8, 19))
        self.assertEqual(issue.kind, "no_data")

    def test_stale_beyond_threshold_flags_hard_failure(self):
        entry = _entry()
        as_of = date(2026, 8, 19)
        series = _series(entry, [(date(2026, 8, 3), 100, 1000)])  # ~2 weeks stale
        issue = check_freshness(entry, series, as_of=as_of, max_stale_sessions=3)
        self.assertEqual(issue.kind, "stale")

    def test_within_stale_budget_is_fine(self):
        entry = _entry()
        as_of = date(2026, 8, 19)  # Wednesday
        series = _series(entry, [(date(2026, 8, 17), 100, 1000)])  # Monday, 2 sessions back
        self.assertIsNone(check_freshness(entry, series, as_of=as_of, max_stale_sessions=3))


class TestCheckSanity(unittest.TestCase):
    def test_large_move_flagged_as_outlier(self):
        entry = _entry()
        series = _series(
            entry,
            [(date(2026, 8, 17), 100, 1000), (date(2026, 8, 18), 200, 1000)],  # +100%
        )
        issues = check_sanity(entry, series)
        self.assertTrue(any(i.kind == "outlier" for i in issues))

    def test_zero_volume_session_flagged(self):
        entry = _entry()
        series = _series(
            entry,
            [(date(2026, 8, 17), 100, 1000), (date(2026, 8, 18), 101, 0)],
        )
        issues = check_sanity(entry, series)
        self.assertTrue(any(i.kind == "zero_volume" for i in issues))

    def test_ordinary_move_is_clean(self):
        entry = _entry()
        series = _series(
            entry,
            [(date(2026, 8, 17), 100, 1000), (date(2026, 8, 18), 101, 1000)],
        )
        self.assertEqual(check_sanity(entry, series), [])

    def test_single_bar_series_has_nothing_to_compare(self):
        entry = _entry()
        series = _series(entry, [(date(2026, 8, 18), 100, 1000)])
        self.assertEqual(check_sanity(entry, series), [])


class TestVerifyLivefeed(unittest.TestCase):
    def test_aggregates_across_entries(self):
        fresh_entry = _entry("FRESH")
        stale_entry = _entry("STALE")
        as_of = date(2026, 8, 19)
        data = MarketDataSet()
        data.add(fresh_entry.key, _series(fresh_entry, [(date(2026, 8, 18), 100, 1000)]))
        data.add(stale_entry.key, _series(stale_entry, [(date(2026, 8, 3), 100, 1000)]))
        instruments = tuple(
            Instrument(
                symbol=e.symbol,
                region=e.region_code,
                asset_class=AssetClass.EQUITY,
                currency=e.currency,
                tick_size=Decimal("0.05"),
                lot_size=Decimal("1"),
                name=e.name,
                sector=e.sector,
            )
            for e in (fresh_entry, stale_entry)
        )
        feed = LiveFeed(
            instruments=instruments,
            entries=(fresh_entry, stale_entry),
            data=data,
            fx=FXRates("INR", {}),
            as_of={"india": as_of},
        )
        issues = verify_livefeed(feed, as_of=as_of)
        kinds_by_key: dict[str, set[str]] = {}
        for issue in issues:
            kinds_by_key.setdefault(issue.key, set()).add(issue.kind)
        self.assertNotIn(fresh_entry.key, kinds_by_key)
        self.assertIn("stale", kinds_by_key[stale_entry.key])

    def test_a_long_symbol_does_not_collide_with_its_detail(self):
        """64 of the 325 live symbols are 12 characters or more. At a fixed
        12-wide column they printed as "IN:ZYDUSLIFE2025-03-18" -- the one
        thing the reader needs, welded to the next field."""
        issues = [
            QualityIssue("IN:ZYDUSLIFE", "zero_volume", "2025-03-18: zero reported volume"),
            QualityIssue("IN:JUNIORBEES", "outlier", "2026-05-28: close moved 36%"),
            QualityIssue("US:F", "stale", "4 sessions behind"),
        ]
        for line, issue in zip(format_issues(issues), issues, strict=True):
            self.assertIn(f"{issue.key} ", line, f"{issue.key} must be followed by a space")
            self.assertTrue(line.endswith(issue.detail))
            head = line[: line.index(issue.detail)]
            self.assertIn(f"{issue.kind} ", head)

    def test_columns_line_up_across_rows(self):
        # A report whose columns jitter per row is no easier to scan than one
        # with none, so the width is shared, not per-line.
        issues = [
            QualityIssue("IN:ZYDUSLIFE", "zero_volume", "a"),
            QualityIssue("US:F", "stale", "b"),
        ]
        lines = format_issues(issues)
        self.assertEqual(*[len(line) - len(i.detail) for line, i in zip(lines, issues, strict=True)])

    def test_no_issues_formats_to_nothing(self):
        self.assertEqual(format_issues([]), [])

    def test_hard_failure_kinds_are_no_data_and_stale(self):
        self.assertEqual(HARD_FAILURE_KINDS, frozenset({"no_data", "stale"}))


if __name__ == "__main__":
    unittest.main()
