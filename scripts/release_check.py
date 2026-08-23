"""Verify a release end to end: local gate, git, CI, Vercel, live site.

Written because eight consecutive CI runs failed without anyone noticing. The
local suite was green each time and was reported as though that settled it,
while GitHub Actions had not started a runner in hours — the jobs were being
refused for a billing reason, which fails in three seconds and looks exactly
like a fast pass if nobody opens it.

So this checks every link in the chain and says which one broke. It
deliberately distinguishes three outcomes that all present as "not green":

* **failed** — something is wrong with the code, and the log says what.
* **blocked** — the platform refused to run it: billing, quota, permissions.
  Nothing in the repository will fix this and a retry will not help.
* **pending** — still running; wait rather than conclude.

Run it after pushing::

    python3 scripts/release_check.py --wait

Exit code is non-zero if any step is failed or blocked, so it can gate a
release rather than merely describe one.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

OK, FAIL, BLOCKED, PENDING, SKIP = "ok", "failed", "blocked", "pending", "skipped"

#: GitHub reports a refused job as a plain failure. These phrases are how a
#: refusal is told apart from a real one, and they change nothing about the
#: code — surfacing them as "failed" would send someone debugging tests that
#: never ran.
BLOCKED_MARKERS = (
    "recent account payments have failed",
    "spending limit",
    "billing",
    "quota",
    "exceeded a secondary rate limit",
)


@dataclass
class Step:
    name: str
    status: str
    detail: str = ""
    fix: str = ""
    lines: list[str] = field(default_factory=list)


def _run(cmd: list[str], *, timeout: int = 300) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except FileNotFoundError:
        return 127, f"{cmd[0]} not installed"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} timed out"


def check_local_gate(skip: bool) -> list[Step]:
    """The suite and the linter, before anything is claimed about them."""
    if skip:
        return [Step("Local test gate", SKIP, "not run (--skip-local)")]
    code, out = _run(["python3", "verify.py"], timeout=900)
    total = next((ln for ln in out.splitlines() if "Accuracy:" in ln), "").strip()
    steps = [Step("Local test gate", OK if code == 0 else FAIL,
                  total or "verify.py produced no summary",
                  fix="" if code == 0 else "read the failure above before pushing")]
    code, out = _run(["ruff", "check", "src", "tests", "api"], timeout=300)
    if code == 127:
        steps.append(Step("Lint", SKIP, "ruff not installed locally"))
    else:
        steps.append(Step("Lint", OK if code == 0 else FAIL,
                          "clean" if code == 0 else out.strip().splitlines()[-1][:120]))
    return steps


def check_git() -> tuple[Step, str | None]:
    """Whether what is local is actually what the remote has."""
    _, local = _run(["git", "rev-parse", "HEAD"])
    local = local.strip()
    code, _ = _run(["git", "fetch", "--quiet"], timeout=120)
    _, remote = _run(["git", "rev-parse", "@{u}"])
    remote = remote.strip()
    _, dirty = _run(["git", "status", "--porcelain"])

    if code != 0:
        return Step("Pushed to remote", FAIL, "could not reach the remote"), None
    if local != remote:
        return Step("Pushed to remote", FAIL,
                    f"local {local[:7]} is not the remote's {remote[:7]}",
                    fix="git push"), local
    detail = f"{local[:7]} matches the remote"
    if dirty.strip():
        detail += f" — but {len(dirty.strip().splitlines())} file(s) uncommitted"
    return Step("Pushed to remote", OK, detail), local


def _gh_runs(sha: str) -> list[dict]:
    code, out = _run(
        ["gh", "run", "list", "--commit", sha, "--limit", "20",
         "--json", "name,status,conclusion,databaseId,workflowName"],
        timeout=180)
    if code != 0:
        return []
    try:
        return json.loads(out)
    except ValueError:
        return []


def _blocked_reason(run_id: int) -> str:
    """Why a run failed, when the reason is the platform rather than the code."""
    _, out = _run(["gh", "run", "view", str(run_id)], timeout=180)
    low = out.lower()
    for marker in BLOCKED_MARKERS:
        if marker in low:
            for line in out.splitlines():
                if marker in line.lower():
                    return line.strip().lstrip("X ").strip()
            return marker
    return ""


def check_ci(sha: str | None, wait: int) -> list[Step]:
    if not sha:
        return [Step("GitHub Actions", SKIP, "no commit to check")]
    deadline = time.time() + wait
    while True:
        runs = _gh_runs(sha)
        if not runs:
            if time.time() < deadline:
                time.sleep(10)
                continue
            return [Step("GitHub Actions", PENDING,
                         "no run found for this commit",
                         fix="check that workflows are enabled for the repository")]
        if any(r.get("status") != "completed" for r in runs) and time.time() < deadline:
            time.sleep(10)
            continue
        break

    steps = []
    for run in runs:
        name = run.get("workflowName") or run.get("name") or "workflow"
        if run.get("status") != "completed":
            steps.append(Step(f"CI · {name}", PENDING, "still running"))
            continue
        if run.get("conclusion") == "success":
            steps.append(Step(f"CI · {name}", OK, "passed"))
            continue
        reason = _blocked_reason(run.get("databaseId"))
        if reason:
            steps.append(Step(
                f"CI · {name}", BLOCKED, reason[:150],
                fix="This is an account setting, not a code problem. Nothing in "
                    "the repository will fix it and a re-run will not help."))
        else:
            steps.append(Step(
                f"CI · {name}", FAIL, f"conclusion: {run.get('conclusion')}",
                fix=f"gh run view {run.get('databaseId')} --log-failed"))
    return steps


def check_vercel(project: str, wait: int) -> list[Step]:
    """Status of the newest production deployment.

    Read through ``vercel inspect`` rather than the ``vercel ls`` table,
    because ``ls`` drops the table and prints bare URLs when it is not
    attached to a terminal — which is always, here. Parsing its human output
    reported a healthy deployment as failed, which is the exact class of false
    alarm this script exists to avoid.
    """
    code, _ = _run(["vercel", "--version"], timeout=60)
    if code == 127:
        return [Step("Vercel deploy", SKIP, "vercel CLI not installed")]

    code, out = _run(["vercel", "ls", project, "--prod"], timeout=180)
    if code != 0:
        return [Step("Vercel deploy", FAIL, "could not list deployments",
                     fix="vercel login")]
    urls = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("https://")]
    if not urls:
        return [Step("Vercel deploy", PENDING, "no production deployment found")]
    newest = urls[0]

    deadline = time.time() + wait
    while True:
        code, detail = _run(["vercel", "inspect", newest], timeout=180)
        status = ""
        age = ""
        for line in detail.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] == "status":
                status = parts[1].strip().lstrip("● ").strip()
            if len(parts) == 2 and parts[0] == "created" and "[" in parts[1]:
                age = parts[1].split("[")[-1].rstrip("]").strip()
        if status in ("Building", "Queued", "Initializing") and time.time() < deadline:
            time.sleep(15)
            continue
        break

    if status == "Ready":
        return [Step("Vercel deploy", OK,
                     f"newest production deploy is Ready{f' ({age})' if age else ''}")]
    if status in ("Building", "Queued", "Initializing"):
        return [Step("Vercel deploy", PENDING, f"{status.lower()}",
                     fix="re-run with a longer --wait")]
    if not status:
        return [Step("Vercel deploy", PENDING, "could not read a status",
                     fix=f"vercel inspect {newest}")]
    return [Step("Vercel deploy", FAIL, f"status: {status}",
                 fix=f"vercel inspect {newest} --logs")]


def check_live(url: str, markers: tuple[str, ...]) -> list[Step]:
    """That the deployment actually serves, and serves the right thing."""
    steps = []
    try:
        request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read().decode("utf-8", "replace")
            status = response.status
    except (urllib.error.URLError, TimeoutError) as error:
        return [Step("Live site", FAIL, f"{url} unreachable: {error}")]
    steps.append(Step("Live site", OK if status == 200 else FAIL, f"HTTP {status}"))
    missing = [m for m in markers if m not in body]
    steps.append(Step(
        "Live content", OK if not missing else FAIL,
        "expected markers present" if not missing else f"missing: {missing}",
        fix="" if not missing else "the CDN may still be serving the previous build"))
    return steps


ICON = {OK: "PASS", FAIL: "FAIL", BLOCKED: "BLOCKED", PENDING: "PENDING", SKIP: "skip"}


def report(steps: list[Step]) -> int:
    width = max(len(s.name) for s in steps) + 2
    print("\n  Release check\n  " + "-" * (width + 46))
    for step in steps:
        print(f"  {ICON[step.status]:<8} {step.name:<{width}} {step.detail}")
        if step.fix and step.status in (FAIL, BLOCKED, PENDING):
            print(f"  {'':<8} {'':<{width}} -> {step.fix}")
    bad = [s for s in steps if s.status in (FAIL, BLOCKED)]
    pending = [s for s in steps if s.status == PENDING]
    print()
    if bad:
        blocked = [s for s in bad if s.status == BLOCKED]
        if blocked and len(blocked) == len(bad):
            print("  Not green — but every failure is a platform block, not the code.")
        else:
            print(f"  Not green: {len(bad)} step(s) need attention.")
        return 1
    if pending:
        print("  Nothing has failed, but some steps are still running.")
        return 2
    print("  Green across local, git, CI, Vercel and the live site.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a release end to end")
    parser.add_argument("--url", default="https://markets-pro.anchit-tandon.com/")
    parser.add_argument("--project", default="markets-pro")
    parser.add_argument("--wait", type=int, default=0,
                        help="seconds to wait for CI and Vercel to finish")
    parser.add_argument("--skip-local", action="store_true",
                        help="skip the local suite (it may already have run)")
    parser.add_argument("--marker", action="append", default=[],
                        help="text that must appear on the live page")
    args = parser.parse_args(argv)

    steps = check_local_gate(args.skip_local)
    git_step, sha = check_git()
    steps.append(git_step)
    steps += check_ci(sha, args.wait)
    steps += check_vercel(args.project, args.wait)
    steps += check_live(args.url, tuple(args.marker) or ("Markets Pro",))
    return report(steps)


if __name__ == "__main__":
    sys.exit(main())
