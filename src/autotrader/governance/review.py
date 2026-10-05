"""Immutable post-trade review facts.

The review compares the plan that existed before the trade with what actually
happened. It is intentionally factual: a later model may summarize these facts,
but it must not rewrite the original thesis, entry, stop, target, or size.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..core.money import to_decimal
from .trade_plan import Side, TradePlan


class ThesisOutcome(str, Enum):
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class TradeOutcome:
    actual_entry: Decimal
    actual_exit: Decimal
    quantity: int
    fees: Decimal = Decimal("0")
    thesis_outcome: ThesisOutcome = ThesisOutcome.UNRESOLVED

    def __post_init__(self) -> None:
        object.__setattr__(self, "actual_entry", to_decimal(self.actual_entry))
        object.__setattr__(self, "actual_exit", to_decimal(self.actual_exit))
        object.__setattr__(self, "fees", to_decimal(self.fees))


@dataclass(frozen=True)
class PostTradeReview:
    symbol: str
    thesis: str
    planned_entry: Decimal
    actual_entry: Decimal
    planned_stop: Decimal
    planned_target: Decimal
    planned_quantity: int
    actual_quantity: int
    entry_slippage: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    r_multiple: Decimal | None
    thesis_outcome: ThesisOutcome
    size_violation: bool


def review_trade(plan: TradePlan, outcome: TradeOutcome) -> PostTradeReview:
    """Create the mandatory factual review for one closed trade."""

    if outcome.quantity <= 0:
        raise ValueError("actual quantity must be positive")
    if outcome.actual_entry <= 0 or outcome.actual_exit <= 0:
        raise ValueError("actual prices must be positive")
    if outcome.fees < 0:
        raise ValueError("fees cannot be negative")

    direction = Decimal("1") if plan.side is Side.LONG else Decimal("-1")
    gross = (
        (outcome.actual_exit - outcome.actual_entry)
        * outcome.quantity
        * direction
    )
    net = gross - outcome.fees

    planned_risk = abs(plan.entry - plan.stop) * plan.quantity
    r_multiple = net / planned_risk if planned_risk > 0 else None

    entry_slippage = (
        (outcome.actual_entry - plan.entry) * direction
    )

    return PostTradeReview(
        symbol=plan.symbol,
        thesis=plan.thesis,
        planned_entry=plan.entry,
        actual_entry=outcome.actual_entry,
        planned_stop=plan.stop,
        planned_target=plan.target,
        planned_quantity=plan.quantity,
        actual_quantity=outcome.quantity,
        entry_slippage=entry_slippage,
        gross_pnl=gross,
        net_pnl=net,
        r_multiple=r_multiple,
        thesis_outcome=outcome.thesis_outcome,
        size_violation=outcome.quantity > plan.quantity,
    )


@dataclass(frozen=True)
class ReviewSummary:
    """Batch review used to decide whether a rule deserves investigation.

    It deliberately returns a recommendation, never a parameter mutation. One
    trade is not evidence for retuning a strategy.
    """

    trades: int
    win_rate: Decimal
    average_r: Decimal | None
    thesis_confirmed: int
    thesis_invalidated: int
    size_violations: int
    recommendation: str


def summarize_reviews(
    reviews: list[PostTradeReview] | tuple[PostTradeReview, ...],
    *,
    minimum_sample: int = 20,
) -> ReviewSummary:
    """Summarize closed trades without auto-optimizing from hindsight."""

    if minimum_sample < 1:
        raise ValueError("minimum_sample must be positive")

    count = len(reviews)
    if count == 0:
        return ReviewSummary(
            trades=0,
            win_rate=Decimal("0"),
            average_r=None,
            thesis_confirmed=0,
            thesis_invalidated=0,
            size_violations=0,
            recommendation="COLLECT_MORE_DATA",
        )

    wins = sum(1 for review in reviews if review.net_pnl > 0)
    confirmed = sum(
        1 for review in reviews
        if review.thesis_outcome is ThesisOutcome.CONFIRMED
    )
    invalidated = sum(
        1 for review in reviews
        if review.thesis_outcome is ThesisOutcome.INVALIDATED
    )
    violations = sum(1 for review in reviews if review.size_violation)
    r_values = [review.r_multiple for review in reviews if review.r_multiple is not None]
    average_r = (
        sum(r_values, Decimal("0")) / Decimal(len(r_values))
        if r_values
        else None
    )

    if violations:
        recommendation = "HALT_EXECUTION_REVIEW"
    elif count < minimum_sample:
        recommendation = "COLLECT_MORE_DATA"
    elif average_r is not None and average_r <= 0:
        recommendation = "STRATEGY_REVIEW"
    else:
        recommendation = "NO_RULE_CHANGE"

    return ReviewSummary(
        trades=count,
        win_rate=Decimal(wins) / Decimal(count),
        average_r=average_r,
        thesis_confirmed=confirmed,
        thesis_invalidated=invalidated,
        size_violations=violations,
        recommendation=recommendation,
    )
