"""CLI: refresh the live daily-bar cache.

Usage::

    PYTHONPATH=src python3 -m autotrader.data.fetch --regions india us --out data/live

Exit code is non-zero if any symbol failed, but one bad symbol never aborts
the run — a single delisted or halted name must not block the whole nightly
refresh. Failed symbols keep their previous cache file, so the build degrades
to slightly stale data rather than a hole in the universe.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .universe import UNIVERSES, universe
from .yahoo import FetchError, _http_get_json, fetch_daily, parse_chart, write_cache


def fetch_usdinr() -> str:
    """Last completed close of the USD/INR rate, as a string."""
    payload = _http_get_json(
        "https://query1.finance.yahoo.com/v8/finance/chart/INR=X?range=5d&interval=1d"
    )
    rows, _ = parse_chart(payload, today=datetime.now(timezone.utc).date())
    if not rows:
        raise FetchError("no completed USD/INR sessions in payload")
    return rows[-1].close


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the live daily-bar cache from Yahoo Finance"
    )
    parser.add_argument(
        "--regions", nargs="+", default=sorted(UNIVERSES), choices=sorted(UNIVERSES)
    )
    parser.add_argument("--out", default="data/live", help="cache root directory")
    parser.add_argument(
        "--range", dest="range_", default="2y", help="history window, e.g. 1y, 2y, 5y"
    )
    parser.add_argument("--pause", type=float, default=0.4, help="seconds between requests")
    args = parser.parse_args(argv)

    root = Path(args.out)
    failures: list[str] = []
    for region in args.regions:
        for entry in universe(region):
            try:
                rows, currency = fetch_daily(entry, range_=args.range_)
                if not rows:
                    raise FetchError("no completed sessions in payload")
                write_cache(root, entry, rows, currency)
                print(f"{entry.region}/{entry.symbol}: {len(rows)} bars through {rows[-1].day}")
            except FetchError as error:
                failures.append(entry.symbol)
                print(f"{entry.region}/{entry.symbol}: FAILED — {error}", file=sys.stderr)
            time.sleep(args.pause)

    try:
        rate = fetch_usdinr()
        fx_path = root / "fx.json"
        fx_path.parent.mkdir(parents=True, exist_ok=True)
        fx_path.write_text(
            json.dumps(
                {
                    "USDINR": rate,
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
                indent=1,
            )
            + "\n"
        )
        print(f"fx: USDINR {rate}")
    except FetchError as error:
        failures.append("INR=X")
        print(f"fx: FAILED — {error}", file=sys.stderr)

    if failures:
        print(f"{len(failures)} symbol(s) failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
