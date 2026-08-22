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

Two providers are supported because coverage differs and neither is obvious
from the outside:

* **Alpha Vantage** (``ALPHAVANTAGE_KEY``) — verified against a live key:
  ``OVERVIEW`` returns a full record for ``IBM`` and an **empty object** for
  ``RELIANCE.BSE``. It indexes Indian symbols for search but carries no
  fundamentals for them. It is still useful: it supplies beta, analyst target
  price, dividend yield and PEG for US names, none of which EDGAR publishes.
* **Twelve Data** (``TWELVEDATA_KEY``) — its keyless catalogue endpoint lists
  Reliance on NSE with full metadata, so the instrument is in its universe.
  Whether the statistics endpoint is on the free plan can only be settled with
  a key, which is why ``probe()`` exists: it answers that in one call before
  anything is built on top of it.

Either key is optional and everything degrades to "not available" without one,
because an absent fundamental is honest and a guessed one is not.
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


def api_key(config: dict | None = None, provider: str = "alphavantage") -> str | None:
    """The key for one provider, from the environment or the live config."""
    env = {"alphavantage": "ALPHAVANTAGE_KEY", "twelvedata": "TWELVEDATA_KEY"}[provider]
    key = os.environ.get(env, "").strip()
    if not key and config:
        key = str(config.get(env.lower(), "")).strip()
    return key or None


_TWELVE = "https://api.twelvedata.com/statistics?symbol={symbol}&apikey={key}"

#: Twelve Data's statistics payload → the names the app already renders.
_TWELVE_FIELDS = {
    ("valuations_metrics", "trailing_pe"): "pe_ratio",
    ("valuations_metrics", "price_to_book_mrq"): "price_to_book",
    ("valuations_metrics", "market_capitalization"): "market_cap",
    ("financials", "profit_margin"): "net_margin",
    ("financials", "operating_margin"): "operating_margin",
    ("financials", "return_on_equity_ttm"): "return_on_equity",
    ("financials", "return_on_assets_ttm"): "return_on_assets",
    ("stock_price_summary", "beta"): "beta",
    ("dividends_and_splits", "forward_annual_dividend_yield"): "dividend_yield",
}


def fetch_twelve(symbol: str, key: str, *, timeout: float = 25.0) -> dict | None:
    """One instrument from Twelve Data's statistics endpoint."""
    url = _TWELVE.format(symbol=urllib.parse.quote(symbol), key=urllib.parse.quote(key))
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)

    if payload.get("code") or payload.get("status") == "error":
        raise RuntimeError(str(payload.get("message") or payload)[:140])
    stats = payload.get("statistics") or {}
    if not stats:
        return None

    ratios = {}
    for (group, field), name in _TWELVE_FIELDS.items():
        value = _number((stats.get(group) or {}).get(field))
        if value is not None:
            ratios[name] = value
    if not ratios:
        return None
    return {
        "entity": None,
        "provider": "Twelve Data",
        "as_of": None,
        "ratios": ratios,
        "series": {},
    }


def probe(config: dict | None = None) -> dict:
    """Answer, in one call per provider, whether it carries Indian figures.

    Written because a provider listing an instrument in its catalogue does not
    mean its fundamentals endpoint covers it — that difference cost a wasted
    signup once and should not cost another.
    """
    findings = {}
    av = api_key(config, "alphavantage")
    if av:
        try:
            findings["alphavantage"] = (
                "carries Indian fundamentals" if fetch_one("RELIANCE.BSE", av)
                else "no Indian fundamentals (US only)"
            )
        except Exception as error:  # noqa: BLE001
            findings["alphavantage"] = f"error: {error}"
    else:
        findings["alphavantage"] = "no key set"

    td = api_key(config, "twelvedata")
    if td:
        try:
            findings["twelvedata"] = (
                "carries Indian fundamentals" if fetch_twelve("RELIANCE:NSE", td)
                else "no Indian fundamentals on this plan"
            )
        except Exception as error:  # noqa: BLE001
            findings["twelvedata"] = f"error: {error}"
    else:
        findings["twelvedata"] = "no key set"
    return findings


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


def refresh(
    root: Path, config: dict | None = None, *, pause: float = 1.0,
    force: bool = False,
) -> dict:
    """Fill in what EDGAR cannot cover, using whichever provider has a key."""
    from .universe import universe

    path = root / "fundamentals.json"
    document = (
        json.loads(path.read_text()) if path.exists()
        else {"version": 1, "companies": {}, "unavailable": {}}
    )

    twelve = api_key(config, "twelvedata")
    alpha = api_key(config, "alphavantage")
    if not twelve and not alpha:
        print(
            "no provider key set — Indian fundamentals stay marked unavailable, "
            "which is what the page already says"
        )
        return document

    # The free tier allows 25 calls a day on Alpha Vantage. The nightly job
    # runs twice and Vercel rebuilds on every push, so without a date guard a
    # busy day would spend the allowance before the evening refresh needed it.
    from datetime import date as _date

    today = _date.today().isoformat()
    if document.get("intl_fetched_on") == today and not force:
        print(f"provider fundamentals already fetched today ({today}); skipping")
        return document
    document["intl_fetched_on"] = today

    used = 0
    for entry in universe("india"):
        if used >= DAILY_BUDGET:
            print(f"stopping at {used} calls to stay inside the free daily allowance")
            break
        record = None
        # Twelve Data first: its catalogue lists NSE instruments, and its free
        # allowance is far larger. Alpha Vantage is tried only as a fallback,
        # and is known not to carry Indian fundamentals.
        if twelve:
            try:
                used += 1
                record = fetch_twelve(f"{entry.symbol}:NSE", twelve)
            except Exception as error:  # noqa: BLE001
                print(f"fundamentals {entry.symbol} (twelvedata): {error}")
        if record is None and alpha:
            try:
                used += 1
                record = fetch_one(f"{entry.symbol}.BSE", alpha)
            except Exception as error:  # noqa: BLE001
                print(f"fundamentals {entry.symbol} (alphavantage): {error}")

        if record:
            document["companies"][entry.key] = record
            document["unavailable"].pop(entry.key, None)
            print(f"fundamentals {entry.symbol}: {len(record['ratios'])} ratios")
        else:
            document["unavailable"][entry.key] = (
                "the configured provider does not carry fundamentals for this "
                "listing"
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
    parser.add_argument(
        "--probe", action="store_true",
        help="ask each configured provider whether it carries Indian figures",
    )
    args = parser.parse_args(argv)

    config = None
    config_path = Path(args.config)
    if config_path.exists():
        config = json.loads(config_path.read_text())
    if args.probe:
        for provider, finding in probe(config).items():
            print(f"{provider:<14} {finding}")
        return 0

    document = refresh(Path(args.out), config)
    print(f"{len(document['companies'])} companies with fundamentals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
