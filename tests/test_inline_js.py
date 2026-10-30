"""Every inline script on the dashboard must be parseable JavaScript.

A `<th scope="col">` accessibility pass reflowed a line to satisfy the line
length limit and left a JS string literal open across a newline:

    posEl.innerHTML = '<table><thead><tr><th scope="col">Instrument</th>
    <th class="num" scope="col">Qty</th>' +

A single-quoted JavaScript string cannot span a raw newline, so the whole
20KB script block failed to parse and the paper-portfolio table it builds
rendered nothing. Every test passed, the HTML was well formed, the page
looked fine until a tab was opened, and the browser reported only
"SyntaxError: Invalid or unexpected token" with no line number.

CI installs nothing, so there is no JS engine here to parse with. This
tracks quote state instead, which is what the bug actually was: a string
left open at the end of a line.
"""

from __future__ import annotations

import importlib
import unittest

#: Every module in the web package that carries browser code.
_MODULES = ("render", "auth", "broker_ui", "pulse_ui", "search_ui")


def js_constants() -> list[tuple[str, str]]:
    """(qualified name, source) for every ``*_JS`` constant that ships.

    The JS does not live inside ``<script>`` tags in the source -- it lives
    in module-level ``*_JS`` strings that are wrapped in script tags only at
    assembly time. Scanning the rendered page instead would miss whichever
    blocks that particular render path happens not to emit, which is exactly
    how the paper-portfolio block shipped broken.
    """
    out: list[tuple[str, str]] = []
    for name in _MODULES:
        module = importlib.import_module(f"autotrader.web.{name}")
        for attr in sorted(dir(module)):
            if not attr.endswith("_JS"):
                continue
            value = getattr(module, attr)
            if isinstance(value, str):
                out.append((f"{name}.{attr}", value))
    return out


def unterminated_strings(js: str) -> list[tuple[int, str]]:
    """Lines where a ' or " string literal is still open at end of line.

    Deliberately not a JavaScript parser: it answers one question, and only
    knows the constructs it must skip to answer it without crying wolf --
    comments, template literals (which may legally span lines), escapes, and
    regex literals, whose character classes cheerfully contain quotes
    (``/[&<>"]/g`` is not the start of a string).
    """
    #: A '/' here starts a regex, not a division. After a value -- an
    #: identifier, a number, ')' or ']' -- it is division.
    _REGEX_OK = set("(,=:[!&|?{};+-*%~^<>") | {"\n"}

    bad: list[tuple[int, str]] = []
    quote: str | None = None
    in_template = in_block_comment = False
    for lineno, line in enumerate(js.splitlines(), 1):
        i, prev = 0, "\n"          # start of line counts as "expression here"
        while i < len(line):
            ch = line[i]
            if in_block_comment:
                if line.startswith("*/", i):
                    in_block_comment, i = False, i + 2
                else:
                    i += 1
                continue
            if quote is None and not in_template:
                if line.startswith("//", i):
                    break
                if line.startswith("/*", i):
                    in_block_comment, i = True, i + 2
                    continue
                if ch == "/" and prev in _REGEX_OK:
                    i = _skip_regex(line, i)
                    prev = "/"
                    continue
                if ch in "'\"":
                    quote, i = ch, i + 1
                    continue
                if ch == "`":
                    in_template, i = True, i + 1
                    continue
                if not ch.isspace():
                    prev = ch
                i += 1
                continue
            if ch == "\\":
                i += 2
                continue
            if in_template and ch == "`":
                in_template, i = False, i + 1
                continue
            if quote is not None and ch == quote:
                quote, i = None, i + 1
                prev = quote or '"'
                continue
            i += 1
        if quote is not None:
            # Stop at the first one: once a literal is left open, every
            # quote after it is read in the wrong state, so later lines
            # would be reported as broken whether they are or not.
            bad.append((lineno, line.strip()[:90]))
            break
    return bad


def _skip_regex(line: str, i: int) -> int:
    """Index just past the regex literal starting at ``line[i] == '/'``."""
    i += 1
    in_class = False
    while i < len(line):
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            i += 1
            while i < len(line) and line[i].isalpha():   # flags
                i += 1
            return i
        i += 1
    return i


class InlineScriptsParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.constants = js_constants()

    def test_every_js_constant_is_collected(self):
        """A collector that found nothing would pass the test below."""
        self.assertGreaterEqual(len(self.constants), 15)
        names = {n for n, _ in self.constants}
        # The one that shipped broken, and a couple of the larger blocks.
        for expected in ("render.PAPER_JS", "render.SIGNALS_JS", "render.DETAIL_JS"):
            self.assertIn(expected, names)

    def test_no_js_constant_leaves_a_string_literal_open(self):
        failures = [
            f"{name} line {line}: {text}"
            for name, body in self.constants
            for line, text in unterminated_strings(body)
        ]
        self.assertEqual(
            failures, [],
            "a JS string literal is left open at end of line:\n" + "\n".join(failures),
        )

    def test_the_checker_catches_the_bug_it_exists_for(self):
        """Otherwise a broken checker would make the real test vacuous."""
        # The exact shape of the shipped regression.
        broken = (
            "var a = 1;\n"
            "el.innerHTML = '<table><tr><th>A</th>\n"
            "<th>B</th>' +\n"
        )
        self.assertEqual([n for n, _ in unterminated_strings(broken)], [2])

    def test_it_allows_template_literals_and_escapes(self):
        ok = (
            "var t = `a\nmulti line\ntemplate`;\n"
            "var e = 'it\\'s fine';\n"
            'var d = "say \\"hi\\"";\n'
            "var u = 'a' + // trailing 'comment\n"
            "        'b';\n"
            "/* a 'block' comment\n   spanning lines */\n"
        )
        self.assertEqual(unterminated_strings(ok), [])


if __name__ == "__main__":
    unittest.main()
