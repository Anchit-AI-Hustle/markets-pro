"""Positions, tax lots and realized P&L.

Lots are matched **FIFO**, which is the default cost-basis method in the US
(absent a specific-lot election) and mandated in India. Average-cost matching
would produce a different — and in most jurisdictions incorrect — realized gain,
so the lot queue is kept explicitly rather than collapsed to an average.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.instrument import Instrument
from ..core.money import Money, to_decimal


@dataclass
class Lot:
    """One acquisition tranche: quantity, unit cost, and the day it was opened."""

    quantity: Decimal          # always positive; direction lives on the Position
    price: Decimal
    opened: date

    def __post_init__(self) -> None:
        self.quantity = to_decimal(self.quantity)
        self.price = to_decimal(self.price)
        if self.quantity <= 0:
            raise ValueError("lot quantity must be positive")


@dataclass
class FillResult:
    """Outcome of applying a fill to a position."""

    realized_pnl: Money
    closed_quantity: Decimal
    opened_quantity: Decimal
    flipped: bool = False


class Position:
    """Net position in one instrument, backed by a FIFO lot queue.

    A position is either flat, net long, or net short — never both at once. A
    fill large enough to cross through zero closes the existing side (realizing
    P&L) and opens the remainder on the other side, which is exactly how a
    broker would book it.
    """

    __slots__ = ("instrument", "_lots", "_direction", "realized")

    def __init__(self, instrument: Instrument) -> None:
        self.instrument = instrument
        self._lots: deque[Lot] = deque()
        self._direction = 0          # +1 long, -1 short, 0 flat
        self.realized = Money.zero(instrument.currency)

    # -- state -----------------------------------------------------------
    @property
    def quantity(self) -> Decimal:
        """Signed quantity: positive long, negative short, zero flat."""
        total = sum((lot.quantity for lot in self._lots), Decimal("0"))
        return total * self._direction

    @property
    def abs_quantity(self) -> Decimal:
        return sum((lot.quantity for lot in self._lots), Decimal("0"))

    @property
    def is_flat(self) -> bool:
        return not self._lots

    @property
    def is_long(self) -> bool:
        return self._direction > 0 and bool(self._lots)

    @property
    def is_short(self) -> bool:
        return self._direction < 0 and bool(self._lots)

    @property
    def lots(self) -> list[Lot]:
        return list(self._lots)

    @property
    def average_cost(self) -> Decimal:
        """Quantity-weighted average entry price; zero when flat."""
        qty = self.abs_quantity
        if qty == 0:
            return Decimal("0")
        gross = sum((lot.quantity * lot.price for lot in self._lots), Decimal("0"))
        return gross / qty

    @property
    def opened_on(self) -> date | None:
        """Open date of the oldest lot — the position's entry date."""
        return self._lots[0].opened if self._lots else None

    # -- valuation -------------------------------------------------------
    def market_value(self, price: Decimal) -> Money:
        """Signed mark-to-market value of the position."""
        value = self.instrument.contract_value(to_decimal(price), self.quantity)
        return Money(value, self.instrument.currency)

    def notional_exposure(self, price: Decimal) -> Money:
        """Absolute exposure, used for gross-leverage limits."""
        return abs(self.market_value(price))

    def unrealized_pnl(self, price: Decimal) -> Money:
        """Open P&L at ``price``, gross of any exit costs."""
        if self.is_flat:
            return Money.zero(self.instrument.currency)
        px = to_decimal(price)
        total = Decimal("0")
        for lot in self._lots:
            move = (px - lot.price) * self._direction
            total += move * lot.quantity * self.instrument.multiplier
        return Money(total, self.instrument.currency)

    def sellable_quantity(self, as_of: date, same_day_sell_allowed: bool) -> Decimal:
        """Quantity eligible to be closed on ``as_of``.

        Under a T+1 trading restriction (mainland China A-shares) lots opened
        today are locked until the next session, so they are excluded here.
        """
        if same_day_sell_allowed:
            return self.abs_quantity
        return sum(
            (lot.quantity for lot in self._lots if lot.opened < as_of),
            Decimal("0"),
        )

    # -- mutation --------------------------------------------------------
    def apply_fill(self, signed_quantity: Decimal, price: Decimal, day: date) -> FillResult:
        """Apply a signed fill and return the realized P&L it produced.

        Positive ``signed_quantity`` buys, negative sells. Fees are *not*
        deducted here — the portfolio owns cash and charges them separately, so
        that gross trading P&L and cost drag stay separable in reporting.
        """
        qty = to_decimal(signed_quantity)
        px = to_decimal(price)
        if qty == 0:
            return FillResult(Money.zero(self.instrument.currency), Decimal("0"), Decimal("0"))
        if px <= 0:
            raise ValueError(f"fill price must be positive, got {px}")

        incoming_dir = 1 if qty > 0 else -1
        remaining = abs(qty)

        if self.is_flat:
            self._direction = incoming_dir
            self._lots.append(Lot(remaining, px, day))
            return FillResult(
                Money.zero(self.instrument.currency), Decimal("0"), remaining
            )

        if incoming_dir == self._direction:
            self._lots.append(Lot(remaining, px, day))
            return FillResult(
                Money.zero(self.instrument.currency), Decimal("0"), remaining
            )

        # Opposing fill: consume lots FIFO, realizing P&L as we go.
        realized = Decimal("0")
        closed = Decimal("0")
        while remaining > 0 and self._lots:
            lot = self._lots[0]
            matched = min(lot.quantity, remaining)
            move = (px - lot.price) * self._direction
            realized += move * matched * self.instrument.multiplier
            closed += matched
            remaining -= matched
            lot.quantity -= matched
            if lot.quantity == 0:
                self._lots.popleft()

        flipped = False
        opened = Decimal("0")
        if not self._lots:
            self._direction = 0
            if remaining > 0:
                # Crossed through zero: open the residual on the other side.
                self._direction = incoming_dir
                self._lots.append(Lot(remaining, px, day))
                opened = remaining
                flipped = True

        realized_money = Money(realized, self.instrument.currency)
        self.realized = self.realized + realized_money
        return FillResult(realized_money, closed, opened, flipped)

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"Position({self.instrument.key} qty={self.quantity} "
            f"avg={self.average_cost})"
        )


@dataclass
class PositionSnapshot:
    """Immutable record of a position for reporting and equity attribution."""

    key: str
    symbol: str
    region: str
    currency: str
    quantity: Decimal
    average_cost: Decimal
    last_price: Decimal
    market_value: Money
    unrealized_pnl: Money
    realized_pnl: Money
    opened_on: date | None = None
    weight: float = 0.0
    extras: dict[str, object] = field(default_factory=dict)
