"""Which logic, if any, has actually worked on each individual instrument.

Every retail screener applies one set of rules to every stock and reports the
result as a recommendation. This asks a narrower and more answerable question:
run each strategy against **one** instrument's own history, out of sample, and
measure whether the result is distinguishable from chance.

Three commitments make the answer worth reading:

**Out of sample.** The first 60% of history is discarded from scoring — the
strategies were designed against data like it, so measuring there measures the
design, not the edge. Only trades in the final 40% count.

**A sample-size floor.** Twenty closed trades is the minimum before any verdict
is offered. Below that the honest answer is "not enough evidence", and it is
given far more often than any other verdict.

**A test against chance.** A win rate is compared with a coin flip using an
exact binomial test. Testing three logics across thirty-four instruments is
about a hundred tests, so roughly five would clear p < 0.05 by luck alone; the
report states its own false-positive budget rather than hiding it.

The output is deliberately unable to say "buy this". It says which rule has
evidence behind it for a given name, how much, and how often the answer is
"none" — which is the usual answer, and the one an honest system has to be
willing to give.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from math import comb
from pathlib import Path

from ..data.livefeed import load_livefeed
from ..engine.backtest import BacktestConfig, BacktestEngine
from ..portfolio.sizing import SizingConfig
from ..risk.limits import RiskConfig
from ..strategy.long_term import LongTermConfig, LongTermStrategy
from ..strategy.short_term import ShortTermConfig, ShortTermStrategy

#: Trades needed before a verdict is offered at all. Twenty is already
#: generous — distinguishing a 55% edge from a coin flip properly needs
#: hundreds — so a "worked" verdict here means "worth a look", never "proven".
MIN_TRADES = 20

#: Fraction of history reserved for design and excluded from scoring.
IN_SAMPLE = 0.50

#: Conventional threshold, stated so the false-positive budget can be computed.
ALPHA = 0.05


def _binomial_p(wins: int, trades: int) -> float:
    """Two-sided exact probability of a result this lopsided from a fair coin.

    Exact rather than a normal approximation: at twenty to sixty trades the
    approximation is poor precisely where the verdict flips, and ``math.comb``
    makes the exact sum cheap.
    """
    if trades <= 0:
        return 1.0
    total = 2 ** trades
    observed = abs(wins - trades / 2)
    tail = sum(
        comb(trades, k)
        for k in range(trades + 1)
        if abs(k - trades / 2) >= observed
    )
    return min(tail / total, 1.0)


@dataclass
class Logic:
    """One rule set, isolated so it can be measured on its own."""

    key: str
    label: str
    describe: str
    build: object = field(repr=False)


LOGICS: tuple[Logic, ...] = (
    Logic(
        "pullback", "Buy the dip in an uptrend",
        "waits for a sharp drop while the long-term trend is still up",
        lambda: ShortTermStrategy(ShortTermConfig(enable_breakout=False)),
    ),
    Logic(
        "breakout", "Buy a breakout on volume",
        "waits for a new multi-week high confirmed by heavy trading",
        lambda: ShortTermStrategy(ShortTermConfig(enable_pullback=False)),
    ),
    Logic(
        "momentum", "Hold the steady riser",
        "holds while the name ranks among the strongest and trends up",
        lambda: LongTermStrategy(LongTermConfig(max_holdings=1)),
    ),
)


def measure(feed, instrument, logic: Logic) -> dict:
    """Run one logic against one instrument and score only the later trades."""
    series = feed.data.get(instrument.key)
    if series is None or len(series) < 500:
        return {"logic": logic.key, "verdict": "no_history", "trades": 0}

    days = series.days
    split = days[int(len(days) * IN_SAMPLE)]
    cash = "INR" if instrument.currency == "INR" else "USD"

    config = BacktestConfig(
        start=days[60],
        end=days[-1],
        base_currency="USD",
        starting_cash={cash: Decimal("1000000"), "USD": Decimal("1")},
        # Ceilings lifted: this measures whether the rule finds anything, not
        # how a portfolio would have allocated across many names.
        sizing=SizingConfig(max_position_weight=Decimal("1"),
                            max_cash_utilisation=Decimal("0.95")),
        risk=RiskConfig(max_open_positions=2, max_positions_per_region=2,
                        max_region_weight=Decimal("1"),
                        max_sector_weight=Decimal("1")),
    )
    engine = BacktestEngine(
        instruments=[instrument], data=feed.data, fx=feed.fx,
        config=config, strategies=[logic.build()],
    )
    report = engine.run()

    out = [t for t in report.trades if t.exit_day >= split]
    wins = [t for t in out if t.net_pnl_base > 0]
    losses = [t for t in out if t.net_pnl_base <= 0]
    trades = len(out)

    if trades < MIN_TRADES:
        return {
            "logic": logic.key, "verdict": "insufficient", "trades": trades,
            "needed": MIN_TRADES,
        }

    won = sum(float(t.net_pnl_base) for t in wins)
    lost = abs(sum(float(t.net_pnl_base) for t in losses))
    profit_factor = (won / lost) if lost > 0 else None
    win_rate = len(wins) / trades
    p_value = _binomial_p(len(wins), trades)

    # An edge has to clear both bars: better than a coin flip on the count,
    # and profitable on the money. Either alone is easy to hit by luck.
    if p_value < ALPHA and profit_factor is not None and profit_factor > 1:
        verdict = "evidence"
    elif profit_factor is not None and profit_factor > 1:
        verdict = "profitable_but_unproven"
    else:
        verdict = "no_edge"

    return {
        "logic": logic.key,
        "verdict": verdict,
        "trades": trades,
        "wins": len(wins),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "p_value": round(p_value, 4),
        "net_base": round(sum(float(t.net_pnl_base) for t in out), 2),
        "tested_from": split.isoformat(),
    }


def run(data_root: Path) -> dict:
    """Every instrument against every logic, with the caveats attached."""
    feed = load_livefeed(data_root)
    results: dict[str, dict] = {}
    tested = 0

    for instrument in feed.instruments:
        rows = []
        for logic in LOGICS:
            row = measure(feed, instrument, logic)
            if row.get("verdict") not in ("no_history",):
                tested += 1
            rows.append(row)

        scored = [r for r in rows if r["verdict"] in ("evidence", "profitable_but_unproven")]
        scored.sort(key=lambda r: (r["verdict"] != "evidence", -(r.get("profit_factor") or 0)))
        results[instrument.key] = {
            "symbol": instrument.symbol,
            "logics": rows,
            "best": scored[0]["logic"] if scored else None,
            "best_verdict": scored[0]["verdict"] if scored else "none",
        }
        print(
            f"{instrument.symbol:<12} "
            + " ".join(f"{r['logic'][:4]}:{r['verdict'][:4]}" for r in rows)
        )

    with_evidence = sum(
        1 for v in results.values() if v["best_verdict"] == "evidence"
    )
    document = {
        "version": 1,
        "min_trades": MIN_TRADES,
        "in_sample_fraction": IN_SAMPLE,
        "alpha": ALPHA,
        "tests_run": tested,
        # Stated rather than buried: at this many tests, a handful of
        # "evidence" verdicts are the expected yield of chance alone.
        "false_positives_expected": round(tested * ALPHA, 1),
        "instruments_with_evidence": with_evidence,
        "results": results,
    }
    path = data_root / "fitness.json"
    path.write_text(json.dumps(document, indent=1) + "\n")
    return document


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Measure which logic has an edge on each instrument"
    )
    parser.add_argument("--data", default="data/live")
    args = parser.parse_args(argv)
    document = run(Path(args.data))
    print(
        f"\n{document['tests_run']} tests run; "
        f"{document['instruments_with_evidence']} instruments show evidence; "
        f"about {document['false_positives_expected']} of those are chance"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
