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


def _history(feed: LiveFeed, key: str, sessions: int = 505) -> dict:
    """Closes, volumes and dates for the ranges a detail chart offers.

    Two years is the cache depth, which supports every range up to 2Y. Closes
    are rounded to two places and volumes to whole shares: the extra digits
    are noise at chart resolution and they triple the payload. Dates travel
    with the series because trading days are not evenly spaced — weekends and
    holidays mean an index cannot be turned back into a date.
    """
    series = feed.data.get(key)
    if series is None or not len(series):
        return {}
    bars = list(series)[-sessions:]
    return {
        "d": [bar.day.isoformat() for bar in bars],
        "c": [round(float(bar.close), 2) for bar in bars],
        "v": [int(bar.volume) for bar in bars],
    }


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


def _watchlist(
    engine: BacktestEngine, feed: LiveFeed, orders: list[dict], positions: list[dict]
) -> list[dict]:
    """Every name the strategies watch, priced and with its recent record.

    The list of names alone answers nothing a reader would ask of it. This adds
    what each one has actually done — last close, moves over a day, a week, a
    month and a quarter — plus whether the book is currently in it, so the
    watchlist explains why a name is or is not on today's list rather than
    merely asserting that it is watched.
    """
    held = {p["key"] for p in positions}
    signalled = {o["key"] for o in orders if o["fresh"]}
    resting = {o["key"] for o in orders} - signalled

    rows = []
    for entry in feed.entries:
        series = feed.data.get(entry.key)
        closes = [bar.close for bar in series] if series is not None else []
        if not closes:
            continue
        last = closes[-1]

        def move(sessions: int, closes=closes, last=last) -> str | None:
            """Percentage change over N completed sessions.

            The series is bound at definition rather than captured, so this
            cannot silently read the last instrument's prices if it is ever
            called outside the iteration that made it. Returns None when the
            history is too short — an unknown move is never shown as zero.
            """
            if len(closes) <= sessions:
                return None
            earlier = closes[-1 - sessions]
            if earlier <= 0:
                return None
            return _s((last - earlier) / earlier)

        if entry.key in held:
            status, status_note = "held", "in the book"
        elif entry.key in signalled:
            status, status_note = "signal", "suggested today"
        elif entry.key in resting:
            status, status_note = "resting", "order still open"
        else:
            status, status_note = "watching", "no setup"

        # 52-week context: where this price sits inside its own year is the
        # first thing anyone asks of a quote, and it cannot be read off a
        # percentage change.
        year = closes[-252:] if len(closes) >= 2 else closes
        high_52, low_52 = max(year), min(year)
        span = high_52 - low_52
        volumes = [bar.volume for bar in series][-21:] if series is not None else []

        rows.append({
            "key": entry.key,
            "high_52w": _s(high_52),
            "low_52w": _s(low_52),
            "off_high": _s((last - high_52) / high_52) if high_52 > 0 else None,
            "off_low": _s((last - low_52) / low_52) if low_52 > 0 else None,
            "range_position": _s((last - low_52) / span) if span > 0 else None,
            "avg_volume": _s(sum(volumes) / len(volumes)) if volumes else None,
            "symbol": entry.symbol,
            "name": entry.name,
            "region": entry.region,
            "sector": entry.sector,
            "currency": entry.currency,
            "yahoo": entry.yahoo,
            "exchange": entry.exchange,
            "last": _s(last),
            "change_1d": move(1),
            "change_1w": move(5),
            "change_1m": move(21),
            "change_3m": move(63),
            "sessions": len(closes),
            "status": status,
            "status_note": status_note,
            "spark": _spark(feed, entry.key),
            "history": _history(feed, entry.key),
        })

    # Biggest movers first: on a list this long, the ones that did something
    # are the ones worth the top of the screen.
    rows.sort(key=lambda r: abs(float(r["change_1d"] or 0)), reverse=True)
    return rows


def _benchmarks(data_root: Path) -> list[dict]:
    """Index, commodity and currency levels with their recent moves."""
    path = data_root / "benchmarks.json"
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    rows = []
    for yahoo, series in (document.get("series") or {}).items():
        closes = [Decimal(str(c)) for c in (series.get("closes") or [])]
        if len(closes) < 2:
            continue
        last = closes[-1]

        def move(sessions: int, closes=closes, last=last) -> str | None:
            if len(closes) <= sessions:
                return None
            earlier = closes[-1 - sessions]
            return None if earlier <= 0 else _s((last - earlier) / earlier)

        days = series.get("days") or []
        rows.append({
            "yahoo": yahoo,
            "label": series.get("label", yahoo),
            "group": series.get("group", "global"),
            "kind": series.get("kind", "index"),
            "currency": series.get("currency", ""),
            "last": _s(last),
            "change_1d": move(1),
            "change_1w": move(5),
            "change_1m": move(21),
            "change_1y": move(251),
            "as_of": days[-1] if days else None,
            "spark": [round(float(c), 4) for c in closes[-60:]],
        })
    return rows


def _market(watchlist: list[dict], data_root: Path) -> dict:
    """The market page: what moved, which way, and how broadly.

    Movers and breadth are computed from the same cached closes the strategies
    read, so the market summary and the signals can never disagree about what
    a price did. Breadth is the honest headline number here — an index up on
    four names is a different market from an index up on thirty, and only the
    advance/decline split shows which one happened.
    """
    by_region: dict[str, dict] = {}
    for region in ("india", "us"):
        names = [r for r in watchlist if r["region"] == region and r.get("change_1d")]
        if not names:
            continue
        ranked = sorted(names, key=lambda r: float(r["change_1d"]), reverse=True)
        advancing = sum(1 for r in names if float(r["change_1d"]) > 0)
        declining = sum(1 for r in names if float(r["change_1d"]) < 0)
        unchanged = len(names) - advancing - declining

        sectors: dict[str, list[float]] = {}
        for row in names:
            sectors.setdefault(row["sector"], []).append(float(row["change_1d"]))
        sector_rows = sorted(
            (
                {
                    "sector": sector,
                    "change": _s(Decimal(str(sum(moves) / len(moves)))),
                    "count": len(moves),
                    "advancing": sum(1 for m in moves if m > 0),
                }
                for sector, moves in sectors.items()
            ),
            key=lambda s: float(s["change"]),
            reverse=True,
        )

        by_region[region] = {
            "gainers": ranked[:5],
            "losers": list(reversed(ranked[-5:])),
            "breadth": {
                "advancing": advancing,
                "declining": declining,
                "unchanged": unchanged,
                "total": len(names),
            },
            "sectors": sector_rows,
        }

    return {"benchmarks": _benchmarks(data_root), "regions": by_region}


def _fundamentals(data_root: Path, watchlist: list[dict]) -> dict:
    """Filed fundamentals per instrument, with derived ratios priced to today.

    Ratios are computed here rather than cached because two of them (market
    cap, P/E, price-to-book) depend on the current price, and a cached ratio
    would quietly age against a moving quote.
    """
    path = data_root / "fundamentals.json"
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}

    from ..data.fundamentals import derive

    prices = {row["key"]: row.get("last") for row in watchlist}
    out: dict = {"companies": {}, "unavailable": document.get("unavailable", {})}
    for key, record in (document.get("companies") or {}).items():
        price = prices.get(key)
        ratios = derive(record, price=float(price) if price else None)
        merged = {k: _s(Decimal(str(v))) for k, v in ratios.items()}
        # Provider-only fields (beta, analyst target, dividend yield) are not
        # derivable from a filing, so they are carried through from the cache.
        # Derived values win on any overlap: a figure computed from a filed
        # EPS is more traceable than the same ratio from a vendor.
        for name, value in (record.get("ratios") or {}).items():
            if name not in merged:
                merged[name] = _s(Decimal(str(value)))
        out["companies"][key] = {
            "entity": record.get("entity"),
            "cik": record.get("cik"),
            "source": record.get("source"),
            "provider": record.get("provider"),
            "extras_provider": record.get("extras_provider"),
            "series": record.get("series", {}),
            "ratios": merged,
        }
    return out


def _corporate_actions(data_root: Path, watchlist: list[dict]) -> dict:
    """Dividends and splits, with a trailing yield where one can be computed."""
    path = data_root / "corporate_actions.json"
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}

    prices = {row["key"]: row.get("last") for row in watchlist}
    today = date.today()
    out: dict = {}
    for key, record in (document.get("instruments") or {}).items():
        dividends = record.get("dividends") or []
        # Trailing twelve months, by ex-date. A yield built from anything
        # longer would flatter a company that has cut its dividend.
        recent = [
            d for d in dividends
            if d.get("date") and (today - date.fromisoformat(d["date"])).days <= 365
        ]
        paid = sum(Decimal(str(d["amount"])) for d in recent if d.get("amount"))
        price = prices.get(key)
        yield_pct = None
        if price and Decimal(str(price)) > 0 and paid > 0:
            yield_pct = _s(paid / Decimal(str(price)))
        out[key] = {
            "dividends": dividends[:12],
            "splits": record.get("splits") or [],
            "ttm_paid": _s(paid) if paid > 0 else None,
            "ttm_count": len(recent),
            "yield": yield_pct,
        }
    return out


def _mechanics(engine: BacktestEngine, feed: LiveFeed) -> dict:
    """The constants the run actually used, for the page to quote back.

    The walkthrough on the dashboard explains how a suggestion is produced, and
    every number it states is read from here rather than typed into the copy —
    so retuning the engine cannot leave the explanation describing a system
    that no longer exists.
    """
    config = engine.config
    # The two strategies describe their own entry tests, so the walkthrough can
    # state the actual rules rather than a paraphrase that rots when they are
    # retuned. Each is read off the live strategy config, not typed into copy.
    rules = []
    for strategy in engine.strategies:
        cfg = getattr(strategy, "config", None)
        if cfg is None:
            continue
        if hasattr(cfg, "breakout_period"):
            if getattr(cfg, "enable_pullback", False):
                rules.append({
                    "book": "Short-term",
                    "name": "Buy the dip inside an uptrend",
                    "tests": [
                        f"price above its {cfg.trend_ma}-day average "
                        "(only buys dips in things already trending up)",
                        f"{cfg.rsi_period}-day RSI below {cfg.rsi_entry:.0f} "
                        "(a sharp, short drop rather than a slow bleed)",
                    ],
                    "exit": f"sold when RSI recovers past {cfg.rsi_exit:.0f}, "
                            f"or at the stop, or after {cfg.max_holding_days} days",
                })
            if getattr(cfg, "enable_breakout", False):
                rules.append({
                    "book": "Short-term",
                    "name": "Buy a breakout that volume confirms",
                    "tests": [
                        f"closes above its highest price in {cfg.breakout_period} days",
                        f"ADX above {cfg.breakout_min_adx:.0f} "
                        "(the move has real direction, not chop)",
                        f"volume at least {cfg.min_volume_ratio:.1f}x its "
                        f"{cfg.volume_ma}-day average",
                    ],
                    "exit": f"stop {cfg.stop_atr_multiple} ATR away, target "
                            f"{cfg.reward_risk_ratio}x that distance, closed after "
                            f"{cfg.max_holding_days} days either way",
                })
        elif hasattr(cfg, "momentum_lookback"):
            months = round(cfg.momentum_lookback / 21)
            skip = round(cfg.momentum_skip / 21)
            rules.append({
                "book": "Long-term",
                "name": "Hold the strongest steady risers",
                "tests": [
                    f"ranked on {months}-month gain, ignoring the last "
                    f"{skip} month (recent noise is skipped deliberately)",
                    f"{cfg.fast_ma}-day average above the {cfg.slow_ma}-day",
                    f"ADX above {cfg.min_adx:.0f}, and the gain must be positive",
                ],
                "exit": f"dropped once it falls {cfg.exit_rank_buffer} places below "
                        f"the top {cfg.max_holdings}",
            })

    return {
        "names": len(feed.entries),
        "regions": len(feed.as_of),
        "sessions": len(feed.data.all_days()),
        "rules": rules,
        "stop_atr_multiple": _s(getattr(
            next((getattr(s, "config", None) for s in engine.strategies
                  if hasattr(getattr(s, "config", None), "stop_atr_multiple")), None),
            "stop_atr_multiple", None)),
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
    data_root: Path | None = None,
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

    # Built once: the market summary is derived from the same rows the
    # watchlist shows, so the two can never disagree about a price.
    watchlist = _watchlist(engine, feed, orders, positions)

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
        "watchlist": watchlist,
        "market": _market(watchlist, data_root or Path("data/live")),
        "fundamentals": _fundamentals(data_root or Path("data/live"), watchlist),
        "corporate_actions": _corporate_actions(
            data_root or Path("data/live"), watchlist
        ),
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
    return (
        build_snapshot(engine, feed, live_config, report, data_root=data_root),
        report,
    )


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
