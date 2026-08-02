"""Trading calendars.

The backtest clock is driven by the *union* of every market's sessions, while
each market only acts on its own. Without this, a global portfolio would either
skip days (intersection) or trade venues that were closed (naive daily loop).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .market import MarketSpec


@dataclass(frozen=True)
class TradingCalendar:
    """Session calendar for a single market."""

    spec: MarketSpec

    def is_trading_day(self, day: date) -> bool:
        if day.weekday() in self.spec.weekend_days:
            return False
        return day not in self.spec.holidays

    def next_trading_day(self, day: date, *, inclusive: bool = False) -> date:
        """First session on or after ``day`` (strictly after unless inclusive)."""
        cursor = day if inclusive else day + timedelta(days=1)
        for _ in range(_MAX_SCAN):
            if self.is_trading_day(cursor):
                return cursor
            cursor += timedelta(days=1)
        raise RuntimeError(f"no trading day found within {_MAX_SCAN} days of {day}")

    def previous_trading_day(self, day: date, *, inclusive: bool = False) -> date:
        cursor = day if inclusive else day - timedelta(days=1)
        for _ in range(_MAX_SCAN):
            if self.is_trading_day(cursor):
                return cursor
            cursor -= timedelta(days=1)
        raise RuntimeError(f"no trading day found within {_MAX_SCAN} days of {day}")

    def sessions(self, start: date, end: date) -> list[date]:
        """All sessions in the inclusive range ``[start, end]``."""
        if end < start:
            return []
        out: list[date] = []
        cursor = start
        while cursor <= end:
            if self.is_trading_day(cursor):
                out.append(cursor)
            cursor += timedelta(days=1)
        return out

    def add_sessions(self, day: date, count: int) -> date:
        """Advance ``count`` sessions from ``day`` (negative walks backwards)."""
        if count == 0:
            return day if self.is_trading_day(day) else self.next_trading_day(day)
        step = self.next_trading_day if count > 0 else self.previous_trading_day
        cursor = day
        for _ in range(abs(count)):
            cursor = step(cursor)
        return cursor

    def session_count(self, start: date, end: date) -> int:
        return len(self.sessions(start, end))

    def settlement_date(self, trade_date: date) -> date:
        """Date on which cash from a trade on ``trade_date`` actually settles."""
        return self.add_sessions(trade_date, self.spec.settlement_days)


_MAX_SCAN = 3650  # ten years; a longer gap means the holiday set is corrupt


@dataclass(frozen=True)
class GlobalCalendar:
    """Union clock across several markets.

    ``sessions`` yields every date on which *at least one* venue is open, which
    is the correct driver for a portfolio that spans time zones.
    """

    calendars: dict[str, TradingCalendar]

    @classmethod
    def from_specs(cls, specs: Iterable[MarketSpec]) -> GlobalCalendar:
        return cls({s.code: TradingCalendar(s) for s in specs})

    def open_markets(self, day: date) -> list[str]:
        """Region codes whose venue is open on ``day``, in registry order."""
        return [code for code, cal in self.calendars.items() if cal.is_trading_day(day)]

    def is_any_open(self, day: date) -> bool:
        return any(cal.is_trading_day(day) for cal in self.calendars.values())

    def sessions(self, start: date, end: date) -> list[date]:
        if end < start:
            return []
        out: list[date] = []
        cursor = start
        while cursor <= end:
            if self.is_any_open(cursor):
                out.append(cursor)
            cursor += timedelta(days=1)
        return out

    def __iter__(self) -> Iterator[TradingCalendar]:  # pragma: no cover - trivial
        return iter(self.calendars.values())

    def for_region(self, code: str) -> TradingCalendar:
        return self.calendars[code.upper()]


def merge_sessions(sequences: Sequence[Sequence[date]]) -> list[date]:
    """Sorted union of several session lists, de-duplicated."""
    seen: set[date] = set()
    for seq in sequences:
        seen.update(seq)
    return sorted(seen)
