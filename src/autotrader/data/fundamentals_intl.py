"""Fundamentals for listings the SEC does not cover — India in particular.

Why this exists separately from ``fundamentals.py``: EDGAR is keyless and
official but US-only. For NSE listings there is no equivalent open filing API.
Every route that needs no key was tested and rejected:

* **NSE and BSE company APIs** return ``403`` to automated clients, including
  the cookie-seeded flow their own site uses.
* **Yahoo's quoteSummary** is crumb-gated and the crumb endpoint rate-limits
  datacenter addresses, which is exactly what a CI runner is.
* **Commercial aggregators** expose the numbers only through their frontend's
  private payloads. Those are undocumented, change without notice, and using
  them is against the terms of the sites that publish them.

What remains is a documented API on a free tier, which needs a key the account
holder creates. This module is that integration, written so it does nothing
at all until a key exists and the page keeps saying "not available" until then
— an absent fundamental stays honest rather than becoming a guess.

Set ``ALPHAVANTAGE_KEY`` in the environment (or ``alphavantage_key`` in
``config/live.json``) and the nightly refresh starts filling Indian pages.
The free tier allows 25 calls a day, which covers the Indian universe once
daily with room to spare.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

_ENDPOINT = "https://www.alphavantage.co/query?function=OVERVIEW&symbol={symbol}&apikey={key}"
_USER_AGENT = "MarketsPro/1.0 (anchit.tandon@gmail.com)"

#: Free tier: 25 requests a day. The Indian universe is 17 names, so one pass
#: fits with room spare; anything beyond this stops rather than burning the
#: allowance a partial refresh would waste.
DAILY_BUDGET = 22

#: Alpha Vantage field → the name the rest of the app already uses, so an
#: Indian page renders through exactly the same code as a US one.
_FIELDS = {
    "MarketCapitalization": "market_cap",
    "PERatio": "pe_ratio",
    "PriceToBookRatio": "price_to_book",
    "ProfitMargin": "net_margin",
    "OperatingMarginTTM": "operating_margin",
    "ReturnOnEquityTTM": "return_on_equity",
    "ReturnOnAssetsTTM": "return_on_assets",
    "BookValue": "book_value_per_share",
    "QuarterlyRevenueGrowthYOY": "revenue_growth",
    "QuarterlyEarningsGrowthYOY": "earnings_growth",
    "DividendYield": "dividend_yield",
    "EPS": "eps",
    "Beta": "beta",
    "AnalystTargetPrice": "analyst_target",
}


def api_key(config: dict | None = None) -> str | None:
    """The key, from the environment or the live config. None means disabled."""
    key = os.environ.get("ALPHAVANTAGE_KEY", "").strip()
    if not key and config:
        key = str(config.get("alphavantage_key", "")).strip()
    return key or None


def _number(value: object) -> float | None:
    """Alpha Vantage returns '-' and 'None' as strings for missing figures."""
    if value in (None, "", "-", "None", "0"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_one(symbol: str, key: str, *, timeout: float = 25.0) -> dict | None:
    url = _ENDPOINT.format(symbol=urllib.parse.quote(symbol), key=urllib.parse.quote(key))
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)

    # The free tier answers 200 with a note when the allowance is spent, and
    # an empty object for a symbol it does not carry.
    if payload.get("Note") or payload.get("Information"):
        raise RuntimeError(str(payload.get("Note") or payload.get("Information"))[:120])
    if not payload.get("Symbol"):
        return None

    ratios = {}
    for source, name in _FIELDS.items():
        value = _number(payload.get(source))
        if value is not None:
            ratios[name] = value
    if not ratios:
        return None
    return {
        "entity": payload.get("Name"),
        "provider": "Alpha Vantage",
        "as_of": payload.get("LatestQuarter"),
        "ratios": ratios,
        "series": {},          # the free tier carries ratios, not statements
    }


def refresh(root: Path, config: dict | None = None, *, pause: float = 1.0) -> dict:
    """Fill in what EDGAR cannot cover, if a key is configured."""
    from .universe import universe

    key = api_key(config)
    path = root / "fundamentals.json"
    document = (
        json.loads(path.read_text()) if path.exists()
        else {"version": 1, "companies": {}, "unavailable": {}}
    )

    if not key:
        print(
            "no ALPHAVANTAGE_KEY set — Indian fundamentals stay marked "
            "unavailable, which is what the page already says"
        )
        return document

    used = 0
    for entry in universe("india"):
        if used >= DAILY_BUDGET:
            print(f"stopping at {used} calls to stay inside the free daily allowance")
            break
        # Alpha Vantage indexes NSE names under their BSE listing.
        candidates = (f"{entry.symbol}.BSE", f"{entry.symbol}.NSE")
        record = None
        for candidate in candidates:
            try:
                used += 1
                record = fetch_one(candidate, key)
            except Exception as error:  # noqa: BLE001 — one symbol must not stop the run
                print(f"fundamentals {entry.symbol}: {error}")
                record = None
                break
            if record:
                break
            time.sleep(pause)
        if record:
            document["companies"][entry.key] = record
            document["unavailable"].pop(entry.key, None)
            print(f"fundamentals {entry.symbol}: {len(record['ratios'])} ratios")
        else:
            document["unavailable"][entry.key] = (
                "the configured provider does not carry this listing"
            )
        time.sleep(pause)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1) + "\n")
    return document


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Fill non-US fundamentals from a keyed free provider"
    )
    parser.add_argument("--out", default="data/live")
    parser.add_argument("--config", default="config/live.json")
    args = parser.parse_args(argv)

    config = None
    config_path = Path(args.config)
    if config_path.exists():
        config = json.loads(config_path.read_text())
    document = refresh(Path(args.out), config)
    print(f"{len(document['companies'])} companies with fundamentals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
