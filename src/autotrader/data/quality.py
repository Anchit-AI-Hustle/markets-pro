"""Data-quality checks for the live cache: freshness and basic sanity.

Screeners and strategies both consume the committed cache under ``data/live/``
without re-fetching, so a stale or corrupt file degrades silently unless
something checks it. This module is that check — it never mutates the cache,
only reports on what it finds, so it is safe to run in read-only CI jobs
alongside the nightly refresh.

Two kinds of problem are distinguished deliberately:

* **Freshness** (``no_data`` / ``stale``) — the pipeline itself is broken: a
  symbol never fetched, or fell behind its own market's completed sessions.
  This is a hard failure; a screener or strategy run against it is reasoning
  about the past as if it were the present.
* **Sanity** (``outlier`` / ``zero_volume``) — the data *arrived* but looks
  wrong: an implausible single-session move, or a session with no reported
  volume. These can be real market events (a genuine halt, a genuine circuit-
  breaker day), so they are surfaced as warnings, not failures.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..core.calendar import TradingCalendar
from ..core.market import get_market
from .bars import BarSeries
from .livefeed import LiveFeed, load_livefeed
from .universe import UNIVERSES, UniverseEntry

#: A cache is "stale" once it has missed this many of its own market's
#: completed sessions — generous enough to absorb one skipped nightly refresh
#: (a holiday miscount, a transient fetch failure) without false-alarming,
#: tight enough to catch a genuinely broken feed within a trading week.
DEFAULT_MAX_STALE_SESSIONS = 3

#: A single-session close-to-close move beyond this magnitude is flagged as a
#: probable data error (a bad tick, a decimal-shift bug) rather than treated
#: as unremarkable. Real single-day moves this large happen — this is a
#: warning to look, not proof of a bug.
DEFAULT_MAX_DAILY_MOVE = 0.35


@dataclass(frozen=True)
class QualityIssue:
    """One finding against one instrument's cached series."""

    key: str
    kind: str  # "no_data" | "stale" | "outlier" | "zero_volume"
    detail: str


#: Kinds that mean the pipeline itself failed, not just an unusual session.
HARD_FAILURE_KINDS = frozenset({"no_data", "stale"})


def check_freshness(
    entry: UniverseEntry,
    series: BarSeries | None,
    *,
    as_of: date,
    max_stale_sessions: int = DEFAULT_MAX_STALE_SESSIONS,
) -> QualityIssue | None:
    """``None`` when the cache is current enough; a hard-failure issue otherwise."""
    last_day = series.last_day if series is not None else None
    if last_day is None:
        return QualityIssue(entry.key, "no_data", "no cached bars at all")
    if last_day >= as_of:
        return None
    calendar = TradingCalendar(get_market(entry.region_code))
    missed = calendar.session_count(calendar.next_trading_day(last_day), as_of)
    if missed > max_stale_sessions:
        return QualityIssue(
            entry.key,
            "stale",
            f"last bar {last_day} is {missed} completed session(s) behind {as_of}",
        )
    return None


def check_sanity(
    entry: UniverseEntry,
    series: BarSeries | None,
    *,
    max_daily_move: float = DEFAULT_MAX_DAILY_MOVE,
) -> list[QualityIssue]:
    """Warnings only — an implausible move or a silent (zero-volume) session."""
    if series is None or len(series) < 2:
        return []
    issues: list[QualityIssue] = []
    bars = list(series)
    for prev, curr in zip(bars, bars[1:], strict=False):
        if prev.close > 0:
            move = abs(float(curr.close) - float(prev.close)) / float(prev.close)
            if move > max_daily_move:
                issues.append(
                    QualityIssue(
                        entry.key,
                        "outlier",
                        f"{prev.day}->{curr.day}: close moved {move:.0%} in one session",
                    )
                )
        if curr.volume == 0:
            issues.append(
                QualityIssue(entry.key, "zero_volume", f"{curr.day}: zero reported volume")
            )
    return issues


def verify_livefeed(
    feed: LiveFeed,
    *,
    as_of: date,
    max_stale_sessions: int = DEFAULT_MAX_STALE_SESSIONS,
    max_daily_move: float = DEFAULT_MAX_DAILY_MOVE,
) -> list[QualityIssue]:
    """Every finding across every instrument the feed says it loaded.

    Symbols the feed itself already dropped (a fetch failure with no prior
    cache at all) are invisible here by construction — :func:`load_livefeed`
    skips them rather than raising, so there is nothing in ``feed.entries`` to
    check. That is the correct division of labour: this function verifies what
    *was* loaded, not what could not be found at all.
    """
    issues: list[QualityIssue] = []
    for entry in feed.entries:
        series = feed.data.get(entry.key)
        fresh_issue = check_freshness(
            entry, series, as_of=as_of, max_stale_sessions=max_stale_sessions
        )
        if fresh_issue is not None:
            issues.append(fresh_issue)
        issues.extend(check_sanity(entry, series, max_daily_move=max_daily_move))
    return issues


def format_issues(issues: Sequence[QualityIssue]) -> list[str]:
    """One line per issue, columns sized to the rows actually being printed.

    A fixed 12-wide symbol column ran 64 of the 325 live symbols straight into
    their own detail text -- "IN:ZYDUSLIFE2025-03-18" reads as neither a symbol
    nor a date. This report exists to say which instrument is broken, so the
    instrument has to survive being printed next to anything else.
    """
    kind_width = max((len(i.kind) for i in issues), default=0) + 2
    key_width = max((len(i.key) for i in issues), default=0) + 2
    return [
        f"{i.kind:<{kind_width}}{i.key:<{key_width}}{i.detail}" for i in issues
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify freshness and sanity of the live daily-bar cache"
    )
    parser.add_argument("--data", default="data/live", help="live cache root")
    parser.add_argument(
        "--regions", nargs="+", default=sorted(UNIVERSES), choices=sorted(UNIVERSES)
    )
    parser.add_argument("--max-stale-sessions", type=int, default=DEFAULT_MAX_STALE_SESSIONS)
    parser.add_argument("--max-daily-move", type=float, default=DEFAULT_MAX_DAILY_MOVE)
    args = parser.parse_args(argv)

    feed = load_livefeed(Path(args.data), args.regions)
    today = date.today()
    issues = verify_livefeed(
        feed,
        as_of=today,
        max_stale_sessions=args.max_stale_sessions,
        max_daily_move=args.max_daily_move,
    )
    for line in format_issues(issues):
        print(line, file=sys.stderr)

    hard = [i for i in issues if i.kind in HARD_FAILURE_KINDS]
    print(
        f"{len(feed.entries)} instrument(s) checked as of {today}: "
        f"{len(issues)} issue(s), {len(hard)} hard failure(s)"
    )
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
