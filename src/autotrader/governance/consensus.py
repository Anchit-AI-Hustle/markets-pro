"""Deterministic consensus gate for independent research desks.

Agents may research and express views; this module owns the final mechanical
rule. A missing mandatory desk, degraded input, veto, or directional conflict
returns WAIT. No language-model confidence score can override the gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VoteState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"


class Stance(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    WAIT = "wait"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class DeskVote:
    desk: str
    state: VoteState
    stance: Stance = Stance.NEUTRAL
    reason: str = ""


@dataclass(frozen=True)
class ConsensusDecision:
    allowed: bool
    action: str
    code: str
    reasons: tuple[str, ...]


class ConsensusKernel:
    """Fail-closed vote aggregation."""

    DEFAULT_REQUIRED = (
        "data",
        "risk",
        "liquidity",
        "portfolio",
        "execution",
        "red_team",
    )

    def __init__(self, required_desks: tuple[str, ...] | None = None) -> None:
        self.required_desks = required_desks or self.DEFAULT_REQUIRED

    def evaluate(
        self,
        votes: list[DeskVote] | tuple[DeskVote, ...],
        *,
        proposed_action: Stance,
    ) -> ConsensusDecision:
        if proposed_action not in (Stance.BUY, Stance.SELL):
            raise ValueError("proposed_action must be BUY or SELL")

        by_desk: dict[str, DeskVote] = {}
        for vote in votes:
            if vote.desk in by_desk:
                raise ValueError(f"duplicate vote from desk: {vote.desk}")
            by_desk[vote.desk] = vote

        missing = [desk for desk in self.required_desks if desk not in by_desk]
        if missing:
            return ConsensusDecision(
                False,
                "WAIT",
                "missing_required_desk",
                tuple(f"missing {desk}" for desk in missing),
            )

        blocked = [
            vote for vote in votes
            if vote.state in (VoteState.FAIL, VoteState.UNAVAILABLE)
        ]
        if blocked:
            return ConsensusDecision(
                False,
                "WAIT",
                "veto",
                tuple(
                    f"{vote.desk}: {vote.state.value}"
                    + (f" - {vote.reason}" if vote.reason else "")
                    for vote in blocked
                ),
            )

        conflicts = [
            vote for vote in votes
            if vote.stance in (Stance.BUY, Stance.SELL, Stance.HOLD, Stance.WAIT)
            and vote.stance is not proposed_action
        ]
        if conflicts:
            return ConsensusDecision(
                False,
                "WAIT",
                "conflicting_signal",
                tuple(
                    f"{vote.desk}: {vote.stance.value}"
                    + (f" - {vote.reason}" if vote.reason else "")
                    for vote in conflicts
                ),
            )

        return ConsensusDecision(True, "APPROVE", "ok", ())
