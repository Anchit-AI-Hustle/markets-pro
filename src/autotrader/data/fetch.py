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
import urllib.parse
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


def _prefer_fresher_series(
    previous: dict | None, candidate: dict
) -> tuple[dict, bool]:
    """Return the candidate unless it moves a benchmark's date horizon backward."""
    if not previous:
        return candidate, False
    previous_days = previous.get("days") or []
    candidate_days = candidate.get("days") or []
    if previous_days and (not candidate_days or candidate_days[-1] < previous_days[-1]):
        return previous, True
    return candidate, False


def fetch_benchmarks(root: Path, *, range_: str = "2y", pause: float = 0.3) -> list[str]:
    """Cache the indices, commodities and FX the market page quotes.

    Kept in one file rather than one per symbol: these are read together, as a
    single market summary, and never fed to the engine. A benchmark that fails
    is simply absent from the file — the page then shows the rest rather than
    inventing a level for it.
    """
    from .universe import BENCHMARKS

    path = root / "benchmarks.json"
    previous_series: dict = {}
    if path.exists():
        try:
            previous_series = (json.loads(path.read_text()).get("series") or {})
        except (OSError, json.JSONDecodeError, TypeError):
            previous_series = {}

    document: dict = {"version": 1, "series": {}}
    failed: list[str] = []
    for mark in BENCHMARKS:
        try:
            payload = _http_get_json(
                "https://query1.finance.yahoo.com/v8/finance/chart/"
                f"{urllib.parse.quote(mark.yahoo)}?range={range_}&interval=1d"
            )
            rows, currency = parse_chart(
                payload, today=datetime.now(timezone.utc).date()
            )
            if len(rows) < 2:
                raise FetchError("not enough completed sessions")
            candidate = {
                "label": mark.label,
                "group": mark.group,
                "kind": mark.kind,
                "currency": currency,
                "closes": [row.close for row in rows[-520:]],
                "days": [row.day.isoformat() for row in rows[-520:]],
            }
            selected, regressed = _prefer_fresher_series(
                previous_series.get(mark.yahoo), candidate
            )
            document["series"][mark.yahoo] = selected
            if regressed:
                failed.append(mark.yahoo)
                candidate_day = candidate["days"][-1] if candidate["days"] else "no data"
                print(
                    f"benchmark {mark.yahoo}: FAILED — provider response regressed "
                    f"from {selected['days'][-1]} to {candidate_day}; kept previous series",
                    file=sys.stderr,
                )
            else:
                print(f"benchmark {mark.yahoo}: {len(rows)} sessions")
        except FetchError as error:
            failed.append(mark.yahoo)
            if mark.yahoo in previous_series:
                document["series"][mark.yahoo] = previous_series[mark.yahoo]
            print(f"benchmark {mark.yahoo}: FAILED — {error}", file=sys.stderr)
        time.sleep(pause)

    document["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1) + "\n")
    return failed


def fetch_corporate_actions(root: Path, *, pause: float = 0.25) -> list[str]:
    """Dividends and splits per instrument, from the price feed's own events.

    Carried separately from the bar cache because they are sparse and change
    only when a company acts — refetching two years of events nightly costs
    one request per name and keeps the detail pages honest about what a price
    series has been adjusted for.
    """
    from .universe import universe

    document: dict = {"version": 1, "instruments": {}}
    failed: list[str] = []
    for region in ("india", "us"):
        for entry in universe(region):
            try:
                payload = _http_get_json(
                    "https://query1.finance.yahoo.com/v8/finance/chart/"
                    f"{urllib.parse.quote(entry.yahoo)}"
                    "?range=5y&interval=1d&events=div,split"
                )
                result = payload["chart"]["result"][0]
                events = result.get("events") or {}
                offset = int(result.get("meta", {}).get("gmtoffset", 0))

                def when(stamp: int, offset: int = offset) -> str:
                    return datetime.fromtimestamp(
                        stamp + offset, tz=timezone.utc
                    ).date().isoformat()

                dividends = [
                    {"date": when(int(row["date"])), "amount": row.get("amount")}
                    for row in (events.get("dividends") or {}).values()
                    if row.get("amount") is not None
                ]
                splits = [
                    {
                        "date": when(int(row["date"])),
                        "ratio": row.get("splitRatio")
                        or f"{row.get('numerator')}:{row.get('denominator')}",
                    }
                    for row in (events.get("splits") or {}).values()
                ]
                dividends.sort(key=lambda d: d["date"], reverse=True)
                splits.sort(key=lambda s: s["date"], reverse=True)
                document["instruments"][entry.key] = {
                    "dividends": dividends[:20],
                    "splits": splits[:10],
                }
                if dividends or splits:
                    print(
                        f"actions {entry.symbol}: {len(dividends)} dividends, "
                        f"{len(splits)} splits"
                    )
            except (FetchError, KeyError, IndexError, TypeError) as error:
                failed.append(entry.symbol)
                print(f"actions {entry.symbol}: FAILED — {error}", file=sys.stderr)
            time.sleep(pause)

    document["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = root / "corporate_actions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1) + "\n")
    return failed


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
        fetch_corporate_actions(root, pause=args.pause)
    except Exception as error:  # noqa: BLE001 — context is optional, bars are not
        print(f"corporate actions: FAILED — {error}", file=sys.stderr)

    try:
        benchmark_failures = fetch_benchmarks(root, pause=args.pause)
        failures.extend(benchmark_failures)
    except Exception as error:  # noqa: BLE001 — context is optional, bars are not
        print(f"benchmarks: FAILED — {error}", file=sys.stderr)

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
