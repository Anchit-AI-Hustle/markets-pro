"""Strategy interface.

A strategy receives only :class:`~autotrader.data.bars.HistoryWindow` objects
clipped to the decision date, and returns :class:`Signal` objects. It never sees
the portfolio's cash, never sizes its own positions, and never places orders.
That separation is deliberate: sizing and risk are portfolio-level concerns, and
a strategy that sizes its own positions cannot be risk-limited coherently
alongside other strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import IntEnum

from ..core.instrument import Instrument
from ..data.bars import HistoryWindow
from ..execution.orders import Horizon


class Direction(IntEnum):
    LONG = 1
    FLAT = 0
    SHORT = -1


@dataclass(frozen=True)
class Signal:
    """A strategy's view on one instrument at one point in time."""

    instrument: Instrument
    direction: Direction
    horizon: Horizon
    #: Conviction in ``[0, 1]``; scales size within the risk envelope.
    strength: float = 1.0
    #: Ranking score used to select among competing signals (higher is better).
    score: float = 0.0
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    target_weight: Decimal | None = None
    atr_value: Decimal | None = None
    max_holding_days: int | None = None
    trailing_stop_pct: Decimal | None = None
    reason: str = ""
    diagnostics: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.strength <= 1.0):
            raise ValueError(f"strength must be in [0, 1], got {self.strength}")

    @property
    def is_entry(self) -> bool:
        return self.direction is not Direction.FLAT

    @property
    def is_exit(self) -> bool:
        return self.direction is Direction.FLAT


@dataclass
class StrategyContext:
    """Read-only view of portfolio state passed to strategies each session."""

    day: date
    equity: Decimal
    open_keys: frozenset[str] = frozenset()
    held_since: dict[str, date] = field(default_factory=dict)
    entries_halted: bool = False
    #: Entry price of each live position, for exit rules that reason in R units.
    entry_prices: dict[str, Decimal] = field(default_factory=dict)
    #: Active stop level of each live position.
    stop_levels: dict[str, Decimal] = field(default_factory=dict)

    def holds(self, key: str) -> bool:
        return key in self.open_keys

    def r_multiple(self, key: str, price: Decimal) -> Decimal | None:
        """Open profit on ``key`` expressed in units of initial risk.

        ``1.0`` means the position has gained exactly the distance from entry to
        its stop. Returns ``None`` when entry or stop is unknown, so callers can
        distinguish "no profit yet" from "cannot tell".
        """
        entry = self.entry_prices.get(key)
        stop = self.stop_levels.get(key)
        if entry is None or stop is None:
            return None
        risk = abs(entry - stop)
        if risk <= 0:
            return None
        return (Decimal(price) - entry) / risk


class Strategy(ABC):
    """Base class for all strategies."""

    name: str = "strategy"
    horizon: Horizon = Horizon.SHORT_TERM
    #: Minimum bars of history required before the strategy will emit anything.
    warmup_bars: int = 0

    @abstractmethod
    def generate(
        self,
        as_of: date,
        windows: dict[str, HistoryWindow],
        instruments: dict[str, Instrument],
        context: StrategyContext,
    ) -> list[Signal]:
        """Return signals for ``as_of``, using only data visible in ``windows``."""

    def should_run(self, as_of: date, context: StrategyContext) -> bool:
        """Whether the strategy acts on this session. Default: every session."""
        return True

    def _ready(self, window: HistoryWindow) -> bool:
        return window is not None and window.has(self.warmup_bars)


def is_month_boundary(current: date, previous: date | None) -> bool:
    """True when ``current`` is the first observed session of a new month."""
    if previous is None:
        return True
    return (current.year, current.month) != (previous.year, previous.month)


def is_week_boundary(current: date, previous: date | None) -> bool:
    """True when ``current`` starts a new ISO week."""
    if previous is None:
        return True
    return current.isocalendar()[:2] != previous.isocalendar()[:2]
