"""Regional market specifications.

Each market has rules that materially change what a strategy is allowed to do.
Ignoring them is the single most common way a backtest produces returns that
cannot be reproduced live. The ones modelled here:

* **Settlement / same-day sell.** Mainland China A-shares are T+1: shares bought
  today cannot be sold today. A backtest that ignores this will happily book
  intraday round trips that the exchange would have rejected.
* **Daily price limits.** China caps daily moves at +/-10% (20% on STAR and
  ChiNext); India applies circuit bands; the US has LULD halts. Orders through a
  limit do not fill.
* **Lot sizes.** China trades in board lots of 100 shares on the buy side. An
  order for 137 shares is not a valid order.
* **Short selling.** Restricted or effectively unavailable in several venues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import Mapping

from .money import to_decimal


@dataclass(frozen=True)
class MarketSpec:
    """Microstructure and regulatory rules for one regional market."""

    code: str
    name: str
    currency: str
    timezone: str
    open_time: time
    close_time: time
    default_tick_size: Decimal
    default_lot_size: Decimal
    settlement_days: int
    same_day_sell_allowed: bool
    short_selling_allowed: bool
    daily_price_limit_pct: Decimal | None
    holidays: frozenset[date] = field(default_factory=frozenset)
    #: Weekday numbers (Mon=0) on which the venue does not trade.
    weekend_days: frozenset[int] = frozenset({5, 6})

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", self.code.upper())
        object.__setattr__(self, "currency", self.currency.upper())
        object.__setattr__(self, "default_tick_size", to_decimal(self.default_tick_size))
        object.__setattr__(self, "default_lot_size", to_decimal(self.default_lot_size))
        if self.daily_price_limit_pct is not None:
            object.__setattr__(
                self, "daily_price_limit_pct", to_decimal(self.daily_price_limit_pct)
            )
        if self.settlement_days < 0:
            raise ValueError("settlement_days cannot be negative")

    def price_limits(self, reference_close: Decimal) -> tuple[Decimal, Decimal] | None:
        """Return ``(lower, upper)`` tradable bounds for the session.

        ``reference_close`` is the prior session's official close. Returns
        ``None`` when the venue imposes no hard daily limit.
        """
        if self.daily_price_limit_pct is None:
            return None
        ref = to_decimal(reference_close)
        band = ref * self.daily_price_limit_pct
        return (ref - band, ref + band)

    def is_within_limits(self, price: Decimal, reference_close: Decimal) -> bool:
        """True when ``price`` is tradable given the prior close."""
        limits = self.price_limits(reference_close)
        if limits is None:
            return True
        lower, upper = limits
        return lower <= to_decimal(price) <= upper


# --------------------------------------------------------------------------
# Built-in regional registry.
#
# Holiday sets are intentionally left empty here and injected by the data layer;
# hard-coding a partial holiday calendar is worse than none, because it silently
# looks authoritative. `TradingCalendar` handles weekends correctly regardless.
# --------------------------------------------------------------------------

INDIA = MarketSpec(
    code="IN",
    name="India (NSE/BSE)",
    currency="INR",
    timezone="Asia/Kolkata",
    open_time=time(9, 15),
    close_time=time(15, 30),
    default_tick_size=Decimal("0.05"),
    default_lot_size=Decimal("1"),
    settlement_days=1,
    same_day_sell_allowed=True,      # intraday (MIS) round trips are permitted
    short_selling_allowed=True,      # intraday only for retail; see RiskManager
    daily_price_limit_pct=Decimal("0.20"),
)

UNITED_STATES = MarketSpec(
    code="US",
    name="United States (NYSE/NASDAQ)",
    currency="USD",
    timezone="America/New_York",
    open_time=time(9, 30),
    close_time=time(16, 0),
    default_tick_size=Decimal("0.01"),
    default_lot_size=Decimal("1"),
    settlement_days=1,
    same_day_sell_allowed=True,
    short_selling_allowed=True,
    daily_price_limit_pct=None,      # LULD halts rather than a fixed daily band
)

RUSSIA = MarketSpec(
    code="RU",
    name="Russia (MOEX)",
    currency="RUB",
    timezone="Europe/Moscow",
    open_time=time(10, 0),
    close_time=time(18, 40),
    default_tick_size=Decimal("0.01"),
    default_lot_size=Decimal("1"),
    settlement_days=1,
    same_day_sell_allowed=True,
    short_selling_allowed=False,     # restricted; treated as unavailable
    daily_price_limit_pct=Decimal("0.20"),
)

CHINA = MarketSpec(
    code="CN",
    name="China (SSE/SZSE)",
    currency="CNY",
    timezone="Asia/Shanghai",
    open_time=time(9, 30),
    close_time=time(15, 0),
    default_tick_size=Decimal("0.01"),
    default_lot_size=Decimal("100"),  # board lot
    settlement_days=1,
    same_day_sell_allowed=False,      # T+1: cannot sell what you bought today
    short_selling_allowed=False,
    daily_price_limit_pct=Decimal("0.10"),
)

HONG_KONG = MarketSpec(
    code="HK",
    name="Hong Kong (HKEX)",
    currency="HKD",
    timezone="Asia/Hong_Kong",
    open_time=time(9, 30),
    close_time=time(16, 0),
    default_tick_size=Decimal("0.01"),
    default_lot_size=Decimal("100"),
    settlement_days=2,
    same_day_sell_allowed=True,
    short_selling_allowed=True,
    daily_price_limit_pct=None,
)


_REGISTRY: dict[str, MarketSpec] = {
    m.code: m for m in (INDIA, UNITED_STATES, RUSSIA, CHINA, HONG_KONG)
}


def get_market(code: str) -> MarketSpec:
    """Look up a market by region code, e.g. ``"IN"``."""
    try:
        return _REGISTRY[code.upper()]
    except KeyError:
        raise KeyError(
            f"unknown market {code!r}; known: {sorted(_REGISTRY)}"
        ) from None


def register_market(spec: MarketSpec) -> None:
    """Add or replace a market in the registry (for venues not shipped here)."""
    _REGISTRY[spec.code] = spec


def all_markets() -> Mapping[str, MarketSpec]:
    return dict(_REGISTRY)


def with_holidays(spec: MarketSpec, holidays: set[date]) -> MarketSpec:
    """Return a copy of ``spec`` with an exchange holiday calendar attached."""
    return MarketSpec(
        code=spec.code,
        name=spec.name,
        currency=spec.currency,
        timezone=spec.timezone,
        open_time=spec.open_time,
        close_time=spec.close_time,
        default_tick_size=spec.default_tick_size,
        default_lot_size=spec.default_lot_size,
        settlement_days=spec.settlement_days,
        same_day_sell_allowed=spec.same_day_sell_allowed,
        short_selling_allowed=spec.short_selling_allowed,
        daily_price_limit_pct=spec.daily_price_limit_pct,
        holidays=frozenset(holidays),
        weekend_days=spec.weekend_days,
    )
