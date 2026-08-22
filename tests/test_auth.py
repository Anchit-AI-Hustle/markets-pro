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
        self.assertEqual(SYNCED_DOCUMENTS, ("settings", "paper"))
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
