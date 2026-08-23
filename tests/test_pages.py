"""The disclosure surface, and the switch that must not get ahead of it.

Two independent audits of this product reached the same critical finding: it
puts trade suggestions in front of Indian retail investors while carrying no
regulatory disclosure, no terms, no privacy statement and no jurisdiction.
They separately flagged that the site is ``noindex`` and unfindable.

Those two findings interact, and the order matters — becoming discoverable
before the disclosures exist makes the first one worse, not better. These
tests hold both halves: the disclosures must say the necessary things, and the
indexable switch must be able to say no.
"""

from __future__ import annotations

import re
import unittest

from autotrader.web.pages import about, disclosures, privacy, robots, sitemap

SITE = "https://markets-pro.anchit-tandon.com"


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


class DisclosureTest(unittest.TestCase):
    def setUp(self):
        self.html = disclosures({})
        self.text = _text(self.html)

    def test_it_names_the_regulations_it_is_not_registered_under(self):
        # "Not advice" alone is what every unregistered tipster also says. The
        # specific regulations are what make the position checkable.
        self.assertIn("Research Analysts) Regulations, 2014", self.text)
        self.assertIn("Investment Advisers) Regulations, 2013", self.text)
        self.assertIn("not registered", self.text.lower())

    def test_it_says_no_consideration_is_charged(self):
        # Registration turns on giving recommendations *for consideration*, so
        # whether anything is charged is the load-bearing fact.
        self.assertIn("consideration", self.text.lower())

    def test_it_states_a_jurisdiction(self):
        self.assertIn("Indian law", self.text)

    def test_it_leads_with_the_negative_record(self):
        # A disclosure page that omits the losing record would be a disclosure
        # page working against its own purpose.
        self.assertIn("negative", self.text.lower())
        self.assertIn("absence of an edge", self.text)

    def test_it_disclaims_being_a_broker(self):
        self.assertIn("not a broker", self.text.lower())
        self.assertIn("holds no money", self.text.lower())

    def test_it_warns_about_total_loss(self):
        self.assertIn("entire capital", self.text)
        self.assertIn("does not predict future results", self.text)

    def test_a_missing_contact_is_stated_rather_than_faked(self):
        self.assertIn("No contact address is published", _text(disclosures({})))
        with_contact = _text(disclosures({"contact": "hello@example.com"}))
        self.assertIn("hello@example.com", with_contact)
        self.assertNotIn("No contact address is published", with_contact)


class PrivacyTest(unittest.TestCase):
    def setUp(self):
        self.text = _text(privacy({}))

    def test_it_describes_each_storage_tier_separately(self):
        for heading in ("Without an account", "With an account",
                        "If you connect a broker", "Usage counting"):
            self.assertIn(heading, self.text)

    def test_it_states_that_broker_tokens_never_reach_the_browser(self):
        self.assertIn("never reaches the browser", self.text)

    def test_it_states_that_credentials_are_never_seen(self):
        self.assertIn("never seen by this site", self.text)

    def test_it_says_what_the_usage_counting_does_not_hold(self):
        for absent in ("No identifier", "no session", "no IP address",
                       "no page path", "no cookie"):
            self.assertIn(absent, self.text)


class AboutTest(unittest.TestCase):
    def test_it_links_to_the_disclosures(self):
        self.assertIn('href="/disclosures.html"', about({}))

    def test_attribution_is_omitted_rather_than_invented(self):
        self.assertIn("No author details are published", _text(about({})))
        named = _text(about({"author": "A Person", "contact": "a@example.com"}))
        self.assertIn("A Person", named)
        self.assertNotIn("No author details are published", named)


class IndexingTest(unittest.TestCase):
    """The switch, and the two files that must never disagree about it."""

    def test_not_indexable_disallows_everything(self):
        txt = robots(indexable=False, site=SITE)
        self.assertIn("Disallow: /", txt)
        self.assertNotIn("Sitemap:", txt)

    def test_indexable_allows_pages_but_not_data(self):
        txt = robots(indexable=True, site=SITE)
        self.assertIn("Allow: /", txt)
        # Sidecars are data. Indexing them would put raw JSON in results.
        self.assertIn("Disallow: /d/", txt)
        self.assertIn("Disallow: /api/", txt)
        self.assertIn(f"Sitemap: {SITE}/sitemap.xml", txt)

    def test_the_page_meta_and_robots_txt_read_the_same_flag(self):
        """A meta tag saying one thing and robots.txt another is how a site
        gets indexed by accident."""
        from autotrader.web.render import render_dashboard

        from .test_web import make_report

        for indexable in (True, False):
            html = render_dashboard(make_report(), site={"indexable": indexable})
            meta = re.search(r'<meta name="robots" content="([^"]+)"', html).group(1)
            txt = robots(indexable=indexable, site=SITE)
            if indexable:
                self.assertIn("index", meta)
                self.assertNotIn("noindex", meta)
                self.assertIn("Allow: /", txt)
            else:
                self.assertIn("noindex", meta)
                self.assertIn("Disallow: /", txt)

    def test_the_default_is_not_indexable(self):
        # Discoverability should be a decision someone took, not something a
        # missing config key turned on.
        from autotrader.web.render import render_dashboard

        from .test_web import make_report

        self.assertIn('content="noindex"', render_dashboard(make_report()))
        self.assertIn('content="noindex"', render_dashboard(make_report(), site={}))

    def test_the_sitemap_lists_the_pages_that_exist(self):
        xml = sitemap(site=SITE, pages=("/", "/about.html"))
        self.assertIn(f"<loc>{SITE}/</loc>", xml)
        self.assertIn(f"<loc>{SITE}/about.html</loc>", xml)
        self.assertTrue(xml.startswith("<?xml"))


class FooterTest(unittest.TestCase):
    def test_every_page_is_reachable_from_the_app(self):
        from autotrader.web.render import render_dashboard

        from .test_web import make_report

        html = render_dashboard(make_report())
        for page in ("about.html", "disclosures.html", "privacy.html"):
            self.assertIn(f'href="{page}"', html, f"{page} is published but unlinked")

    def test_the_footer_states_the_position_without_a_click(self):
        from autotrader.web.render import render_dashboard

        from .test_web import make_report

        html = _text(render_dashboard(make_report()))
        self.assertIn("Not investment advice", html)
        self.assertIn("no demonstrated edge", html)


if __name__ == "__main__":
    unittest.main()
