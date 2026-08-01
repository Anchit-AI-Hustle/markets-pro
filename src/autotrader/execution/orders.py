"""Order types and validation."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from ..core.instrument import Instrument
from ..core.money import to_decimal


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class TimeInForce(str, Enum):
    DAY = "day"          # cancelled if unfilled at the close
    GTC = "gtc"          # rests until filled or explicitly cancelled


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Horizon(str, Enum):
    """Which book an order belongs to.

    The two books are accounted and risk-limited separately: long-term holdings
    are rebalanced on a schedule and sized by target weight, short-term trades
    are sized by stop distance and carry a hard time-based exit.
    """

    LONG_TERM = "long_term"
    SHORT_TERM = "short_term"


_ORDER_IDS = itertools.count(1)


@dataclass
class Order:
    """An instruction to trade, before it reaches the venue."""

    instrument: Instrument
    side: Side
    quantity: Decimal
    horizon: Horizon = Horizon.SHORT_TERM
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    created_on: date | None = None
    reason: str = ""
    order_id: int = field(default_factory=lambda: next(_ORDER_IDS))
    #: Protective levels carried alongside the entry, applied once filled.
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    max_holding_days: int | None = None

    def __post_init__(self) -> None:
        self.quantity = to_decimal(self.quantity)
        if self.quantity <= 0:
            raise ValueError(
                f"order quantity must be positive; use side to express direction "
                f"(got {self.quantity})"
            )
        for name in ("limit_price", "stop_price", "stop_loss", "take_profit"):
            value = getattr(self, name)
            if value is not None:
                value = to_decimal(value)
                if value <= 0:
                    raise ValueError(f"{name} must be positive, got {value}")
                setattr(self, name, value)

        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit order requires a limit_price")
        if self.order_type is OrderType.STOP and self.stop_price is None:
            raise ValueError("stop order requires a stop_price")
        if self.quantity % self.instrument.lot_size != 0:
            raise ValueError(
                f"{self.instrument.key}: quantity {self.quantity} is not a "
                f"multiple of lot size {self.instrument.lot_size}"
            )

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity * self.side.sign

    @property
    def is_entry(self) -> bool:
        return self.stop_loss is not None or self.take_profit is not None


@dataclass(frozen=True)
class Rejection:
    """Why the venue refused an order. Rejections are recorded, never silent."""

    order: Order
    code: str
    detail: str


@dataclass(frozen=True)
class Fill:
    """A completed execution, priced net of slippage and with costs attached."""

    order_id: int
    instrument: Instrument
    side: Side
    quantity: Decimal
    price: Decimal
    day: date
    horizon: Horizon
    commission: Decimal
    taxes: Decimal
    fees: Decimal
    slippage_per_unit: Decimal
    reason: str = ""

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity * self.side.sign

    @property
    def gross_value(self) -> Decimal:
        return self.instrument.contract_value(self.price, self.quantity)

    @property
    def total_cost(self) -> Decimal:
        return self.commission + self.taxes + self.fees

    @property
    def cash_delta(self) -> Decimal:
        """Signed change to cash: buys pay out, sells take in, costs always out."""
        return -self.gross_value * self.side.sign - self.total_cost
