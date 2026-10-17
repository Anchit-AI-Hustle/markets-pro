"""The consecutive-loss breaker.

`daily_loss_limit` catches one bad day by size. It does not catch a run of
small losses that never adds up to 5% but is still the account being chipped
away by a strategy that has stopped working today. The streak breaker answers
that second question, so both run.

Counted on the round trip's NET result: a trade that only lost to brokerage
still lost money, and a breaker that ignored costs would let exactly the
cheapest kind of bleed through.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from autotrader.risk.limits import RiskConfig, RiskManager


def _mgr(limit: int = 3, equity: str = "100000") -> RiskManager:
    m = RiskManager(RiskConfig(max_consecutive_losses=limit))
    m.start_day(Decimal(equity))
    return m


class StreakBreakerTest(unittest.TestCase):
    def test_it_halts_on_the_nth_consecutive_loss_and_not_before(self):
        m = _mgr(3)
        for _ in range(2):
            m.record_round_trip(Decimal("-10"))
            self.assertFalse(m.entries_halted, "halted early")
        m.record_round_trip(Decimal("-10"))
        self.assertTrue(m.entries_halted)
        self.assertEqual(m.state.halt_reason, "max_consecutive_losses")

    def test_a_win_resets_the_streak(self):
        """Two losses, a win, two more losses is not a run of four."""
        m = _mgr(3)
        m.record_round_trip(Decimal("-10"))
        m.record_round_trip(Decimal("-10"))
        m.record_round_trip(Decimal("25"))
        self.assertEqual(m.state.consecutive_losses, 0)
        m.record_round_trip(Decimal("-10"))
        m.record_round_trip(Decimal("-10"))
        self.assertFalse(m.entries_halted)

    def test_a_break_even_trade_neither_extends_nor_clears(self):
        # It is not evidence either way, so it must not be counted as either.
        m = _mgr(3)
        m.record_round_trip(Decimal("-10"))
        m.record_round_trip(Decimal("0"))
        self.assertEqual(m.state.consecutive_losses, 1)
        m.record_round_trip(Decimal("-10"))
        m.record_round_trip(Decimal("-10"))
        self.assertTrue(m.entries_halted)

    def test_a_small_loss_counts_even_though_it_never_moves_the_daily_limit(self):
        """The whole reason this breaker exists."""
        m = _mgr(3)
        for _ in range(3):
            m.record_round_trip(Decimal("-1"))      # 0.001% of equity, each
        self.assertTrue(m.entries_halted, "three tiny losses must still halt")
        self.assertEqual(m.state.halt_reason, "max_consecutive_losses")

    def test_a_new_day_clears_the_halt_and_the_count(self):
        m = _mgr(3)
        for _ in range(3):
            m.record_round_trip(Decimal("-10"))
        self.assertTrue(m.entries_halted)
        m.start_day(Decimal("99970"))
        self.assertFalse(m.entries_halted)
        self.assertEqual(m.state.consecutive_losses, 0)

    def test_it_never_downgrades_a_drawdown_halt(self):
        """A drawdown halt outlives the day; a streak halt does not. Letting
        the streak overwrite the reason would see it cleared at the next open
        and quietly resume trading an account that is 20% underwater."""
        m = RiskManager(RiskConfig(max_consecutive_losses=2, max_drawdown_halt=Decimal("0.10")))
        m.start_day(Decimal("100000"))
        m.update_equity(Decimal("80000"))           # -20%, trips drawdown
        self.assertEqual(m.state.halt_reason, "max_drawdown_halt")
        m.record_round_trip(Decimal("-10"))
        m.record_round_trip(Decimal("-10"))
        self.assertEqual(m.state.halt_reason, "max_drawdown_halt", "reason was overwritten")
        m.start_day(Decimal("80000"))
        self.assertTrue(m.entries_halted, "drawdown halt must survive the new day")

    def test_zero_disables_it(self):
        m = _mgr(0)
        for _ in range(50):
            m.record_round_trip(Decimal("-10"))
        self.assertFalse(m.entries_halted)
        self.assertEqual(m.state.consecutive_losses, 0)

    def test_a_negative_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            RiskConfig(max_consecutive_losses=-1)


if __name__ == "__main__":
    unittest.main()
