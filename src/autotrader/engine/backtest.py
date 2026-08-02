"""The backtest event loop.

The ordering of operations inside a session is the whole ballgame. This engine
runs each session ``D`` as:

1. **Roll the risk clock** — record the equity the day opened at.
2. **Fill yesterday's orders at today's open.** Orders were decided using data up
   to the close of ``D-1``; they cannot fill at a price from ``D-1``.
3. **Evaluate exits against today's full bar** — stops, targets, trailing stops
   and time limits, resolved pessimistically (see :mod:`autotrader.risk.exits`).
4. **Mark to market on today's close** and update the drawdown kill-switch.
5. **Generate tomorrow's orders** from data up to today's close.

Step 5 comes last and its output cannot be executed until step 2 of the next
session. That single constraint is what makes the results reproducible in live
trading rather than an artefact of the simulation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.calendar import GlobalCalendar, TradingCalendar
from ..core.instrument import Instrument
from ..core.market import MarketSpec, get_market
from ..core.money import FXRates, Money, to_decimal
from ..data.bars import Bar, MarketDataSet
from ..execution.costs import CostModel, SlippageModel, get_cost_model
from ..execution.orders import Fill, Horizon, Order, OrderType, Rejection, Side
from ..execution.simulator import ExecutionConfig, ExecutionSimulator
from ..portfolio.portfolio import InsufficientCash, OpenTrade, Portfolio, TradeBook
from ..portfolio.sizing import SizingConfig, size_order
from ..risk.exits import (
    ExitReason,
    ExitSignal,
    effective_stop,
    evaluate_exit,
    update_trailing,
)
from ..risk.limits import RiskConfig, RiskManager
from ..strategy.base import Direction, Signal, Strategy, StrategyContext
from .metrics import PerformanceReport, RoundTrip, build_report


@dataclass
class BacktestConfig:
    """Everything the engine needs that is not data or strategy."""

    start: date
    end: date
    base_currency: str = "USD"
    starting_cash: Mapping[str, Decimal] = field(default_factory=dict)
    sizing: SizingConfig = field(default_factory=SizingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    slippage: SlippageModel = field(default_factory=SlippageModel)
    risk_free_rate: float = 0.0
    #: Sessions of average volume used for the liquidity cap.
    volume_lookback: int = 20
    allow_margin: bool = False

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"end {self.end} precedes start {self.start}")
        if not self.starting_cash:
            raise ValueError("starting_cash must specify at least one currency")


@dataclass
class _EntryRecord:
    """Running record of an open position, used to emit a round trip on exit.

    ``realized_at_entry`` snapshots the instrument's cumulative realized P&L when
    the position was opened. Without it, the second round trip in a name would
    inherit the first one's profit, because :class:`~autotrader.portfolio.position.Position`
    accumulates realized P&L across its whole lifetime.
    """

    key: str
    region: str
    horizon: str
    currency: str
    entry_day: date
    entry_notional: Decimal
    quantity: Decimal
    costs: Decimal
    realized_at_entry: Decimal = Decimal("0")

    @property
    def average_entry(self) -> Decimal:
        return self.entry_notional / self.quantity if self.quantity else Decimal("0")


class BacktestEngine:
    """Runs strategies over historical data and produces a performance report."""

    def __init__(
        self,
        *,
        instruments: Sequence[Instrument],
        data: MarketDataSet,
        strategies: Sequence[Strategy],
        config: BacktestConfig,
        fx: FXRates | Callable[[date], FXRates],
        cost_models: Mapping[str, CostModel] | None = None,
        markets: Mapping[str, MarketSpec] | None = None,
    ) -> None:
        self.instruments = {i.key: i for i in instruments}
        self.data = data
        self.strategies = list(strategies)
        self.config = config
        self._fx = fx
        self.cost_models = dict(cost_models or {})
        self.markets: dict[str, MarketSpec] = dict(markets or {})
        for instrument in instruments:
            self.markets.setdefault(instrument.region, get_market(instrument.region))

        self.portfolio = Portfolio(
            config.base_currency, config.starting_cash, allow_margin=config.allow_margin
        )
        self.risk = RiskManager(config.risk)
        self.simulator = ExecutionSimulator(config.slippage, config.execution)
        self.trades = TradeBook()
        self.calendar = GlobalCalendar.from_specs(self.markets.values())

        self.pending_orders: list[Order] = []
        self.round_trips: list[RoundTrip] = []
        self.rejections: list[Rejection] = []
        self.last_prices: dict[str, Decimal] = {}
        self._entries: dict[str, _EntryRecord] = {}
        self._pending_exit_reason: dict[str, str] = {}
        #: Protective levels for an entry order, held until its fill arrives.
        self._pending_meta: dict[str, tuple] = {}

    # -- helpers ----------------------------------------------------------
    def fx_on(self, day: date) -> FXRates:
        return self._fx(day) if callable(self._fx) else self._fx

    def market_for(self, instrument: Instrument) -> MarketSpec:
        return self.markets[instrument.region]

    def cost_model_for(self, instrument: Instrument) -> CostModel:
        return self.cost_models.get(instrument.region) or get_cost_model(instrument.region)

    def _average_volume(self, key: str, day: date) -> Decimal | None:
        window = self.data.window(key, day)
        if window is None or window.is_empty:
            return None
        volumes = window.volumes(self.config.volume_lookback)
        if not volumes:
            return None
        total = sum(volumes, Decimal("0"))
        return total / Decimal(len(volumes)) if total > 0 else None

    def _previous_close(self, key: str, day: date) -> Decimal | None:
        series = self.data.get(key)
        if series is None:
            return None
        idx = series.index_asof(day)
        # index_asof(day) is today's bar when it exists; step back one for prior.
        if idx >= 1 and series[idx].day == day:
            return series[idx - 1].close
        return series[idx].close if idx >= 0 else None

    # -- main loop --------------------------------------------------------
    def run(self) -> PerformanceReport:
        """Execute the backtest and return the report."""
        cfg = self.config
        sessions = self.calendar.sessions(cfg.start, cfg.end)
        if not sessions:
            raise ValueError(
                f"no trading sessions between {cfg.start} and {cfg.end}"
            )

        for day in sessions:
            fx = self.fx_on(day)
            self._seed_prices(day)

            equity = self.portfolio.total_equity(self.last_prices, fx)
            self.risk.start_day(equity.amount)

            self._process_pending_orders(day, fx)
            self._process_exits(day, fx)

            self._seed_prices(day)     # refresh with today's closes post-trading
            equity = self.portfolio.record_equity(day, self.last_prices, fx)
            self.risk.update_equity(equity.equity)

            self._generate_orders(day, fx)

        return self._build_report(sessions)

    # -- step 1: prices ---------------------------------------------------
    def _seed_prices(self, day: date) -> None:
        """Carry forward the last observed close for every instrument.

        Markets are open on different days; a position in a closed market must
        still be marked, and marking it at a stale-but-real price is correct,
        whereas dropping it from the valuation would understate exposure.
        """
        for key in self.instruments:
            bar = self.data.bar_on(key, day)
            if bar is not None:
                self.last_prices[key] = bar.close

    # -- step 2: fills ----------------------------------------------------
    def _process_pending_orders(self, day: date, fx: FXRates) -> None:
        """Fill orders raised yesterday against today's open."""
        orders, self.pending_orders = self.pending_orders, []
        for order in orders:
            instrument = order.instrument
            market = self.market_for(instrument)
            calendar = TradingCalendar(market)
            if not calendar.is_trading_day(day):
                # Venue closed: the order rests until its market next opens.
                self.pending_orders.append(order)
                continue

            bar = self.data.bar_on(instrument.key, day)
            if bar is None:
                self.rejections.append(
                    Rejection(order, "no_data", f"no bar for {instrument.key} on {day}")
                )
                continue

            self._try_fill(order, bar, day, fx, market)

    def _try_fill(
        self, order: Order, bar: Bar, day: date, fx: FXRates, market: MarketSpec
    ) -> None:
        instrument = order.instrument
        is_exit = order.reason.startswith("exit:") or self._is_reducing(order)

        decision = self.risk.check(
            order,
            day=day,
            portfolio=self.portfolio,
            market=market,
            price=bar.open,
            prices=self.last_prices,
            fx=fx,
            is_exit=is_exit,
        )
        if not decision.allowed:
            self.rejections.append(Rejection(order, decision.code, decision.detail))
            return

        result = self.simulator.execute(
            order,
            bar,
            market=market,
            previous_close=self._previous_close(instrument.key, day),
            average_volume=self._average_volume(instrument.key, day),
            cost_model=self.cost_model_for(instrument),
        )
        if isinstance(result, Rejection):
            self.rejections.append(result)
            return

        self._book_fill(result, day, order=order)

    def _is_reducing(self, order: Order) -> bool:
        """True when the order shrinks or closes an existing position."""
        position = self.portfolio.get_position(order.instrument.key)
        if position is None:
            return False
        if position.is_long and order.side is Side.SELL:
            return True
        if position.is_short and order.side is Side.BUY:
            return True
        return False

    def _book_fill(self, fill: Fill, day: date, *, order: Order) -> None:
        """Apply a fill to the ledger and maintain round-trip bookkeeping."""
        key = fill.instrument.key
        position_before = self.portfolio.get_position(key)
        quantity_before = position_before.abs_quantity if position_before else Decimal("0")
        realized_before = (
            self.portfolio.positions[key].realized.amount
            if key in self.portfolio.positions
            else Decimal("0")
        )

        try:
            self.portfolio.apply_fill(fill)
        except InsufficientCash as exc:
            self.rejections.append(Rejection(order, "insufficient_cash", str(exc)))
            self._pending_meta.pop(key, None)
            self._pending_exit_reason.pop(key, None)
            return

        position_after = self.portfolio.get_position(key)
        quantity_after = position_after.abs_quantity if position_after else Decimal("0")
        increased = quantity_after > quantity_before

        record = self._entries.get(key)
        if record is None:
            self._entries[key] = _EntryRecord(
                key=key,
                region=fill.instrument.region,
                horizon=fill.horizon.value,
                currency=fill.instrument.currency,
                entry_day=day,
                entry_notional=fill.gross_value,
                quantity=fill.quantity,
                costs=fill.total_cost,
                realized_at_entry=realized_before,
            )
        else:
            record.costs += fill.total_cost
            if increased:
                record.entry_notional += fill.gross_value
                record.quantity += fill.quantity

        if position_after is None:
            self._close_round_trip(key, fill, day)
        elif fill.horizon is Horizon.SHORT_TERM and increased:
            self._register_trade(fill, day)

    def _register_trade(self, fill: Fill, day: date) -> None:
        """Attach protective levels to a freshly opened short-term position."""
        key = fill.instrument.key
        if key in self.trades:
            return
        order_meta = self._pending_meta.pop(key, None)
        if order_meta is None:
            return
        stop, target, max_days, trail = order_meta
        self.trades.open(
            OpenTrade(
                key=key,
                horizon=fill.horizon,
                entry_price=fill.price,
                entry_day=day,
                stop_loss=stop,
                take_profit=target,
                max_holding_days=max_days,
                trailing_stop_pct=trail,
                high_water_mark=fill.price,
            )
        )

    def _close_round_trip(self, key: str, fill: Fill, day: date) -> None:
        """Emit a :class:`RoundTrip` when a position returns to flat."""
        record = self._entries.pop(key, None)
        self.trades.close(key)
        if record is None:
            return
        position = self.portfolio.positions.get(key)
        realized = position.realized.amount if position else Decimal("0")
        gross = realized - record.realized_at_entry
        reason = self._pending_exit_reason.pop(key, fill.reason)
        # Capture the exit-day rate so aggregate statistics can add rupee,
        # rouble and dollar trades together in a single currency.
        base = self.config.base_currency
        fx_rate = self.fx_on(day).rate(record.currency, base)
        self.round_trips.append(
            RoundTrip(
                key=key,
                region=record.region,
                horizon=record.horizon,
                entry_day=record.entry_day,
                exit_day=day,
                entry_price=record.average_entry,
                exit_price=fill.price,
                quantity=record.quantity,
                gross_pnl=gross,
                costs=record.costs,
                exit_reason=reason,
                currency=record.currency,
                base_currency=base,
                fx_rate=fx_rate,
            )
        )

    # -- step 3: exits ----------------------------------------------------
    def _process_exits(self, day: date, fx: FXRates) -> None:
        """Apply stop, target, trailing and time exits against today's bar."""
        for trade in self.trades.all():
            position = self.portfolio.get_position(trade.key)
            if position is None:
                self.trades.close(trade.key)
                continue

            instrument = self.instruments[trade.key]
            market = self.market_for(instrument)
            if not TradingCalendar(market).is_trading_day(day):
                continue

            bar = self.data.bar_on(trade.key, day)
            if bar is None:
                continue

            is_long = position.is_long
            if trade.entry_day < day:
                trade.bars_held += 1
            update_trailing(trade, bar, is_long)

            signal = evaluate_exit(trade, bar, is_long)
            if signal is None:
                continue

            # T+1 venues lock same-session exits; the stop simply waits a day.
            sellable = position.sellable_quantity(day, market.same_day_sell_allowed)
            if sellable <= 0:
                continue

            self._execute_exit(trade.key, position, signal, day, fx, market, sellable)

    def _execute_exit(
        self,
        key: str,
        position,
        signal: ExitSignal,
        day: date,
        fx: FXRates,
        market: MarketSpec,
        quantity: Decimal,
    ) -> None:
        instrument = self.instruments[key]
        side = Side.SELL if position.is_long else Side.BUY
        order = Order(
            instrument=instrument,
            side=side,
            quantity=quantity,
            horizon=Horizon.SHORT_TERM,
            created_on=day,
            reason=f"exit:{signal.reason.value}",
        )
        self._pending_exit_reason[key] = signal.reason.value
        fill = self.simulator.execute_at_price(
            order,
            signal.price,
            day,
            market=market,
            cost_model=self.cost_model_for(instrument),
            average_volume=self._average_volume(key, day),
        )
        self._book_fill(fill, day, order=order)

    # -- step 5: signals --------------------------------------------------
    def _generate_orders(self, day: date, fx: FXRates) -> None:
        """Turn strategy signals into sized, risk-checked orders for tomorrow."""
        equity = self.portfolio.total_equity(self.last_prices, fx)
        if equity.amount <= 0:
            return

        open_keys = frozenset(self.portfolio.open_positions())
        # Entry and stop levels let exit rules reason in units of risk (R)
        # rather than raw price, which is what keeps a signal exit from
        # systematically cutting winners shorter than losers.
        entry_prices: dict[str, Decimal] = {}
        stop_levels: dict[str, Decimal] = {}
        for trade in self.trades.all():
            entry_prices[trade.key] = trade.entry_price
            stop = effective_stop(trade, is_long=True)
            if stop is not None:
                stop_levels[trade.key] = stop

        context = StrategyContext(
            day=day,
            equity=equity.amount,
            open_keys=open_keys,
            held_since={
                k: p.opened_on
                for k, p in self.portfolio.open_positions().items()
                if p.opened_on
            },
            entries_halted=self.risk.entries_halted,
            entry_prices=entry_prices,
            stop_levels=stop_levels,
        )

        for strategy in self.strategies:
            if not strategy.should_run(day, context):
                continue
            windows = self._windows_for(day)
            if not windows:
                continue
            for signal in strategy.generate(day, windows, self.instruments, context):
                order = self._order_from_signal(signal, day, equity, fx)
                if order is not None:
                    self.pending_orders.append(order)

    def _windows_for(self, day: date) -> dict:
        """History windows for every instrument whose market is open today."""
        out = {}
        for key, instrument in self.instruments.items():
            market = self.market_for(instrument)
            if not TradingCalendar(market).is_trading_day(day):
                continue
            window = self.data.window(key, day)
            if window is None or window.is_empty:
                continue
            out[key] = window
        return out

    def _order_from_signal(
        self, signal: Signal, day: date, equity: Money, fx: FXRates
    ) -> Order | None:
        instrument = signal.instrument
        key = instrument.key
        position = self.portfolio.get_position(key)
        price = self.last_prices.get(key)
        if price is None:
            return None

        if signal.direction is Direction.FLAT:
            if position is None:
                return None
            self._pending_exit_reason[key] = ExitReason.SIGNAL_EXIT.value
            return Order(
                instrument=instrument,
                side=Side.SELL if position.is_long else Side.BUY,
                quantity=position.abs_quantity,
                horizon=signal.horizon,
                created_on=day,
                reason=f"exit:{signal.reason}",
            )

        if self.risk.entries_halted:
            return None

        available = self.portfolio.cash_in(instrument.currency)
        sized = size_order(
            instrument,
            equity=fx.convert(equity, instrument.currency),
            available_cash=available,
            price=price,
            config=self.config.sizing,
            stop_price=signal.stop_loss,
            target_weight=signal.target_weight,
            atr_value=signal.atr_value,
            average_volume=self._average_volume(key, day),
            conviction=to_decimal(signal.strength),
        )
        if not sized.is_tradable:
            return None

        target_quantity = sized.quantity
        current = position.abs_quantity if position else Decimal("0")

        if signal.target_weight is not None:
            delta = target_quantity - current
            if delta == 0:
                return None
            side = Side.BUY if delta > 0 else Side.SELL
            quantity = abs(delta)
            # Skip rebalances too small to be worth the round-trip cost.
            if instrument.contract_value(price, quantity) < self.config.sizing.min_order_notional:
                return None
        else:
            if current > 0:
                return None      # already in the name; do not pyramid
            side = Side.BUY
            quantity = target_quantity

        if quantity <= 0:
            return None

        if signal.horizon is Horizon.SHORT_TERM and side is Side.BUY:
            self._pending_meta[key] = (
                signal.stop_loss,
                signal.take_profit,
                signal.max_holding_days,
                signal.trailing_stop_pct,
            )

        return Order(
            instrument=instrument,
            side=side,
            quantity=quantity,
            horizon=signal.horizon,
            order_type=OrderType.MARKET,
            created_on=day,
            reason=signal.reason,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            max_holding_days=signal.max_holding_days,
        )

    # -- reporting --------------------------------------------------------
    def _build_report(self, sessions: Sequence[date]) -> PerformanceReport:
        fx = self.fx_on(sessions[-1])
        curve = self.portfolio.equity_curve
        return build_report(
            days=[p.day for p in curve],
            equity=[p.equity for p in curve],
            trades=self.round_trips,
            base_currency=self.config.base_currency,
            total_costs=self.portfolio.costs_paid(fx).amount,
            total_fills=len(self.portfolio.fills),
            rejections=len(self.rejections),
            risk_free_rate=self.config.risk_free_rate,
        )
