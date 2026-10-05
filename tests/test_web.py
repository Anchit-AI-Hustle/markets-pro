"""Dashboard rendering and routing."""

import re
import unittest
from datetime import date
from decimal import Decimal

from autotrader.engine.metrics import RoundTrip, build_report
from autotrader.web.render import (
    JOURNEY_HOLDS,
    JOURNEY_JS,
    JOURNEY_STEPS,
    TABS_JS,
    _pct,
    equity_chart_svg,
    render_dashboard,
)
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

    def test_shows_the_risk_disclaimer(self):
        """Assert the substance, not the wording, so copy can be improved
        without the guarantee quietly disappearing with it."""
        self.assertIn("No profit is promised", self.html)
        self.assertIn("not advice", self.html)
        self.assertIn("do not predict future returns", self.html)

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


def make_signals(**overrides):
    """A snapshot shaped like the live one, with the fields the tour reads."""
    signals = {
        "as_of": {"india": "2026-08-17", "us": "2026-08-17"},
        "usdinr": "88.0",
        "kite_api_key": "",
        "daily_cap": {"INR": "20000", "USD": "250"},
        "starting_cash": {"INR": "500000", "USD": "10000"},
        "governance": {
            "enabled": True,
            "policy": {
                "protected_fraction": "0.90",
                "max_risk_sleeve_fraction": "0.05",
                "profit_lock_fraction": "0.75",
            },
        },
        "watchlist": [
            {"key": "IN:RELIANCE", "symbol": "RELIANCE", "name": "Reliance Industries",
             "region": "india", "sector": "energy"},
            {"key": "IN:TCS", "symbol": "TCS", "name": "TCS", "region": "india", "sector": "tech"},
            {"key": "US:AAPL", "symbol": "AAPL", "name": "Apple", "region": "us", "sector": "tech"},
            {"key": "US:NVDA", "symbol": "NVDA", "name": "NVIDIA", "region": "us", "sector": "tech"},
        ],
        "mechanics": {
            "names": 4, "regions": 2, "sessions": 518,
            "risk_per_trade": "0.0075", "max_position_weight": "0.12",
            "max_cash_utilisation": "0.90", "max_open_positions": 10,
            "max_drawdown_halt": "0.25", "daily_loss_limit": "0.06",
        },
        "orders": [
            {
                "key": "US:AAPL", "symbol": "AAPL", "name": "Apple", "yahoo": "AAPL",
                "region": "us", "exchange": "NASDAQ", "currency": "USD",
                "side": "BUY", "quantity": "5", "reference_price": "300.00",
                "horizon": "short_term", "created_on": "2026-08-17", "fresh": True,
                "reason": "pullback: RSI(2) 5.9 above SMA200",
                "stop_loss": "285.00", "take_profit": "330.00",
                "max_holding_days": 10, "trailing_stop_pct": None,
                "invested": "1500.00", "profit_at_target": "150.00",
                "profit_at_target_pct": "0.10", "loss_at_stop": "75.00",
                "loss_at_stop_pct": "0.05", "reward_risk": "2.0",
                "spark": [290.0, 296.0, 288.0, 302.0, 300.0],
                "history": {"trades": 154, "win_rate": 0.44, "median_days_held": 8},
                "alpaca": {"symbol": "AAPL", "qty": "5", "side": "buy",
                           "type": "market", "time_in_force": "day"},
            },
            {
                "key": "IN:TCS", "symbol": "TCS", "name": "TCS", "yahoo": "TCS.NS",
                "region": "india", "exchange": "NSE", "currency": "INR",
                "side": "BUY", "quantity": "3", "reference_price": "3600.00",
                "horizon": "long_term", "created_on": "2026-08-14", "fresh": False,
                "reason": "momentum rank 2", "stop_loss": "3400.00",
                "take_profit": "4000.00", "max_holding_days": None,
                "trailing_stop_pct": None, "invested": "10800.00",
                "profit_at_target": "1200.00", "loss_at_stop": "600.00",
                "spark": [], "history": {},
                "kite": {"exchange": "NSE", "tradingsymbol": "TCS",
                         "transaction_type": "BUY", "quantity": 3,
                         "order_type": "MARKET", "product": "CNC", "readonly": False},
            },
        ],
        "positions": [],
        "totals": {"signals": {"count": 1}, "positions": {"count": 0}},
    }
    signals.update(overrides)
    return signals


def journey_of(html):
    """Just the walkthrough section, so assertions cannot match its stylesheet."""
    start = html.index('<section class="journey"')
    return html[start:html.index("</section>", start)]


class TestJourney(unittest.TestCase):
    """The self-playing walkthrough that opens the dashboard.

    Its job is to answer "what is this and where do I come into it" before the
    page asks for money, so the checks here are mostly about honesty: the
    figures it states have to be the run's own, and it has to degrade to plain
    readable content when there is no script or no appetite for motion.
    """

    def setUp(self):
        self.report = make_report()
        self.signals = make_signals()
        self.html = render_dashboard(self.report, signals=self.signals)

    def test_renders_seven_steps_wired_as_a_tablist(self):
        self.assertIn('<section class="journey" data-journey', self.html)
        self.assertEqual(self.html.count('role="tabpanel" id="jpanel-'), 7)
        self.assertEqual(self.html.count('data-jgo="'), 7)
        for i in range(7):
            self.assertIn(f'id="jtab-{i}"', self.html)
            self.assertIn(f'aria-controls="jpanel-{i}"', self.html)
            self.assertIn(f'aria-labelledby="jtab-{i}"', self.html)
        self.assertIn('role="tablist" aria-label="Walkthrough steps"', self.html)

    def test_only_the_first_step_starts_selected(self):
        self.assertEqual(self._journey().count('aria-selected="true"'), 1)
        self.assertIn('id="jtab-0" data-jgo="0" aria-controls="jpanel-0" '
                      'aria-selected="true" tabindex="0"', self.html)

    def test_steps_are_readable_without_javascript(self):
        # Panels ship visible; the player is what hides them. A reader with no
        # script gets the whole explanation as an ordinary list.
        panels = re.findall(r'<div class="jpanel"[^>]*>', self._journey())
        self.assertEqual(len(panels), 7)
        for panel in panels:
            self.assertNotIn("hidden", panel)

    def test_each_panel_carries_its_own_hold_duration(self):
        # The script reads pacing off the DOM, so copy and timing cannot drift.
        for hold in JOURNEY_HOLDS:
            self.assertIn(f'data-jhold="{hold}"', self.html)
        self.assertEqual(len(JOURNEY_HOLDS), len(JOURNEY_STEPS))

    def test_the_scan_step_names_the_real_watchlist(self):
        journey = self._journey()
        for i, row in enumerate(self.signals["watchlist"]):
            # The chip's position is what the animation keys off; the name
            # inside it is a link like every other name on the page.
            chip = journey.split(f'<span class="jtick" style="--i:{i}">', 1)[1]
            self.assertIn(row["symbol"], chip.split("</span>", 1)[0])
        self.assertIn("<strong>4</strong> names", self._journey())
        self.assertIn("<strong>518</strong>", self.html)

    def test_the_funnel_counts_are_todays_real_counts(self):
        journey = self._journey()
        # 4 watched, 2 pending on the book, 1 of them fresh.
        self.assertIn(">4</span>", journey)
        self.assertIn(">2</span>", journey)
        self.assertIn(">1</span>", journey)
        self.assertIn("Worth acting on today", journey)

    def test_the_sizing_step_quotes_the_engines_own_limits(self):
        journey = self._journey()
        self.assertIn("<strong>0.75%</strong>", journey)   # risk_per_trade
        self.assertIn("<strong>12%</strong>", journey)     # max_position_weight
        self.assertIn("<strong>10</strong>", journey)      # max_open_positions
        self.assertIn("<strong>6%</strong>", journey)      # daily_loss_limit

    def test_the_trade_step_uses_the_live_signal_with_both_exits(self):
        journey = self._journey()
        self.assertIn("AAPL", journey)
        self.assertIn("target 330.00", journey)
        self.assertIn("stop 285.00", journey)
        self.assertIn("entry 300.00", journey)
        self.assertIn("If the target hits", journey)
        self.assertIn("If the stop hits", journey)

    def test_the_trade_step_prefers_a_fresh_signal_over_a_resting_one(self):
        # TCS is on the book but resting; showing it as "today's trade" would
        # be presenting stale intent as new.
        card = self._journey()
        card = card[card.index("jtradehead"):card.index("joutcomes")]
        self.assertIn("AAPL", card)
        self.assertNotIn("TCS", card)

    def test_a_quiet_day_says_so_instead_of_inventing_a_trade(self):
        """A quiet day may illustrate itself with a trade that already
        finished, but must never present one as actionable."""
        journey = journey_of(
            render_dashboard(self.report, signals=make_signals(orders=[]))
        )
        self.assertIn("No suggestion is live at the moment", journey)
        self.assertIn("Worth acting on today", journey)   # the funnel still says 0
        # Anything shown must be unmistakably in the past.
        self.assertIn("most recent completed trade", journey)
        self.assertIn(">Closed<", journey)
        self.assertIn("win or lose, not\nthe best one", journey)
        # And nothing in that step may look like something to press.
        step = journey[journey.index("jpastgrid"):journey.index("jpastend")]
        self.assertNotIn("data-paper-buy", step)
        self.assertNotIn("data-exec", step)

    def test_a_quiet_day_with_no_history_falls_back_to_prose(self):
        """With no completed trades either, it says so plainly."""
        empty = build_report(
            days=[date(2024, 1, 2), date(2024, 6, 28)],
            equity=[Decimal("100000"), Decimal("101000")],
            trades=[], base_currency="USD",
            total_costs=Decimal("0"), total_fills=0, rejections=0,
        )
        journey = journey_of(
            render_dashboard(empty, signals=make_signals(orders=[]))
        )
        self.assertIn("no live suggestion right now", journey)
        self.assertNotIn("jpastgrid", journey)

    def test_the_quiet_day_trade_is_the_latest_not_the_best(self):
        """Reaching for the winner on a quiet day would be selling."""
        journey = journey_of(
            render_dashboard(self.report, signals=make_signals(orders=[]))
        )
        latest = max(self.report.trades, key=lambda t: t.exit_day)
        self.assertIn(str(latest.exit_day), journey)
        self.assertIn(latest.key.split(":")[-1], journey)

    def test_each_step_states_its_specifics_not_just_its_claim(self):
        """"Rules cut the list down" is not an explanation unless it says
        which rules; every step must carry its own detail."""
        journey = self._journey()
        # Step 1: both amounts and the limit that gates them.
        self.assertIn("Two amounts, one per market", journey)
        self.assertIn("A daily limit, set beside it", journey)
        # Step 2: what is recomputed, and what it refuses to look at.
        self.assertIn("What is recomputed", journey)
        self.assertIn("only completed sessions are used", journey)
        # Step 4: the sizing arithmetic, spelled out.
        self.assertIn("How that becomes a share count", journey)
        self.assertIn("buys <em>fewer</em> shares", journey)
        # Step 6: the routes named, not gestured at.
        self.assertIn("Capped auto-execute", journey)
        self.assertIn("Hand off to your broker", journey)

    def test_the_rules_step_quotes_the_running_strategies(self):
        """Retuning a strategy must not leave the copy describing a system
        that no longer exists, so the tests come from mechanics."""
        signals = make_signals()
        signals["mechanics"] = dict(signals.get("mechanics") or {}, rules=[{
            "book": "Short-term",
            "name": "Buy the dip inside an uptrend",
            "tests": ["price above its 200-day average", "2-day RSI below 10"],
            "exit": "sold when RSI recovers past 60",
        }])
        journey = journey_of(render_dashboard(self.report, signals=signals))
        self.assertIn("Buy the dip inside an uptrend", journey)
        self.assertIn("2-day RSI below 10", journey)
        self.assertIn("sold when RSI recovers past 60", journey)
        self.assertIn("All of these must be true on the same day", journey)

    def test_reading_holds_the_walkthrough(self):
        """Denser steps must not advance out from under a reader. The player
        lives in the page script, not the section markup."""
        html = render_dashboard(self.report, signals=make_signals())
        self.assertIn("pointerenter", html)
        self.assertIn("heldByReader", html)
        self.assertIn("focusin", html)
        # A deliberate pause must not be undone by the pointer wandering off.
        self.assertIn("if (!heldByReader) return;", html)

    def test_the_closing_step_leads_with_the_unflattering_numbers(self):
        journey = self._journey()
        self.assertIn("of trades finished ahead", journey)
        self.assertIn("worst peak-to-trough fall", journey)
        self.assertIn("losses in a row, at worst", journey)
        self.assertIn(f"-{_pct(self.report.max_drawdown)}", journey)
        self.assertIn(f"{_pct(self.report.win_rate, 1)}", journey)

    def test_the_closing_step_promises_nothing(self):
        self.assertIn("Nothing here is a promise", self._journey())

    def test_it_comes_before_the_page_asks_for_money(self):
        self.assertLess(self.html.index("data-journey"),
                        self.html.index("data-needs-setup"))

    def test_it_plays_once_and_does_not_loop(self):
        # The page's motion rule: nothing moves on its own beside live numbers.
        # A tour that restarted forever would be exactly that.
        self.assertNotIn("setInterval", JOURNEY_JS)
        self.assertIn("finished = true", JOURNEY_JS)

    def test_it_can_be_paused_and_jumped(self):
        self.assertIn("data-journey-toggle", self.html)
        self.assertIn('aria-label="Pause the walkthrough"', self.html)
        self.assertIn("ArrowRight", self.html)
        self.assertIn("Home", self.html)

    def test_it_waits_until_it_is_on_screen_and_stops_on_a_hidden_tab(self):
        self.assertIn("IntersectionObserver", self.html)
        self.assertIn("visibilitychange", self.html)

    def test_reduced_motion_gets_the_whole_thing_as_a_document(self):
        self.assertIn("root.classList.add('static')", self.html)
        self.assertIn(".journey.static .jpanel[hidden]{display:flex}", self.html)
        # ...and the stage must reclaim the rail's grid column, not sit in it.
        self.assertIn(".journey.static .jbody{grid-template-columns:1fr}", self.html)

    def test_hidden_panels_are_actually_hidden(self):
        # .jpanel sets `display`, which outranks the user-agent [hidden] rule.
        self.assertIn(".jpanel[hidden]{display:none}", self.html)

    def test_hostile_watchlist_and_signal_text_is_escaped(self):
        signals = make_signals()
        signals["watchlist"][0]["symbol"] = "<script>alert(1)</script>"
        signals["orders"][0]["name"] = "<img src=x onerror=alert(1)>"
        signals["orders"][0]["reason"] = "</style><script>alert(1)</script>"
        html = render_dashboard(self.report, signals=signals)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)

    def test_a_snapshot_without_the_new_fields_still_renders(self):
        # Older cached snapshots predate `watchlist` and `mechanics`; the tour
        # must degrade rather than take the whole page down with it.
        signals = make_signals()
        del signals["watchlist"]
        del signals["mechanics"]
        html = render_dashboard(self.report, signals=signals)
        self.assertIn("data-journey", html)
        self.assertIn("watchlist unavailable", html)

    def test_the_offline_research_dashboard_has_no_tour(self):
        html = render_dashboard(self.report)
        self.assertNotIn('<section class="journey"', html)
        self.assertNotIn("data-jpanel", html)

    def test_it_hands_the_reader_to_the_amount_field(self):
        self.assertIn("data-journey-start", self.html)
        self.assertIn("[data-needs-setup]", JOURNEY_JS)
        self.assertIn("input.focus({preventScroll: true})", JOURNEY_JS)

    def _journey(self):
        return journey_of(self.html)


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


class HeroTest(unittest.TestCase):
    """The first screen has to explain the product on its own.

    A visitor who cannot tell what something does in the first viewport
    leaves. Before this the page opened on a status line and a walkthrough of
    the mechanism, both of which assume the reader already knows what they are
    looking at.
    """

    def setUp(self):
        self.html = render_dashboard(make_report(), signals=make_signals())
        self.hero = self.html.split('<section class="hero">', 1)[1] \
                             .split("</section>", 1)[0]

    def test_the_hero_comes_before_anything_that_assumes_knowledge(self):
        # Ahead of the walkthrough and ahead of the live numbers: both are
        # explanations of a thing the reader has not been told about yet.
        body = self.html.split('id="panel-dashboard"', 1)[1]
        self.assertLess(
            body.index('class="hero"'), body.index("journey"),
            "the walkthrough precedes the explanation of what this is",
        )

    def test_it_says_what_the_product_does(self):
        self.assertIn("Know what to buy", self.hero)
        self.assertIn("your own broker", self.hero)

    def test_it_says_which_markets_and_that_it_is_free(self):
        self.assertIn("Indian", self.hero)
        self.assertIn("free", self.hero.lower())

    def test_it_offers_a_way_in(self):
        self.assertIn("data-tabgo", self.hero)

    def test_the_headline_is_not_shouted(self):
        # h2 is uppercase everywhere else on the page by design; a sentence
        # set in it becomes shouting and is measurably harder to read.
        # Asserted against the rendered page rather than a named constant, so
        # moving the rule between stylesheets does not fail the test for a
        # reason that has nothing to do with the headline.
        rule = self.html.split(".heroline{", 1)[1][:220]
        self.assertIn("text-transform:none", rule)

    def test_a_pass_count_is_never_shown_without_its_luck_budget(self):
        """Three passes out of 975 tests sounds like three rules that work.

        Set against the ~49 that this many tests hand out on luck alone, it is
        the opposite. The two numbers only mean anything together, and showing
        the flattering half alone would be the single most misleading thing
        this product could do — so it is asserted, not left to care.
        """
        html = render_dashboard(make_report(), signals=make_signals(), fitness={
            "tests_run": 975, "instruments_with_evidence": 3,
            "false_positives_expected": 48.8, "alpha": 0.05, "results": {},
        })
        hero = html.split('<section class="hero">', 1)[1].split("</section>", 1)[0]
        self.assertIn("3", hero)
        self.assertIn("luck", hero.lower(),
                      "the pass count appears without the false-positive budget")
        # And the same wherever the study is reported at length.
        self.assertIn("luck alone", html)

    def test_more_passes_than_luck_would_not_claim_an_edge_either(self):
        # Guards the other branch: if a future study does clear the bar, the
        # page must still hand the reader the comparison rather than a boast.
        html = render_dashboard(make_report(), signals=make_signals(), fitness={
            "tests_run": 100, "instruments_with_evidence": 40,
            "false_positives_expected": 5.0, "alpha": 0.05, "results": {},
        })
        self.assertIn("luck alone", html)
        self.assertNotIn("proven", html.lower().split("<footer")[0].replace(
            "unproven", ""), "the page should never call a pass proof")

    def test_the_unflattering_number_is_in_the_hero_too(self):
        # The study found nothing that beat chance. Reporting that on the
        # first screen rather than burying it in a tab is the whole basis for
        # trusting the numbers that would have appeared had anything passed.
        html = render_dashboard(
            make_report(), signals=make_signals(),
            fitness={"tests_run": 102, "instruments_with_evidence": 0},
        )
        hero = html.split('<section class="hero">', 1)[1].split("</section>", 1)[0]
        self.assertIn("102", hero)
        self.assertIn("beat chance", hero)

    def test_it_promises_nothing(self):
        self.assertIn("No", self.hero)
        self.assertIn("profit promised", self.hero)


class ClickableAssetTest(unittest.TestCase):
    """Every named asset opens its own page, wherever the name appears.

    Checked structurally rather than by counting links: the guarantee is that
    a reader who can see a name can open it, so the test asserts on the
    containers that hold a name and fails when a new one is added without a
    route. A symbol that is a link in one table and inert text in another is
    worse than either choice made consistently, because it teaches people not
    to try.
    """

    #: container class -> where it comes from, for a readable failure.
    CONTAINERS = {
        "moversym": "top gainers and losers",
        "wsym": "watchlist rows",
        "screensym": "screener rows",
        "signame": "today's suggested trades",
        "jtick": "the walkthrough's ticker chips",
    }

    def setUp(self):
        self.html = render_dashboard(make_report(), signals=make_signals())

    def _blocks(self, css_class):
        # The element and everything up to its close. Crude on purpose: a real
        # parser here would test the parser, not the page.
        return re.findall(
            r'<[^>]*class="[^"]*\b' + css_class + r'\b[^"]*"[^>]*>(.*?)</',
            self.html, re.S,
        )

    def test_every_named_asset_container_routes_somewhere(self):
        seen = 0
        for css_class, where in self.CONTAINERS.items():
            for block in self._blocks(css_class):
                seen += 1
                self.assertRegex(
                    block, r'data-stock="[^"]+"',
                    f"an asset name in {where} does not open its detail page",
                )
        # A floor, so the test cannot pass by rendering nothing at all.
        self.assertGreater(seen, 3, "no asset containers rendered — fixture drifted")

    def test_completed_trades_link_their_instrument(self):
        record = self.html.split('id="panel-performance"', 1)[1].split("</section>", 1)[0]
        self.assertIn("data-stock", record)

    def test_a_ticker_without_a_key_degrades_to_plain_text(self):
        # An asset the app has no detail page for must still be shown. A dead
        # link that opens an empty page is worse than a name that is just a
        # name.
        from autotrader.web.render import _ticker

        self.assertNotIn("data-stock", _ticker("", "MYSTERY"))
        self.assertIn("MYSTERY", _ticker("", "MYSTERY"))

    def test_a_ticker_escapes_what_it_is_given(self):
        from autotrader.web.render import _ticker

        rendered = _ticker('IN:X"><script>', '<script>alert(1)</script>')
        self.assertNotIn("<script>", rendered)


class TabBarTest(unittest.TestCase):
    """The row has to survive the number of tabs actually in it."""

    def test_tabs_keep_their_own_width_on_a_phone(self):
        # An equal-share rule was fine for five tabs and overlaps their labels
        # at eleven. Whatever the count, a tab sizes to its label and the row
        # scrolls.
        from autotrader.web.render import CSS

        mobile = CSS.split("@media (max-width:640px)")[1]
        self.assertIn(".tabs button{flex:none", mobile)
        self.assertNotIn("flex:1 1 0", mobile)

    def test_a_scrolling_row_reveals_the_active_tab(self):
        # Otherwise the tab a reader is on can sit off-screen with nothing
        # they did to explain it.
        # In show(), not go(): a #hash link and the first load are the two
        # paths where nothing the reader did brought the tab into view, and
        # neither of them goes through go().
        self.assertIn("scrollIntoView", TABS_JS)
        show = TABS_JS.split("function show(")[1].split("function go(")[0]
        self.assertIn("reveal(b)", show)

    def test_every_tab_button_has_a_panel(self):
        # Scoped to the nav: the tab module's own source mentions the
        # attribute too, and matching that would test nothing.
        html = render_dashboard(make_report())
        nav = html.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
        buttons = set(re.findall(r'data-tabbtn="([^"]+)"', nav))
        panels = set(re.findall(r'data-tab="([^"]+)"', html))
        self.assertTrue(buttons)
        self.assertEqual(buttons - panels, set(), "tab with no panel to open")


if __name__ == "__main__":
    unittest.main()
