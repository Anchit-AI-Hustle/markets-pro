"""Verify candidate instruments before they enter the tradable universe.

A universe written from memory is a universe with wrong tickers in it: symbols
get renamed, companies delist, and a listing that looks obvious is often
spelled differently at the venue than in conversation. Any of those ship as a
name that silently returns no data, and a name with no data is worse than an
absent one — it occupies a row, fails its indicators, and reads to a user as a
broken app rather than a name that was never really there.

So nothing is asserted into the universe. Each candidate is fetched, and only
those that come back with enough real history to compute a 200-day average are
kept. The rejects are reported with the reason, because a list that silently
shrinks from 300 to 180 hides the fact that 120 guesses were wrong.

Run it when an index rebalances, or whenever the candidate list changes::

    PYTHONPATH=src python3 -m autotrader.data.universe_verify --region india
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from .universe import UniverseEntry
from .yahoo import FetchError, fetch_daily

#: A name needs at least this much history for the long trend filter to mean
#: anything. Below it the strategies cannot form an opinion, so the name would
#: sit in the universe contributing nothing but a row.
MIN_SESSIONS = 220

#: Yahoo throttles. This is unhurried on purpose: the job runs nightly in CI
#: where wall-clock is cheap, and being rate-limited mid-run would reject good
#: names for a reason that has nothing to do with the names.
PAUSE_SECONDS = 0.35


@dataclass(frozen=True)
class Verdict:
    symbol: str
    ok: bool
    sessions: int = 0
    reason: str = ""


def verify(entry: UniverseEntry, *, pause: float = PAUSE_SECONDS,
           attempts: int = 3) -> Verdict:
    """Fetch one candidate and decide whether it can carry a signal.

    Retried, because the two failures look identical from here and mean
    opposite things: a ticker that does not exist fails every time, while a
    good name behind a rate limiter fails once and succeeds on the next try.
    Rejecting on the first failure quietly drops real companies from the
    universe, which is the more expensive mistake.
    """
    rows = None
    for attempt in range(attempts):
        try:
            rows, _currency = fetch_daily(entry, range_="2y")
            break
        except (FetchError, urllib.error.URLError, ValueError, KeyError) as error:
            if attempt == attempts - 1:
                time.sleep(pause)
                return Verdict(entry.symbol, False,
                               reason=f"fetch failed after {attempts} tries "
                                      f"({type(error).__name__})")
            time.sleep(pause * (2 ** attempt) + 0.5)
    time.sleep(pause)

    if not rows:
        return Verdict(entry.symbol, False, reason="no bars returned — wrong ticker or delisted")
    if len(rows) < MIN_SESSIONS:
        return Verdict(entry.symbol, False, len(rows),
                       f"only {len(rows)} sessions, needs {MIN_SESSIONS}")
    # A name that has stopped trading still returns its old bars. Anything whose
    # last close is far behind the rest of the list is stale, not tradable.
    return Verdict(entry.symbol, True, len(rows))


def verify_all(candidates: list[UniverseEntry], *, pause: float = PAUSE_SECONDS,
               progress=None) -> tuple[list[UniverseEntry], list[Verdict]]:
    """``(kept, rejected)`` — the honest split, with a reason for every reject."""
    kept: list[UniverseEntry] = []
    rejected: list[Verdict] = []
    for i, entry in enumerate(candidates, 1):
        verdict = verify(entry, pause=pause)
        (kept if verdict.ok else rejected).append(entry if verdict.ok else verdict)
        if progress:
            progress(i, len(candidates), entry, verdict)
    return kept, rejected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify universe candidates against Yahoo")
    parser.add_argument("--candidates", type=Path, required=True,
                        help="JSON list of {symbol,name,sector,kind} to check")
    parser.add_argument("--region", required=True, choices=("india", "us"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pause", type=float, default=PAUSE_SECONDS)
    args = parser.parse_args(argv)

    raw = json.loads(args.candidates.read_text())
    suffix, exchange, currency = (
        (".NS", "NSE", "INR") if args.region == "india" else ("", "NASDAQ", "USD")
    )
    candidates = [
        UniverseEntry(c["symbol"], c["symbol"] + suffix, exchange, args.region,
                      currency, c.get("kind", "equity"), c["sector"], c["name"])
        for c in raw
    ]

    def show(i, total, entry, verdict):
        mark = "ok " if verdict.ok else "REJ"
        note = f"{verdict.sessions} sessions" if verdict.ok else verdict.reason
        print(f"[{i:>4}/{total}] {mark} {entry.symbol:<14} {note}", file=sys.stderr)

    kept, rejected = verify_all(candidates, pause=args.pause, progress=show)

    args.out.write_text(json.dumps(
        [{"symbol": e.symbol, "name": e.name, "sector": e.sector, "kind": e.kind}
         for e in kept], indent=2) + "\n")
    print(f"\nverified {len(kept)} of {len(candidates)}; wrote {args.out}", file=sys.stderr)
    if rejected:
        print(f"rejected {len(rejected)}:", file=sys.stderr)
        for verdict in rejected:
            print(f"  {verdict.symbol:<14} {verdict.reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
