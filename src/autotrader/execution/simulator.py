"""Fill simulation.

The central rule: **an order decided using data up to the close of day D fills at
the open of day D+1.** Filling at day D's close — a very common shortcut — hands
the strategy a price it could not have traded at, because the decision required
that same close to exist. Everything else here is an attempt to make the fill
price achievable rather than optimistic:

* slippage always moves against the order;
* orders through a daily price limit are rejected, not filled;
* size is capped at a fraction of that session's volume;
* the fill price is snapped to the exchange tick grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.market import MarketSpec
from ..core.money import to_decimal
from ..data.bars import Bar
from .costs import CostModel, SlippageModel, get_cost_model
from .orders import Fill, Order, OrderType, Rejection, Side


@dataclass
class ExecutionConfig:
    """Knobs governing how orders are turned into fills."""

    #: Cap on the fraction of a session's volume a single order may take.
    max_volume_participation: Decimal = Decimal("0.10")
    #: Reject rather than partially fill when volume is insufficient.
    reject_on_insufficient_volume: bool = False
    #: Treat same-session round trips as intraday for tax purposes.
    intraday_tax_treatment: bool = False

    def __post_init__(self) -> None:
        self.max_volume_participation = to_decimal(self.max_volume_participation)


class ExecutionSimulator:
    """Turns orders into fills against a bar, or explains why they failed."""

    def __init__(
        self,
        slippage: SlippageModel | None = None,
        config: ExecutionConfig | None = None,
    ) -> None:
        self.slippage = slippage or SlippageModel()
        self.config = config or ExecutionConfig()

    # -- public ----------------------------------------------------------
    def execute(
        self,
        order: Order,
        bar: Bar,
        *,
        market: MarketSpec,
        previous_close: Decimal | None = None,
        average_volume: Decimal | None = None,
        cost_model: CostModel | None = None,
        intraday: bool = False,
    ) -> Fill | Rejection:
        """Attempt to fill ``order`` against ``bar`` (the *next* session's bar)."""
        instrument = order.instrument

        trigger = self._reference_price(order, bar)
        if trigger is None:
            return Rejection(
                order, "not_triggered",
                f"{order.order_type.value} order did not trigger within "
                f"[{bar.low}, {bar.high}] on {bar.day}",
            )

        quantity, volume_note = self._cap_quantity(order, bar, average_volume)
        if quantity <= 0:
            return Rejection(
                order, "no_liquidity",
                f"session volume {bar.volume} cannot support order on {bar.day}",
            )
        if volume_note and self.config.reject_on_insufficient_volume:
            return Rejection(order, "insufficient_volume", volume_note)

        reference_volume = (
            to_decimal(average_volume) if average_volume is not None else bar.volume
        )
        raw_price = self.slippage.apply(
            trigger, order.side, quantity, reference_volume
        )
        fill_price = instrument.round_price(raw_price)

        # A tick-rounded price can land outside the bar; clamp it back inside so
        # the fill remains a price that actually traded.
        fill_price = max(bar.low, min(bar.high, fill_price))
        if fill_price <= 0:
            return Rejection(order, "invalid_price", f"computed fill price {fill_price}")

        if previous_close is not None and not market.is_within_limits(
            fill_price, previous_close
        ):
            limits = market.price_limits(to_decimal(previous_close))
            return Rejection(
                order, "price_limit",
                f"{fill_price} outside {market.code} daily band {limits} "
                f"(prior close {previous_close})",
            )

        model = cost_model or get_cost_model(instrument.region)
        costs = model.compute(
            instrument, order.side, quantity, fill_price,
            intraday=intraday or self.config.intraday_tax_treatment,
        )

        return Fill(
            order_id=order.order_id,
            instrument=instrument,
            side=order.side,
            quantity=quantity,
            price=fill_price,
            day=bar.day,
            horizon=order.horizon,
            commission=costs.commission,
            taxes=costs.taxes,
            fees=costs.fees,
            slippage_per_unit=abs(fill_price - to_decimal(trigger)),
            reason=order.reason,
        )

    def execute_at_price(
        self,
        order: Order,
        price: Decimal,
        day: date,
        *,
        market: MarketSpec,
        cost_model: CostModel | None = None,
        average_volume: Decimal | None = None,
        intraday: bool = False,
        apply_slippage: bool = True,
    ) -> Fill:
        """Fill at a known price — used for stop and target exits.

        The exit level is already determined by :mod:`autotrader.risk.exits`;
        this only applies slippage and costs on top of it. Exits are never
        rejected for liquidity, because a position that cannot be exited is not
        a position the risk model can reason about.
        """
        instrument = order.instrument
        px = to_decimal(price)
        if apply_slippage:
            px = self.slippage.apply(
                px, order.side, order.quantity,
                to_decimal(average_volume) if average_volume else Decimal("0"),
            )
        fill_price = instrument.round_price(px)
        model = cost_model or get_cost_model(instrument.region)
        costs = model.compute(
            instrument, order.side, order.quantity, fill_price,
            intraday=intraday or self.config.intraday_tax_treatment,
        )
        return Fill(
            order_id=order.order_id,
            instrument=instrument,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            day=day,
            horizon=order.horizon,
            commission=costs.commission,
            taxes=costs.taxes,
            fees=costs.fees,
            slippage_per_unit=abs(fill_price - to_decimal(price)),
            reason=order.reason,
        )

    # -- internals -------------------------------------------------------
    @staticmethod
    def _reference_price(order: Order, bar: Bar) -> Decimal | None:
        """Price the order would transact at before slippage, or ``None``.

        Limit and stop orders only transact if the bar's range reaches their
        trigger. When the bar *opens* beyond the trigger, the open is the
        achievable price — a limit buy at 100 on a bar opening at 95 fills at
        95, not 100.
        """
        if order.order_type is OrderType.MARKET:
            return bar.open

        if order.order_type is OrderType.LIMIT:
            limit = order.limit_price
            if order.side is Side.BUY:
                if bar.low > limit:
                    return None
                return min(limit, bar.open)
            if bar.high < limit:
                return None
            return max(limit, bar.open)

        stop = order.stop_price
        if order.side is Side.BUY:
            if bar.high < stop:
                return None
            return max(stop, bar.open)
        if bar.low > stop:
            return None
        return min(stop, bar.open)

    def _cap_quantity(
        self, order: Order, bar: Bar, average_volume: Decimal | None
    ) -> tuple[Decimal, str]:
        """Reduce order size to a realistic share of available volume."""
        reference = (
            to_decimal(average_volume) if average_volume is not None else bar.volume
        )
        if reference <= 0:
            # No volume data: assume the order is small enough to fill.
            return order.quantity, ""

        cap = reference * self.config.max_volume_participation
        if order.quantity <= cap:
            return order.quantity, ""

        instrument = order.instrument
        lots = (cap / instrument.lot_size).to_integral_value(rounding="ROUND_DOWN")
        capped = lots * instrument.lot_size
        note = (
            f"order {order.quantity} exceeds {self.config.max_volume_participation:.0%} "
            f"of volume {reference}; capped to {capped}"
        )
        return capped, note
