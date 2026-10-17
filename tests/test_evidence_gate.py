"""The gate between the evidence study and the suggestions.

The study has always run. Nothing read it. The Evidence tab printed "no
demonstrated edge" while the dashboard went on suggesting trades from the
rules that earned that verdict, which is the single widest gap between what
this product measures and what it does.

These tests pin both directions: a failed rule must not reach a suggestion,
and the gate must not claim more than a verdict supports.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autotrader.research.evidence_gate import (
    VERDICT_ORDER,
    EvidenceGate,
    load_verdicts,
    logic_for,
)


class LogicMappingTest(unittest.TestCase):
    def test_it_maps_each_live_signal_to_the_rule_that_produced_it(self):
        self.assertEqual(logic_for("short_term", "pullback: RSI(14) 28.3 above SMA200"), "pullback")
        self.assertEqual(logic_for("short_term", "breakout above 55d high, ADX 31, volume 2.1x"), "breakout")
        self.assertEqual(logic_for("long_term", "momentum rank 3"), "momentum")

    def test_an_unrecognised_signal_maps_to_no_rule(self):
        """Assigning it to a rule it did not come from would apply someone
        else's verdict to it."""
        self.assertIsNone(logic_for("short_term", "mean reversion complete: RSI 61.0"))
        self.assertIsNone(logic_for("", ""))


class GateTest(unittest.TestCase):
    def setUp(self):
        self.v = {
            ("IN:GOOD", "pullback"): "evidence",
            ("IN:MEH", "pullback"): "profitable_but_unproven",
            ("IN:BAD", "pullback"): "no_edge",
            ("IN:THIN", "pullback"): "insufficient",
        }

    def test_a_rule_with_evidence_is_allowed(self):
        g = EvidenceGate(self.v)
        self.assertTrue(g.evaluate("IN:GOOD", "short_term", "pullback: x").allowed)

    def test_a_rule_the_study_failed_is_blocked(self):
        g = EvidenceGate(self.v)
        d = g.evaluate("IN:BAD", "short_term", "pullback: x")
        self.assertFalse(d.allowed)
        self.assertEqual(d.verdict, "no_edge")
        self.assertIn("no_edge", d.reason)

    def test_insufficient_is_not_a_pass(self):
        """Too few trades to judge is not evidence of working. Treating it as
        a pass would let every thinly traded name straight through."""
        g = EvidenceGate(self.v)
        self.assertFalse(g.evaluate("IN:THIN", "short_term", "pullback: x").allowed)

    def test_profitable_but_unproven_is_blocked_at_the_strict_default(self):
        g = EvidenceGate(self.v)
        self.assertFalse(g.evaluate("IN:MEH", "short_term", "pullback: x").allowed)

    def test_but_can_be_admitted_by_lowering_the_bar_deliberately(self):
        g = EvidenceGate(self.v, minimum="profitable_but_unproven")
        self.assertTrue(g.evaluate("IN:MEH", "short_term", "pullback: x").allowed)
        self.assertFalse(g.evaluate("IN:BAD", "short_term", "pullback: x").allowed)

    def test_an_untested_pair_is_blocked_not_waved_through(self):
        """Absence of a verdict is absence of evidence. Defaulting to allow
        would mean any instrument the study missed trades unchecked."""
        g = EvidenceGate(self.v)
        d = g.evaluate("IN:NEVERTESTED", "short_term", "pullback: x")
        self.assertFalse(d.allowed)
        self.assertEqual(d.verdict, "untested")

    def test_a_signal_from_no_studied_rule_is_not_judged(self):
        # The study says nothing about it, so the gate must not invent a verdict.
        g = EvidenceGate(self.v)
        self.assertTrue(g.evaluate("IN:BAD", "short_term", "mean reversion complete").allowed)

    def test_disabled_allows_everything(self):
        g = EvidenceGate(self.v, enabled=False)
        self.assertTrue(g.evaluate("IN:BAD", "short_term", "pullback: x").allowed)

    def test_an_unknown_minimum_is_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceGate({}, minimum="probably_fine")

    def test_verdict_order_is_strongest_first(self):
        self.assertEqual(VERDICT_ORDER[0], "evidence")
        self.assertEqual(VERDICT_ORDER[-1], "insufficient")


class LoadTest(unittest.TestCase):
    def test_it_reads_the_real_study_shape(self):
        blob = {"results": {"IN:X": {"symbol": "X", "logics": [
            {"logic": "pullback", "verdict": "no_edge"},
            {"logic": "breakout", "verdict": "evidence"},
        ]}}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fitness.json"
            p.write_text(json.dumps(blob))
            v = load_verdicts(p)
        self.assertEqual(v[("IN:X", "pullback")], "no_edge")
        self.assertEqual(v[("IN:X", "breakout")], "evidence")

    def test_a_missing_or_broken_study_yields_no_verdicts(self):
        # Which, with the gate's untested-is-blocked rule, fails closed.
        self.assertEqual(load_verdicts("/nonexistent/fitness.json"), {})
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("{not json")
            self.assertEqual(load_verdicts(p), {})

    def test_a_missing_study_blocks_rather_than_opens_the_floodgates(self):
        g = EvidenceGate(load_verdicts("/nonexistent/fitness.json"))
        self.assertFalse(g.evaluate("IN:ANY", "short_term", "pullback: x").allowed)


if __name__ == "__main__":
    unittest.main()
