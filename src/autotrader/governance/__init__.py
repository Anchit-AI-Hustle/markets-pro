"""Deterministic governance above strategy, sizing, risk, and execution.

The objects in this package deliberately do not place orders. They decide
whether a proposed trade is even eligible to reach the existing risk/execution
stack.
"""

from .consensus import (
    ConsensusDecision,
    ConsensusKernel,
    DeskVote,
    Stance,
    VoteState,
)
from .floor import (
    CapitalFloorConfig,
    CapitalFloorKernel,
    FloorDecision,
    ProfitSplit,
)

__all__ = [
    "CapitalFloorConfig",
    "CapitalFloorKernel",
    "ConsensusDecision",
    "ConsensusKernel",
    "DeskVote",
    "FloorDecision",
    "ProfitSplit",
    "Stance",
    "VoteState",
]
