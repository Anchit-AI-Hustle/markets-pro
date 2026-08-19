"""Screener: composite ranking, regime selection, and peer/sector comparison.

Uses the same deterministic synthetic generators as the strategy tests
(:mod:`autotrader.data.synthetic`) rather than hand-typed bars — building 260
sessions of coherent OHLC by hand is impractical, and the generators are
already the project's answer to "verify mechanics, not a specific market".
"""

import json
import unittest
from datetime import date
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.money import FXRates
from autotrader.data.bars import MarketDataSet
from autotrader.data.livefeed import LiveFeed
from autotrader.data.synthetic import (
    business_days,
    generate_oscillating_series,
    generate_trending_series,
)
from autotrader.data.universe import UniverseEntry
from autotrader.screener.core import (
    build_snapshot,
    screen_instrument,
    screen_universe,
    sector_performance,
)

_TICK = Decimal("0.01")


def _entry(symbol: str, sector: str) -> UniverseEntry:
    return UniverseEntry(
        symbol=symbol,
        yahoo=symbol,
        exchange="NASDAQ",
        region="us",
        currency="USD",
        kind="equity",
        sector=sector,
        name=symbol,
    )


def _instrument(entry: UniverseEntry) -> Instrument:
    return Instrument(
        symbol=entry.symbol,
        region=entry.region_code,
        asset_class=AssetClass.EQUITY,
        currency=entry.currency,
        tick_size=_TICK,
        lot_size=Decimal("1"),
        name=entry.name,
        sector=entry.sector,
    )


#: symbol -> (sector, generator, kwargs). TUP/EDOWN are cleanly trending so
#: their regime and direction are unambiguous; TFLAT/EFLAT are range-bound
#: peers in the same sectors, used to test the sector-relative adjustment.
_SPECS = {
    "TUP": ("tech", generate_trending_series, {"daily_drift": 0.004, "seed": 1}),
    "TFLAT": ("tech", generate_oscillating_series, {"drift": 0.0002, "amplitude": 0.03, "seed": 2}),
    "EDOWN": ("energy", generate_trending_series, {"daily_drift": -0.004, "seed": 3}),
    "EFLAT": ("energy", generate_oscillating_series, {"drift": 0.0001, "amplitude": 0.03, "seed": 4}),
}


def _build_feed() -> tuple[LiveFeed, list[date]]:
    days = business_days(date(2025, 1, 2), 260)
    entries: list[UniverseEntry] = []
    instruments: list[Instrument] = []
    data = MarketDataSet()
    for symbol, (sector, generator, kwargs) in _SPECS.items():
        entry = _entry(symbol, sector)
        entries.append(entry)
        instruments.append(_instrument(entry))
        data.add(entry.key, generator(entry.key, days, **kwargs))
    feed = LiveFeed(
        instruments=tuple(instruments),
        entries=tuple(entries),
        data=data,
        fx=FXRates("USD", {}),
        as_of={"us": days[-1]},
    )
    return feed, days


class TestScreenUniverse(unittest.TestCase):
    def test_screens_every_ready_instrument(self):
        feed, _days = _build_feed()
        results = screen_universe(feed)
        self.assertEqual({r.key for r in results}, {e.key for e in feed.entries})

    def test_sorted_descending_by_score(self):
        feed, _ = _build_feed()
        scores = [r.score for r in screen_universe(feed)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_strong_uptrend_is_bullish_strong_downtrend_is_bearish(self):
        feed, _ = _build_feed()
        by_key = {r.key: r for r in screen_universe(feed)}
        self.assertEqual(by_key["US:TUP"].signal, "bullish")
        self.assertEqual(by_key["US:EDOWN"].signal, "bearish")

    def test_peer_relative_momentum_ranks_leader_above_laggard_in_same_sector(self):
        feed, _ = _build_feed()
        by_key = {r.key: r for r in screen_universe(feed)}
        leader, laggard = by_key["US:TUP"], by_key["US:TFLAT"]
        self.assertEqual(leader.sector, laggard.sector)
        self.assertIsNotNone(leader.relative_momentum_long)
        self.assertIsNotNone(laggard.relative_momentum_long)
        self.assertGreater(leader.relative_momentum_long, laggard.relative_momentum_long)
        self.assertGreater(leader.score, laggard.score)

    def test_not_enough_history_is_excluded_not_raised(self):
        days = business_days(date(2025, 1, 2), 30)  # short of required_bars
        entry = _entry("SHORT", "tech")
        instrument = _instrument(entry)
        data = MarketDataSet()
        data.add(entry.key, generate_trending_series(entry.key, days))
        feed = LiveFeed(
            instruments=(instrument,),
            entries=(entry,),
            data=data,
            fx=FXRates("USD", {}),
            as_of={"us": days[-1]},
        )
        self.assertEqual(screen_universe(feed), [])

    def test_screen_instrument_returns_none_pre_warmup(self):
        days = business_days(date(2025, 1, 2), 30)
        entry = _entry("SHORT", "tech")
        series = generate_trending_series(entry.key, days)
        window = series.window(days[-1])
        self.assertIsNone(screen_instrument(entry.key, window, entry))

    def test_empty_feed_returns_empty(self):
        feed = LiveFeed(
            instruments=(), entries=(), data=MarketDataSet(), fx=FXRates("USD", {}), as_of={}
        )
        self.assertEqual(screen_universe(feed), [])


class TestSectorPerformance(unittest.TestCase):
    def test_tech_outranks_energy(self):
        feed, _ = _build_feed()
        sectors = sector_performance(screen_universe(feed))
        by_sector = {s.sector: s for s in sectors}
        self.assertGreater(
            by_sector["tech"].avg_momentum_long, by_sector["energy"].avg_momentum_long
        )
        self.assertEqual(sectors[0].sector, "tech")

    def test_counts_cover_every_result_sorted_descending(self):
        feed, _ = _build_feed()
        results = screen_universe(feed)
        sectors = sector_performance(results)
        self.assertEqual(sum(s.count for s in sectors), len(results))
        moms = [s.avg_momentum_long for s in sectors]
        self.assertEqual(moms, sorted(moms, reverse=True))


class TestVolatilityBucket(unittest.TestCase):
    def test_every_result_has_a_valid_bucket(self):
        feed, _ = _build_feed()
        for result in screen_universe(feed):
            self.assertIn(result.volatility_bucket, {"low", "medium", "high", "unknown"})


class TestSnapshot(unittest.TestCase):
    def test_snapshot_is_json_serialisable_and_shaped(self):
        feed, _ = _build_feed()
        results = screen_universe(feed)
        sectors = sector_performance(results)
        snapshot = build_snapshot(results, sectors)
        payload = json.loads(json.dumps(snapshot))
        self.assertEqual(payload["count"], len(results))
        self.assertIn("top_stocks", payload)
        self.assertIn("top_industries", payload)
        self.assertEqual(len(payload["results"]), len(results))
        self.assertEqual(len(payload["top_industries"]), len(sectors))


if __name__ == "__main__":
    unittest.main()
