"""Position sizing.

Sizing is where most of the realised risk in a strategy actually lives. A good
signal sized badly loses money; a mediocre signal sized well survives. Three
methods are provided, all of which floor to the exchange lot size and refuse to
exceed available cash:

* **Fixed-fractional risk** — risk a constant fraction of equity per trade,
  derived from the distance to the stop. This is the short-term book's method.
* **Volatility targeting** — size inversely to ATR so each position contributes
  a comparable amount of risk regardless of how volatile the instrument is.
* **Target weight** — size to a fraction of portfolio value. This is the
  long-term book's method.

A capped **fractional Kelly** multiplier is available to scale conviction, but is
clamped hard. Full Kelly is the growth-optimal bet only if your edge estimate is
exact; it is not, and full Kelly on an overestimated edge is ruinous.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..core.instrument import Instrument
from ..core.money import Money, floor_to_increment, to_decimal


@dataclass(frozen=True)
class SizingResult:
    """A sizing decision, including why it landed where it did."""

    quantity: Decimal
    notional: Decimal
    reason: str = "ok"

    @property
    def is_tradable(self) -> bool:
        return self.quantity > 0


@dataclass(frozen=True)
class SizingConfig:
    """Bounds applied to every sizing decision."""

    #: Fraction of equity risked on a single short-term trade (loss at stop).
    risk_per_trade: Decimal = Decimal("0.01")
    #: Hard ceiling on any single position as a fraction of equity.
    max_position_weight: Decimal = Decimal("0.10")
    #: Orders below this notional are skipped — fixed fees would dominate.
    min_order_notional: Decimal = Decimal("100")
    #: Fraction of available cash a single order may consume.
    max_cash_utilisation: Decimal = Decimal("0.95")
    #: Cap on the participation rate against average daily volume.
    max_volume_participation: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        if not (0 < self.risk_per_trade <= 1):
            raise ValueError("risk_per_trade must be in (0, 1]")
        if not (0 < self.max_position_weight <= 1):
            raise ValueError("max_position_weight must be in (0, 1]")


def _lot_floor(instrument: Instrument, quantity: Decimal) -> Decimal:
    """Round a raw quantity down to a tradable multiple of the lot size."""
    if instrument.is_fractional:
        return to_decimal(quantity)
    return floor_to_increment(to_decimal(quantity), instrument.lot_size)


def risk_based_quantity(
    instrument: Instrument,
    equity: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    config: SizingConfig,
) -> Decimal:
    """Quantity such that a move from ``entry_price`` to ``stop_price`` costs
    exactly ``risk_per_trade`` of equity (before rounding down to a lot).
    """
    entry = to_decimal(entry_price)
    stop = to_decimal(stop_price)
    per_unit_risk = abs(entry - stop) * instrument.multiplier
    if per_unit_risk <= 0:
        return Decimal("0")
    risk_budget = to_decimal(equity) * config.risk_per_trade
    return _lot_floor(instrument, risk_budget / per_unit_risk)


def volatility_target_quantity(
    instrument: Instrument,
    equity: Decimal,
    price: Decimal,
    atr_value: Decimal,
    target_risk_fraction: Decimal,
    atr_multiple: Decimal = Decimal("2"),
) -> Decimal:
    """Size so that an ``atr_multiple``-ATR adverse move costs a fixed fraction.

    Equivalent to risk-based sizing with the stop placed ``atr_multiple`` ATRs
    away, expressed separately because the long-term book uses it without ever
    placing a hard stop order.
    """
    atr_value = to_decimal(atr_value)
    if atr_value <= 0:
        return Decimal("0")
    risk_budget = to_decimal(equity) * to_decimal(target_risk_fraction)
    per_unit_risk = atr_value * to_decimal(atr_multiple) * instrument.multiplier
    if per_unit_risk <= 0:
        return Decimal("0")
    return _lot_floor(instrument, risk_budget / per_unit_risk)


def weight_based_quantity(
    instrument: Instrument,
    equity: Decimal,
    price: Decimal,
    target_weight: Decimal,
) -> Decimal:
    """Quantity whose notional is ``target_weight`` of ``equity``."""
    px = to_decimal(price)
    if px <= 0:
        return Decimal("0")
    target_notional = to_decimal(equity) * to_decimal(target_weight)
    if target_notional <= 0:
        return Decimal("0")
    return _lot_floor(instrument, target_notional / (px * instrument.multiplier))


def kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    *,
    cap: float = 0.25,
) -> float:
    """Fractional Kelly, clamped to ``[0, cap]``.

    ``f* = p - (1 - p) / R`` where ``R = avg_win / avg_loss``. A non-positive
    result means the edge does not justify a bet, and returns 0. The clamp is
    not conservatism for its own sake: Kelly assumes the edge is known exactly,
    and an overestimate produces a bet size that compounds to ruin.
    """
    if not (0 <= win_rate <= 1):
        raise ValueError("win_rate must be in [0, 1]")
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    payoff = avg_win / avg_loss
    f = win_rate - (1 - win_rate) / payoff
    return max(0.0, min(f, cap))


def apply_constraints(
    instrument: Instrument,
    quantity: Decimal,
    price: Decimal,
    equity: Decimal,
    available_cash: Decimal,
    config: SizingConfig,
    average_volume: Decimal | None = None,
) -> SizingResult:
    """Clamp a raw quantity to every hard limit, reporting which one bound.

    Order of application matters: the tightest constraint must win, so each is
    applied in turn and the reason recorded whenever a clamp actually bites.
    """
    qty = _lot_floor(instrument, to_decimal(quantity))
    px = to_decimal(price)
    if qty <= 0 or px <= 0:
        return SizingResult(Decimal("0"), Decimal("0"), "zero_quantity")

    reason = "ok"

    # 1. Single-position weight ceiling.
    max_notional = to_decimal(equity) * config.max_position_weight
    if instrument.contract_value(px, qty) > max_notional:
        qty = _lot_floor(instrument, max_notional / (px * instrument.multiplier))
        reason = "max_position_weight"

    # 2. Available cash.
    spendable = to_decimal(available_cash) * config.max_cash_utilisation
    if qty > 0 and instrument.contract_value(px, qty) > spendable:
        qty = _lot_floor(instrument, spendable / (px * instrument.multiplier))
        reason = "cash_constrained"

    # 3. Liquidity: never assume you can trade more than a slice of daily volume.
    if average_volume is not None and to_decimal(average_volume) > 0:
        cap = _lot_floor(
            instrument, to_decimal(average_volume) * config.max_volume_participation
        )
        if qty > cap:
            qty = cap
            reason = "liquidity_capped"

    if qty <= 0:
        outcome = reason if reason != "ok" else "zero_quantity"
        return SizingResult(Decimal("0"), Decimal("0"), outcome)

    notional = instrument.contract_value(px, qty)

    # 4. Economic minimum — below this, fixed costs swamp any edge.
    if notional < config.min_order_notional:
        return SizingResult(Decimal("0"), Decimal("0"), "below_min_notional")

    return SizingResult(qty, notional, reason)


def size_order(
    instrument: Instrument,
    *,
    equity: Money,
    available_cash: Money,
    price: Decimal,
    config: SizingConfig,
    stop_price: Decimal | None = None,
    target_weight: Decimal | None = None,
    atr_value: Decimal | None = None,
    average_volume: Decimal | None = None,
    conviction: Decimal = Decimal("1"),
) -> SizingResult:
    """Front door for sizing: pick a method from the inputs, then clamp.

    Precedence is explicit — a stop distance is the most informative input, then
    a target weight, then ATR. ``conviction`` scales the raw size before
    constraints and is expected to be in ``(0, 1]``.
    """
    eq = equity.amount
    if eq <= 0:
        return SizingResult(Decimal("0"), Decimal("0"), "no_equity")

    if stop_price is not None:
        raw = risk_based_quantity(instrument, eq, price, stop_price, config)
    elif target_weight is not None:
        raw = weight_based_quantity(instrument, eq, price, target_weight)
    elif atr_value is not None:
        raw = volatility_target_quantity(
            instrument, eq, price, atr_value, config.risk_per_trade
        )
    else:
        return SizingResult(Decimal("0"), Decimal("0"), "no_sizing_basis")

    raw = raw * to_decimal(conviction)
    return apply_constraints(
        instrument, raw, price, eq, available_cash.amount, config, average_volume
    )
