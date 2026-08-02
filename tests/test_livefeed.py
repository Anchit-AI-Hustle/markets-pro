"""Live-cache → engine adapter: instruments, bars and FX must arrive intact."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from autotrader.data.livefeed import load_fx, load_livefeed
from autotrader.data.universe import universe
from autotrader.data.yahoo import DailyRow, FetchError, write_cache


def seed_region(root: Path, region: str, *, days: int = 5, price: float = 100.0):
    start = date(2026, 7, 1)
    rows = []
    for i in range(days):
        day = start + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        p = price + i
        rows.append(
            DailyRow(day, f"{p:.4f}", f"{p + 2:.4f}", f"{p - 1:.4f}", f"{p + 1:.4f}", "5000")
        )
    for entry in universe(region):
        write_cache(root, entry, rows, entry.currency)
    return rows


class TestLoadLivefeed(unittest.TestCase):
    def test_loads_both_regions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = seed_region(root, "india")
            seed_region(root, "us")
            feed = load_livefeed(root)

        self.assertEqual(len(feed.instruments), len(universe("india")) + len(universe("us")))
        self.assertEqual(feed.as_of["india"], rows[-1].day)
        keys = {inst.key for inst in feed.instruments}
        self.assertIn("IN:RELIANCE", keys)
        self.assertIn("US:AAPL", keys)
        series = feed.data.series("IN:RELIANCE")
        self.assertEqual(series.last_day, rows[-1].day)
        self.assertEqual(series[0].close, Decimal("101.0000"))

    def test_instrument_venue_conventions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_region(root, "india")
            seed_region(root, "us")
            feed = load_livefeed(root)
        by_key = {inst.key: inst for inst in feed.instruments}
        reliance = by_key["IN:RELIANCE"]
        self.assertEqual(reliance.currency, "INR")
        self.assertEqual(reliance.tick_size, Decimal("0.05"))
        self.assertNotEqual(reliance.sector, "unknown")
        aapl = by_key["US:AAPL"]
        self.assertEqual(aapl.currency, "USD")
        self.assertEqual(aapl.tick_size, Decimal("0.01"))

    def test_missing_symbols_degrade_but_empty_region_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_region(root, "india")
            # us region entirely absent
            with self.assertRaises(FetchError):
                load_livefeed(root)
            feed = load_livefeed(root, regions=("india",))
        self.assertEqual(len(feed.instruments), len(universe("india")))


class TestLoadFx(unittest.TestCase):
    def test_reads_cached_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fx.json").write_text(json.dumps({"USDINR": "88.1234"}))
            fx = load_fx(root)
        self.assertEqual(fx.rate("USD", "INR"), Decimal("88.1234"))

    def test_falls_back_when_missing_or_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = load_fx(root)
            (root / "fx.json").write_text("not json")
            corrupt = load_fx(root)
        self.assertGreater(missing.rate("USD", "INR"), Decimal("1"))
        self.assertEqual(missing.rate("USD", "INR"), corrupt.rate("USD", "INR"))


if __name__ == "__main__":
    unittest.main()
