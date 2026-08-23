"""Nothing ships to a reader that nothing uses.

Every byte in the page is downloaded and parsed by every visitor, so an unused
function is not merely untidy — it is a cost paid by people who will never
benefit from it. This module caught six JS functions and a family of CSS rules
that were orphaned when a duplicated section was removed and that had been
shipping ever since.

Deliberately conservative. A class assembled at runtime — ``'num' + (pp ?
' pivotpp' : '')`` — is invisible to a naive scan, so the check counts *any*
mention outside the rule that defines it. That under-reports rather than
over-reports, which is the right direction for a test whose failure mode
would otherwise be deleting something live.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "src" / "autotrader" / "web"

#: Selectors the page never writes itself. State classes toggled by script,
#: or hooks a future section will use, belong here with a reason rather than
#: being silently tolerated.
ALLOWED_UNUSED: dict[str, str] = {
    # Both halves are assembled at runtime — `spark-{tone}` in Python and
    # `'spark-' + (rising ? 'up' : 'down')` in script — so neither name ever
    # exists as a literal to find. Verified by hand at both sites.
    "spark-up": "built as spark-{tone} / 'spark-' + direction",
    "spark-down": "built as spark-{tone} / 'spark-' + direction",
}


def _sources() -> str:
    return "\n".join(p.read_text() for p in sorted(WEB.glob("*.py")))


def _blocks(suffix: str) -> str:
    """The contents of every ``NAME_CSS`` / ``NAME_JS`` triple-quoted constant.

    Scoped deliberately. An earlier version scanned the whole Python source
    for ``.name`` and reported ``document.children`` and every module import
    as an unused CSS class, which is the kind of failing test people learn to
    ignore.
    """
    return "\n".join(
        re.findall(r'^[A-Z_]*' + suffix + r' = """(.*?)"""', _sources(), re.S | re.M)
    )


class DeadJavaScriptTest(unittest.TestCase):
    def test_every_function_defined_is_called(self):
        scripts = _blocks("_JS")
        self.assertTrue(scripts, "no JS constants found — the scan is broken")
        names = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", scripts))
        dead = sorted(
            name for name in names
            if len(re.findall(r"\b" + re.escape(name) + r"\b", scripts)) <= 1
        )
        self.assertEqual(
            dead, [],
            f"defined but never called, and shipped to every visitor: {dead}",
        )


class DeadStylesheetTest(unittest.TestCase):
    def test_every_class_rule_has_a_user(self):
        styles = _blocks("_CSS")
        self.assertTrue(styles, "no CSS constants found — the scan is broken")
        # Where a class could be applied: markup and script, anywhere in the
        # package. A class assembled at runtime still shows up as a string.
        appliers = _sources()
        defined = set(re.findall(r"\.([a-zA-Z][\w-]{2,})(?=[\s,{:.\[>+~])", styles))
        dead = []
        for name in sorted(defined):
            if name in ALLOWED_UNUSED:
                continue
            mentions = len(re.findall(r"\b" + re.escape(name) + r"\b", appliers))
            as_rule = len(re.findall(r"\." + re.escape(name) + r"(?=[\s,{:.\[>+~])", styles))
            if mentions <= as_rule:
                dead.append(name)
        self.assertEqual(
            dead, [],
            "styled but never applied — remove the rule, or add it to "
            f"ALLOWED_UNUSED with a reason: {dead}",
        )


if __name__ == "__main__":
    unittest.main()
