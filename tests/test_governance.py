"""Independent-desk consensus gate tests."""

import unittest

from autotrader.governance.consensus import (
    ConsensusKernel,
    DeskVote,
    Stance,
    VoteState,
)


def required_votes():
    return [
        DeskVote("data", VoteState.PASS),
        DeskVote("risk", VoteState.PASS),
        DeskVote("liquidity", VoteState.PASS),
        DeskVote("portfolio", VoteState.PASS),
        DeskVote("execution", VoteState.PASS),
        DeskVote("red_team", VoteState.PASS),
    ]


class ConsensusKernelTest(unittest.TestCase):
    def setUp(self):
        self.kernel = ConsensusKernel()

    def test_every_required_desk_must_report(self):
        votes = required_votes()[:-1]
        decision = self.kernel.evaluate(votes, proposed_action=Stance.BUY)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "missing_required_desk")

    def test_unavailable_data_fails_closed(self):
        votes = required_votes()
        votes[0] = DeskVote("data", VoteState.UNAVAILABLE, reason="stale cache")
        decision = self.kernel.evaluate(votes, proposed_action=Stance.BUY)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "veto")

    def test_red_team_can_veto_everyone_else(self):
        votes = required_votes()
        votes[-1] = DeskVote("red_team", VoteState.FAIL, reason="catalyst already priced")
        decision = self.kernel.evaluate(votes, proposed_action=Stance.BUY)
        self.assertFalse(decision.allowed)

    def test_conflicting_direction_means_wait(self):
        votes = required_votes() + [
            DeskVote("analyst", VoteState.PASS, Stance.BUY),
            DeskVote("quant", VoteState.PASS, Stance.SELL),
        ]
        decision = self.kernel.evaluate(votes, proposed_action=Stance.BUY)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "conflicting_signal")

    def test_wait_stance_blocks_an_entry(self):
        votes = required_votes() + [
            DeskVote("news", VoteState.PASS, Stance.WAIT, "event not confirmed")
        ]
        decision = self.kernel.evaluate(votes, proposed_action=Stance.BUY)
        self.assertFalse(decision.allowed)

    def test_aligned_research_and_mandatory_passes_approve(self):
        votes = required_votes() + [
            DeskVote("analyst", VoteState.PASS, Stance.BUY),
            DeskVote("quant", VoteState.PASS, Stance.BUY),
            DeskVote("news", VoteState.PASS, Stance.NEUTRAL),
        ]
        decision = self.kernel.evaluate(votes, proposed_action=Stance.BUY)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.action, "APPROVE")

    def test_duplicate_desk_is_rejected(self):
        votes = required_votes() + [DeskVote("risk", VoteState.PASS)]
        with self.assertRaises(ValueError):
            self.kernel.evaluate(votes, proposed_action=Stance.BUY)

    def test_kernel_does_not_decide_hold_or_wait_as_a_trade(self):
        with self.assertRaises(ValueError):
            self.kernel.evaluate(required_votes(), proposed_action=Stance.WAIT)


if __name__ == "__main__":
    unittest.main()
