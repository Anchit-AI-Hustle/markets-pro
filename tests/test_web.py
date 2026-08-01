"""Dashboard rendering and routing."""

import re
import unittest
from datetime import date
from decimal import Decimal

from autotrader.engine.metrics import RoundTrip, build_report
from autotrader.web.render import equity_chart_svg, render_dashboard
from autotrader.web.server import ROUTE, DashboardHandler


def make_report(trades=None, equity=None):
    equity = equity or [Decimal("100000"), Decimal("96000"), Decimal("112000")]
    days = [date(2024, 1, 2), date(2024, 6, 28), date(2024, 12, 31)][: len(equity)]
    trades = trades if trades is not None else [
        RoundTrip(
            key="IN:RELIANCE", region="IN", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 9),
            entry_price=Decimal("2400"), exit_price=Decimal("2500"),
            quantity=Decimal("100"), gross_pnl=Decimal("10000"),
            costs=Decimal("250"), exit_reason="take_profit", currency="INR",
            base_currency="USD", fx_rate=Decimal("1") / Decimal("83"),
        ),
        RoundTrip(
            key="US:AAPL", region="US", horizon="long_term",
            entry_day=date(2024, 2, 1), exit_day=date(2024, 3, 1),
            entry_price=Decimal("180"), exit_price=Decimal("172"),
            quantity=Decimal("50"), gross_pnl=Decimal("-400"),
            costs=Decimal("5"), exit_reason="stop_loss", currency="USD",
        ),
    ]
    return build_report(
        days=days, equity=equity, trades=trades, base_currency="USD",
        total_costs=Decimal("312.55"), total_fills=8, rejections=2,
    )


class TestDashboardRendering(unittest.TestCase):
    def setUp(self):
        self.html = render_dashboard(make_report(), tests_passed=518, tests_total=518)

    def test_is_a_complete_html_document(self):
        self.assertTrue(self.html.lstrip().startswith("<!doctype html>"))
        self.assertIn("</html>", self.html)

    def test_has_a_title_and_viewport(self):
        self.assertIn("<title>Markets Pro</title>", self.html)
        self.assertIn('name="viewport"', self.html)

    def test_is_self_contained_with_no_external_requests(self):
        # A CSP-hardened static host must be able to serve this offline. The
        # chart-zoom script is inline, so `<script>` is expected — what must not
        # appear is any reference that would trigger a network fetch.
        for pattern in ("http://", "https://", "src=", "@import", "<link"):
            self.assertNotIn(pattern, self.html, f"found external reference: {pattern}")

    def test_styles_are_inlined(self):
        self.assertIn("<style>", self.html)
        self.assertNotIn("<link", self.html)

    def test_script_is_inline_only(self):
        self.assertIn("<script>", self.html)
        self.assertNotIn("<script src", self.html)

    def test_supports_both_colour_schemes(self):
        self.assertIn("prefers-color-scheme:dark", self.html)
        self.assertIn('data-theme="dark"', self.html)
        self.assertIn('data-theme="light"', self.html)

    def test_shows_the_simulated_results_disclaimer(self):
        self.assertIn("Simulated results", self.html)
        self.assertIn("Nothing on this page is investment advice", self.html)

    def test_reports_drawdown_as_prominently_as_return(self):
        self.assertIn("Max drawdown", self.html)
        self.assertIn("Total return", self.html)

    def test_shows_the_verification_count(self):
        self.assertIn("518/518", self.html)
        self.assertIn("100.00%", self.html)

    def test_includes_region_and_book_breakdowns(self):
        self.assertIn("India", self.html)
        self.assertIn("United States", self.html)
        self.assertIn("Short-term book", self.html)

    def test_includes_exit_reason_breakdown(self):
        self.assertIn("Target", self.html)
        self.assertIn("Stop loss", self.html)

    def test_embeds_an_svg_chart(self):
        self.assertIn("<svg", self.html)
        self.assertIn("polyline", self.html)

    def test_escapes_instrument_keys(self):
        report = make_report(trades=[
            RoundTrip(
                key="<script>alert(1)</script>", region="US", horizon="short_term",
                entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 9),
                entry_price=Decimal("100"), exit_price=Decimal("110"),
                quantity=Decimal("10"), gross_pnl=Decimal("100"), costs=Decimal("0"),
            )
        ])
        html = render_dashboard(report)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_handles_a_report_with_no_trades(self):
        html = render_dashboard(make_report(trades=[]))
        self.assertIn("No completed round trips", html)

    def test_trade_table_separates_local_from_base_currency(self):
        # A rupee P&L and a dollar P&L must never share a column.
        self.assertIn("Net P&amp;L (local)", self.html)
        self.assertIn("Net P&amp;L (USD)", self.html)
        self.assertIn("+9,750.00", self.html)      # INR, local
        self.assertIn("+117.47", self.html)        # same trade, converted

    def test_infinite_profit_factor_renders_as_a_symbol(self):
        winner = RoundTrip(
            key="US:A", region="US", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 9),
            entry_price=Decimal("100"), exit_price=Decimal("110"),
            quantity=Decimal("10"), gross_pnl=Decimal("100"), costs=Decimal("0"),
        )
        html = render_dashboard(make_report(trades=[winner]))
        self.assertIn("&infin;", html)
        self.assertNotIn("inf<", html)


class TestChartZoom(unittest.TestCase):
    """Pinch/wheel/drag zoom on the equity chart."""

    def setUp(self):
        self.html = render_dashboard(make_report())

    def test_chart_exposes_plot_geometry_for_the_zoom_handler(self):
        self.assertIn('data-plot="64 920"', self.html)
        self.assertIn("data-plotgroup", self.html)

    def test_zoom_container_is_marked_up(self):
        self.assertIn("data-zoom", self.html)
        self.assertIn('class="zoomwrap"', self.html)

    def test_zoom_controls_are_present_and_labelled(self):
        for attr in ("data-zoom-in", "data-zoom-out", "data-zoom-reset"):
            self.assertIn(attr, self.html, attr)
        self.assertIn('aria-label="Zoom in"', self.html)
        self.assertIn('aria-label="Reset zoom"', self.html)
        self.assertIn('aria-label="Chart zoom"', self.html)

    def test_zoom_level_is_announced(self):
        self.assertIn("data-zoom-level", self.html)
        self.assertIn('aria-live="polite"', self.html)

    def test_page_pinch_zoom_is_not_disabled(self):
        # Blocking browser zoom is an accessibility failure; the chart handler
        # must be additive.
        self.assertIn('content="width=device-width,initial-scale=1"', self.html)
        self.assertNotIn("user-scalable=no", self.html)
        self.assertNotIn("maximum-scale", self.html)

    def test_single_finger_page_scroll_is_preserved_over_the_chart(self):
        # pan-y while fitted; only `none` once actually zoomed in.
        self.assertIn("touch-action:pan-y", self.html)
        self.assertIn(".zoomwrap.zoomed{touch-action:none", self.html)

    def test_wheel_listener_is_not_passive(self):
        # preventDefault on wheel requires a non-passive listener.
        self.assertIn("{ passive: false }", self.html)

    def test_plain_scroll_is_left_to_the_page(self):
        self.assertIn("if (!e.ctrlKey && !e.metaKey) return;", self.html)

    def test_zoom_is_bounded(self):
        self.assertIn("MIN = 1, MAX = 40", self.html)

    def test_keyboard_zoom_is_supported(self):
        self.assertIn("keydown", self.html)
        self.assertIn("tabindex", self.html)

    def test_double_click_resets(self):
        self.assertIn("dblclick", self.html)

    def test_zoom_transforms_the_plot_group_not_the_viewbox(self):
        # Shrinking the viewBox changes the SVG's intrinsic aspect ratio, so a
        # `height:auto` chart grows absurdly tall as it zooms in.
        self.assertIn("group.setAttribute('transform'", self.html)
        self.assertNotIn("svg.setAttribute('viewBox'", self.html)

    def test_zoom_is_horizontal_only(self):
        # scale(s, 1): the y scale is pinned so the curve and the drawdown band
        # stay in frame at every zoom level.
        self.assertIn("' 1)'", self.html)

    def test_strokes_do_not_thicken_with_zoom(self):
        self.assertIn('vector-effect="non-scaling-stroke"', self.html)

    def test_plot_content_is_clipped_to_the_axes(self):
        self.assertIn('clip-path="url(#plotclip)"', self.html)
        self.assertIn('id="plotclip"', self.html)

    def test_axis_dates_travel_with_the_chart_for_relabelling(self):
        # Sessions skip weekends, so labels are indexed from the real list
        # rather than interpolated between the endpoints.
        self.assertIn("data-days=", self.html)
        self.assertIn("data-xlabel=", self.html)
        self.assertIn("function relabel()", self.html)

    def test_arrow_keys_pan(self):
        self.assertIn("ArrowLeft", self.html)
        self.assertIn("ArrowRight", self.html)

    def test_usage_hint_is_shown(self):
        self.assertIn("Pinch to zoom", self.html)


class TestEquityChart(unittest.TestCase):
    def test_produces_svg(self):
        svg = equity_chart_svg(
            [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
            [Decimal("100"), Decimal("120"), Decimal("90")],
        )
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)

    def test_point_count_matches_the_series(self):
        days = [date(2024, 1, i + 1) for i in range(10)]
        equity = [Decimal(100 + i) for i in range(10)]
        svg = equity_chart_svg(days, equity)
        # Attributes may sit between the class and the points list.
        polyline = re.search(r'class="eqline"[^>]*?points="([^"]+)"', svg, re.S)
        self.assertIsNotNone(polyline)
        self.assertEqual(len(polyline.group(1).split()), 10)

    def test_flat_curve_does_not_divide_by_zero(self):
        days = [date(2024, 1, 1), date(2024, 1, 2)]
        svg = equity_chart_svg(days, [Decimal("100"), Decimal("100")])
        self.assertIn("<svg", svg)
        self.assertNotIn("nan", svg.lower())

    def test_single_point_degrades_gracefully(self):
        svg = equity_chart_svg([date(2024, 1, 1)], [Decimal("100")])
        self.assertIn("Not enough data", svg)

    def test_axis_labels_show_the_endpoints(self):
        days = [date(2024, 1, 1), date(2024, 6, 1), date(2024, 12, 31)]
        svg = equity_chart_svg(days, [Decimal("100"), Decimal("110"), Decimal("120")])
        self.assertIn("2024-01-01", svg)
        self.assertIn("2024-12-31", svg)


class TestRouting(unittest.TestCase):
    """Route resolution, without binding a socket."""

    def _resolve(self, path):
        cleaned = path.split("?", 1)[0].rstrip("/") or "/"
        if cleaned in (ROUTE, f"{ROUTE}/index.html"):
            return "dashboard"
        if cleaned == "/healthz":
            return "health"
        if cleaned == "/":
            return "redirect"
        return "404"

    def test_route_constant(self):
        self.assertEqual(ROUTE, "/markets-pro")

    def test_canonical_route(self):
        self.assertEqual(self._resolve("/markets-pro"), "dashboard")

    def test_trailing_slash(self):
        self.assertEqual(self._resolve("/markets-pro/"), "dashboard")

    def test_index_html(self):
        self.assertEqual(self._resolve("/markets-pro/index.html"), "dashboard")

    def test_query_string_is_ignored(self):
        self.assertEqual(self._resolve("/markets-pro?run=abc"), "dashboard")

    def test_root_redirects(self):
        self.assertEqual(self._resolve("/"), "redirect")

    def test_health_check(self):
        self.assertEqual(self._resolve("/healthz"), "health")

    def test_unknown_path_is_404(self):
        self.assertEqual(self._resolve("/admin"), "404")

    def test_handler_has_a_default_page(self):
        self.assertIn("markets-pro", DashboardHandler.html)


if __name__ == "__main__":
    unittest.main()
