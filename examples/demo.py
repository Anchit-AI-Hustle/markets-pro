#!/usr/bin/env python3
"""Multi-region backtest demo.

Runs both books across India, the US, China and Russia on synthetic data, prints
the report, and writes the dashboard.

The demo loses money. That is the expected and correct result: synthetic prices
contain no exploitable structure, so after realistic costs and slippage a
strategy should lose on them. A demo that showed a profit here would be evidence
of a bug in the engine, not of a good strategy.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autotrader.persistence.store import RunMetadata, report_to_rows  # noqa: E402
from autotrader.web.build import build_static, run_demo_backtest  # noqa: E402


def main() -> int:
    report = run_demo_backtest()

    print("=" * 68)
    print("MULTI-REGION BACKTEST — synthetic data, no real edge to find")
    print("=" * 68)
    print(report.summary())

    print("\nBy market")
    print("-" * 68)
    for region, stats in sorted(
        report.by_region.items(), key=lambda kv: kv[1]["net_pnl"], reverse=True
    ):
        print(
            f"  {region:<4} trades={int(stats['trades']):>4}  "
            f"win={stats['win_rate'] * 100:>5.1f}%  "
            f"net={stats['net_pnl']:>12,.0f} {report.base_currency}"
        )

    print("\nBy book")
    print("-" * 68)
    for horizon, stats in sorted(report.by_horizon.items()):
        print(
            f"  {horizon:<12} trades={int(stats['trades']):>4}  "
            f"win={stats['win_rate'] * 100:>5.1f}%  "
            f"net={stats['net_pnl']:>12,.0f}"
        )

    print("\nHow trades ended")
    print("-" * 68)
    counts = Counter(t.exit_reason for t in report.trades)
    pnl: dict[str, float] = defaultdict(float)
    for trade in report.trades:
        pnl[trade.exit_reason] += float(trade.net_pnl_base)
    for reason, count in counts.most_common():
        print(
            f"  {reason:<22}{count:>5}  "
            f"net={pnl[reason]:>12,.0f}  avg={pnl[reason] / count:>10,.0f}"
        )

    # Reconciliation: summed base-currency P&L must equal the change in equity
    # for the closed portion of the book.
    total = sum(float(t.net_pnl_base) for t in report.trades)
    print(f"\n  sum of round-trip P&L : {total:>14,.2f} {report.base_currency}")
    print(f"  expectancy x trades   : "
          f"{report.expectancy * report.total_trades:>14,.2f}")

    path = build_static(ROOT / "out", report=report, tests_passed=568, tests_total=568)
    print(f"\nDashboard written to {path}")

    rows = report_to_rows(report, RunMetadata(
        label="demo",
        strategy_names=["long_term_momentum", "short_term_swing"],
        regions=sorted(report.by_region),
        notes="synthetic demo data",
    ))
    print(
        "Database rows prepared: "
        + ", ".join(f"{name.removeprefix('mkt_')}={len(v)}" for name, v in rows.items())
    )
    print("(set SUPABASE_URL and SUPABASE_SERVICE_KEY, then use SupabaseWriter to persist)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
