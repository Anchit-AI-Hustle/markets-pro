"""The nightly refresh must always reach its commit step.

This workflow deadlocked for fourteen days. The quality gate was changed to
fail hard, which aborted the job before the commit; the cache then froze, went
a day staler every night, produced more stale failures, and aborted again. By
the time anyone looked, all 325 instruments were failing and the check that
exists to detect a stale cache was the sole cause of it.

The fetch step tolerates a partial failure on purpose — "committing what
succeeded" is its stated design. Any step between the fetch and the commit
that can abort the job silently cancels that design, and nothing about the
failure says so: the run is red for "stale data" while the fresh data it just
downloaded sits in the runner being thrown away.

So the structural property is tested, not the wording: every step that can
fail between fetching and committing must either swallow its failure or carry
`continue-on-error`, and the commit must not be conditional on any of them.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github/workflows/refresh-signals.yml"


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["refresh"]["steps"]


def _index_of(name_fragment: str, steps: list[dict]) -> int:
    for i, st in enumerate(steps):
        if name_fragment.lower() in (st.get("name") or "").lower():
            return i
    raise AssertionError(f"no step named like {name_fragment!r}")


class CommitIsReachableTest(unittest.TestCase):
    def setUp(self):
        self.steps = _steps()
        self.fetch = _index_of("Fetch EOD bars", self.steps)
        self.commit = _index_of("Commit refreshed cache", self.steps)

    def test_the_commit_step_comes_after_the_fetch(self):
        self.assertLess(self.fetch, self.commit)

    def test_no_step_between_fetch_and_commit_can_abort_the_job(self):
        """The exact regression: one hard-failing step in this span skipped
        the commit and froze the cache for a fortnight."""
        for st in self.steps[self.fetch : self.commit]:
            name = st.get("name") or "(unnamed)"
            run = st.get("run") or ""
            # A bare "||" is not enough to judge by: the weekly study's own
            # shell condition contains one, and a step could carry an
            # unrelated OR while still aborting the job. Only the two
            # error-swallowing idioms count.
            tolerated = (
                st.get("continue-on-error") is True
                or "|| echo" in run
                or "|| true" in run
            )
            self.assertTrue(
                tolerated,
                f"step {name!r} sits between the fetch and the commit and can "
                f"abort the job, which skips the commit and freezes the cache",
            )

    def test_the_commit_step_is_not_conditional(self):
        """An `if:` on the commit is another way to skip it."""
        self.assertIsNone(self.steps[self.commit].get("if"))

    def test_the_commit_step_actually_pushes(self):
        run = self.steps[self.commit].get("run") or ""
        self.assertIn("git commit", run)
        self.assertIn("git push", run)


class FailureIsStillVisibleTest(unittest.TestCase):
    """Reaching the commit must not come at the price of hiding a real problem.

    The fix that caused the deadlock was itself fixing something real: a
    quality failure used to vanish into a `::warning::` nobody read. So the
    verdict has to survive — just after the data is safe, not instead of it.
    """

    def setUp(self):
        self.steps = _steps()

    def test_a_quality_failure_still_turns_the_run_red(self):
        quality = self.steps[_index_of("Verify cache freshness", self.steps)]
        self.assertEqual(quality.get("id"), "quality", "needs an id to be re-raised")
        raiser = [
            st for st in self.steps
            if "steps.quality.outcome" in (st.get("if") or "")
        ]
        self.assertTrue(raiser, "a quality failure must be re-raised somewhere")
        self.assertIn("exit 1", raiser[0].get("run") or "")

    def test_the_re_raise_happens_after_the_commit(self):
        # Before the commit it would be the original deadlock again.
        commit = _index_of("Commit refreshed cache", self.steps)
        raiser = next(
            i for i, st in enumerate(self.steps)
            if "steps.quality.outcome" in (st.get("if") or "")
        )
        self.assertGreater(raiser, commit)


if __name__ == "__main__":
    unittest.main()
