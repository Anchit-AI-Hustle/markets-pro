"""The portfolio ledger: multi-currency cash, positions, and equity.

Cash is held **per currency**, not converted on the fly. A rupee balance and a
dollar balance are different things; collapsing them into one number at trade
time hides FX exposure and makes the equity curve depend on when conversions
happened to be booked. Conversion to the base currency happens only at
mark-to-market, using that day's rate.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.instrument import Instrument
from ..core.money import FXRates, Money, to_decimal
from ..execution.orders import Fill, Horizon
from .position import Position, PositionSnapshot


class InsufficientCash(RuntimeError):
    """Raised when a fill would overdraw a currency balance beyond the allowance."""


@dataclass
class EquityPoint:
    """One row of the equity curve, in base currency."""

    day: date
    equity: Decimal
    cash: Decimal
    positions_value: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    costs_paid: Decimal
    open_positions: int

    @property
    def leverage(self) -> float:
        return float(self.gross_exposure / self.equity) if self.equity > 0 else 0.0


class Portfolio:
    """Positions plus cash, valued in a single base currency."""

    def __init__(
        self,
        base_currency: str,
        starting_cash: Mapping[str, Decimal],
        *,
        allow_margin: bool = False,
    ) -> None:
        self.base_currency = base_currency.upper()
        self.cash: dict[str, Money] = {
            code.upper(): Money(to_decimal(amount), code.upper())
            for code, amount in starting_cash.items()
        }
        self.cash.setdefault(self.base_currency, Money.zero(self.base_currency))
        self.positions: dict[str, Position] = {}
        self.allow_margin = allow_margin
        self.fills: list[Fill] = []
        self.equity_curve: list[EquityPoint] = []
        self._costs_paid: dict[str, Money] = {}
        self._realized: dict[str, Money] = {}
        self._initial_cash = {c: m for c, m in self.cash.items()}

    # -- cash ------------------------------------------------------------
    def cash_in(self, currency: str) -> Money:
        currency = currency.upper()
        return self.cash.get(currency, Money.zero(currency))

    def credit(self, amount: Money) -> None:
        self.cash[amount.currency] = self.cash_in(amount.currency) + amount

    def debit(self, amount: Money) -> None:
        self.cash[amount.currency] = self.cash_in(amount.currency) - amount

    # -- positions -------------------------------------------------------
    def position(self, instrument: Instrument) -> Position:
        """Get or create the position for ``instrument``."""
        pos = self.positions.get(instrument.key)
        if pos is None:
            pos = Position(instrument)
            self.positions[instrument.key] = pos
        return pos

    def get_position(self, key: str) -> Position | None:
        pos = self.positions.get(key)
        return pos if pos is not None and not pos.is_flat else None

    def open_positions(self) -> dict[str, Position]:
        return {k: p for k, p in self.positions.items() if not p.is_flat}

    def has_position(self, key: str) -> bool:
        return key in self.positions and not self.positions[key].is_flat

    # -- fills -----------------------------------------------------------
    def apply_fill(self, fill: Fill) -> Money:
        """Book a fill: adjust the position, move cash, record costs.

        Returns the realized P&L (in the instrument's currency). Raises
        :class:`InsufficientCash` when the trade would overdraw and margin is
        disabled — a backtest that silently goes negative on cash is reporting
        returns on money it never had.
        """
        instrument = fill.instrument
        currency = instrument.currency
        delta = Money(fill.cash_delta, currency)
        projected = self.cash_in(currency) + delta

        if projected.is_negative and not self.allow_margin:
            raise InsufficientCash(
                f"{fill.day} {instrument.key}: fill needs "
                f"{-delta.amount} {currency} but only "
                f"{self.cash_in(currency).amount} available"
            )

        pos = self.position(instrument)
        result = pos.apply_fill(fill.signed_quantity, fill.price, fill.day)

        self.credit(delta)
        costs = Money(fill.total_cost, currency)
        self._costs_paid[currency] = (
            self._costs_paid.get(currency, Money.zero(currency)) + costs
        )
        self._realized[currency] = (
            self._realized.get(currency, Money.zero(currency)) + result.realized_pnl
        )
        self.fills.append(fill)
        return result.realized_pnl

    # -- valuation -------------------------------------------------------
    def total_cash(self, fx: FXRates) -> Money:
        total = Money.zero(self.base_currency)
        for money in self.cash.values():
            total = total + fx.convert(money, self.base_currency)
        return total

    def positions_value(self, prices: Mapping[str, Decimal], fx: FXRates) -> Money:
        """Signed mark-to-market of all open positions, in base currency."""
        total = Money.zero(self.base_currency)
        for key, pos in self.positions.items():
            if pos.is_flat:
                continue
            price = prices.get(key)
            if price is None:
                raise KeyError(f"no mark price for open position {key}")
            total = total + fx.convert(pos.market_value(price), self.base_currency)
        return total

    def gross_exposure(self, prices: Mapping[str, Decimal], fx: FXRates) -> Money:
        """Sum of absolute position values — the leverage numerator."""
        total = Money.zero(self.base_currency)
        for key, pos in self.positions.items():
            if pos.is_flat:
                continue
            price = prices.get(key)
            if price is None:
                continue
            total = total + fx.convert(pos.notional_exposure(price), self.base_currency)
        return total

    def total_equity(self, prices: Mapping[str, Decimal], fx: FXRates) -> Money:
        """Net asset value: cash plus signed position value, in base currency."""
        return self.total_cash(fx) + self.positions_value(prices, fx)

    def unrealized_pnl(self, prices: Mapping[str, Decimal], fx: FXRates) -> Money:
        total = Money.zero(self.base_currency)
        for key, pos in self.positions.items():
            if pos.is_flat:
                continue
            price = prices.get(key)
            if price is None:
                continue
            total = total + fx.convert(pos.unrealized_pnl(price), self.base_currency)
        return total

    def realized_pnl(self, fx: FXRates) -> Money:
        total = Money.zero(self.base_currency)
        for money in self._realized.values():
            total = total + fx.convert(money, self.base_currency)
        return total

    def costs_paid(self, fx: FXRates) -> Money:
        total = Money.zero(self.base_currency)
        for money in self._costs_paid.values():
            total = total + fx.convert(money, self.base_currency)
        return total

    def initial_equity(self, fx: FXRates) -> Money:
        total = Money.zero(self.base_currency)
        for money in self._initial_cash.values():
            total = total + fx.convert(money, self.base_currency)
        return total

    # -- reporting -------------------------------------------------------
    def record_equity(
        self, day: date, prices: Mapping[str, Decimal], fx: FXRates
    ) -> EquityPoint:
        """Append one point to the equity curve and return it."""
        cash = self.total_cash(fx)
        pos_value = self.positions_value(prices, fx)
        gross = self.gross_exposure(prices, fx)
        point = EquityPoint(
            day=day,
            equity=(cash + pos_value).amount,
            cash=cash.amount,
            positions_value=pos_value.amount,
            gross_exposure=gross.amount,
            net_exposure=pos_value.amount,
            realized_pnl=self.realized_pnl(fx).amount,
            unrealized_pnl=self.unrealized_pnl(prices, fx).amount,
            costs_paid=self.costs_paid(fx).amount,
            open_positions=len(self.open_positions()),
        )
        self.equity_curve.append(point)
        return point

    def snapshots(
        self, prices: Mapping[str, Decimal], fx: FXRates
    ) -> list[PositionSnapshot]:
        equity = self.total_equity(prices, fx)
        out: list[PositionSnapshot] = []
        for key, pos in sorted(self.open_positions().items()):
            price = to_decimal(prices.get(key, pos.average_cost))
            mv = pos.market_value(price)
            mv_base = fx.convert(mv, self.base_currency)
            weight = (
                float(mv_base.amount / equity.amount) if equity.amount > 0 else 0.0
            )
            out.append(
                PositionSnapshot(
                    key=key,
                    symbol=pos.instrument.symbol,
                    region=pos.instrument.region,
                    currency=pos.instrument.currency,
                    quantity=pos.quantity,
                    average_cost=pos.average_cost,
                    last_price=price,
                    market_value=mv,
                    unrealized_pnl=pos.unrealized_pnl(price),
                    realized_pnl=pos.realized,
                    opened_on=pos.opened_on,
                    weight=weight,
                )
            )
        return out


@dataclass
class OpenTrade:
    """Tracks the protective levels and clock for one short-term entry."""

    key: str
    horizon: Horizon
    entry_price: Decimal
    entry_day: date
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    max_holding_days: int | None = None
    trailing_stop_pct: Decimal | None = None
    high_water_mark: Decimal = Decimal("0")
    bars_held: int = 0

    def __post_init__(self) -> None:
        self.entry_price = to_decimal(self.entry_price)
        if self.high_water_mark == 0:
            self.high_water_mark = self.entry_price


class TradeBook:
    """Registry of live trades and their exit conditions."""

    def __init__(self) -> None:
        self._trades: dict[str, OpenTrade] = {}

    def open(self, trade: OpenTrade) -> None:
        self._trades[trade.key] = trade

    def close(self, key: str) -> OpenTrade | None:
        return self._trades.pop(key, None)

    def get(self, key: str) -> OpenTrade | None:
        return self._trades.get(key)

    def all(self) -> Iterable[OpenTrade]:
        return list(self._trades.values())

    def __contains__(self, key: str) -> bool:
        return key in self._trades

    def __len__(self) -> int:
        return len(self._trades)
