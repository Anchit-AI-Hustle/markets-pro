"""Refuse to suggest a trade from a rule this project measured as having no edge.

The evidence study tests every (instrument, rule) pair over twenty years and
files a verdict. Nothing consulted it. The study ran, the Evidence tab
published "no demonstrated edge", and the suggestion engine went on proposing
trades from those same rules — the one number the product is built on had no
effect on the product.

This gate closes that. A rule that failed on an instrument, or was never
shown to work on it, does not get to suggest a trade in it.

What it is not: a promise that permitted trades win. A verdict is a statement
about the past of one rule on one name, and 48.6 of the 972 verdicts are
expected to be flukes of multiple testing. The gate removes trades the
evidence argues against; it cannot add an edge that the study did not find.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Strongest first. ``evidence`` cleared the significance bar after the
#: false-positive budget; ``profitable_but_unproven`` made money without
#: clearing it; ``no_edge`` was tested and failed; ``insufficient`` never had
#: enough trades to judge, which is not the same as passing.
VERDICT_ORDER: tuple[str, ...] = (
    "evidence",
    "profitable_but_unproven",
    "no_edge",
    "insufficient",
)
_RANK = {v: len(VERDICT_ORDER) - i for i, v in enumerate(VERDICT_ORDER)}


def logic_for(horizon: str, reason: str) -> str | None:
    """Which studied rule produced this signal, or None if it maps to none.

    The study's three logics are each a strategy configured down to one
    behaviour, so the mapping has to be made from what the live signal says
    about itself. An unrecognised signal returns None and is treated as
    ungated rather than silently assigned to a rule it did not come from.
    """
    horizon = (horizon or "").lower()
    reason = (reason or "").strip().lower()
    if horizon in ("long_term", "longterm", "long"):
        return "momentum"
    if reason.startswith("pullback"):
        return "pullback"
    if reason.startswith("breakout"):
        return "breakout"
    return None


def load_verdicts(path: Path | str) -> dict[tuple[str, str], str]:
    """Map ``(instrument key, logic) -> verdict`` from a fitness study."""
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text())
    except (ValueError, OSError):
        return {}
    out: dict[tuple[str, str], str] = {}
    for key, record in (raw.get("results") or {}).items():
        for entry in record.get("logics") or []:
            logic, verdict = entry.get("logic"), entry.get("verdict")
            if logic and verdict:
                out[(key, logic)] = verdict
    return out


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    verdict: str
    reason: str


class EvidenceGate:
    """Allows a signal only if its rule met ``minimum`` on that instrument."""

    def __init__(
        self,
        verdicts: dict[tuple[str, str], str] | None = None,
        *,
        minimum: str = "evidence",
        enabled: bool = True,
    ) -> None:
        if minimum not in _RANK:
            raise ValueError(f"minimum must be one of {VERDICT_ORDER}, got {minimum!r}")
        self.verdicts = verdicts or {}
        self.minimum = minimum
        self.enabled = enabled

    @classmethod
    def from_study(cls, path: Path | str, **kw) -> EvidenceGate:
        return cls(load_verdicts(path), **kw)

    def evaluate(self, key: str, horizon: str, reason: str) -> GateDecision:
        if not self.enabled:
            return GateDecision(True, "", "evidence gate off")
        logic = logic_for(horizon, reason)
        if logic is None:
            # Not one of the studied rules, so the study says nothing about
            # it. Blocking here would be the gate inventing a verdict.
            return GateDecision(True, "", "not a studied rule")
        verdict = self.verdicts.get((key, logic))
        if verdict is None:
            return GateDecision(
                False, "untested",
                f"{logic} has never been tested on {key}",
            )
        if _RANK.get(verdict, 0) >= _RANK[self.minimum]:
            return GateDecision(True, verdict, f"{logic} on {key}: {verdict}")
        return GateDecision(
            False, verdict,
            f"{logic} on {key} is '{verdict}', below the required '{self.minimum}'",
        )
