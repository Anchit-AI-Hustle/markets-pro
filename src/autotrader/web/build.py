"""Build the static dashboard.

The demo run uses **synthetic** price data, which is stated on the page. It
exercises the full engine across four regions and two books; it says nothing
about whether the strategies work, because generated data has no real structure
to find. Point the engine at real history to get a result worth interpreting.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.instrument import AssetClass, Instrument
from ..core.money import FXRates
from ..data.bars import MarketDataSet
from ..data.synthetic import (
    business_days,
    generate_oscillating_series,
    generate_series,
    generate_trending_series,
)
from ..engine.backtest import BacktestConfig, BacktestEngine
from ..engine.metrics import PerformanceReport
from ..execution.costs import SlippageModel
from ..execution.simulator import ExecutionConfig
from ..portfolio.sizing import SizingConfig
from ..risk.limits import RiskConfig
from ..strategy.long_term import LongTermConfig, LongTermStrategy
from ..strategy.short_term import ShortTermConfig, ShortTermStrategy
from .render import render_dashboard

FX = FXRates(
    "USD",
    {"INR": Decimal("83.20"), "CNY": Decimal("7.10"), "RUB": Decimal("90.50")},
)

#: symbol, region, currency, tick, lot, start price, sector, series shape, seed
UNIVERSE_SPEC = [
    ("AAPL", "US", "USD", "0.01", "1", "180", "tech", "trend", 101),
    ("MSFT", "US", "USD", "0.01", "1", "370", "tech", "trend", 102),
    ("XOM", "US", "USD", "0.01", "1", "105", "energy", "oscillate", 103),
    ("JPM", "US", "USD", "0.01", "1", "165", "financials", "random", 104),
    ("RELIANCE", "IN", "INR", "0.05", "1", "2450", "energy", "trend", 105),
    ("TCS", "IN", "INR", "0.05", "1", "3600", "tech", "oscillate", 106),
    ("HDFCBANK", "IN", "INR", "0.05", "1", "1550", "financials", "random", 107),
    ("600519", "CN", "CNY", "0.01", "100", "1680", "consumer", "trend", 108),
    ("000858", "CN", "CNY", "0.01", "100", "148", "consumer", "oscillate", 109),
    ("GAZP", "RU", "RUB", "0.01", "1", "165", "energy", "random", 110),
    ("SBER", "RU", "RUB", "0.01", "1", "270", "financials", "trend", 111),
]


def build_universe(sessions: list[date]) -> tuple[list[Instrument], MarketDataSet]:
    """Instrument definitions plus synthetic price series for each."""
    instruments: list[Instrument] = []
    data = MarketDataSet()

    for symbol, region, currency, tick, lot, price, sector, shape, seed in UNIVERSE_SPEC:
        instrument = Instrument(
            symbol=symbol,
            region=region,
            asset_class=AssetClass.EQUITY,
            currency=currency,
            tick_size=Decimal(tick),
            lot_size=Decimal(lot),
            name=symbol,
            sector=sector,
        )
        instruments.append(instrument)

        start = Decimal(price)
        tick_dec = Decimal(tick)
        if shape == "trend":
            series = generate_trending_series(
                instrument.key, sessions, start_price=start,
                daily_drift=0.0009, noise=0.011, seed=seed, tick_size=tick_dec,
            )
        elif shape == "oscillate":
            series = generate_oscillating_series(
                instrument.key, sessions, start_price=start,
                amplitude=0.09, period=45, drift=0.0004,
                tick_size=tick_dec, seed=seed,
            )
        else:
            from ..data.synthetic import SeriesSpec
            series = generate_series(
                instrument.key, sessions,
                SeriesSpec(
                    start_price=start, annual_drift=0.05, annual_volatility=0.24,
                    tick_size=tick_dec, seed=seed,
                ),
            )
        data.add(instrument.key, series)

    return instruments, data


def run_demo_backtest(*, sessions: int = 750) -> PerformanceReport:
    """Run both books across four regions on synthetic data."""
    days = business_days(date(2022, 1, 3), sessions)
    instruments, data = build_universe(days)

    config = BacktestConfig(
        start=days[0],
        end=days[-1],
        base_currency="USD",
        starting_cash={
            "USD": Decimal("250000"),
            "INR": Decimal("20800000"),   # ~250k USD
            "CNY": Decimal("1775000"),    # ~250k USD
            "RUB": Decimal("22625000"),   # ~250k USD
        },
        sizing=SizingConfig(
            risk_per_trade=Decimal("0.0075"),
            max_position_weight=Decimal("0.12"),
            min_order_notional=Decimal("500"),
            max_cash_utilisation=Decimal("0.90"),
            max_volume_participation=Decimal("0.03"),
        ),
        risk=RiskConfig(
            max_open_positions=12,
            max_positions_per_region=4,
            max_region_weight=Decimal("0.45"),
            max_sector_weight=Decimal("0.40"),
            max_gross_leverage=Decimal("0.95"),
            max_drawdown_halt=Decimal("0.25"),
            daily_loss_limit=Decimal("0.06"),
        ),
        execution=ExecutionConfig(max_volume_participation=Decimal("0.05")),
        slippage=SlippageModel(
            half_spread_bps=Decimal("2"), impact_coefficient=Decimal("12")
        ),
    )

    engine = BacktestEngine(
        instruments=instruments,
        data=data,
        strategies=[
            LongTermStrategy(LongTermConfig(max_holdings=6,
                                            total_allocation=Decimal("0.55"))),
            ShortTermStrategy(ShortTermConfig(max_concurrent=5)),
        ],
        config=config,
        fx=FX,
    )
    return engine.run()


def build_static(
    out_dir: Path,
    *,
    report: PerformanceReport | None = None,
    tests_passed: int = 0,
    tests_total: int = 0,
    signals: dict | None = None,
    subtitle: str | None = None,
    screener: dict | None = None,
) -> Path:
    """Write ``out_dir/markets-pro/index.html`` and return its path."""
    report = report or run_demo_backtest()
    target_dir = out_dir / "markets-pro"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "index.html"
    html = render_dashboard(
        report,
        title="Markets Pro",
        subtitle=subtitle
        or (
            f"{report.start_day} to {report.end_day} &middot; 4 markets &middot; "
            f"base {report.base_currency} &middot; "
            "<strong>synthetic demo data</strong>"
        ),
        tests_passed=tests_passed,
        tests_total=tests_total,
        signals=signals,
        screener=screener,
    )
    target.write_text(html, encoding="utf-8")
    return target


def _try_live(data_root: Path, config_path: Path) -> tuple[dict, PerformanceReport] | None:
    """Live signals from the committed cache, or ``None`` to fall back to demo.

    The deploy must never break because a fetch failed: any problem here means
    the site ships the (clearly labelled) synthetic dashboard instead of no
    site at all. The failure is printed so the deploy log shows what happened.
    """
    if not data_root.exists():
        return None
    try:
        from ..signals.live import generate

        return generate(data_root, config_path)
    except Exception as error:  # noqa: BLE001 — degrade to demo, loudly
        print(f"live signal build failed ({error!r}); falling back to demo data")
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the markets-pro dashboard")
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--sessions", type=int, default=750)
    parser.add_argument("--tests-passed", type=int, default=0)
    parser.add_argument("--tests-total", type=int, default=0)
    parser.add_argument("--live", type=Path, default=None,
                        help="live cache root; renders real-data signals when present")
    parser.add_argument("--live-config", type=Path, default=Path("config/live.json"))
    args = parser.parse_args(argv)

    signals = None
    subtitle = None
    live = _try_live(args.live, args.live_config) if args.live else None
    if live is not None:
        signals, report = live
        fresh = sum(1 for order in signals["orders"] if order["fresh"])
        headline = (
            f"<strong>{fresh} trade{'' if fresh == 1 else 's'} suggested today</strong>"
            if fresh
            else "<strong>No trades suggested today</strong>"
        )
        latest = max(signals["as_of"].values()) if signals.get("as_of") else report.end_day
        subtitle = (
            f"{headline} &middot; Indian and US stocks &middot; "
            f"prices through {latest}, refreshed after each market close"
        )
    else:
        report = run_demo_backtest(sessions=args.sessions)

    # The screener runs on every data refresh and commits its own file; the
    # build reads it if present rather than re-running it, so the page always
    # shows the same ranking the refresh recorded.
    screener = None
    if args.live:
        screener_path = args.live / "screener.json"
        if screener_path.exists():
            try:
                import json as _json

                screener = _json.loads(screener_path.read_text())
            except (OSError, ValueError) as error:
                print(f"screener unreadable ({error}); the tab will say so")

    path = build_static(
        args.out, report=report, screener=screener,
        tests_passed=args.tests_passed, tests_total=args.tests_total,
        signals=signals, subtitle=subtitle,
    )
    print(report.summary())
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
