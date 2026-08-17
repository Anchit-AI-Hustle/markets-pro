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


#: Sessions of price history drawn behind each instrument. Roughly a quarter,
#: which is long enough to show the setup the strategy reacted to and short
#: enough that the current move is still legible.
SPARK_SESSIONS = 60


def _spark(feed: LiveFeed, key: str) -> list[float]:
    """Recent closes for a sparkline, oldest first."""
    series = feed.data.get(key)
    if series is None or not len(series):
        return []
    bars = list(series)[-SPARK_SESSIONS:]
    return [round(float(bar.close), 4) for bar in bars]


def _s(value: object) -> str | None:
    """Decimal/date → JSON-safe string; None passes through."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def horizon_stats(report: PerformanceReport) -> dict[str, dict]:
    """Measured per-book statistics: hit rate and how long trades actually ran.

    Every forward-looking number the page shows is anchored to these, so they
    must come from completed trades in this run rather than from an assumption.
    A book with no closed trades yet reports ``None`` — an unknown hit rate is
    shown as unknown, never silently defaulted to something reassuring.
    """
    stats: dict[str, dict] = {}
    for horizon, bucket in report.by_horizon.items():
        held = [
            (trade.exit_day - trade.entry_day).days
            for trade in report.trades
            if trade.horizon == horizon
        ]
        trades = int(bucket.get("trades", 0))
        stats[horizon] = {
            "trades": trades,
            "win_rate": bucket.get("win_rate") if trades else None,
            "median_days_held": sorted(held)[len(held) // 2] if held else None,
        }
    return stats


def _economics(
    *,
    side: str,
    quantity: Decimal,
    price: Decimal | None,
    stop: Decimal | None,
    target: Decimal | None,
    currency: str,
    fx,
) -> dict:
    """What this trade means in money: at target, at stop, and the ratio.

    Only the two modelled outcomes are quantified, because they are the only
    two the strategy actually defines. Anything else — an "expected profit" —
    would require a forecast the engine does not make and cannot honour.
    Amounts are also carried in the base currency so India and US rows can be
    summed into one meaningful total.
    """
    if price is None or price <= 0:
        return {}
    direction = Decimal("1") if side == "BUY" else Decimal("-1")
    invested = quantity * price
    to_base = fx.rate(currency, "USD")

    profit = loss = None
    if target is not None:
        profit = (target - price) * direction * quantity
    if stop is not None:
        loss = (price - stop) * direction * quantity

    reward_risk = None
    if profit is not None and loss is not None and loss > 0:
        reward_risk = profit / loss

    return {
        "invested": _s(invested),
        "invested_base": _s(invested * to_base),
        "profit_at_target": _s(profit),
        "profit_at_target_base": None if profit is None else _s(profit * to_base),
        "profit_at_target_pct": None if profit is None else _s(profit / invested),
        "loss_at_stop": _s(loss),
        "loss_at_stop_base": None if loss is None else _s(loss * to_base),
        "loss_at_stop_pct": None if loss is None else _s(loss / invested),
        "reward_risk": _s(reward_risk),
    }


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


def _order_row(
    order: Order,
    engine: BacktestEngine,
    feed: LiveFeed,
    stats: dict,
    equity_base: Decimal,
) -> dict:
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
        "history": stats.get(order.horizon.value, {}),
        "spark": _spark(feed, key),
    }
    row.update(
        _economics(
            side=side,
            quantity=quantity,
            price=last_price,
            stop=order.stop_loss,
            target=order.take_profit,
            currency=entry.currency,
            fx=feed.fx,
        )
    )
    # The share count above is sized for THIS run's book, which is not the
    # reader's money. Carrying the intended allocation as a fraction lets the
    # page restate every quantity and outcome in terms of the capital the user
    # actually has, instead of quoting them someone else's position size.
    if row.get("invested_base") is not None and equity_base > 0:
        row["weight"] = _s(Decimal(row["invested_base"]) / equity_base)
    row.update(_broker_payloads(entry, side, quantity))
    return row


def _totals(rows: list[dict], *, only_fresh: bool) -> dict:
    """Base-currency totals across rows. Summing raw local amounts would add
    rupees to dollars, so only the ``*_base`` fields are ever accumulated."""

    def total(field: str) -> Decimal:
        return sum(
            (
                Decimal(row[field])
                for row in rows
                if row.get(field) is not None and (row["fresh"] if only_fresh else True)
            ),
            Decimal("0"),
        )

    counted = [row for row in rows if row["fresh"] or not only_fresh]
    invested = total("invested_base")
    profit = total("profit_at_target_base")
    loss = total("loss_at_stop_base")
    return {
        "count": len(counted),
        "invested_base": _s(invested),
        "profit_at_target_base": _s(profit),
        "loss_at_stop_base": _s(loss),
        "profit_at_target_pct": _s(profit / invested) if invested > 0 else None,
        "loss_at_stop_pct": _s(loss / invested) if invested > 0 else None,
    }


def _mechanics(engine: BacktestEngine, feed: LiveFeed) -> dict:
    """The constants the run actually used, for the page to quote back.

    The walkthrough on the dashboard explains how a suggestion is produced, and
    every number it states is read from here rather than typed into the copy —
    so retuning the engine cannot leave the explanation describing a system
    that no longer exists.
    """
    config = engine.config
    return {
        "names": len(feed.entries),
        "regions": len(feed.as_of),
        "sessions": len(feed.data.all_days()),
        "risk_per_trade": _s(config.sizing.risk_per_trade),
        "max_position_weight": _s(config.sizing.max_position_weight),
        "max_cash_utilisation": _s(config.sizing.max_cash_utilisation),
        "max_open_positions": config.risk.max_open_positions,
        "max_drawdown_halt": _s(config.risk.max_drawdown_halt),
        "daily_loss_limit": _s(config.risk.daily_loss_limit),
    }


def build_snapshot(
    engine: BacktestEngine,
    feed: LiveFeed,
    live_config: dict,
    report: PerformanceReport | None = None,
    *,
    generated_at: datetime | None = None,
) -> dict:
    """The one JSON document the dashboard, buttons and executors all consume."""
    stamp = generated_at or datetime.now(timezone.utc)
    fx = feed.fx
    stats = horizon_stats(report) if report is not None else {}
    equity_base = engine.portfolio.total_equity(engine.last_prices, fx).amount

    orders = [
        _order_row(o, engine, feed, stats, equity_base) for o in engine.pending_orders
    ]
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
        to_base = fx.rate(entry.currency, "USD")
        cost_basis = position.average_cost * position.quantity
        row = {
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
            "unrealized_base": None if unrealized is None else _s(unrealized * to_base),
            "unrealized_pct": (
                None if unrealized is None or cost_basis <= 0 else _s(unrealized / cost_basis)
            ),
            "cost_basis": _s(cost_basis),
            "cost_basis_base": _s(cost_basis * to_base),
            "opened_on": _s(position.opened_on),
            "horizon": horizon,
            "stop": _s(stop),
            "take_profit": _s(target),
            "days_held": days_held,
            "max_holding_days": max_days,
            "days_left": None if max_days is None or days_held is None else max_days - days_held,
            "fresh": True,  # every open position counts toward portfolio totals
            "spark": _spark(feed, key),
        }
        # Remaining upside/downside from HERE, not from the original entry.
        row.update(
            _economics(
                side="BUY" if position.is_long else "SELL",
                quantity=position.quantity,
                price=last_price,
                stop=stop,
                target=target,
                currency=entry.currency,
                fx=fx,
            )
        )
        positions.append(row)

    return {
        "version": SNAPSHOT_VERSION,
        "generated_at": stamp.isoformat(timespec="seconds"),
        "as_of": {region: day.isoformat() for region, day in sorted(feed.as_of.items())},
        "base_currency": "USD",
        "equity": _s(equity_base),
        "cash": {ccy: _s(money.amount) for ccy, money in sorted(engine.portfolio.cash.items())},
        "usdinr": _s(fx.rate("USD", "INR")),
        "daily_cap": dict(live_config["daily_cap"]),
        "starting_cash": dict(live_config["starting_cash"]),
        "kite_api_key": live_config.get("kite_api_key", ""),
        "horizon_stats": stats,
        "watchlist": [
            {
                "symbol": entry.symbol,
                "name": entry.name,
                "region": entry.region,
                "sector": entry.sector,
            }
            for entry in feed.entries
        ],
        "mechanics": _mechanics(engine, feed),
        "totals": {
            "signals": _totals(orders, only_fresh=True),
            "positions": _totals(positions, only_fresh=False),
            "open_unrealized_base": _s(
                sum(
                    (
                        Decimal(p["unrealized_base"])
                        for p in positions
                        if p.get("unrealized_base") is not None
                    ),
                    Decimal("0"),
                )
            ),
        },
        "orders": orders,
        "positions": positions,
    }


def generate(data_root: Path, config_path: Path | None) -> tuple[dict, PerformanceReport]:
    """Load cache → run engine → snapshot. The one entry point for callers."""
    live_config = load_live_config(config_path)
    feed = load_livefeed(data_root)
    engine, report = run_live(feed, live_config)
    return build_snapshot(engine, feed, live_config, report), report


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
