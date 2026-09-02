"""Landmarks and table semantics the page must not lose.

These are the accessibility affordances that are invisible when present and
silent when removed: no visual regression, no failing render, just a page that
became harder to use for people who navigate by landmark or by table header.
A test is the only thing that notices.

Scope is deliberately narrow — structure that is cheap to assert and expensive
to lose. Contrast, focus order and screen-reader phrasing are not testable this
way and are not claimed here.
"""

from __future__ import annotations

import re
import unittest

from autotrader.web.render import render_dashboard
from tests.test_web import make_report


class LandmarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = render_dashboard(make_report())

    def test_there_is_exactly_one_main_landmark(self):
        """Screen readers offer "jump to main content" only if it exists. The
        header and footer sit outside it so the jump lands on the tabs."""
        self.assertEqual(len(re.findall(r"<main[ >]", self.html)), 1)
        self.assertEqual(len(re.findall(r"</main>", self.html)), 1)

    def test_landmarks_are_in_document_order(self):
        order = [m.group(0) for m in re.finditer(r"<header|<nav |<main|</main>|<footer", self.html)]
        self.assertEqual(order[:5], ["<header", "<nav ", "<main", "</main>", "<footer"])

    def test_a_skip_link_precedes_the_tab_bar(self):
        """Ten tabs sit between the top of the page and the content. Without a
        skip link a keyboard user tabs through every one of them, on every
        page load, to reach what they came for."""
        skip = re.search(r'<a class="skip" href="#content"', self.html)
        self.assertIsNotNone(skip, "no skip link")
        self.assertLess(skip.start(), self.html.index("<nav "), "skip link must come before the nav")
        self.assertIn('id="content"', self.html)

    def test_the_skip_link_is_hidden_until_focused(self):
        # Off-screen by default, on-screen on :focus -- a permanently visible
        # skip link is its own visual regression.
        self.assertRegex(self.html, r"\.skip\{[^}]*left:-9999px")
        self.assertRegex(self.html, r"\.skip:focus\{[^}]*left:")


class TableSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = render_dashboard(make_report())

    def test_every_header_cell_declares_its_scope(self):
        """This page is mostly tables of numbers. Without scope, a screen
        reader announcing a cell cannot reliably say which column it is in,
        which is the one thing that makes a table of numbers navigable."""
        unscoped = re.findall(r"<th(?=[ >])(?![^>]*scope=)[^>]*>", self.html)
        self.assertEqual(unscoped, [], f"{len(unscoped)} <th> without scope=")

    def test_headers_are_column_headers(self):
        # Every table here is a flat grid with one header row, so scope="col"
        # is correct everywhere. A row header would need scope="row" and this
        # assertion is what would catch that being added blindly.
        for th in re.findall(r"<th(?=[ >])[^>]*scope=\"([a-z]+)\"", self.html):
            self.assertEqual(th, "col")

    def test_tables_still_have_head_and_body(self):
        self.assertGreaterEqual(len(re.findall(r"<thead>", self.html)), 3)


if __name__ == "__main__":
    unittest.main()
