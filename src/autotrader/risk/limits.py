"""Pre-trade risk checks and portfolio kill-switches.

Every order passes through :meth:`RiskManager.check` before reaching the venue.
A rejected order is *recorded with its reason*, never dropped silently — a
strategy whose orders are all being rejected by a concentration limit looks
identical to one that generates no signals unless the rejections are visible.

The limits are hard constraints, not preferences. They are the only thing
standing between a strategy with a bad day and a strategy with no capital.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.market import MarketSpec
from ..core.money import FXRates, Money, to_decimal
from ..execution.orders import Order, Side
from ..portfolio.portfolio import Portfolio


@dataclass(frozen=True)
class RiskDecision:
    """Outcome of a risk check."""

    allowed: bool
    code: str = "ok"
    detail: str = ""

    @classmethod
    def ok(cls) -> RiskDecision:
        return cls(True)

    @classmethod
    def deny(cls, code: str, detail: str) -> RiskDecision:
        return cls(False, code, detail)


@dataclass
class RiskConfig:
    """Portfolio-level risk envelope."""

    max_open_positions: int = 20
    max_positions_per_region: int = 8
    max_region_weight: Decimal = Decimal("0.50")
    max_sector_weight: Decimal = Decimal("0.35")
    max_gross_leverage: Decimal = Decimal("1.0")     # 1.0 = fully invested, no margin
    max_net_exposure: Decimal = Decimal("1.0")
    #: Halt *new entries* once drawdown from the equity peak exceeds this.
    max_drawdown_halt: Decimal = Decimal("0.20")
    #: Halt new entries for the rest of the day after this loss vs the open.
    daily_loss_limit: Decimal = Decimal("0.05")
    #: Total capital at risk across all open short-term stops.
    max_portfolio_heat: Decimal = Decimal("0.06")
    allow_short: bool = False

    def __post_init__(self) -> None:
        for name in (
            "max_region_weight", "max_sector_weight", "max_gross_leverage",
            "max_net_exposure", "max_drawdown_halt", "daily_loss_limit",
            "max_portfolio_heat",
        ):
            setattr(self, name, to_decimal(getattr(self, name)))
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be at least 1")


@dataclass
class RiskState:
    """Mutable risk telemetry carried across the backtest."""

    equity_peak: Decimal = Decimal("0")
    day_open_equity: Decimal = Decimal("0")
    current_equity: Decimal = Decimal("0")
    halted: bool = False
    halt_reason: str = ""
    rejections: list[tuple[date, str, str, str]] = field(default_factory=list)

    @property
    def drawdown(self) -> Decimal:
        if self.equity_peak <= 0:
            return Decimal("0")
        return (self.equity_peak - self.current_equity) / self.equity_peak

    @property
    def daily_return(self) -> Decimal:
        if self.day_open_equity <= 0:
            return Decimal("0")
        return (self.current_equity - self.day_open_equity) / self.day_open_equity


class RiskManager:
    """Applies :class:`RiskConfig` to orders and to the portfolio as a whole."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()
        self.state = RiskState()

    # -- portfolio-level -------------------------------------------------
    def start_day(self, equity: Decimal) -> None:
        """Reset the intraday loss clock and roll the equity high-water mark."""
        equity = to_decimal(equity)
        self.state.day_open_equity = equity
        self.state.current_equity = equity
        if equity > self.state.equity_peak:
            self.state.equity_peak = equity
        # A new day clears a daily-loss halt but not a drawdown halt.
        if self.state.halt_reason == "daily_loss_limit":
            self.state.halted = False
            self.state.halt_reason = ""

    def update_equity(self, equity: Decimal) -> None:
        """Mark equity and trip the kill-switches if a threshold is breached."""
        equity = to_decimal(equity)
        self.state.current_equity = equity
        if equity > self.state.equity_peak:
            self.state.equity_peak = equity

        if self.state.drawdown > self.config.max_drawdown_halt:
            self.state.halted = True
            self.state.halt_reason = "max_drawdown_halt"
        elif -self.state.daily_return > self.config.daily_loss_limit:
            self.state.halted = True
            self.state.halt_reason = "daily_loss_limit"

    @property
    def entries_halted(self) -> bool:
        """When true, only exits are permitted."""
        return self.state.halted

    # -- order-level -----------------------------------------------------
    def check(
        self,
        order: Order,
        *,
        day: date,
        portfolio: Portfolio,
        market: MarketSpec,
        price: Decimal,
        prices: Mapping[str, Decimal],
        fx: FXRates,
        is_exit: bool,
    ) -> RiskDecision:
        """Run every applicable check. Exits bypass entry-only limits."""
        decision = self._check_market_rules(order, day, portfolio, market)
        if not decision.allowed:
            return self._record(day, order, decision)

        if is_exit:
            # Exits reduce risk; only venue rules can block them.
            return RiskDecision.ok()

        if self.entries_halted:
            return self._record(
                day, order,
                RiskDecision.deny("halted", f"entries halted: {self.state.halt_reason}"),
            )

        for check in (
            self._check_position_count,
            self._check_region_limits,
            self._check_exposure,
        ):
            decision = check(order, portfolio, market, price, prices, fx)
            if not decision.allowed:
                return self._record(day, order, decision)

        return RiskDecision.ok()

    # -- individual checks -----------------------------------------------
    def _check_market_rules(
        self, order: Order, day: date, portfolio: Portfolio, market: MarketSpec
    ) -> RiskDecision:
        instrument = order.instrument
        position = portfolio.get_position(instrument.key)

        if order.side is Side.SELL:
            held = position.abs_quantity if position and position.is_long else Decimal("0")
            # Selling more than held opens a short.
            if order.quantity > held:
                if not market.short_selling_allowed:
                    return RiskDecision.deny(
                        "short_not_allowed",
                        f"{market.code} does not permit short selling",
                    )
                if not self.config.allow_short:
                    return RiskDecision.deny(
                        "short_disabled", "short selling disabled in RiskConfig"
                    )
                if not instrument.is_shortable:
                    return RiskDecision.deny(
                        "not_shortable", f"{instrument.asset_class} cannot be shorted"
                    )

            # T+1 markets lock same-day purchases (China A-shares).
            if position is not None and position.is_long:
                sellable = position.sellable_quantity(day, market.same_day_sell_allowed)
                if order.quantity > sellable:
                    return RiskDecision.deny(
                        "t_plus_one",
                        f"{market.code} T+{market.settlement_days}: only {sellable} "
                        f"of {position.abs_quantity} sellable on {day}",
                    )

        if order.quantity % instrument.lot_size != 0:
            return RiskDecision.deny(
                "lot_size",
                f"quantity {order.quantity} not a multiple of {instrument.lot_size}",
            )
        return RiskDecision.ok()

    def _check_position_count(
        self,
        order: Order,
        portfolio: Portfolio,
        market: MarketSpec,
        price: Decimal,
        prices: Mapping[str, Decimal],
        fx: FXRates,
    ) -> RiskDecision:
        open_positions = portfolio.open_positions()
        if order.instrument.key in open_positions:
            return RiskDecision.ok()   # adding to an existing name

        if len(open_positions) >= self.config.max_open_positions:
            return RiskDecision.deny(
                "max_positions",
                f"{len(open_positions)} open, limit {self.config.max_open_positions}",
            )

        region = order.instrument.region
        in_region = sum(
            1 for p in open_positions.values() if p.instrument.region == region
        )
        if in_region >= self.config.max_positions_per_region:
            return RiskDecision.deny(
                "max_region_positions",
                f"{in_region} open in {region}, limit "
                f"{self.config.max_positions_per_region}",
            )
        return RiskDecision.ok()

    def _check_region_limits(
        self,
        order: Order,
        portfolio: Portfolio,
        market: MarketSpec,
        price: Decimal,
        prices: Mapping[str, Decimal],
        fx: FXRates,
    ) -> RiskDecision:
        equity = portfolio.total_equity(prices, fx)
        if equity.amount <= 0:
            return RiskDecision.deny("no_equity", "portfolio equity is not positive")

        instrument = order.instrument
        incoming = fx.convert(
            Money(instrument.contract_value(to_decimal(price), order.quantity),
                  instrument.currency),
            portfolio.base_currency,
        )

        region_value = Money.zero(portfolio.base_currency)
        sector_value = Money.zero(portfolio.base_currency)
        for key, pos in portfolio.open_positions().items():
            mark = prices.get(key)
            if mark is None:
                continue
            exposure = fx.convert(pos.notional_exposure(mark), portfolio.base_currency)
            if pos.instrument.region == instrument.region:
                region_value = region_value + exposure
            if pos.instrument.sector == instrument.sector:
                sector_value = sector_value + exposure

        region_weight = (region_value + incoming).amount / equity.amount
        if region_weight > self.config.max_region_weight:
            return RiskDecision.deny(
                "max_region_weight",
                f"{instrument.region} would reach {region_weight:.1%}, limit "
                f"{self.config.max_region_weight:.1%}",
            )

        if instrument.sector != "unknown":
            sector_weight = (sector_value + incoming).amount / equity.amount
            if sector_weight > self.config.max_sector_weight:
                return RiskDecision.deny(
                    "max_sector_weight",
                    f"sector {instrument.sector} would reach {sector_weight:.1%}, "
                    f"limit {self.config.max_sector_weight:.1%}",
                )
        return RiskDecision.ok()

    def _check_exposure(
        self,
        order: Order,
        portfolio: Portfolio,
        market: MarketSpec,
        price: Decimal,
        prices: Mapping[str, Decimal],
        fx: FXRates,
    ) -> RiskDecision:
        equity = portfolio.total_equity(prices, fx)
        if equity.amount <= 0:
            return RiskDecision.deny("no_equity", "portfolio equity is not positive")

        instrument = order.instrument
        incoming = fx.convert(
            Money(instrument.contract_value(to_decimal(price), order.quantity),
                  instrument.currency),
            portfolio.base_currency,
        )
        gross = portfolio.gross_exposure(prices, fx) + incoming
        leverage = gross.amount / equity.amount
        if leverage > self.config.max_gross_leverage:
            return RiskDecision.deny(
                "max_leverage",
                f"gross leverage would reach {leverage:.2f}x, limit "
                f"{self.config.max_gross_leverage:.2f}x",
            )
        return RiskDecision.ok()

    # -- bookkeeping -----------------------------------------------------
    def _record(self, day: date, order: Order, decision: RiskDecision) -> RiskDecision:
        self.state.rejections.append(
            (day, order.instrument.key, decision.code, decision.detail)
        )
        return decision

    def portfolio_heat(
        self,
        portfolio: Portfolio,
        stops: Mapping[str, Decimal],
        prices: Mapping[str, Decimal],
        fx: FXRates,
    ) -> Decimal:
        """Total fraction of equity that would be lost if every stop triggered."""
        equity = portfolio.total_equity(prices, fx)
        if equity.amount <= 0:
            return Decimal("0")
        total = Money.zero(portfolio.base_currency)
        for key, pos in portfolio.open_positions().items():
            stop = stops.get(key)
            mark = prices.get(key)
            if stop is None or mark is None:
                continue
            per_unit = abs(to_decimal(mark) - to_decimal(stop))
            risk = per_unit * pos.abs_quantity * pos.instrument.multiplier
            total = total + fx.convert(
                Money(risk, pos.instrument.currency), portfolio.base_currency
            )
        return total.amount / equity.amount
