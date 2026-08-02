"""Live universe: identities must be consistent across every venue."""

import unittest

from autotrader.data.universe import UNIVERSES, entry_for_key, universe


class TestUniverse(unittest.TestCase):
    def test_regions_present(self):
        self.assertEqual(sorted(UNIVERSES), ["india", "us"])

    def test_keys_are_unique_across_regions(self):
        keys = [entry.key for entries in UNIVERSES.values() for entry in entries]
        self.assertEqual(len(keys), len(set(keys)))

    def test_india_entries_use_nse_conventions(self):
        for entry in universe("india"):
            self.assertEqual(entry.currency, "INR")
            self.assertEqual(entry.exchange, "NSE")
            self.assertEqual(entry.yahoo, f"{entry.symbol}.NS")
            self.assertTrue(entry.key.startswith("IN:"))

    def test_us_entries_use_us_conventions(self):
        for entry in universe("us"):
            self.assertEqual(entry.currency, "USD")
            self.assertEqual(entry.yahoo, entry.symbol)
            self.assertTrue(entry.key.startswith("US:"))

    def test_every_entry_has_a_sector_for_risk_limits(self):
        for entries in UNIVERSES.values():
            for entry in entries:
                self.assertTrue(entry.sector)
                self.assertNotEqual(entry.sector, "unknown")

    def test_entry_for_key_round_trips(self):
        for entries in UNIVERSES.values():
            for entry in entries:
                self.assertIs(entry_for_key(entry.key), entry)

    def test_entry_for_key_rejects_unknown(self):
        with self.assertRaises(KeyError):
            entry_for_key("IN:NOSUCH")

    def test_unknown_region_rejected(self):
        with self.assertRaises(ValueError):
            universe("mars")


if __name__ == "__main__":
    unittest.main()
