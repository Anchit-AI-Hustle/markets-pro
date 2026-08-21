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

from dataclasses import dataclass

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


_INDIA: tuple[UniverseEntry, ...] = tuple(
    UniverseEntry(sym, f"{sym}.NS", "NSE", "india", "INR", kind, sector, name)
    for sym, kind, sector, name in [
        ("RELIANCE", "equity", "energy", "Reliance Industries"),
        ("HDFCBANK", "equity", "financials", "HDFC Bank"),
        ("ICICIBANK", "equity", "financials", "ICICI Bank"),
        ("INFY", "equity", "tech", "Infosys"),
        ("TCS", "equity", "tech", "Tata Consultancy Services"),
        ("LT", "equity", "industrials", "Larsen & Toubro"),
        ("SBIN", "equity", "financials", "State Bank of India"),
        ("BHARTIARTL", "equity", "telecom", "Bharti Airtel"),
        ("ITC", "equity", "consumer", "ITC"),
        ("TATAMOTORS", "equity", "auto", "Tata Motors"),
        ("MARUTI", "equity", "auto", "Maruti Suzuki"),
        ("ASIANPAINT", "equity", "consumer", "Asian Paints"),
        ("BAJFINANCE", "equity", "financials", "Bajaj Finance"),
        ("TITAN", "equity", "consumer", "Titan Company"),
        ("NIFTYBEES", "etf", "index", "Nippon Nifty 50 ETF"),
        ("BANKBEES", "etf", "index", "Nippon Bank Nifty ETF"),
        ("GOLDBEES", "etf", "commodity", "Nippon Gold ETF"),
    ]
)

_US: tuple[UniverseEntry, ...] = tuple(
    UniverseEntry(sym, sym, exch, "us", "USD", kind, sector, name)
    for sym, exch, kind, sector, name in [
        ("AAPL", "NASDAQ", "equity", "tech", "Apple"),
        ("MSFT", "NASDAQ", "equity", "tech", "Microsoft"),
        ("NVDA", "NASDAQ", "equity", "tech", "NVIDIA"),
        ("AMZN", "NASDAQ", "equity", "consumer", "Amazon"),
        ("GOOGL", "NASDAQ", "equity", "tech", "Alphabet"),
        ("META", "NASDAQ", "equity", "tech", "Meta Platforms"),
        ("TSLA", "NASDAQ", "equity", "auto", "Tesla"),
        ("JPM", "NYSE", "equity", "financials", "JPMorgan Chase"),
        ("UNH", "NYSE", "equity", "healthcare", "UnitedHealth"),
        ("XOM", "NYSE", "equity", "energy", "Exxon Mobil"),
        ("V", "NYSE", "equity", "financials", "Visa"),
        ("PG", "NYSE", "equity", "consumer", "Procter & Gamble"),
        ("COST", "NASDAQ", "equity", "consumer", "Costco"),
        ("AVGO", "NASDAQ", "equity", "tech", "Broadcom"),
        ("SPY", "NYSEARCA", "etf", "index", "SPDR S&P 500 ETF"),
        ("QQQ", "NASDAQ", "etf", "index", "Invesco QQQ"),
        ("IWM", "NYSEARCA", "etf", "index", "iShares Russell 2000 ETF"),
        ("GLD", "NYSEARCA", "etf", "commodity", "SPDR Gold Shares"),
    ]
)

UNIVERSES: dict[str, tuple[UniverseEntry, ...]] = {"india": _INDIA, "us": _US}


def universe(region: str) -> tuple[UniverseEntry, ...]:
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
