"""Adapter: the on-disk live cache → engine-ready instruments, bars and FX.

This is the seam between real market data and the backtest engine. Everything
past this module is identical for synthetic and live runs — same Bar/BarSeries
validation, same lookahead guard, same Decimal accounting — which is the point:
the signal run inherits every verified invariant of the research engine.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.instrument import AssetClass, Instrument
from ..core.money import FXRates
from .bars import Bar, BarSeries, MarketDataSet
from .universe import UniverseEntry, universe
from .yahoo import FetchError, read_cache

_TICK_SIZE = {"india": Decimal("0.05"), "us": Decimal("0.01")}
_FALLBACK_USDINR = Decimal("83.5")


@dataclass(frozen=True)
class LiveFeed:
    """Everything the engine needs, loaded from the committed cache."""

    instruments: tuple[Instrument, ...]
    entries: tuple[UniverseEntry, ...]
    data: MarketDataSet
    fx: FXRates
    as_of: dict[str, date]  # region -> last completed session in the cache


def _series_from_cache(document: dict, key: str) -> BarSeries:
    bars = [
        Bar(
            day=date.fromisoformat(row["day"]),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )
        for row in document["bars"]
    ]
    return BarSeries(key, bars)


def load_fx(root: Path) -> FXRates:
    """USD-base FX from the cached rate, falling back to a static rate.

    The fallback keeps the build deploying when the FX fetch failed; sizing
    precision suffers slightly, signal direction does not.
    """
    path = root / "fx.json"
    usdinr = _FALLBACK_USDINR
    if path.exists():
        try:
            usdinr = Decimal(json.loads(path.read_text())["USDINR"])
        except (KeyError, ValueError, ArithmeticError, json.JSONDecodeError):
            pass
    return FXRates("USD", {"INR": usdinr, "USD": Decimal("1")})


def load_livefeed(root: Path, regions: Sequence[str] = ("india", "us")) -> LiveFeed:
    """Load every cached symbol for the given regions.

    Symbols missing from the cache are skipped (a failed fetch must degrade
    coverage, not abort the build); an entirely empty region raises, because a
    signal page silently covering zero instruments would be worse than no page.
    """
    instruments: list[Instrument] = []
    entries: list[UniverseEntry] = []
    data = MarketDataSet()
    as_of: dict[str, date] = {}

    for region in regions:
        loaded = 0
        for entry in universe(region):
            try:
                document = read_cache(root, entry)
            except FetchError:
                continue
            series = _series_from_cache(document, entry.key)
            if not len(series):
                continue
            last_day = series.last_day
            if last_day is None:
                continue
            data.add(entry.key, series)
            instruments.append(
                Instrument(
                    symbol=entry.symbol,
                    region=entry.region_code,
                    asset_class=AssetClass.EQUITY,
                    currency=entry.currency,
                    tick_size=_TICK_SIZE[entry.region],
                    lot_size=Decimal("1"),
                    name=entry.name,
                    sector=entry.sector,
                )
            )
            entries.append(entry)
            if region not in as_of or last_day > as_of[region]:
                as_of[region] = last_day
            loaded += 1
        if loaded == 0:
            raise FetchError(f"live cache at {root} has no usable symbols for region {region!r}")

    return LiveFeed(
        instruments=tuple(instruments),
        entries=tuple(entries),
        data=data,
        fx=load_fx(root),
        as_of=as_of,
    )
