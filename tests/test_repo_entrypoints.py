"""Every documented way in actually leads somewhere.

`make dashboard` ran `examples/build_dashboard.py`, a file that has never
existed in this repository -- the target was wrong from the day it was
written, and nothing failed because nothing ran it. A Makefile is a menu of
promises to whoever clones the repo, and the cost of a stale one is a new
contributor concluding the project is broken.

These checks are structural, not behavioural: they confirm each entry point
resolves, not that it produces the right answer. Running the real builds
belongs in CI, which has the data and the minutes; this belongs anywhere.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"

#: `$(PY) some/script.py` and `$(PY) -m package.module`, as the recipes write
#: them. Anything else in a recipe (rm, ruff, plain shell) is not ours to
#: resolve, so it is deliberately not matched.
SCRIPT = re.compile(r"\$\(PY\)\s+([\w./-]+\.py)\b")
MODULE = re.compile(r"\$\(PY\)\s+-m\s+([\w.]+)")


def _recipes() -> list[str]:
    return [ln for ln in MAKEFILE.read_text().splitlines() if ln.startswith("\t")]


class MakefileEntryPointTest(unittest.TestCase):
    def setUp(self):
        self.recipes = _recipes()
        self.assertTrue(self.recipes, "Makefile has no recipe lines to check")

    def test_every_script_a_recipe_runs_exists(self):
        for line in self.recipes:
            for path in SCRIPT.findall(line):
                self.assertTrue(
                    (ROOT / path).is_file(),
                    f"Makefile runs {path!r}, which does not exist",
                )

    def test_every_module_a_recipe_runs_is_importable(self):
        src = str(ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        for line in self.recipes:
            for module in MODULE.findall(line):
                self.assertIsNotNone(
                    importlib.util.find_spec(module),
                    f"Makefile runs -m {module}, which cannot be imported",
                )

    def test_every_target_is_declared_phony(self):
        """A target absent from .PHONY stops working the day a file or
        directory of the same name appears -- `out/` and `dashboard` are one
        rename apart."""
        text = MAKEFILE.read_text()
        declared = set(
            re.sub(r"\\\s*\n", " ", text).split(".PHONY:", 1)[1].split("\n", 1)[0].split()
        )
        targets = {
            m.group(1)
            for m in re.finditer(r"^([a-zA-Z][\w-]*):", text, re.MULTILINE)
        }
        self.assertEqual(
            targets - declared, set(), "targets missing from .PHONY"
        )


class BuildCommandTest(unittest.TestCase):
    def test_the_makefile_and_vercel_build_the_same_way(self):
        """Two build paths that drift produce a local preview that is not the
        thing being deployed, which is worse than having no local preview."""
        import json

        vercel = json.loads((ROOT / "vercel.json").read_text())["buildCommand"]
        recipe = next(ln for ln in _recipes() if "autotrader.web.build" in ln)
        self.assertIn("-m autotrader.web.build", vercel)
        self.assertIn("-m autotrader.web.build", recipe)
        for flag in ("--out", "--live"):
            self.assertIn(flag, vercel)
            self.assertIn(flag, recipe)


if __name__ == "__main__":
    unittest.main()
