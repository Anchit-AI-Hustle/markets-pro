"""Data-quality checks: freshness and sanity of the live cache."""

import unittest
from datetime import date, timedelta
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.money import FXRates
from autotrader.data.bars import Bar, BarSeries, MarketDataSet
from autotrader.data.livefeed import LiveFeed
from autotrader.data.quality import (
    DEFAULT_DEAD_AFTER_SESSIONS,
    DEFAULT_MIN_HISTORY_BARS,
    HARD_FAILURE_KINDS,
    QualityIssue,
    check_freshness,
    check_history,
    check_sanity,
    format_issues,
    hard_failures,
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


class TestShortHistory(unittest.TestCase):
    """An instrument too new to screen must say so rather than vanish.

    IN:ICICIPRULI held 71 bars against a universe median of 495. The screener
    needs 201 before it will score anything, so the name was quietly absent
    from the screener's "All 324" and from the evidence study, while the
    freshness and sanity checks both passed it: the bars it did have were
    current and sane. Nothing in the product said a name was missing.
    """

    def _series(self, n: int) -> BarSeries:
        start = date(2026, 1, 5)
        bars = [
            Bar(
                day=start + timedelta(days=i),
                open=Decimal("100"), high=Decimal("101"),
                low=Decimal("99"), close=Decimal("100"), volume=10_000,
            )
            for i in range(n)
        ]
        return BarSeries(key="IN:TESTCO", bars=tuple(bars))

    def test_a_thin_series_is_reported(self):
        issue = check_history(_entry(), self._series(71))
        self.assertIsNotNone(issue)
        self.assertEqual(issue.kind, "short_history")
        self.assertIn("71", issue.detail)

    def test_enough_history_is_silent(self):
        self.assertIsNone(check_history(_entry(), self._series(DEFAULT_MIN_HISTORY_BARS)))

    def test_one_bar_short_is_still_reported(self):
        self.assertIsNotNone(
            check_history(_entry(), self._series(DEFAULT_MIN_HISTORY_BARS - 1)))

    def test_no_series_is_left_to_the_freshness_check(self):
        """Otherwise an uncached instrument would be reported twice, once as
        missing and once as thin, for the same single cause."""
        self.assertIsNone(check_history(_entry(), None))

    def test_it_never_fails_the_run_on_its_own(self):
        """A recent listing is a fact about the listing, not a broken fetch."""
        issues = [QualityIssue("IN:NEW", "short_history", "only 71 bar(s)")]
        self.assertEqual(hard_failures(issues, universe_size=325), [])


class TestWhichIssuesFailTheRun(unittest.TestCase):
    """The rule that caused a fortnight-long outage, and what replaced it.

    One US ticker stopped reporting. Staleness failed the run whatever its
    extent, so that single symbol aborted the job before its commit step and
    froze the cache the gate exists to protect. The frozen cache then went a
    session staler every night, growing the gate's own verdict from one
    failure to 325 -- a check that was the sole cause of what it reported.
    """

    def _stale(self, n: int, sessions: int = 4) -> list[QualityIssue]:
        return [
            QualityIssue(f"US:S{i:03d}", "stale", f"{sessions} behind", sessions=sessions)
            for i in range(n)
        ]

    def test_one_dead_ticker_does_not_fail_a_healthy_universe(self):
        self.assertEqual(hard_failures(self._stale(1), universe_size=325), [])

    def test_a_handful_of_dead_tickers_does_not_either(self):
        self.assertEqual(hard_failures(self._stale(6), universe_size=325), [])

    def test_a_stale_universe_is_a_broken_fetch_and_fails(self):
        issues = self._stale(325)
        self.assertEqual(len(hard_failures(issues, universe_size=325)), 325)

    def test_the_threshold_is_a_share_of_the_universe(self):
        # 2% of 325 is 7 symbols; one short of it is still tolerated.
        self.assertEqual(hard_failures(self._stale(6), universe_size=325), [])
        self.assertEqual(len(hard_failures(self._stale(7), universe_size=325)), 7)

    def test_a_small_universe_still_needs_two_symbols_to_agree(self):
        """A share alone would make a single symbol a broken fetch here."""
        self.assertEqual(hard_failures(self._stale(1), universe_size=10), [])
        self.assertEqual(len(hard_failures(self._stale(2), universe_size=10)), 2)

    def test_a_gap_too_long_to_be_transient_fails_on_its_own(self):
        """So a dead ticker cannot be tolerated forever without anyone acting."""
        lingering = self._stale(1, sessions=DEFAULT_DEAD_AFTER_SESSIONS + 1)
        self.assertEqual(len(hard_failures(lingering, universe_size=325)), 1)

    def test_a_gap_at_the_limit_is_still_tolerated(self):
        at_limit = self._stale(1, sessions=DEFAULT_DEAD_AFTER_SESSIONS)
        self.assertEqual(hard_failures(at_limit, universe_size=325), [])

    def test_an_uncached_instrument_always_fails(self):
        """``no_data`` is a configuration error, not a dead symbol: a key in
        the universe that was never fetched at all."""
        issues = [QualityIssue("US:NEW", "no_data", "no cached bars at all")]
        self.assertEqual(len(hard_failures(issues, universe_size=325)), 1)

    def test_warnings_never_fail_the_run(self):
        issues = [
            QualityIssue("US:AAA", "outlier", "moved 40%"),
            QualityIssue("US:BBB", "zero_volume", "silent session"),
        ]
        self.assertEqual(hard_failures(issues, universe_size=325), [])

    def test_the_original_outage_would_not_have_happened(self):
        """The exact shape of run 101: 365 warnings, one stale US ticker."""
        issues = [
            *(QualityIssue(f"IN:S{i:03d}", "zero_volume", "silent") for i in range(357)),
            *(QualityIssue(f"US:O{i}", "outlier", "moved 36%") for i in range(8)),
            QualityIssue("US:WBD", "stale", "4 behind", sessions=4),
        ]
        self.assertEqual(hard_failures(issues, universe_size=325), [])


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
        # This test is about freshness aggregation, so the history threshold is
        # held at 1: these fixtures carry a single bar each by design.
        issues = verify_livefeed(feed, as_of=as_of, min_history_bars=1)
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
