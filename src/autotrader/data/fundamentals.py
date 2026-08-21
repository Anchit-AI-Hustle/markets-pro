"""Company fundamentals from SEC EDGAR — official filings, no API key.

Why this source and not a market-data vendor: EDGAR is the filings themselves,
free, rate-limited but unmetered, and it is the same XBRL every US financial
site is ultimately quoting. Nothing here is estimated, smoothed or modelled —
each figure is a tagged value from a 10-K or 10-Q, carried with the period it
covers and the form it came from so a reader can check it against the filing.

**Coverage is US-only, and that is a hard limit rather than an oversight.**
The SEC has no jurisdiction over NSE listings, and the Indian equivalents
(NSE and BSE company APIs) refuse automated access. Rather than fill Indian
pages with numbers from an unverifiable source, this module returns nothing
for them and the page says so — an absent fundamental is honest, an invented
one is not.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

#: SEC requires a declaring User-Agent with a contact address, and asks for no
#: more than ten requests a second. The nightly job makes about twenty.
_USER_AGENT = "MarketsPro/1.0 (anchit.tandon@gmail.com)"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

CACHE_VERSION = 1

#: Concepts to read, in preference order — filers tag the same idea under
#: different names, and the first one present wins.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss",),
    "operating_income": ("OperatingIncomeLoss",),
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "CommonStockSharesOutstanding",
    ),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
}


class FundamentalsError(RuntimeError):
    """A filing could not be fetched or parsed."""


def _get(url: str, *, retries: int = 3, timeout: float = 30.0):
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last = error
            time.sleep(1.5 * (attempt + 1))
    raise FundamentalsError(f"GET {url} failed: {last}")


def ticker_to_cik() -> dict[str, int]:
    """SEC's own ticker → CIK index."""
    payload = _get(_TICKERS_URL)
    return {
        str(row["ticker"]).upper(): int(row["cik_str"])
        for row in payload.values()
        if row.get("ticker")
    }


def _annual(facts: dict, names: tuple[str, ...], *, unit: str = "USD") -> list[dict]:
    """Annual (10-K) values for the first concept present, oldest first.

    Annual rather than quarterly on purpose: quarterly tags mix year-to-date
    and three-month figures depending on the filer, and silently summing those
    produces numbers that look plausible and are wrong.
    """
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for name in names:
        concept = gaap.get(name)
        if not concept:
            continue
        for unit_key in (unit, "USD/shares", "shares", "pure"):
            rows = concept.get("units", {}).get(unit_key)
            if not rows:
                continue
            annual = {}
            for row in rows:
                if row.get("form") != "10-K" or row.get("fp") != "FY":
                    continue
                # Full-year periods only: a 10-K also carries prior-quarter
                # comparatives, and those must not be read as the year.
                start, end = row.get("start"), row.get("end")
                if start and end and (
                    int(end[:4]) * 12 + int(end[5:7])
                    - (int(start[:4]) * 12 + int(start[5:7])) < 10
                ):
                    continue
                year = row.get("fy")
                if year is None:
                    continue
                annual[year] = {
                    "year": year,
                    "end": end,
                    "value": row.get("val"),
                    "form": row.get("form"),
                    "filed": row.get("filed"),
                }
            if annual:
                return [annual[y] for y in sorted(annual)][-6:]
    return []


def extract(facts: dict) -> dict:
    """Reduce a 3–20 MB companyfacts payload to the figures the page shows."""
    out: dict = {"entity": facts.get("entityName"), "series": {}}
    for label, names in CONCEPTS.items():
        unit = "USD/shares" if label == "eps_diluted" else (
            "shares" if label == "shares" else "USD"
        )
        rows = _annual(facts, names, unit=unit)
        if rows:
            out["series"][label] = rows
    return out


def latest(series: list[dict]) -> float | None:
    return float(series[-1]["value"]) if series else None


def derive(record: dict, *, price: float | None) -> dict:
    """Ratios computed from the filings, only where every input exists.

    A ratio with a missing input is omitted rather than defaulted. The whole
    value of using filings is that each number is traceable; a silently
    substituted zero would destroy that.
    """
    series = record.get("series", {})
    revenue = latest(series.get("revenue", []))
    net_income = latest(series.get("net_income", []))
    operating = latest(series.get("operating_income", []))
    assets = latest(series.get("assets", []))
    liabilities = latest(series.get("liabilities", []))
    equity = latest(series.get("equity", []))
    eps = latest(series.get("eps_diluted", []))
    shares = latest(series.get("shares", []))
    debt = latest(series.get("long_term_debt", []))

    out: dict = {}
    if revenue and net_income is not None:
        out["net_margin"] = net_income / revenue
    if revenue and operating is not None:
        out["operating_margin"] = operating / revenue
    if equity and net_income is not None and equity > 0:
        out["return_on_equity"] = net_income / equity
    if assets and net_income is not None and assets > 0:
        out["return_on_assets"] = net_income / assets
    if equity and debt is not None and equity > 0:
        out["debt_to_equity"] = debt / equity
    if assets and liabilities is not None and assets > 0:
        out["liabilities_to_assets"] = liabilities / assets
    if equity and shares and shares > 0:
        out["book_value_per_share"] = equity / shares
    if shares and price:
        out["market_cap"] = shares * price
    if price and eps and eps > 0:
        out["pe_ratio"] = price / eps
    if price and out.get("book_value_per_share"):
        bvps = out["book_value_per_share"]
        if bvps > 0:
            out["price_to_book"] = price / bvps

    # Revenue growth over the filed years, when at least two exist.
    revenues = series.get("revenue", [])
    if len(revenues) >= 2 and revenues[-2]["value"]:
        out["revenue_growth"] = (
            float(revenues[-1]["value"]) / float(revenues[-2]["value"]) - 1
        )
    incomes = series.get("net_income", [])
    if len(incomes) >= 2 and incomes[-2]["value"]:
        prior = float(incomes[-2]["value"])
        if prior > 0:
            out["earnings_growth"] = float(incomes[-1]["value"]) / prior - 1
    return out


def refresh(root: Path, *, pause: float = 0.2) -> dict:
    """Fetch and cache fundamentals for every US name in the universe."""
    from .universe import universe

    cik_map = ticker_to_cik()
    document: dict = {"version": CACHE_VERSION, "companies": {}, "unavailable": {}}

    for entry in universe("us"):
        cik = cik_map.get(entry.symbol)
        if cik is None:
            document["unavailable"][entry.key] = "no SEC filer matches this ticker"
            continue
        try:
            facts = _get(_FACTS_URL.format(cik=cik))
            record = extract(facts)
            record["cik"] = cik
            record["source"] = (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                f"&CIK={cik:010d}&type=10-K"
            )
            document["companies"][entry.key] = record
            print(f"fundamentals {entry.symbol}: {len(record['series'])} concepts")
        except FundamentalsError as error:
            document["unavailable"][entry.key] = str(error)
            print(f"fundamentals {entry.symbol}: FAILED — {error}")
        time.sleep(pause)

    # India is stated as unavailable rather than left silently empty, so the
    # page can explain the gap instead of just showing nothing.
    for entry in universe("india"):
        document["unavailable"][entry.key] = (
            "no free filings source: the SEC does not cover NSE listings, and "
            "the exchanges' own APIs refuse automated access"
        )

    path = root / "fundamentals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1) + "\n")
    return document


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Refresh SEC fundamentals cache")
    parser.add_argument("--out", default="data/live")
    args = parser.parse_args(argv)
    document = refresh(Path(args.out))
    print(
        f"\n{len(document['companies'])} companies cached, "
        f"{len(document['unavailable'])} unavailable"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
