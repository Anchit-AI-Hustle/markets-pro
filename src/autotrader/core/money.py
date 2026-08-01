"""Exact monetary arithmetic.

All accounting in this system is done in :class:`decimal.Decimal`. Float is used
only for statistics (returns, volatility, Sharpe) where it is harmless. Money is
never represented as a float, because ``0.1 + 0.2 != 0.3`` is not an acceptable
property for a ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext
from typing import Iterable, Mapping

# Number of minor units (decimal places) each currency is quoted in.
CURRENCY_PRECISION: dict[str, int] = {
    "INR": 2,
    "USD": 2,
    "RUB": 2,
    "CNY": 2,
    "HKD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,
}


class CurrencyMismatch(ValueError):
    """Raised when two amounts in different currencies are combined."""


def to_decimal(value: object) -> Decimal:
    """Coerce ``value`` to ``Decimal`` without ever routing through binary float.

    Floats are converted via ``str`` so that ``to_decimal(0.1)`` is exactly
    ``Decimal("0.1")`` and not ``0.1000000000000000055511151231257827``.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"cannot convert {type(value).__name__} to Decimal")


@dataclass(frozen=True, order=False)
class Money:
    """An exact amount in a single currency.

    ``Money`` is immutable and refuses to combine mismatched currencies, which
    makes cross-currency accounting bugs impossible to express rather than
    merely unlikely.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", to_decimal(self.amount))
        object.__setattr__(self, "currency", self.currency.upper())
        if self.currency not in CURRENCY_PRECISION:
            raise ValueError(f"unknown currency: {self.currency}")

    # -- construction ----------------------------------------------------
    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(Decimal("0"), currency)

    # -- guards ----------------------------------------------------------
    def _check(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"cannot combine {self.currency} with {other.currency}"
            )

    # -- arithmetic ------------------------------------------------------
    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def __abs__(self) -> "Money":
        return Money(abs(self.amount), self.currency)

    def __mul__(self, factor: object) -> "Money":
        return Money(self.amount * to_decimal(factor), self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor: object) -> "Money":
        d = to_decimal(divisor)
        if d == 0:
            raise ZeroDivisionError("division of Money by zero")
        return Money(self.amount / d, self.currency)

    # -- comparison ------------------------------------------------------
    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount >= other.amount

    # -- helpers ---------------------------------------------------------
    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def quantized(self) -> "Money":
        """Round to the currency's minor unit, half-up (the banking default)."""
        places = CURRENCY_PRECISION[self.currency]
        exp = Decimal(1).scaleb(-places)
        return Money(self.amount.quantize(exp, rounding=ROUND_HALF_UP), self.currency)

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.quantized().amount} {self.currency}"


def sum_money(items: Iterable[Money], currency: str) -> Money:
    """Sum an iterable of ``Money``, returning zero in ``currency`` when empty."""
    total = Money.zero(currency)
    for item in items:
        total = total + item
    return total


@dataclass(frozen=True)
class FXRates:
    """Spot FX rates expressed as *units of quote per one unit of base*.

    A rate stored under ``("USD", "INR")`` with value ``83`` means one US dollar
    buys 83 rupees. Inverse pairs are derived automatically, so only one
    direction needs to be supplied.
    """

    base: str
    rates: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", self.base.upper())
        cleaned = {k.upper(): to_decimal(v) for k, v in self.rates.items()}
        cleaned.setdefault(self.base, Decimal("1"))
        for code, rate in cleaned.items():
            if code not in CURRENCY_PRECISION:
                raise ValueError(f"unknown currency in FX table: {code}")
            if rate <= 0:
                raise ValueError(f"FX rate for {code} must be positive, got {rate}")
        object.__setattr__(self, "rates", cleaned)

    def rate(self, frm: str, to: str) -> Decimal:
        """Return the multiplier that converts one unit of ``frm`` into ``to``."""
        frm, to = frm.upper(), to.upper()
        if frm == to:
            return Decimal("1")
        try:
            per_base_from = self.rates[frm]
            per_base_to = self.rates[to]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"no FX rate available for {exc.args[0]}") from exc
        # rates[X] = units of X per 1 unit of `base`.
        with localcontext() as ctx:
            ctx.prec = 28
            return per_base_to / per_base_from

    def convert(self, money: Money, to: str) -> Money:
        """Convert ``money`` into currency ``to`` at the stored spot rate."""
        return Money(money.amount * self.rate(money.currency, to), to)


def round_to_increment(
    value: Decimal, increment: Decimal, mode: str = ROUND_HALF_UP
) -> Decimal:
    """Round ``value`` to the nearest multiple of ``increment``.

    Used for exchange tick sizes (price) and lot sizes (quantity). ``increment``
    of zero means "no constraint" and returns the value untouched.
    """
    increment = to_decimal(increment)
    if increment <= 0:
        return to_decimal(value)
    value = to_decimal(value)
    steps = (value / increment).quantize(Decimal("1"), rounding=mode)
    return (steps * increment).normalize() + Decimal("0")


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Round ``value`` *down* to a multiple of ``increment`` (never overspend)."""
    return round_to_increment(value, increment, mode=ROUND_DOWN)
