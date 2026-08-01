"""Instrument definitions: what can be traded and under what constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .money import round_to_increment, to_decimal


class AssetClass(str, Enum):
    """Asset classes the engine knows how to price and size."""

    EQUITY = "equity"
    ETF = "etf"
    FUTURE = "future"
    BOND = "bond"
    COMMODITY = "commodity"
    FX = "fx"
    CRYPTO = "crypto"


#: Asset classes that may legally be held short in a long/short account.
SHORTABLE = frozenset(
    {AssetClass.EQUITY, AssetClass.ETF, AssetClass.FUTURE, AssetClass.FX,
     AssetClass.COMMODITY}
)

#: Asset classes that trade in fractional units rather than whole shares.
FRACTIONAL = frozenset({AssetClass.CRYPTO, AssetClass.FX})


@dataclass(frozen=True)
class Instrument:
    """A single tradable instrument on a specific venue.

    ``tick_size`` and ``lot_size`` are exchange microstructure constraints: an
    order whose price is not a multiple of the tick, or whose quantity is not a
    multiple of the lot, would be rejected by a real venue. The engine enforces
    both so that backtested fills correspond to orders that could actually
    have been placed.
    """

    symbol: str
    region: str
    asset_class: AssetClass = AssetClass.EQUITY
    currency: str = "USD"
    tick_size: Decimal = Decimal("0.01")
    lot_size: Decimal = Decimal("1")
    multiplier: Decimal = Decimal("1")
    name: str = ""
    sector: str = "unknown"
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "region", self.region.upper())
        object.__setattr__(self, "currency", self.currency.upper())
        object.__setattr__(self, "tick_size", to_decimal(self.tick_size))
        object.__setattr__(self, "lot_size", to_decimal(self.lot_size))
        object.__setattr__(self, "multiplier", to_decimal(self.multiplier))
        if self.tick_size <= 0:
            raise ValueError(f"{self.symbol}: tick_size must be positive")
        if self.lot_size <= 0:
            raise ValueError(f"{self.symbol}: lot_size must be positive")
        if self.multiplier <= 0:
            raise ValueError(f"{self.symbol}: multiplier must be positive")

    @property
    def key(self) -> str:
        """Globally unique identifier, e.g. ``NSE:RELIANCE`` style ``IN:RELIANCE``."""
        return f"{self.region}:{self.symbol}"

    @property
    def is_shortable(self) -> bool:
        return self.asset_class in SHORTABLE

    @property
    def is_fractional(self) -> bool:
        return self.asset_class in FRACTIONAL

    def round_price(self, price: Decimal) -> Decimal:
        """Snap a price to the instrument's tick grid."""
        return round_to_increment(to_decimal(price), self.tick_size)

    def contract_value(self, price: Decimal, quantity: Decimal) -> Decimal:
        """Notional value of ``quantity`` units at ``price``, including multiplier."""
        return to_decimal(price) * to_decimal(quantity) * self.multiplier
