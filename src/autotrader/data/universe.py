"""Tradable universes for live signal generation.

The engine itself is universe-agnostic; this module is the single place that
says which real instruments the nightly signal run covers, and how each one is
named at every venue involved: Yahoo Finance for quotes, the exchange for
execution, and the broker basket for one-tap order handoff.

Curation policy: large, liquid names and index ETFs only. Signal quality
degrades fastest on illiquid tickers — wide spreads eat the systematic edge —
so breadth is deliberately traded away for executability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REGION_CODES = {"india": "IN", "us": "US"}


@dataclass(frozen=True)
class UniverseEntry:
    """One tradable instrument across its venue-specific identities."""

    symbol: str        # exchange trading symbol (what the broker basket needs)
    yahoo: str         # Yahoo Finance ticker (what the quote fetch needs)
    exchange: str      # "NSE" or a US listing venue
    region: str        # "india" | "us"
    currency: str      # "INR" | "USD"
    kind: str          # "equity" | "etf"
    sector: str        # sector bucket consumed by RiskConfig.max_sector_weight
    name: str          # human-readable, shown on the dashboard

    @property
    def region_code(self) -> str:
        return REGION_CODES[self.region]

    @property
    def key(self) -> str:
        return f"{self.region_code}:{self.symbol}"


#: Where the verified lists live. These are *outputs* of
#: :mod:`autotrader.data.universe_verify`, not hand-maintained files: every
#: symbol in them was fetched and returned at least a year of real history
#: before it was written. That matters more than it sounds — verifying this
#: list is what surfaced that TATAMOTORS had stopped resolving after the
#: demerger and had been silently absent from the product, and that ZOMATO and
#: GMRINFRA had both been renamed at the exchange.
_DATA = Path(__file__).parent / "universe_data"

#: Kept so the package still works if the data files are missing — a handful of
#: names is a degraded universe, but an import error is a dead application.
_FALLBACK = {
    "india": [("RELIANCE", "Reliance Industries", "energy", "equity"),
              ("HDFCBANK", "HDFC Bank", "financials", "equity"),
              ("INFY", "Infosys", "tech", "equity"),
              ("NIFTYBEES", "Nippon Nifty 50 ETF", "index", "index")],
    "us": [("AAPL", "Apple", "tech", "equity"),
           ("MSFT", "Microsoft", "tech", "equity"),
           ("JPM", "JPMorgan Chase", "financials", "equity"),
           ("SPY", "SPDR S&P 500 ETF", "index", "index")],
}

_VENUE = {
    "india": (".NS", "NSE", "INR"),
    "us": ("", "NASDAQ", "USD"),
}


def _load(region: str) -> tuple[UniverseEntry, ...]:
    """Build a region's universe from its verified list."""
    suffix, exchange, currency = _VENUE[region]
    path = _DATA / f"{region}.json"
    try:
        rows = [(r["symbol"], r["name"], r["sector"], r.get("kind", "equity"))
                for r in json.loads(path.read_text())]
    except (OSError, ValueError, KeyError):
        rows = _FALLBACK[region]
    return tuple(
        UniverseEntry(symbol, symbol + suffix, exchange, region, currency,
                      kind, sector, name)
        for symbol, name, sector, kind in rows
    )


_INDIA = _load("india")
_US = _load("us")

UNIVERSES: dict[str, tuple[UniverseEntry, ...]] = {"india": _INDIA, "us": _US}


def universe(region: str) -> tuple[UniverseEntry, ...]:
    """Every instrument covered in ``region``.

    ValueError rather than KeyError: a mistyped region is a caller error worth
    naming, and the message lists what is actually available.
    """
    try:
        return UNIVERSES[region]
    except KeyError:
        raise ValueError(
            f"unknown region {region!r}; expected one of {sorted(UNIVERSES)}"
        ) from None


def entry_for_key(key: str) -> UniverseEntry:
    """Look up a universe entry by its engine key ("IN:RELIANCE")."""
    for entries in UNIVERSES.values():
        for entry in entries:
            if entry.key == key:
                return entry
    raise KeyError(key)

@dataclass(frozen=True)
class Benchmark:
    """A reference series that is quoted but never traded.

    Indices, commodities and FX are shown for context — what the market did,
    what oil and gold did, where the rupee sits. They are deliberately kept out
    of ``UNIVERSES`` so nothing can generate an order against something that
    has no shares to buy.
    """

    yahoo: str
    label: str
    group: str        # "india" | "us" | "global" | "commodity" | "currency"
    kind: str         # "index" | "commodity" | "currency" | "volatility"


BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark("^NSEI", "Nifty 50", "india", "index"),
    Benchmark("^NSEBANK", "Nifty Bank", "india", "index"),
    Benchmark("^BSESN", "BSE Sensex", "india", "index"),
    Benchmark("^GSPC", "S&P 500", "us", "index"),
    Benchmark("^IXIC", "Nasdaq Composite", "us", "index"),
    Benchmark("^DJI", "Dow Jones", "us", "index"),
    Benchmark("^RUT", "Russell 2000", "us", "index"),
    Benchmark("^VIX", "Volatility (VIX)", "us", "volatility"),
    Benchmark("GC=F", "Gold", "commodity", "commodity"),
    Benchmark("CL=F", "Crude oil (WTI)", "commodity", "commodity"),
    Benchmark("SI=F", "Silver", "commodity", "commodity"),
    Benchmark("INR=X", "US dollar / rupee", "currency", "currency"),
    Benchmark("EURUSD=X", "Euro / US dollar", "currency", "currency"),
)

BENCHMARK_GROUPS: tuple[tuple[str, str], ...] = (
    ("india", "India"),
    ("us", "United States"),
    ("commodity", "Commodities"),
    ("currency", "Currencies"),
)
