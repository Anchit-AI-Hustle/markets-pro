"""Build the static dashboard.

The demo run uses **synthetic** price data, which is stated on the page. It
exercises the full engine across four regions and two books; it says nothing
about whether the strategies work, because generated data has no real structure
to find. Point the engine at real history to get a result worth interpreting.
"""

from __future__ import annotations

import argparse
import json
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

#: Files written beside the page and fetched by the browser on demand. The
#: subdomain serves the document itself at "/" through a rewrite, so each of
#: these needs a rewrite of its own or it resolves only under /markets-pro/ --
#: reachable, but not from where the page appears to live. Tested against
#: vercel.json, so adding a fourth without routing it fails the build's suite.
SIDECARS = ("stocks.json", "funds.json")

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
    funds: dict | None = None,
    funds_source: Path | None = None,
    fitness: dict | None = None,
    supabase: dict | None = None,
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
        funds=funds,
        fitness=fitness,
        supabase=supabase,
    )
    target.write_text(html, encoding="utf-8")

    # Detail data lives beside the page and is fetched only when a reader
    # opens a stock, keeping the first load small.
    if signals is not None:
        import json as _json

        from .render import _stock_index

        (target_dir / SIDECARS[0]).write_text(
            _json.dumps(_stock_index(signals, screener)), encoding="utf-8"
        )
        if funds_source is not None and funds_source.exists():
            (target_dir / SIDECARS[1]).write_text(
                funds_source.read_text(), encoding="utf-8"
            )
    return target


def supabase_settings(config_path: Path) -> dict | None:
    """The Supabase project this build signs readers in against, or ``None``.

    Environment wins over the committed file so a deploy can point at a
    different project without a commit. Both halves must be present: a URL
    without a key would render a sign-in button that could not authenticate,
    which is worse than no button at all.
    """
    import os

    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text()).get("supabase") or {}
        except (OSError, ValueError) as error:
            print(f"supabase config unreadable ({error}); sign-in will be omitted")
            config = {}

    url = os.environ.get("SUPABASE_URL") or config.get("url") or ""
    key = os.environ.get("SUPABASE_ANON_KEY") or config.get("anon_key") or ""
    if not url or not key:
        return None
    return {"url": url.rstrip("/"), "anon_key": key}


def check_csp_allows(supabase: dict, vercel_config: Path) -> None:
    """Fail the build if the deployed CSP would block the auth calls.

    The project origin has to appear in two files that nothing otherwise keeps
    in agreement: the config this build reads, and the ``Content-Security-Policy``
    header in ``vercel.json``. When they drift, every sign-in fails in
    production with a console error and nowhere else --- the same shape of bug
    as the sidecar URLs that were correct locally and 404ed once deployed.
    Failing here is cheap and loud; Vercel keeps the previous deployment
    serving, so the cost of a mismatch is a red build rather than a dead site.
    """
    if not vercel_config.exists():
        return
    try:
        document = json.loads(vercel_config.read_text())
    except (OSError, ValueError):
        return
    origin = supabase["url"]
    for header_rule in document.get("headers", []):
        for header in header_rule.get("headers", []):
            if header.get("key", "").lower() != "content-security-policy":
                continue
            policy = header.get("value", "")
            if "connect-src" in policy and origin not in policy:
                raise SystemExit(
                    f"{vercel_config}: connect-src does not permit {origin}, so "
                    "every sign-in would fail once deployed. Add the origin to "
                    "the connect-src directive, or drop the supabase block from "
                    "the build config to ship without sign-in."
                )


def _try_live(data_root: Path, config_path: Path) -> tuple[dict, PerformanceReport] | None:
    """Live signals from the committed cache, or ``None`` to fall back to demo.

    The deploy must never break because a fetch failed: any problem here means
    the site ships the (clearly labelled) synthetic dashboard instead of no
    site at all. The failure is printed so the deploy log shows what happened.
    """
    if not data_root.exists():
        return None

    # A provider key may be configured on the host that builds this site
    # rather than on the job that refreshes the data. Honour either: this is
    # best-effort and rate-guarded to one pass a day, and a failure here just
    # leaves the pages saying "not available", which they already do.
    try:
        import os

        from ..data.fundamentals_intl import api_key, enrich_us

        config = (
            json.loads(config_path.read_text()) if config_path.exists() else None
        )
        if api_key(config) and os.environ.get("SKIP_PROVIDER_FUNDAMENTALS") != "1":
            # US extras only: no free tier was found that carries Indian
            # fundamentals, so attempting them would spend the allowance to
            # learn nothing.
            enrich_us(data_root, config)
    except Exception as error:  # noqa: BLE001 — never fail a deploy over this
        print(f"provider fundamentals skipped ({error!r})")

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

    # Fund NAVs: only the summary counts are needed at build time — the
    # schemes themselves are fetched by the browser from the copied file.
    funds = None
    if args.live:
        funds_path = args.live / "funds.json"
        if funds_path.exists():
            try:
                import json as _fjson

                document = _fjson.loads(funds_path.read_text())
                funds = {k: v for k, v in document.items() if k != "schemes"}
            except (OSError, ValueError) as error:
                print(f"funds cache unreadable ({error}); the tab will say so")

    # The evidence study runs against its own deep cache and is committed
    # like the rest; the build only reads it.
    fitness = None
    for candidate in (Path("data/research/fitness.json"),
                      (args.live / "fitness.json") if args.live else None):
        if candidate and candidate.exists():
            try:
                import json as _kjson

                fitness = _kjson.loads(candidate.read_text())
                break
            except (OSError, ValueError) as error:
                print(f"fitness unreadable ({error}); the tab will say so")

    supabase = supabase_settings(args.live_config)
    if supabase:
        check_csp_allows(supabase, Path("vercel.json"))
        print(f"sign-in enabled against {supabase['url']}")
    else:
        print("no supabase project configured; the page ships without sign-in")

    path = build_static(
        args.out, report=report, screener=screener, funds=funds, fitness=fitness,
        supabase=supabase,
        funds_source=(args.live / "funds.json") if args.live else None,
        tests_passed=args.tests_passed, tests_total=args.tests_total,
        signals=signals, subtitle=subtitle,
    )
    print(report.summary())
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
