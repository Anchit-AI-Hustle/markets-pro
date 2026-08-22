"""Every tab's data, checked against the committed cache.

The other test modules assert that the page *renders*. This one asserts that
what it renders is right, against the real data the site ships rather than a
fixture — which is where the errors that reach a reader actually live. The
one that prompted it labelled a one-month move as three months on every index
detail page: nothing was missing, nothing failed, and the figure was simply
wrong.

Skipped when the cache is absent, so a clone without committed data still runs
green rather than failing for a reason that is not about the code.
"""

import json
import unittest
from decimal import Decimal

from .live_cache import LIVE, ROOT  # noqa: E402
from .live_cache import load as _load


@unittest.skipUnless((LIVE / "benchmarks.json").exists(), "no committed live cache")
class TabDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot, cls.screener, cls.index = _load()

    # -- detail pages, which every other tab links into --------------------

    #: Fraction of a group that must share an identical pair before it stops
    #: looking like coincidence. A copy bug is total within the class it
    #: affects -- the real one hit 13 of 13 benchmarks -- while genuine ties
    #: are a few percent: a stock that closed at the same price one day and
    #: five days ago reports the same 1d and 1w move, honestly.
    COPY_RATIO = 0.5

    def test_no_time_window_is_assigned_from_another(self):
        """1d, 1w, 1m and 3m must be four measurements, not one copied.

        Checked as a rate within each group rather than as an absolute rule.
        The first version of this test forbade any two windows from matching,
        which was right at 47 instruments and wrong at 325 -- exact ties do
        occur, and failing on them would train everyone to ignore the test.
        """
        windows = ("change_1d", "change_1w", "change_1m", "change_3m")
        groups = {"benchmarks": [], "equities": []}
        for record in self.index.values():
            groups["benchmarks" if record.get("is_benchmark")
                   else "equities"].append(record)

        for name, records in groups.items():
            if not records:
                continue
            for i, a in enumerate(windows):
                for b in windows[i + 1:]:
                    tied = sum(
                        1 for r in records
                        if r.get(a) not in (None, "") and r.get(a) == r.get(b)
                    )
                    ratio = tied / len(records)
                    self.assertLess(
                        ratio, self.COPY_RATIO,
                        f"{name}: {a} equals {b} on {tied} of {len(records)} "
                        f"({ratio:.0%}) — one is assigned from the other",
                    )

    def test_every_instrument_has_a_52_week_band(self):
        for key, record in self.index.items():
            self.assertTrue(record.get("high_52w"), f"{key}: no 52-week high")
            self.assertTrue(record.get("low_52w"), f"{key}: no 52-week low")

    def test_the_52_week_band_contains_the_last_price(self):
        for key, record in self.index.items():
            high = Decimal(record["high_52w"])
            low = Decimal(record["low_52w"])
            last = Decimal(record["last"])
            self.assertLessEqual(low, high, f"{key}: low above high")
            self.assertLessEqual(last, high, f"{key}: last above its 52-week high")
            self.assertGreaterEqual(last, low, f"{key}: last below its 52-week low")

    def test_volume_is_present_or_explicitly_absent(self):
        """An index has none; a stock must have one.

        The distinction matters to the reader: a missing figure looks like a
        fetch that failed, and this app does not show a dash where the honest
        answer is "this kind of instrument has no such number".
        """
        for key, record in self.index.items():
            if record.get("has_volume") is False:
                self.assertTrue(record.get("is_benchmark"),
                                f"{key}: only a benchmark may declare no volume")
            else:
                self.assertTrue(record.get("avg_volume"), f"{key}: no average volume")

    def test_no_record_renders_an_empty_tag(self):
        # An empty string reached the markup as a blank pill beside the real
        # tags. Absent is fine; empty is not.
        for key, record in self.index.items():
            for field in ("exchange", "sector", "region"):
                self.assertNotEqual(record.get(field), "",
                                    f"{key}: {field} is empty rather than absent")

    def test_history_days_and_closes_line_up(self):
        for key, record in self.index.items():
            history = record.get("history") or {}
            if not history:
                continue
            days, closes = history.get("d") or [], history.get("c") or []
            self.assertEqual(len(days), len(closes),
                             f"{key}: {len(days)} days against {len(closes)} closes")

    # -- markets -----------------------------------------------------------

    def test_breadth_adds_up(self):
        for region, data in (self.snapshot["market"]["regions"]).items():
            breadth = data["breadth"]
            total = breadth["advancing"] + breadth["declining"] + breadth["unchanged"]
            self.assertEqual(total, breadth["total"], f"{region}: breadth does not sum")

    def test_movers_are_ranked_the_way_they_are_labelled(self):
        for region, data in (self.snapshot["market"]["regions"]).items():
            gainers = [float(r["change_1d"]) for r in data["gainers"]]
            losers = [float(r["change_1d"]) for r in data["losers"]]
            self.assertEqual(gainers, sorted(gainers, reverse=True),
                             f"{region}: gainers out of order")
            self.assertEqual(losers, sorted(losers), f"{region}: losers out of order")

    def test_every_index_card_carries_the_moves_it_displays(self):
        # The 1Y column was empty on every card once because the fetch window
        # was shorter than the period being asked for.
        for bench in self.snapshot["market"]["benchmarks"]:
            for field in ("change_1d", "change_1w", "change_1m", "change_1y"):
                self.assertIsNotNone(bench.get(field),
                                     f"{bench.get('label')}: {field} missing")

    # -- everything that links to a detail page ---------------------------

    def test_every_mover_opens_a_detail_page(self):
        for region, data in (self.snapshot["market"]["regions"]).items():
            for kind in ("gainers", "losers"):
                for row in data[kind]:
                    self.assertIn(row.get("key"), self.index,
                                  f"{region} {kind}: {row.get('symbol')} opens nothing")

    def test_every_screener_row_opens_a_detail_page(self):
        for row in (self.screener or {}).get("results") or []:
            self.assertIn(row.get("key"), self.index,
                          f"screener: {row.get('key')} opens nothing")

    def test_every_watchlist_row_is_priced_and_routable(self):
        for row in self.snapshot["watchlist"]:
            self.assertTrue(row.get("key"), f"{row.get('symbol')}: no key")
            self.assertNotIn(row.get("last"), (None, ""), f"{row.get('key')}: no price")


@unittest.skipUnless((ROOT / "data" / "research" / "fitness.json").exists(),
                     "no committed evidence study")
class EvidenceDataTest(unittest.TestCase):
    VERDICTS = {"evidence", "profitable_but_unproven", "no_edge",
                "insufficient", "no_history"}

    @classmethod
    def setUpClass(cls):
        cls.snapshot, cls.screener, cls.index = _load()
        cls.fitness = json.loads(
            (ROOT / "data" / "research" / "fitness.json").read_text())

    def test_every_studied_name_opens_a_detail_page(self):
        for key in self.fitness.get("results") or {}:
            self.assertIn(key, self.index, f"evidence: {key} opens nothing")

    def test_every_verdict_is_one_the_page_can_label(self):
        # An unknown verdict renders as a blank badge rather than an error.
        for key, record in (self.fitness.get("results") or {}).items():
            for logic in record.get("logics") or []:
                self.assertIn(logic.get("verdict"), self.VERDICTS,
                              f"{key}: unlabelled verdict")

    def test_the_headline_count_matches_the_records(self):
        results = self.fitness.get("results") or {}
        counted = sum(len(r.get("logics") or []) for r in results.values())
        self.assertEqual(counted, self.fitness.get("tests_run"),
                         "the study's own test count disagrees with its records")


if __name__ == "__main__":
    unittest.main()
