"""Sign-in wiring, and the two files that have to agree for it to work."""

import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from autotrader.web.auth import (
    AUTH_CSS,
    AUTH_JS,
    SYNCED_DOCUMENTS,
    auth_account_section,
    auth_blob,
    auth_dialog,
    auth_slot,
)
from autotrader.web.build import check_csp_allows, supabase_settings
from autotrader.web.render import PAPER_JS, SETTINGS_JS, render_dashboard

from .test_web import make_report

PROJECT = {"url": "https://example-ref.supabase.co", "anon_key": "sb_publishable_test"}


class BlobTest(unittest.TestCase):
    """The config element is the feature's on/off switch."""

    def test_no_project_renders_nothing(self):
        self.assertEqual(auth_blob(None), "")

    def test_url_without_key_renders_nothing(self):
        # Half a configuration would draw a sign-in button that cannot
        # authenticate, which is worse than no button.
        self.assertEqual(auth_blob({"url": PROJECT["url"]}), "")

    def test_key_without_url_renders_nothing(self):
        self.assertEqual(auth_blob({"anon_key": "sb_publishable_test"}), "")

    def test_carries_origin_and_key(self):
        blob = auth_blob(PROJECT)
        self.assertIn('id="auth-data"', blob)
        self.assertIn(PROJECT["url"], blob)
        self.assertIn(PROJECT["anon_key"], blob)

    def test_trailing_slash_is_stripped(self):
        # The module builds paths as url + '/auth/v1'; a kept slash would
        # request //auth/v1 and 404.
        blob = auth_blob({**PROJECT, "url": PROJECT["url"] + "/"})
        self.assertIn(f'"url": "{PROJECT["url"]}"', blob)

    def test_angle_bracket_cannot_close_the_script_element(self):
        blob = auth_blob({**PROJECT, "anon_key": "</script><script>alert(1)"})
        self.assertNotIn("</script><script>", blob)
        self.assertIn("\\u003c", blob)

    def test_payload_is_valid_json(self):
        body = auth_blob(PROJECT).split(">", 1)[1].rsplit("<", 1)[0]
        self.assertEqual(json.loads(body)["url"], PROJECT["url"])


class MarkupTest(unittest.TestCase):
    def test_dialog_offers_email(self):
        self.assertIn("data-authemail", auth_dialog())
        self.assertIn('type="email"', auth_dialog())

    def test_optional_providers_start_hidden(self):
        # They are revealed only once the project reports them enabled, so a
        # provider nobody has configured never renders a button that fails.
        dialog = auth_dialog()
        for marker in ("data-authgoogle", "data-authphonego"):
            index = dialog.index(marker)
            self.assertIn("hidden", dialog[index:index + 120])

    def test_script_toggled_elements_can_actually_hide(self):
        # Each of these is shown or hidden by setting .hidden from script. A
        # class rule that sets display outranks the user-agent [hidden] rule,
        # so every one of them needs its own [hidden] declaration or it stays
        # on screen with the attribute set and nothing to show for it.
        for selector in (".authpane[hidden]", ".alt[hidden]", ".sep[hidden]"):
            self.assertIn(selector, AUTH_CSS, f"{selector} has no display:none rule")

    def test_no_form_posts_anywhere(self):
        # The CSP permits form-action only to Zerodha. Every form here is
        # handled in script, so none may carry an action.
        self.assertNotIn("<form action", auth_dialog())

    def test_code_screen_admits_the_link_exists(self):
        # The email carries both. A screen that mentions only the code strands
        # the reader who used the link, and the first sign-in from a new
        # address is exactly when that happens.
        dialog = auth_dialog()
        code_pane = dialog.split('data-pane="code"')[1]
        self.assertIn("link in the same email", code_pane)

    def test_code_screen_names_the_address_it_used(self):
        # So a typo is obvious before the reader searches an inbox that will
        # never receive the mail.
        self.assertIn("data-authwhere", auth_dialog())
        self.assertIn("where.textContent = address", AUTH_JS)

    def test_dialog_states_what_the_account_is_not(self):
        self.assertIn("not a broker login", auth_dialog())

    def test_slot_and_account_are_script_filled(self):
        self.assertIn("data-authslot", auth_slot())
        self.assertIn("data-authacct", auth_account_section())


class ModuleTest(unittest.TestCase):
    def test_only_talks_to_the_configured_origin(self):
        # Every request is built from cfg.url; a hardcoded host would be both
        # a CSP violation, since connect-src names one origin, and a second
        # place for the project reference to drift out of date.
        self.assertEqual(re.findall(r"[a-z]+://[^'\" ]*", AUTH_JS), [])

    def test_syncs_exactly_the_documents_it_claims(self):
        # The watchlist joined the set when it stopped being a fixed list the
        # build chose and became one the reader assembles.
        self.assertEqual(SYNCED_DOCUMENTS, ("settings", "paper", "watchlist"))
        for key in SYNCED_DOCUMENTS:
            self.assertIn(f"markets-pro.{key}.v1", AUTH_JS)

    def test_writes_land_in_the_namespaced_table(self):
        self.assertIn("/mp_state", AUTH_JS)

    def test_upserts_rather_than_duplicating_rows(self):
        self.assertIn("resolution=merge-duplicates", AUTH_JS)

    def test_session_store_is_separate_from_synced_state(self):
        # A session sharing a key with a synced document would be uploaded to
        # the account, putting a refresh token in the database.
        self.assertNotIn("markets-pro.session.v1", str(SYNCED_DOCUMENTS))
        self.assertIn("markets-pro.session.v1", AUTH_JS)

    def test_oauth_fragment_is_stripped_before_anything_reads_it(self):
        self.assertIn("history.replaceState", AUTH_JS)

    def test_state_writers_notify_the_sync_layer(self):
        # Without these the account copy would silently stop tracking.
        self.assertIn("__mpStateChanged", SETTINGS_JS)
        self.assertIn("__mpStateChanged", PAPER_JS)

    def test_account_panel_repaints_when_the_sync_state_changes(self):
        # It renders the time of the last sync, which is not known yet when the
        # panel is first drawn; without a repaint the figure is always stale.
        self.assertGreaterEqual(AUTH_JS.count("renderAccountPanel()"), 3)

    def test_sign_out_does_not_delete_the_reader_state(self):
        self.assertNotIn("localStorage.removeItem('markets-pro.paper.v1')", AUTH_JS)
        self.assertNotIn("localStorage.removeItem('markets-pro.settings.v1')", AUTH_JS)

    def test_paper_buy_fails_closed_without_governance_approval(self):
        self.assertIn("governance.eligible !== true", PAPER_JS)
        self.assertIn("WAIT —", PAPER_JS)

    def test_paper_book_enforces_capital_floor_on_reader_sized_order(self):
        self.assertIn("protected_extra_base", PAPER_JS)
        self.assertIn("availableLoss", PAPER_JS)
        self.assertIn("planned loss", PAPER_JS)
        self.assertIn("deployedNotionalBase", PAPER_JS)

    def test_paper_profit_lock_and_review_are_persisted(self):
        self.assertIn("profit_lock_fraction", PAPER_JS)
        self.assertIn("profit_locked_base", PAPER_JS)
        self.assertIn("r_multiple", PAPER_JS)
        self.assertIn("thesis_outcome", PAPER_JS)


class PageTest(unittest.TestCase):
    def test_page_renders_without_a_project(self):
        # Sign-in is additive: a build with no credentials is the old page.
        html = render_dashboard(make_report())
        self.assertNotIn('id="auth-data"', html)
        self.assertIn("Equity", html)

    def test_page_carries_the_project_when_configured(self):
        html = render_dashboard(make_report(), supabase=PROJECT)
        self.assertIn('id="auth-data"', html)
        self.assertIn(PROJECT["url"], html)

    def test_sign_in_is_never_a_gate(self):
        # The dashboard must be readable signed out; nothing here may hide it.
        html = render_dashboard(make_report(), supabase=PROJECT)
        self.assertIn('id="panel-dashboard"', html)
        self.assertNotIn('id="panel-dashboard" hidden', html)


class SettingsTest(unittest.TestCase):
    def _config(self, payload):
        path = Path(self.tmp) / "live.json"
        path.write_text(json.dumps(payload))
        return path

    def setUp(self):
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name
        self.addCleanup(self._dir.cleanup)

    def test_missing_file_is_not_an_error(self):
        self.assertIsNone(supabase_settings(Path(self.tmp) / "absent.json"))

    def test_config_without_the_block(self):
        self.assertIsNone(supabase_settings(self._config({"daily_cap": {}})))

    def test_config_supplies_the_project(self):
        found = supabase_settings(self._config({"supabase": PROJECT}))
        self.assertEqual(found, PROJECT)

    def test_environment_overrides_the_file(self):
        path = self._config({"supabase": PROJECT})
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://other.supabase.co"}):
            self.assertEqual(supabase_settings(path)["url"], "https://other.supabase.co")

    def test_unreadable_config_degrades_to_no_sign_in(self):
        path = Path(self.tmp) / "broken.json"
        path.write_text("{not json")
        self.assertIsNone(supabase_settings(path))


class CspGuardTest(unittest.TestCase):
    """The build must refuse to ship a page whose sign-in the CSP would block."""

    def setUp(self):
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def _vercel(self, policy):
        path = self.tmp / "vercel.json"
        path.write_text(json.dumps(
            {"headers": [{"source": "/(.*)", "headers": [
                {"key": "Content-Security-Policy", "value": policy}]}]}
        ))
        return path

    def test_missing_origin_fails_the_build(self):
        path = self._vercel("default-src 'none'; connect-src 'self'")
        with self.assertRaises(SystemExit) as raised:
            check_csp_allows(PROJECT, path)
        self.assertIn(PROJECT["url"], str(raised.exception))

    def test_present_origin_passes(self):
        path = self._vercel(f"default-src 'none'; connect-src 'self' {PROJECT['url']}")
        check_csp_allows(PROJECT, path)

    def test_absent_vercel_config_is_not_our_business(self):
        check_csp_allows(PROJECT, self.tmp / "absent.json")

    def test_policy_without_connect_src_is_left_alone(self):
        check_csp_allows(PROJECT, self._vercel("default-src 'self'"))


class SidecarRoutingTest(unittest.TestCase):
    """Every file the page fetches must resolve from where the page lives.

    The subdomain serves the document at "/" through a rewrite while the
    sidecars sit under /markets-pro/. Absolute URLs in the page make that
    work, but /stocks.json on the subdomain still 404s, which is a trap for
    anyone -- or anything -- reasoning about the site from its own root. Each
    sidecar now has its own rewrite, and this fails if a new one is added
    without one.
    """

    def setUp(self):
        from autotrader.web.build import SIDECARS, STATIC_PAGES

        root = Path(__file__).resolve().parent.parent
        # Legal pages and robots/sitemap need routing for the same reason the
        # data sidecars do: the subdomain serves the app at "/", so anything
        # under /markets-pro/ is unreachable from where the page appears to
        # live. A 404 on /disclosures.html would be worse than on stocks.json.
        self.sidecars = (*SIDECARS, *STATIC_PAGES, "robots.txt", "sitemap.xml")
        self.rewrites = json.loads((root / "vercel.json").read_text())["rewrites"]

    def test_every_sidecar_resolves_from_the_site_root(self):
        sources = {r["source"]: r["destination"] for r in self.rewrites}
        for name in self.sidecars:
            self.assertIn(f"/{name}", sources,
                          f"/{name} would 404 on the subdomain")
            self.assertEqual(sources[f"/{name}"], f"/markets-pro/{name}")

    def test_the_document_itself_still_resolves(self):
        sources = {r["source"] for r in self.rewrites}
        self.assertIn("/", sources)

    def test_the_api_route_is_not_shadowed(self):
        # A sidecar rewrite must never be broad enough to swallow /api.
        for rewrite in self.rewrites:
            if rewrite["source"] in ("/", "/markets-pro/api/:path*"):
                continue
            self.assertNotIn(":path*", rewrite["source"],
                             f'{rewrite["source"]} is broad enough to catch other routes')


class PayloadWeightTest(unittest.TestCase):
    """What a first visit costs, guarded.

    Expanding the universe from 35 to 325 instruments turned the single stock
    index into a 5.7 MB file that the finder needed before it could open at
    all — every visitor paying for the full history of every company in order
    to search for one. Splitting it fixed that, and these bounds stop it
    coming back the next time the universe grows.
    """

    #: What a first visit costs before anything is opened. The page carries
    #: the shell of every tab; the heavy tables are sidecars fetched on the
    #: tab that needs them. Raising this bound is a decision to charge every
    #: visitor more, so it should be argued for rather than nudged.
    MAX_PAGE_KB = 700
    #: The light index is fetched by every visitor who searches. It carries a
    #: row per instrument and nothing per-session.
    MAX_LIGHT_KB = 600
    #: A detail file is fetched one at a time, so it can afford full history.
    MAX_DETAIL_KB = 120

    def setUp(self):
        from autotrader.web.render import split_index

        from .live_cache import available, load

        if not available():
            self.skipTest("no committed live cache")
        _snapshot, _screener, index = load()
        self.light, self.details = split_index(index)

    def _kb(self, obj):
        return len(json.dumps(obj).encode()) / 1024

    def test_the_page_itself_stays_within_budget(self):
        """The document every visitor downloads, whatever they came for.

        It was 1.7 MB when the universe grew to 325 instruments, because two
        tabs server-rendered every row and then hid nine tenths of them. This
        fails before that can happen again quietly.
        """
        from autotrader.web.render import render_dashboard

        from .live_cache import load
        from .test_web import make_report

        snapshot, screener, _index = load()
        # The report's own numbers are a fixed handful of rows; what is being
        # measured is the shell around them at 325 instruments.
        page = render_dashboard(make_report(), signals=snapshot, screener=screener)
        size = len(page.encode()) / 1024
        self.assertLess(
            size, self.MAX_PAGE_KB,
            f"the page every visitor downloads is {size:.0f} KB — move a table "
            "to a sidecar rather than raising this bound",
        )

    def test_the_shared_index_stays_small_enough_to_fetch_eagerly(self):
        size = self._kb(self.light)
        self.assertLess(
            size, self.MAX_LIGHT_KB,
            f"the index every visitor downloads is {size:.0f} KB — move a "
            "field out of _LIGHT_FIELDS rather than raising this bound",
        )

    def test_no_single_detail_file_is_oversized(self):
        for key, record in self.details.items():
            size = self._kb(record)
            self.assertLess(size, self.MAX_DETAIL_KB, f"{key} detail is {size:.0f} KB")

    def test_the_light_index_carries_no_history(self):
        # History is the bulk. If it reappears here, the split has been undone.
        for key, record in self.light.items():
            for heavy in ("history", "spark", "fundamentals", "screen"):
                self.assertNotIn(heavy, record, f"{key}: {heavy} is back in the light index")

    def test_every_light_row_can_reach_its_detail_file(self):
        from autotrader.web.render import detail_filename

        for key in self.light:
            self.assertIn(key, self.details, f"{key} has no detail file")
            name = detail_filename(key)
            for illegal in (":", "/", "^"):
                self.assertNotIn(illegal, name, f"{key} -> {name} is not a safe filename")


class PulseTest(unittest.TestCase):
    """Usage counting that cannot become user tracking.

    The value of this telemetry is that it answers "does anyone open the
    Evidence tab" without answering "who". These assert the second half stays
    true, because the drift from counting to tracking is a one-line change
    nobody notices in review.
    """

    def setUp(self):
        import importlib.util

        from autotrader.web.pulse_ui import PULSE_JS

        self.js = PULSE_JS
        spec = importlib.util.spec_from_file_location(
            "mp_pulse_api",
            Path(__file__).resolve().parent.parent / "api" / "pulse.py")
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)

    def test_it_collects_nothing_that_identifies_a_reader(self):
        for forbidden in ("location.href", "location.pathname", "document.cookie",
                          "localStorage", "sessionStorage", "referrer",
                          "screen.width", "timezone"):
            self.assertNotIn(forbidden, self.js,
                             f"{forbidden} would make this tracking, not counting")

    def test_event_names_are_a_closed_grammar(self):
        # An unbounded event name is a free-text field, and a free-text field
        # reaching a telemetry table is how person-shaped data arrives.
        for good in ("visit", "tab.evidence", "find.open", "error.js"):
            self.assertRegex(good, self.api.EVENT_RE)
        for bad in ("", "a" * 65, "user@example.com", "tab evidence",
                    "../etc", "<script>", "IN:RELIANCE"):
            self.assertNotRegex(bad, self.api.EVENT_RE, f"{bad!r} should not be storable")

    def test_the_batch_is_bounded(self):
        self.assertLessEqual(self.api.MAX_EVENTS, 64)
        self.assertLessEqual(self.api.MAX_BODY, 64 * 1024)
        self.assertLessEqual(self.api.MAX_MESSAGE, 500)

    def test_it_sends_once_on_the_way_out(self):
        # A request per interaction would be visible in the network panel of a
        # page that otherwise makes almost none.
        self.assertIn("keepalive", self.js)
        self.assertIn("pagehide", self.js)
        self.assertIn("var sent = false", self.js)

    def test_telemetry_failure_never_disturbs_the_page(self):
        self.assertIn(".catch(", self.js)
        self.assertIn("try {", self.js)


class ShippedConfigTest(unittest.TestCase):
    """The two committed files that have to agree, checked against each other.

    This is the regression that cannot be caught locally: the page builds, the
    tests pass, and every sign-in fails in production because the deployed
    header forbids the origin the page was told to call.
    """

    def test_committed_csp_permits_the_committed_project(self):
        root = Path(__file__).resolve().parent.parent
        project = supabase_settings(root / "config" / "live.json")
        if project is None:
            self.skipTest("this build ships without sign-in")
        check_csp_allows(project, root / "vercel.json")


if __name__ == "__main__":
    unittest.main()
