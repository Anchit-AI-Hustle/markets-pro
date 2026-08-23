"""The release checker's own logic, especially the distinction it exists for.

Eight consecutive CI runs failed without being noticed, because a refused job
fails in three seconds and reads like a fast pass unless someone opens it. The
checker's whole value is telling three things apart that all present as "not
green": the code is broken, the platform refused to run it, or it is still
running. Those lead to completely different actions, so the classification is
tested rather than trusted.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "release_check",
    Path(__file__).resolve().parent.parent / "scripts" / "release_check.py")
rc = importlib.util.module_from_spec(_spec)
# Registered before execution: the module defines a dataclass, and dataclass
# resolves its own annotations through sys.modules. Loading a script by path
# without this raises inside dataclasses rather than anywhere informative.
sys.modules[_spec.name] = rc
_spec.loader.exec_module(rc)


class ClassificationTest(unittest.TestCase):
    def test_a_billing_refusal_is_not_reported_as_a_code_failure(self):
        """Reporting this as "failed" sends someone to debug tests that never
        ran. It is an account setting, and no commit will change it."""
        message = ("The job was not started because recent account payments "
                   "have failed or your spending limit needs to be increased.")
        self.assertTrue(any(m in message.lower() for m in rc.BLOCKED_MARKERS))

    def test_quota_and_rate_limits_are_blocks_too(self):
        for message in ("You have exceeded your quota for this billing cycle",
                        "You have exceeded a secondary rate limit"):
            self.assertTrue(any(m in message.lower() for m in rc.BLOCKED_MARKERS),
                            f"{message!r} should classify as blocked")

    def test_a_real_test_failure_is_not_swallowed_as_a_block(self):
        # The dangerous direction: calling a genuine failure a platform problem
        # would hide a broken build behind a shrug.
        for message in ("Process completed with exit code 1",
                        "AssertionError: 3 != 4",
                        "ruff check found 2 errors",
                        "ModuleNotFoundError: no module named autotrader"):
            self.assertFalse(any(m in message.lower() for m in rc.BLOCKED_MARKERS),
                             f"{message!r} must stay a failure")


class UnreadableCiTest(unittest.TestCase):
    """The checker must never call an unverified chain a quiet one.

    `gh` missing or logged out is the ordinary case on a fresh machine, and it
    is precisely when someone most wants to know whether the push landed. If
    that reads as "still running" the report says "Nothing has failed" and
    exits 2, which is the same false assurance that let eight red builds
    through -- only now printed by the tool written to catch them.
    """

    def setUp(self):
        self._real_run = rc._run
        self.addCleanup(lambda: setattr(rc, "_run", self._real_run))

    def _fake_run(self, code, out):
        rc._run = lambda cmd, **kw: (code, out)

    def test_a_missing_gh_is_reported_as_blocked_not_pending(self):
        self._fake_run(127, "gh not installed")
        steps = rc.check_ci("deadbeef", wait=0)
        self.assertEqual([s.status for s in steps], [rc.BLOCKED])
        self.assertEqual(rc.report(steps), 1, "an unreadable chain must not exit 0 or 2")

    def test_an_unauthenticated_gh_is_blocked_too(self):
        self._fake_run(4, "gh: To get started with GitHub CLI, please run: gh auth login")
        steps = rc.check_ci("deadbeef", wait=0)
        self.assertEqual([s.status for s in steps], [rc.BLOCKED])

    def test_unparseable_output_is_blocked_rather_than_read_as_no_runs(self):
        self._fake_run(0, "<html>proxy error</html>")
        steps = rc.check_ci("deadbeef", wait=0)
        self.assertEqual([s.status for s in steps], [rc.BLOCKED])

    def test_gh_answering_with_no_runs_stays_pending(self):
        # The other direction: when GitHub really was asked and really has no
        # run yet, that is a wait, not a block. Collapsing the two would make
        # the block meaningless.
        self._fake_run(0, "[]")
        steps = rc.check_ci("deadbeef", wait=0)
        self.assertEqual([s.status for s in steps], [rc.PENDING])

    def test_a_successful_run_is_still_reported_green(self):
        self._fake_run(0, '[{"workflowName":"CI","status":"completed",'
                          '"conclusion":"success","databaseId":1}]')
        steps = rc.check_ci("deadbeef", wait=0)
        self.assertEqual([s.status for s in steps], [rc.OK])

    def test_the_reason_reaches_the_reader(self):
        self._fake_run(127, "gh not installed")
        step = rc.check_ci("deadbeef", wait=0)[0]
        self.assertIn("gh not installed", step.detail)
        self.assertTrue(step.fix, "a block the reader can act on needs a fix line")


class ReportTest(unittest.TestCase):
    def test_any_failure_makes_the_exit_code_non_zero(self):
        for status in (rc.FAIL, rc.BLOCKED):
            code = rc.report([rc.Step("x", rc.OK), rc.Step("y", status, "d")])
            self.assertEqual(code, 1, f"{status} should fail the check")

    def test_pending_is_neither_green_nor_a_failure(self):
        code = rc.report([rc.Step("x", rc.OK), rc.Step("y", rc.PENDING, "running")])
        self.assertEqual(code, 2)

    def test_all_clear_exits_zero(self):
        self.assertEqual(rc.report([rc.Step("x", rc.OK), rc.Step("y", rc.OK)]), 0)

    def test_a_skipped_step_does_not_count_as_a_pass_or_a_failure(self):
        self.assertEqual(rc.report([rc.Step("x", rc.OK), rc.Step("y", rc.SKIP)]), 0)

    def test_every_status_has_a_label(self):
        for status in (rc.OK, rc.FAIL, rc.BLOCKED, rc.PENDING, rc.SKIP):
            self.assertIn(status, rc.ICON)


class CoverageTest(unittest.TestCase):
    def test_it_checks_every_link_in_the_chain(self):
        """A checker that skipped a layer would give exactly the false
        assurance that let eight red builds through."""
        source = (Path(__file__).resolve().parent.parent
                  / "scripts" / "release_check.py").read_text()
        for step in ("check_local_gate", "check_git", "check_ci",
                     "check_vercel", "check_live"):
            self.assertIn(f"def {step}", source)
            self.assertIn(f"{step}(", source.split("def main")[1])

    def test_vercel_status_is_not_read_from_the_human_table(self):
        # `vercel ls` prints a table for a terminal and bare URLs otherwise;
        # parsing the table reported a healthy deploy as failed.
        source = (Path(__file__).resolve().parent.parent
                  / "scripts" / "release_check.py").read_text()
        self.assertIn('"inspect"', source)


if __name__ == "__main__":
    unittest.main()
