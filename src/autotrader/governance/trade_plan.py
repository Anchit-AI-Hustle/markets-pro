"""Provider-agnostic gate between research and execution.

A research model may propose a thesis and an independent decision component may
return TRADE, WAIT, or REJECT. Neither can bypass the mechanical requirements
for a complete trade plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ..core.money import to_decimal


class Decision(str, Enum):
    TRADE = "trade"
    WAIT = "wait"
    REJECT = "reject"


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class TradePlan:
    """Everything that must be fixed before an entry is eligible."""

    symbol: str
    side: Side
    entry: Decimal
    stop: Decimal
    target: Decimal
    quantity: int
    confidence: Decimal
    thesis: str
    catalyst: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry", to_decimal(self.entry))
        object.__setattr__(self, "stop", to_decimal(self.stop))
        object.__setattr__(self, "target", to_decimal(self.target))
        object.__setattr__(self, "confidence", to_decimal(self.confidence))


@dataclass(frozen=True)
class PlanDecision:
    allowed: bool
    action: Decision
    code: str
    reasons: tuple[str, ...]
    risk_per_unit: Decimal = Decimal("0")
    reward_per_unit: Decimal = Decimal("0")
    reward_risk: Decimal = Decimal("0")
    maximum_planned_loss: Decimal = Decimal("0")


class TradePlanGate:
    """Fail closed on low confidence or incomplete/illogical trade rules.

    Confidence is only a rejection threshold. A high confidence value never
    grants more risk and never overrides the capital floor, RiskManager, or
    consensus vetoes.
    """

    def __init__(
        self,
        *,
        minimum_confidence: Decimal = Decimal("0.70"),
        minimum_reward_risk: Decimal = Decimal("1.5"),
    ) -> None:
        self.minimum_confidence = to_decimal(minimum_confidence)
        self.minimum_reward_risk = to_decimal(minimum_reward_risk)
        if not Decimal("0") <= self.minimum_confidence <= Decimal("1"):
            raise ValueError("minimum_confidence must be in [0, 1]")
        if self.minimum_reward_risk <= 0:
            raise ValueError("minimum_reward_risk must be positive")

    def evaluate(
        self,
        plan: TradePlan,
        *,
        research_decision: Decision,
        independent_decision: Decision,
    ) -> PlanDecision:
        reasons: list[str] = []

        if research_decision is not Decision.TRADE:
            reasons.append(f"research says {research_decision.value}")
        if independent_decision is not Decision.TRADE:
            reasons.append(f"independent decision says {independent_decision.value}")
        if research_decision is not independent_decision:
            reasons.append("research and independent decision disagree")

        if not plan.symbol.strip():
            reasons.append("symbol is required")
        if not plan.thesis.strip():
            reasons.append("thesis is required")
        if plan.quantity <= 0:
            reasons.append("quantity must be positive")
        if plan.entry <= 0 or plan.stop <= 0 or plan.target <= 0:
            reasons.append("entry, stop and target must be positive")
        if not Decimal("0") <= plan.confidence <= Decimal("1"):
            reasons.append("confidence must be in [0, 1]")
        elif plan.confidence < self.minimum_confidence:
            reasons.append("confidence below threshold")

        risk = Decimal("0")
        reward = Decimal("0")
        if plan.side is Side.LONG:
            if not plan.stop < plan.entry < plan.target:
                reasons.append("long requires stop < entry < target")
            else:
                risk = plan.entry - plan.stop
                reward = plan.target - plan.entry
        elif plan.side is Side.SHORT:
            if not plan.target < plan.entry < plan.stop:
                reasons.append("short requires target < entry < stop")
            else:
                risk = plan.stop - plan.entry
                reward = plan.entry - plan.target

        rr = reward / risk if risk > 0 else Decimal("0")
        if risk > 0 and rr < self.minimum_reward_risk:
            reasons.append("reward/risk below threshold")

        maximum_loss = risk * max(plan.quantity, 0)

        if reasons:
            code = "decision_not_aligned"
            if any("confidence" in reason for reason in reasons):
                code = "low_confidence"
            elif any(
                key in reason
                for reason in reasons
                for key in (
                    "entry", "stop", "target", "quantity",
                    "symbol", "thesis", "reward/risk",
                )
            ):
                code = "invalid_trade_plan"
            return PlanDecision(
                False,
                Decision.WAIT,
                code,
                tuple(reasons),
                risk,
                reward,
                rr,
                maximum_loss,
            )

        return PlanDecision(
            True,
            Decision.TRADE,
            "ok",
            (),
            risk,
            reward,
            rr,
            maximum_loss,
        )
