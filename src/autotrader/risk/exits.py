"""Exit logic: stops, targets, trailing stops and time-based exits.

Two modelling decisions here are the difference between an honest backtest and a
flattering one:

**Gaps.** If a long position's stop is at 95 and the session *opens* at 90, the
fill is at 90, not 95. Filling gapped stops at the stop price is the single most
common way a backtest understates drawdown.

**Stop/target ambiguity.** A daily bar whose low pierces the stop *and* whose
high reaches the target does not say which happened first. This engine always
resolves the ambiguity in favour of the **stop**. That is pessimistic by
construction, and it is the only defensible choice: assuming the target filled
first is equivalent to assuming intraday luck you have no evidence for.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..core.money import to_decimal
from ..data.bars import Bar
from ..portfolio.portfolio import OpenTrade


class ExitReason(str, Enum):
    STOP_LOSS = "stop_loss"
    GAP_THROUGH_STOP = "gap_through_stop"
    TAKE_PROFIT = "take_profit"
    GAP_THROUGH_TARGET = "gap_through_target"
    TRAILING_STOP = "trailing_stop"
    TIME_EXIT = "time_exit"
    SIGNAL_EXIT = "signal_exit"
    REBALANCE = "rebalance"
    RISK_HALT = "risk_halt"


@dataclass(frozen=True)
class ExitSignal:
    """An instruction to close a position, with the price it would fill at."""

    reason: ExitReason
    price: Decimal
    detail: str = ""

    @property
    def is_loss_exit(self) -> bool:
        return self.reason in (
            ExitReason.STOP_LOSS,
            ExitReason.GAP_THROUGH_STOP,
            ExitReason.TRAILING_STOP,
        )


def effective_stop(trade: OpenTrade, is_long: bool) -> Decimal | None:
    """Combine the hard stop with any trailing stop, taking the tighter of the two."""
    hard = trade.stop_loss
    if trade.trailing_stop_pct is None:
        return hard
    pct = to_decimal(trade.trailing_stop_pct)
    if is_long:
        trail = trade.high_water_mark * (Decimal("1") - pct)
        return trail if hard is None else max(hard, trail)
    trail = trade.high_water_mark * (Decimal("1") + pct)
    return trail if hard is None else min(hard, trail)


def update_trailing(trade: OpenTrade, bar: Bar, is_long: bool) -> None:
    """Advance the high-water mark used by the trailing stop.

    The mark only ever moves in the favourable direction, so a trailing stop can
    tighten but never loosen.
    """
    if is_long:
        if bar.high > trade.high_water_mark:
            trade.high_water_mark = bar.high
    else:
        if trade.high_water_mark == 0 or bar.low < trade.high_water_mark:
            trade.high_water_mark = bar.low


def evaluate_exit(
    trade: OpenTrade,
    bar: Bar,
    is_long: bool,
    *,
    sessions_held: int | None = None,
) -> ExitSignal | None:
    """Decide whether ``trade`` exits on ``bar``, and at what price.

    Precedence, applied in order:

    1. Gap through the stop at the open — worst case, fills at the open.
    2. Gap through the target at the open — fills at the open.
    3. Stop touched intrabar.
    4. Target touched intrabar (only reached if the stop was not touched).
    5. Time limit — fills at the close.
    """
    stop = effective_stop(trade, is_long)
    target = trade.take_profit
    held = trade.bars_held if sessions_held is None else sessions_held

    if is_long:
        if stop is not None and bar.open <= stop:
            return ExitSignal(
                ExitReason.GAP_THROUGH_STOP, bar.open,
                f"opened at {bar.open} through stop {stop}",
            )
        if target is not None and bar.open >= target:
            return ExitSignal(
                ExitReason.GAP_THROUGH_TARGET, bar.open,
                f"opened at {bar.open} through target {target}",
            )
        if stop is not None and bar.low <= stop:
            reason = (
                ExitReason.TRAILING_STOP
                if trade.trailing_stop_pct is not None and stop != trade.stop_loss
                else ExitReason.STOP_LOSS
            )
            return ExitSignal(reason, stop, f"low {bar.low} touched stop {stop}")
        if target is not None and bar.high >= target:
            return ExitSignal(
                ExitReason.TAKE_PROFIT, target, f"high {bar.high} reached {target}"
            )
    else:
        if stop is not None and bar.open >= stop:
            return ExitSignal(
                ExitReason.GAP_THROUGH_STOP, bar.open,
                f"opened at {bar.open} through short stop {stop}",
            )
        if target is not None and bar.open <= target:
            return ExitSignal(
                ExitReason.GAP_THROUGH_TARGET, bar.open,
                f"opened at {bar.open} through short target {target}",
            )
        if stop is not None and bar.high >= stop:
            reason = (
                ExitReason.TRAILING_STOP
                if trade.trailing_stop_pct is not None and stop != trade.stop_loss
                else ExitReason.STOP_LOSS
            )
            return ExitSignal(reason, stop, f"high {bar.high} touched stop {stop}")
        if target is not None and bar.low <= target:
            return ExitSignal(
                ExitReason.TAKE_PROFIT, target, f"low {bar.low} reached {target}"
            )

    if trade.max_holding_days is not None and held >= trade.max_holding_days:
        return ExitSignal(
            ExitReason.TIME_EXIT, bar.close,
            f"held {held} sessions, limit {trade.max_holding_days}",
        )
    return None


def compute_stop_and_target(
    entry_price: Decimal,
    atr_value: Decimal,
    *,
    is_long: bool,
    stop_atr_multiple: Decimal = Decimal("2"),
    reward_risk_ratio: Decimal = Decimal("2"),
) -> tuple[Decimal, Decimal]:
    """Derive a volatility-scaled stop and a target at a fixed reward:risk.

    Placing the stop in ATR units rather than at a fixed percentage means the
    stop sits outside normal noise for that instrument, so exits are driven by
    the thesis breaking rather than by ordinary volatility.
    """
    entry = to_decimal(entry_price)
    atr_value = to_decimal(atr_value)
    if atr_value <= 0:
        raise ValueError("ATR must be positive to derive a stop")
    distance = atr_value * to_decimal(stop_atr_multiple)
    reward = distance * to_decimal(reward_risk_ratio)
    if is_long:
        stop = entry - distance
        if stop <= 0:
            raise ValueError(
                f"stop {stop} would be non-positive; ATR {atr_value} too wide "
                f"for price {entry}"
            )
        return stop, entry + reward
    return entry + distance, max(entry - reward, to_decimal("0.01"))
