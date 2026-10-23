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

import ast
import re
import sys
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github/workflows/refresh-signals.yml"


def _steps() -> list[dict]:
    """The job's steps, parsed with the standard library only.

    PyYAML is not a dependency of this project and CI installs nothing before
    running the suite -- "the package has zero runtime dependencies" is the
    stated reason there is no install step. A test that imported yaml passed
    locally and failed on all three CI pythons, which is the exact shape of
    bug this file exists to catch in the workflow, committed in the test.

    So this reads the one structure it needs rather than implementing YAML:
    steps are a flat list under jobs.refresh.steps, each `- name:` at six
    spaces with its properties at eight, and `run: |` blocks running until the
    indentation returns. It is deliberately strict -- an unparsed step would
    silently weaken every assertion below, so the shape is asserted too.
    """
    lines = WORKFLOW.read_text().splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "steps:")
    except StopIteration:  # pragma: no cover - guarded by test_the_parser_works
        raise AssertionError("no 'steps:' key in the workflow") from None

    steps: list[dict] = []
    current: dict | None = None
    block_key: str | None = None
    block: list[str] = []

    def flush() -> None:
        nonlocal block_key, block
        if current is not None and block_key is not None:
            current[block_key] = "\n".join(block)
        block_key, block = None, []

    for ln in lines[start + 1:]:
        if ln.strip() and not ln.startswith(" " * 6):
            break                                    # left the steps list
        if block_key is not None:
            # A run: | block continues while indented past its own key.
            if not ln.strip() or ln.startswith(" " * 10):
                block.append(ln[10:] if len(ln) > 10 else "")
                continue
            flush()
        m = re.match(r"^      - (\w[\w-]*): ?(.*)$", ln)
        if m:                                        # first key of a new step
            flush()
            current = {}
            steps.append(current)
            key, value = m.group(1), m.group(2).strip()
        else:
            m = re.match(r"^        (\w[\w-]*): ?(.*)$", ln)
            if not m or current is None:
                continue                             # comment, blank, or nested
            key, value = m.group(1), m.group(2).strip()
        if value in ("|", ">-", ">"):
            block_key = key
            continue
        current[key] = {"true": True, "false": False}.get(value, value.strip("'\""))
    flush()
    return steps


def _index_of(name_fragment: str, steps: list[dict]) -> int:
    for i, st in enumerate(steps):
        if name_fragment.lower() in (st.get("name") or "").lower():
            return i
    raise AssertionError(f"no step named like {name_fragment!r}")


class ParserTest(unittest.TestCase):
    """A parser that quietly returned nothing would make every other test
    in this file pass by vacuity. Assert its output has the shape expected."""

    def setUp(self):
        self.steps = _steps()

    def test_it_finds_every_step(self):
        self.assertGreaterEqual(len(self.steps), 10)
        self.assertTrue(all(isinstance(st, dict) for st in self.steps))

    def test_it_reads_names_runs_and_flags(self):
        named = [st for st in self.steps if st.get("name")]
        self.assertGreaterEqual(len(named), 10)
        self.assertTrue(any((st.get("run") or "") for st in self.steps), "no run: blocks parsed")
        self.assertTrue(
            any(st.get("continue-on-error") is True for st in self.steps),
            "continue-on-error not parsed as a boolean",
        )

    def test_it_uses_no_third_party_import(self):
        """CI installs nothing before the suite; this file must stay stdlib.

        Read as syntax, not as text: a grep for the import would match the
        assertion that greps for it, which is how this test first failed.
        """
        tree = ast.parse(Path(__file__).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(
            sorted(imported - set(sys.stdlib_module_names)),
            [],
            "CI runs the suite with no install step, so this file must import "
            "only the standard library",
        )


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
