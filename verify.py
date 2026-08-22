#!/usr/bin/env python3
"""Logic-accuracy gate.

Runs the full test suite, prints a per-module breakdown, and exits non-zero
unless **every** test passes.

What "100% accuracy" means here, precisely: every implemented behaviour matches
its hand-computed expected value, and the structural invariants (no lookahead,
the accounting identity, venue settlement rules, determinism) hold across a full
backtest. It does **not** mean, and cannot mean, that the strategies will be
profitable. See the "What is not claimed" section of the README.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

MODULES = [
    ("tests.test_money", "Money, FX, rounding"),
    ("tests.test_calendar", "Trading calendars & settlement"),
    ("tests.test_indicators", "Technical indicators"),
    ("tests.test_bars", "Bars & lookahead guard"),
    ("tests.test_position", "FIFO lots & realized P&L"),
    ("tests.test_portfolio", "Multi-currency ledger"),
    ("tests.test_costs", "Regional costs & slippage"),
    ("tests.test_sizing", "Position sizing"),
    ("tests.test_risk", "Risk limits & kill-switches"),
    ("tests.test_exits", "Stops, targets, trailing, time"),
    ("tests.test_simulator", "Order fill simulation"),
    ("tests.test_metrics", "Performance metrics"),
    ("tests.test_strategy", "Signal generation"),
    ("tests.test_engine", "End-to-end engine invariants"),
    ("tests.test_persistence", "Database row mapping"),
    ("tests.test_web", "Dashboard rendering & routes"),
    ("tests.test_universe", "Live universe identities"),
    ("tests.test_yahoo", "Quote parsing & cache"),
    ("tests.test_livefeed", "Live cache → engine adapter"),
    ("tests.test_data_quality", "Live cache freshness & sanity"),
    ("tests.test_signals", "Signal snapshot contract"),
    ("tests.test_screener", "Universe screener ranking"),
    ("tests.test_broker", "Execution caps & journal"),
    ("tests.test_auth", "Sign-in & state sync"),
    ("tests.test_broker_link", "Broker links & order guards"),
    ("tests.test_tab_data", "Tab data correctness"),
]

BAR = "=" * 74


def run_module(name: str) -> tuple[int, int, int, float]:
    """Return ``(run, failures, errors, seconds)`` for one test module."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(name)
    stream = open("/dev/null", "w") if sys.platform != "win32" else None
    runner = unittest.TextTestRunner(stream=stream, verbosity=0)
    started = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - started
    if stream:
        stream.close()
    return result.testsRun, len(result.failures), len(result.errors), elapsed


def check_coverage() -> list[str]:
    """Test modules on disk that this script does not run.

    Without this, adding a test file and forgetting to list it here would make
    the gate quietly report a smaller total and still claim 100%.
    """
    listed = {name.rsplit(".", 1)[-1] for name, _ in MODULES}
    on_disk = {
        path.stem for path in (ROOT / "tests").glob("test_*.py")
    }
    return sorted(on_disk - listed)


def main() -> int:
    print(BAR)
    print("autotrader — logic accuracy verification")
    print(BAR)

    missing = check_coverage()
    if missing:
        print("\nFAILED — test modules exist but are not registered in verify.py:")
        for name in missing:
            print(f"  tests/{name}.py")
        print("\nAdd them to MODULES so they are covered by the gate.")
        return 1

    print(f"{'Module':<34}{'Tests':>7}{'Pass':>7}{'Fail':>6}{'Time':>9}")
    print("-" * 74)

    total = passed = failed = 0
    total_time = 0.0
    broken: list[str] = []

    for module, label in MODULES:
        try:
            run, failures, errors, elapsed = run_module(module)
        except Exception as exc:                     # import error, bad module
            print(f"{label:<34}{'ERROR':>7}  {exc}")
            broken.append(module)
            failed += 1
            continue
        bad = failures + errors
        total += run
        passed += run - bad
        failed += bad
        total_time += elapsed
        status = f"{run - bad:>7}{bad:>6}"
        print(f"{label:<34}{run:>7}{status}{elapsed:>8.2f}s")
        if bad:
            broken.append(module)

    print("-" * 74)
    rate = (passed / total * 100) if total else 0.0
    print(f"{'TOTAL':<34}{total:>7}{passed:>7}{failed:>6}{total_time:>8.2f}s")
    print(BAR)
    print(f"Accuracy: {passed}/{total} checks passed ({rate:.2f}%)")

    if failed:
        print(f"\nFAILED — {failed} check(s) did not pass in: {', '.join(broken)}")
        print("Run `python -m unittest discover -s tests -t . -v` for detail.")
        return 1

    print("\nVERIFIED: every implemented behaviour matches its expected value,")
    print("and all structural invariants hold:")
    print("  - no lookahead: no strategy ever observed a bar after its decision date")
    print("  - accounting identity: equity == cash-in + realized + unrealized - costs")
    print("  - venue rules: China T+1 blocks same-session round trips; board lots held")
    print("  - determinism: identical inputs produce identical equity curves")
    print()
    print("This verifies CORRECTNESS OF LOGIC, not profitability. No backtest,")
    print("however clean, establishes that a strategy will make money in future.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
