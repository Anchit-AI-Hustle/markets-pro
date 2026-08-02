"""Run the verified strategies over real bars and extract today's signals.

The trick that keeps this honest: the engine generates orders as the LAST step
of each session, and fills happen at the NEXT session's open. So after a run
whose end is the latest real bar, ``engine.pending_orders`` holds exactly the
orders the strategies would place right now — sized by the same code, checked
by the same risk limits, and never fill-simulated against a bar that does not
exist yet. There is no separate "live" code path to drift out of sync with the
backtested one.

The snapshot this module emits is the one artifact every consumer shares: the
dashboard renders it, the broker handoff buttons serialise it, and the capped
auto-invest executors refuse to act on anything else.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..data.livefeed import LiveFeed, load_livefeed
from ..data.universe import UniverseEntry, entry_for_key
from ..engine.backtest import BacktestConfig, BacktestEngine
from ..engine.metrics import PerformanceReport
from ..execution.costs import SlippageModel
from ..execution.orders import Horizon, Order
from ..execution.simulator import ExecutionConfig
from ..portfolio.sizing import SizingConfig
from ..risk.exits import effective_stop
from ..risk.limits import RiskConfig
from ..strategy.long_term import LongTermConfig, LongTermStrategy
from ..strategy.short_term import ShortTermConfig, ShortTermStrategy

SNAPSHOT_VERSION = 1

#: Sessions of book accumulation before "today". History before this window is
#: still visible to indicators (the lookahead guard clips windows to the
#: decision date, not to the run start), so warmup is never the constraint —
#: this is purely how long the simulated book has existed by signal day.
BOOK_SESSIONS = 260

DEFAULT_LIVE_CONFIG: dict = {
    "starting_cash": {"INR": "500000", "USD": "10000"},
    "daily_cap": {"INR": "20000", "USD": "250"},
    "kite_api_key": "",
}


def load_live_config(path: Path | None) -> dict:
    """Merge the user's config file over the defaults; missing file is fine."""
    config = json.loads(json.dumps(DEFAULT_LIVE_CONFIG))
    if path is not None and path.exists():
        config.update(json.loads(path.read_text()))
    return config


def run_live(feed: LiveFeed, live_config: dict) -> tuple[BacktestEngine, PerformanceReport]:
    """Run both books over the cached real bars, ending at the latest session."""
    days = feed.data.all_days()
    if len(days) < 60:
        raise ValueError(f"only {len(days)} sessions cached; need at least 60")
    start = days[max(0, len(days) - BOOK_SESSIONS)]

    config = BacktestConfig(
        start=start,
        end=days[-1],
        base_currency="USD",
        starting_cash={
            currency: Decimal(amount)
            for currency, amount in live_config["starting_cash"].items()
        },
        sizing=SizingConfig(
            risk_per_trade=Decimal("0.0075"),
            max_position_weight=Decimal("0.12"),
            min_order_notional=Decimal("500"),
            max_cash_utilisation=Decimal("0.90"),
            max_volume_participation=Decimal("0.03"),
        ),
        # Two regions instead of the demo's four: region/position ceilings are
        # loosened so capital is not structurally stranded, drawdown and daily
        # loss halts stay at the demo's verified values.
        risk=RiskConfig(
            max_open_positions=10,
            max_positions_per_region=6,
            max_region_weight=Decimal("0.65"),
            max_sector_weight=Decimal("0.40"),
            max_gross_leverage=Decimal("0.95"),
            max_drawdown_halt=Decimal("0.25"),
            daily_loss_limit=Decimal("0.06"),
        ),
        execution=ExecutionConfig(max_volume_participation=Decimal("0.05")),
        slippage=SlippageModel(half_spread_bps=Decimal("2"), impact_coefficient=Decimal("12")),
    )
    strategies = [
        LongTermStrategy(LongTermConfig(max_holdings=6, total_allocation=Decimal("0.55"))),
        ShortTermStrategy(ShortTermConfig(max_concurrent=5)),
    ]
    engine = BacktestEngine(
        instruments=list(feed.instruments),
        data=feed.data,
        strategies=strategies,
        config=config,
        fx=feed.fx,
    )
    report = engine.run()
    return engine, report


# --- snapshot ---------------------------------------------------------------


def _s(value: object) -> str | None:
    """Decimal/date → JSON-safe string; None passes through."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _broker_payloads(entry: UniverseEntry, side: str, quantity: Decimal) -> dict:
    qty = int(quantity)
    if entry.region == "india":
        return {
            "kite": {
                "exchange": entry.exchange,
                "tradingsymbol": entry.symbol,
                "transaction_type": side,
                "quantity": qty,
                "order_type": "MARKET",
                "product": "CNC",
                "readonly": False,
            }
        }
    return {
        "alpaca": {
            "symbol": entry.symbol,
            "qty": str(qty),
            "side": side.lower(),
            "type": "market",
            "time_in_force": "day",
        }
    }


def _order_row(order: Order, engine: BacktestEngine, feed: LiveFeed) -> dict:
    key = order.instrument.key
    entry = entry_for_key(key)
    last_price = engine.last_prices.get(key)
    quantity = order.quantity
    notional = None if last_price is None else (quantity * last_price)
    meta = getattr(engine, "_pending_meta", {}).get(key)
    trailing = meta[3] if meta is not None and len(meta) > 3 else None
    series = feed.data.get(key)
    fresh = series is not None and order.created_on == series.last_day
    side = "BUY" if order.side.name == "BUY" else "SELL"

    row = {
        "key": key,
        "symbol": entry.symbol,
        "name": entry.name,
        "yahoo": entry.yahoo,
        "region": entry.region,
        "exchange": entry.exchange,
        "currency": entry.currency,
        "side": side,
        "quantity": _s(quantity),
        "reference_price": _s(last_price),
        "notional": _s(notional),
        "horizon": order.horizon.value,
        "created_on": _s(order.created_on),
        "fresh": fresh,
        "reason": order.reason,
        "stop_loss": _s(order.stop_loss),
        "take_profit": _s(order.take_profit),
        "max_holding_days": order.max_holding_days,
        "trailing_stop_pct": _s(trailing),
    }
    row.update(_broker_payloads(entry, side, quantity))
    return row


def build_snapshot(
    engine: BacktestEngine,
    feed: LiveFeed,
    live_config: dict,
    *,
    generated_at: datetime | None = None,
) -> dict:
    """The one JSON document the dashboard, buttons and executors all consume."""
    stamp = generated_at or datetime.now(timezone.utc)
    fx = feed.fx

    orders = [_order_row(o, engine, feed) for o in engine.pending_orders]
    orders.sort(key=lambda r: (not r["fresh"], r["region"], r["symbol"]))

    positions = []
    for key, position in sorted(engine.portfolio.open_positions().items()):
        entry = entry_for_key(key)
        last_price = engine.last_prices.get(key)
        trade = engine.trades.get(key)
        stop = target = None
        days_held = max_days = None
        horizon = Horizon.LONG_TERM.value
        if trade is not None:
            horizon = trade.horizon.value
            stop = effective_stop(trade, position.is_long)
            target = trade.take_profit
            days_held = trade.bars_held
            max_days = trade.max_holding_days
        unrealized = (
            None
            if last_price is None
            else (last_price - position.average_cost) * position.quantity
        )
        positions.append(
            {
                "key": key,
                "symbol": entry.symbol,
                "name": entry.name,
                "yahoo": entry.yahoo,
                "region": entry.region,
                "exchange": entry.exchange,
                "currency": entry.currency,
                "quantity": _s(position.quantity),
                "average_cost": _s(position.average_cost),
                "last_price": _s(last_price),
                "unrealized": _s(unrealized),
                "opened_on": _s(position.opened_on),
                "horizon": horizon,
                "stop": _s(stop),
                "take_profit": _s(target),
                "days_held": days_held,
                "max_holding_days": max_days,
            }
        )

    equity = engine.portfolio.total_equity(engine.last_prices, fx)
    return {
        "version": SNAPSHOT_VERSION,
        "generated_at": stamp.isoformat(timespec="seconds"),
        "as_of": {region: day.isoformat() for region, day in sorted(feed.as_of.items())},
        "base_currency": "USD",
        "equity": _s(equity.amount),
        "cash": {ccy: _s(money.amount) for ccy, money in sorted(engine.portfolio.cash.items())},
        "usdinr": _s(fx.rate("USD", "INR")),
        "daily_cap": dict(live_config["daily_cap"]),
        "kite_api_key": live_config.get("kite_api_key", ""),
        "orders": orders,
        "positions": positions,
    }


def generate(data_root: Path, config_path: Path | None) -> tuple[dict, PerformanceReport]:
    """Load cache → run engine → snapshot. The one entry point for callers."""
    live_config = load_live_config(config_path)
    feed = load_livefeed(data_root)
    engine, report = run_live(feed, live_config)
    return build_snapshot(engine, feed, live_config), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate today's signals from the live cache")
    parser.add_argument("--data", default="data/live", help="live cache root")
    parser.add_argument("--config", default="config/live.json", help="live config path")
    parser.add_argument("--out", default=None, help="write snapshot JSON here (default: stdout)")
    args = parser.parse_args(argv)

    snapshot, report = generate(Path(args.data), Path(args.config))
    payload = json.dumps(snapshot, indent=1)
    if args.out:
        Path(args.out).write_text(payload + "\n")
    else:
        print(payload)
    fresh = sum(1 for order in snapshot["orders"] if order["fresh"])
    print(
        f"\n{fresh} fresh signal(s), {len(snapshot['orders'])} total pending, "
        f"{len(snapshot['positions'])} open position(s); "
        f"book equity {snapshot['equity']} {snapshot['base_currency']}",
    )
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
