"""One-way capital-floor governance.

This module solves a narrower problem than strategy selection: how much capital
may the trading subsystem be allowed to lose without crossing a protected
capital floor?

It does not claim that the protected asset itself is risk-free. The caller is
responsible for keeping protected_value in a genuinely segregated account or
instrument. The kernel simply refuses to make protected value available to the
trading sleeve.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..core.money import to_decimal


@dataclass(frozen=True)
class CapitalFloorConfig:
    """Immutable limits for the protected-principal layer."""

    protected_floor: Decimal
    max_risk_sleeve_fraction: Decimal = Decimal("0.05")
    profit_lock_fraction: Decimal = Decimal("0.75")

    def __post_init__(self) -> None:
        floor = to_decimal(self.protected_floor)
        sleeve = to_decimal(self.max_risk_sleeve_fraction)
        lock = to_decimal(self.profit_lock_fraction)
        object.__setattr__(self, "protected_floor", floor)
        object.__setattr__(self, "max_risk_sleeve_fraction", sleeve)
        object.__setattr__(self, "profit_lock_fraction", lock)

        if floor < 0:
            raise ValueError("protected_floor cannot be negative")
        if not Decimal("0") <= sleeve <= Decimal("1"):
            raise ValueError("max_risk_sleeve_fraction must be in [0, 1]")
        if not Decimal("0") <= lock <= Decimal("1"):
            raise ValueError("profit_lock_fraction must be in [0, 1]")


@dataclass(frozen=True)
class ProfitSplit:
    """How realised profit is divided between the vault and risk sleeve."""

    locked: Decimal
    recycled: Decimal


@dataclass(frozen=True)
class FloorDecision:
    """Result of evaluating a proposed addition to portfolio risk."""

    allowed: bool
    code: str
    detail: str
    nav: Decimal
    protected_floor: Decimal
    protected_value: Decimal
    free_surplus: Decimal
    sleeve_cap: Decimal
    committed_risk: Decimal
    available_risk: Decimal
    proposed_loss: Decimal


class CapitalFloorKernel:
    """Hard gate that no strategy or agent can override.

    protected_value is capital already segregated from trading. New risk is
    limited by BOTH the unprotected surplus and max_risk_sleeve_fraction of NAV.
    Existing committed loss budget is deducted before a new trade is considered.
    """

    def __init__(self, config: CapitalFloorConfig) -> None:
        self.config = config

    def capacity(
        self,
        *,
        nav: Decimal,
        protected_value: Decimal,
        committed_risk: Decimal = Decimal("0"),
        proposed_loss: Decimal = Decimal("0"),
    ) -> FloorDecision:
        nav = to_decimal(nav)
        protected = to_decimal(protected_value)
        committed = to_decimal(committed_risk)
        proposed = to_decimal(proposed_loss)

        if nav < 0 or protected < 0 or committed < 0 or proposed < 0:
            raise ValueError("capital and risk inputs cannot be negative")
        if protected > nav:
            return self._deny(
                "invalid_state",
                "protected value cannot exceed total NAV",
                nav,
                protected,
                committed,
                proposed,
            )
        if protected < self.config.protected_floor:
            return self._deny(
                "floor_underfunded",
                "protected value is below the configured floor",
                nav,
                protected,
                committed,
                proposed,
            )

        free_surplus = max(nav - protected, Decimal("0"))
        sleeve_cap = nav * self.config.max_risk_sleeve_fraction
        gross_capacity = min(free_surplus, sleeve_cap)
        available = max(gross_capacity - committed, Decimal("0"))

        if proposed > available:
            return FloorDecision(
                False,
                "risk_budget_exceeded",
                f"proposed loss {proposed} exceeds available risk {available}",
                nav,
                self.config.protected_floor,
                protected,
                free_surplus,
                sleeve_cap,
                committed,
                available,
                proposed,
            )

        return FloorDecision(
            True,
            "ok",
            "",
            nav,
            self.config.protected_floor,
            protected,
            free_surplus,
            sleeve_cap,
            committed,
            available,
            proposed,
        )

    def split_realised_profit(self, profit: Decimal) -> ProfitSplit:
        """Lock a fixed share of realised profit and recycle only the remainder."""

        realised = to_decimal(profit)
        if realised < 0:
            raise ValueError("losses are not profit and cannot be split for recycling")
        locked = realised * self.config.profit_lock_fraction
        return ProfitSplit(locked=locked, recycled=realised - locked)

    def _deny(
        self,
        code: str,
        detail: str,
        nav: Decimal,
        protected: Decimal,
        committed: Decimal,
        proposed: Decimal,
    ) -> FloorDecision:
        free_surplus = max(nav - protected, Decimal("0"))
        sleeve_cap = nav * self.config.max_risk_sleeve_fraction
        available = max(min(free_surplus, sleeve_cap) - committed, Decimal("0"))
        return FloorDecision(
            False,
            code,
            detail,
            nav,
            self.config.protected_floor,
            protected,
            free_surplus,
            sleeve_cap,
            committed,
            available,
            proposed,
        )
