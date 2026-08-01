"""Deterministic synthetic price data.

Used for tests and demos. Every generator is seeded, so a given seed always
produces the same series — a test that fails must fail reproducibly.

Synthetic data is for *verifying mechanics*, never for validating a strategy. A
strategy tuned on generated data has learned the generator, not a market.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ..core.calendar import TradingCalendar
from ..core.market import MarketSpec
from ..core.money import round_to_increment, to_decimal
from .bars import Bar, BarSeries


@dataclass
class SeriesSpec:
    """Parameters for one generated price series."""

    start_price: Decimal = Decimal("100")
    annual_drift: float = 0.08
    annual_volatility: float = 0.20
    intraday_range: float = 0.012      # typical high-low span as a fraction
    base_volume: int = 1_000_000
    tick_size: Decimal = Decimal("0.01")
    seed: int = 7


def generate_series(
    key: str,
    days: list[date],
    spec: SeriesSpec | None = None,
) -> BarSeries:
    """Geometric random walk sampled on ``days``, with plausible OHLC structure."""
    spec = spec or SeriesSpec()
    rng = random.Random(spec.seed)
    dt = 1.0 / 252.0
    mu = spec.annual_drift
    sigma = spec.annual_volatility
    price = float(spec.start_price)
    bars: list[Bar] = []

    for day in days:
        shock = rng.gauss(0.0, 1.0)
        # Ito-corrected GBM step keeps the realised drift equal to `annual_drift`.
        price = price * math.exp(
            (mu - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * shock
        )
        bars.append(_build_bar(day, price, spec, rng))

    return BarSeries(key, bars)


def generate_trending_series(
    key: str,
    days: list[date],
    *,
    start_price: Decimal = Decimal("100"),
    daily_drift: float = 0.002,
    noise: float = 0.003,
    seed: int = 11,
    tick_size: Decimal = Decimal("0.01"),
) -> BarSeries:
    """A cleanly trending series — used to assert that trend logic fires."""
    rng = random.Random(seed)
    spec = SeriesSpec(tick_size=tick_size)
    price = float(start_price)
    bars: list[Bar] = []
    for day in days:
        price *= 1.0 + daily_drift + rng.gauss(0.0, noise)
        bars.append(_build_bar(day, price, spec, rng))
    return BarSeries(key, bars)


def generate_oscillating_series(
    key: str,
    days: list[date],
    *,
    start_price: Decimal = Decimal("100"),
    amplitude: float = 0.08,
    period: int = 40,
    drift: float = 0.0006,
    tick_size: Decimal = Decimal("0.01"),
    seed: int = 13,
) -> BarSeries:
    """A sine wave on a rising trend — produces repeatable pullback setups."""
    rng = random.Random(seed)
    spec = SeriesSpec(tick_size=tick_size)
    base = float(start_price)
    bars: list[Bar] = []
    for i, day in enumerate(days):
        trend = base * (1.0 + drift * i)
        price = trend * (1.0 + amplitude * math.sin(2.0 * math.pi * i / period))
        bars.append(_build_bar(day, price, spec, rng))
    return BarSeries(key, bars)


def _build_bar(day: date, close: float, spec: SeriesSpec, rng: random.Random) -> Bar:
    """Wrap a close into a coherent OHLC bar with high >= max(o,c) etc."""
    span = abs(close) * spec.intraday_range
    open_price = close + rng.uniform(-span / 2, span / 2)
    high = max(open_price, close) + rng.uniform(0, span / 2)
    low = min(open_price, close) - rng.uniform(0, span / 2)
    low = max(low, 0.01)
    volume = int(spec.base_volume * rng.uniform(0.6, 1.6))

    tick = spec.tick_size
    o = round_to_increment(to_decimal(open_price), tick)
    h = round_to_increment(to_decimal(high), tick)
    l = round_to_increment(to_decimal(low), tick)
    c = round_to_increment(to_decimal(close), tick)

    # Rounding can invert the invariants; repair rather than emit an invalid bar.
    h = max(h, o, c)
    l = min(l, o, c)
    if l <= 0:
        l = tick
    return Bar(day=day, open=o, high=h, low=l, close=c, volume=Decimal(volume))


def sessions_for(spec: MarketSpec, start: date, end: date) -> list[date]:
    """Trading sessions for a market between two dates."""
    return TradingCalendar(spec).sessions(start, end)


def business_days(start: date, count: int) -> list[date]:
    """``count`` consecutive weekdays starting at or after ``start``."""
    out: list[date] = []
    cursor = start
    while len(out) < count:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out
