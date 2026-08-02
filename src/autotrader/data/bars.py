"""Price series and the lookahead guard.

Lookahead bias — letting a strategy see data it could not have had at decision
time — is the defect that makes backtests profitable and live trading not. It is
handled here structurally rather than by convention: a strategy is never handed
a raw series, only a :class:`HistoryWindow` clipped to the decision date. There
is no accessor on that window which can reach a future bar.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.money import to_decimal


class LookaheadError(RuntimeError):
    """Raised when code attempts to read a bar at or beyond the decision date."""


@dataclass(frozen=True)
class Bar:
    """One OHLCV observation for a single session."""

    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close", "volume"):
            object.__setattr__(self, name, to_decimal(getattr(self, name)))
        if self.high < self.low:
            raise ValueError(f"{self.day}: high {self.high} below low {self.low}")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"{self.day}: open {self.open} outside [{self.low}, {self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"{self.day}: close {self.close} outside [{self.low}, {self.high}]")
        if self.volume < 0:
            raise ValueError(f"{self.day}: negative volume")

    @property
    def typical_price(self) -> Decimal:
        """(H + L + C) / 3 — the standard VWAP proxy for a daily bar."""
        return (self.high + self.low + self.close) / Decimal("3")

    @property
    def range(self) -> Decimal:
        return self.high - self.low


class BarSeries:
    """Chronologically ordered bars for one instrument.

    Construction validates ordering and rejects duplicate dates, so downstream
    index arithmetic can assume a clean, strictly increasing series.
    """

    __slots__ = ("key", "_bars", "_days")

    def __init__(self, key: str, bars: Sequence[Bar]) -> None:
        ordered = list(bars)
        for prev, nxt in zip(ordered, ordered[1:], strict=False):
            if nxt.day <= prev.day:
                raise ValueError(
                    f"{key}: bars must strictly increase in date; "
                    f"{prev.day} then {nxt.day}"
                )
        self.key = key
        self._bars: list[Bar] = ordered
        self._days: list[date] = [b.day for b in ordered]

    def __len__(self) -> int:
        return len(self._bars)

    def __iter__(self) -> Iterator[Bar]:
        return iter(self._bars)

    def __getitem__(self, index: int) -> Bar:
        return self._bars[index]

    @property
    def days(self) -> list[date]:
        return list(self._days)

    @property
    def first_day(self) -> date | None:
        return self._days[0] if self._days else None

    @property
    def last_day(self) -> date | None:
        return self._days[-1] if self._days else None

    def bar_on(self, day: date) -> Bar | None:
        """Exact-date lookup; ``None`` when the instrument did not trade."""
        idx = bisect_right(self._days, day) - 1
        if idx < 0 or self._days[idx] != day:
            return None
        return self._bars[idx]

    def index_asof(self, day: date) -> int:
        """Index of the last bar at or before ``day``; ``-1`` when none exists."""
        return bisect_right(self._days, day) - 1

    def window(self, as_of: date) -> HistoryWindow:
        """History visible to a decision made *at the close of* ``as_of``."""
        return HistoryWindow(self, self.index_asof(as_of), as_of)


class HistoryWindow:
    """A read-only view of a :class:`BarSeries` clipped to a decision date.

    Every accessor is bounded by ``end_index``. Reaching past it raises
    :class:`LookaheadError` rather than returning a future price, so a lookahead
    bug fails loudly in a test instead of quietly inflating returns.
    """

    __slots__ = ("_series", "_end", "as_of")

    def __init__(self, series: BarSeries, end_index: int, as_of: date) -> None:
        self._series = series
        self._end = end_index
        self.as_of = as_of

    def __len__(self) -> int:
        """Number of bars available up to and including the decision date."""
        return self._end + 1

    @property
    def is_empty(self) -> bool:
        return self._end < 0

    @property
    def latest(self) -> Bar | None:
        """Most recent observable bar, or ``None`` before the series starts."""
        return self._series[self._end] if self._end >= 0 else None

    def ago(self, n: int) -> Bar:
        """Bar ``n`` sessions back; ``ago(0)`` is the latest visible bar."""
        if n < 0:
            raise LookaheadError(f"ago({n}) would read {abs(n)} bars into the future")
        idx = self._end - n
        if idx < 0:
            raise IndexError(f"only {len(self)} bars available, asked for {n} back")
        return self._series[idx]

    def closes(self, count: int | None = None) -> list[Decimal]:
        return [b.close for b in self.bars(count)]

    def highs(self, count: int | None = None) -> list[Decimal]:
        return [b.high for b in self.bars(count)]

    def lows(self, count: int | None = None) -> list[Decimal]:
        return [b.low for b in self.bars(count)]

    def volumes(self, count: int | None = None) -> list[Decimal]:
        return [b.volume for b in self.bars(count)]

    def bars(self, count: int | None = None) -> list[Bar]:
        """The last ``count`` visible bars in chronological order (all if None)."""
        if self._end < 0:
            return []
        stop = self._end + 1
        start = 0 if count is None else max(0, stop - count)
        return [self._series[i] for i in range(start, stop)]

    def has(self, count: int) -> bool:
        """True when at least ``count`` bars of history are available."""
        return len(self) >= count


class MarketDataSet:
    """All instrument series for a backtest, keyed by ``Instrument.key``."""

    def __init__(self, series: dict[str, BarSeries] | None = None) -> None:
        self._series: dict[str, BarSeries] = dict(series or {})

    def add(self, key: str, series: BarSeries) -> None:
        self._series[key] = series

    def __contains__(self, key: str) -> bool:
        return key in self._series

    def __len__(self) -> int:
        return len(self._series)

    @property
    def keys(self) -> list[str]:
        return sorted(self._series)

    def series(self, key: str) -> BarSeries:
        return self._series[key]

    def get(self, key: str) -> BarSeries | None:
        return self._series.get(key)

    def window(self, key: str, as_of: date) -> HistoryWindow | None:
        s = self._series.get(key)
        return None if s is None else s.window(as_of)

    def bar_on(self, key: str, day: date) -> Bar | None:
        s = self._series.get(key)
        return None if s is None else s.bar_on(day)

    def all_days(self) -> list[date]:
        """Sorted union of every date present in any series."""
        seen: set[date] = set()
        for s in self._series.values():
            seen.update(s.days)
        return sorted(seen)
