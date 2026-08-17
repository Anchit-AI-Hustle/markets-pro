"""Signal extraction and the snapshot contract every consumer relies on."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from autotrader.core.money import FXRates
from autotrader.data.universe import universe
from autotrader.data.yahoo import DailyRow, write_cache
from autotrader.engine.metrics import build_report
from autotrader.signals.live import (
    DEFAULT_LIVE_CONFIG,
    _economics,
    _totals,
    generate,
    horizon_stats,
    load_live_config,
)
from autotrader.web.render import plain_reason, render_dashboard


def seed_cache(root: Path, *, sessions: int = 90) -> date:
    """Gently trending bars for every symbol in both regions."""
    day = date(2026, 3, 2)
    days = []
    while len(days) < sessions:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    for region in ("india", "us"):
        base = 2000.0 if region == "india" else 150.0
        for offset, entry in enumerate(universe(region)):
            rows = []
            for i, d in enumerate(days):
                p = base * (1 + 0.02 * offset) * (1 + 0.001 * i)
                rows.append(
                    DailyRow(d, f"{p:.4f}", f"{p * 1.015:.4f}", f"{p * 0.99:.4f}",
                             f"{p * 1.005:.4f}", "100000")
                )
            write_cache(root, entry, rows, entry.currency)
    (root / "fx.json").write_text(json.dumps({"USDINR": "88.0"}))
    return days[-1]


class TestGenerate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.last_day = seed_cache(root)
        cls.snapshot, cls.report = generate(root, None)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_snapshot_is_json_serializable(self):
        json.dumps(self.snapshot)

    def test_snapshot_carries_the_contract_fields(self):
        for field in ("version", "generated_at", "as_of", "equity", "cash",
                      "daily_cap", "orders", "positions", "usdinr"):
            self.assertIn(field, self.snapshot)
        self.assertEqual(self.snapshot["as_of"]["india"], self.last_day.isoformat())
        self.assertEqual(self.snapshot["usdinr"], "88.0")

    def test_snapshot_carries_the_watchlist_it_scanned(self):
        watchlist = self.snapshot["watchlist"]
        self.assertEqual(len(watchlist), len(universe("india")) + len(universe("us")))
        symbols = {row["symbol"] for row in watchlist}
        self.assertIn("RELIANCE", symbols)
        self.assertIn("AAPL", symbols)
        for row in watchlist:
            self.assertEqual(set(row), {"symbol", "name", "region", "sector"})

    def test_mechanics_report_the_constants_the_run_actually_used(self):
        # The dashboard's walkthrough quotes these back as fact, so they have to
        # be read off the run rather than restated in the copy.
        mechanics = self.snapshot["mechanics"]
        self.assertEqual(mechanics["names"], len(self.snapshot["watchlist"]))
        self.assertEqual(mechanics["regions"], len(self.snapshot["as_of"]))
        self.assertEqual(mechanics["risk_per_trade"], "0.0075")
        self.assertEqual(mechanics["max_position_weight"], "0.12")
        self.assertEqual(mechanics["max_open_positions"], 10)
        self.assertEqual(mechanics["daily_loss_limit"], "0.06")
        self.assertGreater(mechanics["sessions"], 0)

    def test_orders_carry_broker_payloads_for_their_region(self):
        for order in self.snapshot["orders"]:
            self.assertIn(order["side"], ("BUY", "SELL"))
            if order["region"] == "india":
                self.assertIn("kite", order)
                self.assertEqual(order["kite"]["exchange"], "NSE")
                self.assertEqual(order["kite"]["quantity"],
                                 int(str(order["quantity"]).split(".")[0]))
            else:
                self.assertIn("alpaca", order)
                self.assertEqual(order["alpaca"]["type"], "market")

    def test_report_period_ends_at_latest_bar(self):
        self.assertEqual(self.report.end_day, self.last_day)

    def test_default_config_used_when_path_missing(self):
        config = load_live_config(Path("/nonexistent/live.json"))
        self.assertEqual(config["daily_cap"], DEFAULT_LIVE_CONFIG["daily_cap"])


class TestEconomics(unittest.TestCase):
    """The money math shown to the user, checked against hand-computed values."""

    def setUp(self):
        self.fx = FXRates("USD", {"INR": Decimal("80"), "USD": Decimal("1")})

    def test_long_trade_profit_loss_and_ratio(self):
        # 10 shares at 100: target 130 → +300; stop 90 → -100; ratio 3:1.
        econ = _economics(
            side="BUY", quantity=Decimal("10"), price=Decimal("100"),
            stop=Decimal("90"), target=Decimal("130"), currency="INR", fx=self.fx,
        )
        self.assertEqual(Decimal(econ["invested"]), Decimal("1000"))
        self.assertEqual(Decimal(econ["profit_at_target"]), Decimal("300"))
        self.assertEqual(Decimal(econ["loss_at_stop"]), Decimal("100"))
        self.assertEqual(Decimal(econ["reward_risk"]), Decimal("3"))
        self.assertEqual(Decimal(econ["profit_at_target_pct"]), Decimal("0.3"))
        self.assertEqual(Decimal(econ["loss_at_stop_pct"]), Decimal("0.1"))

    def test_amounts_convert_to_base_currency(self):
        econ = _economics(
            side="BUY", quantity=Decimal("10"), price=Decimal("100"),
            stop=Decimal("90"), target=Decimal("130"), currency="INR", fx=self.fx,
        )
        # 1000 INR at 80 INR per USD is 12.50 USD.
        self.assertEqual(Decimal(econ["invested_base"]), Decimal("12.5"))
        self.assertEqual(Decimal(econ["profit_at_target_base"]), Decimal("3.75"))
        self.assertEqual(Decimal(econ["loss_at_stop_base"]), Decimal("1.25"))

    def test_short_trade_inverts_direction(self):
        # Short at 100: target 80 is a 20/share GAIN, stop 110 a 10/share LOSS.
        econ = _economics(
            side="SELL", quantity=Decimal("10"), price=Decimal("100"),
            stop=Decimal("110"), target=Decimal("80"), currency="USD", fx=self.fx,
        )
        self.assertEqual(Decimal(econ["profit_at_target"]), Decimal("200"))
        self.assertEqual(Decimal(econ["loss_at_stop"]), Decimal("100"))

    def test_missing_levels_yield_no_fabricated_numbers(self):
        econ = _economics(
            side="BUY", quantity=Decimal("10"), price=Decimal("100"),
            stop=None, target=None, currency="USD", fx=self.fx,
        )
        self.assertIsNone(econ["profit_at_target"])
        self.assertIsNone(econ["loss_at_stop"])
        self.assertIsNone(econ["reward_risk"])
        self.assertEqual(Decimal(econ["invested"]), Decimal("1000"))

    def test_no_price_means_no_economics_at_all(self):
        self.assertEqual(
            _economics(side="BUY", quantity=Decimal("10"), price=None,
                       stop=Decimal("90"), target=Decimal("130"),
                       currency="USD", fx=self.fx),
            {},
        )


class TestPlainReason(unittest.TestCase):
    """Signals must be explainable to someone who does not trade for a living."""

    def test_each_strategy_reason_gets_a_plain_sentence(self):
        cases = {
            "breakout above 20d high, ADX 32, volume 4.1x": "broken above",
            "pullback: RSI(2) 7.5 above SMA200": "buying the dip",
            "momentum +12.3%, ADX 28, vol 24.5%": "steadiest risers",
            "dropped out of momentum ranking or trend filter": "stepping out",
            "mean reversion complete: RSI 65.2": "taking the gain",
        }
        for raw, expected in cases.items():
            plain = plain_reason(raw)
            self.assertIn(expected, plain, f"{raw!r} produced {plain!r}")
            # No indicator jargon may survive into the plain sentence.
            for jargon in ("RSI", "ADX", "SMA", "d high"):
                self.assertNotIn(jargon, plain)

    def test_exit_codes_map_to_their_labels(self):
        self.assertEqual(plain_reason("exit:stop_loss"), "Stop loss")
        self.assertEqual(plain_reason("exit:take_profit"), "Target")

    def test_unknown_reason_passes_through_unchanged(self):
        """Never dress an unrecognised reason up into a claim."""
        self.assertEqual(plain_reason("something new"), "something new")
        self.assertEqual(plain_reason(""), "")


class TestTotals(unittest.TestCase):
    def rows(self):
        return [
            {"fresh": True, "invested_base": "100", "profit_at_target_base": "30",
             "loss_at_stop_base": "10"},
            {"fresh": True, "invested_base": "300", "profit_at_target_base": "60",
             "loss_at_stop_base": "30"},
            {"fresh": False, "invested_base": "999", "profit_at_target_base": "999",
             "loss_at_stop_base": "999"},
        ]

    def test_only_fresh_rows_are_summed_when_requested(self):
        totals = _totals(self.rows(), only_fresh=True)
        self.assertEqual(totals["count"], 2)
        self.assertEqual(Decimal(totals["invested_base"]), Decimal("400"))
        self.assertEqual(Decimal(totals["profit_at_target_base"]), Decimal("90"))
        self.assertEqual(Decimal(totals["loss_at_stop_base"]), Decimal("40"))
        self.assertEqual(Decimal(totals["profit_at_target_pct"]), Decimal("0.225"))

    def test_all_rows_summed_when_not_filtering(self):
        totals = _totals(self.rows(), only_fresh=False)
        self.assertEqual(totals["count"], 3)
        self.assertEqual(Decimal(totals["invested_base"]), Decimal("1399"))

    def test_empty_rows_do_not_divide_by_zero(self):
        totals = _totals([], only_fresh=True)
        self.assertEqual(totals["count"], 0)
        self.assertIsNone(totals["profit_at_target_pct"])

    def test_missing_fields_are_skipped_not_zeroed(self):
        rows = [{"fresh": True, "invested_base": "100"}]
        totals = _totals(rows, only_fresh=True)
        self.assertEqual(Decimal(totals["profit_at_target_base"]), Decimal("0"))
        self.assertEqual(Decimal(totals["invested_base"]), Decimal("100"))


class TestHorizonStats(unittest.TestCase):
    def test_reports_none_rather_than_a_flattering_default(self):
        report = build_report(
            days=[date(2026, 7, 1), date(2026, 7, 2)],
            equity=[Decimal("1000"), Decimal("1000")],
            trades=[],
            base_currency="USD",
            total_costs=Decimal("0"),
            total_fills=0,
            rejections=0,
        )
        self.assertEqual(horizon_stats(report), {})


class TestRenderWithSignals(unittest.TestCase):
    def setUp(self):
        days = [date(2026, 7, 1) + timedelta(days=i) for i in range(3)]
        self.report = build_report(
            days=days,
            equity=[Decimal("100000"), Decimal("100500"), Decimal("101000")],
            trades=[],
            base_currency="USD",
            total_costs=Decimal("0"),
            total_fills=0,
            rejections=0,
        )
        self.signals = {
            "generated_at": "2026-08-02T10:00:00+00:00",
            "as_of": {"india": "2026-07-31", "us": "2026-07-31"},
            "daily_cap": {"INR": "20000", "USD": "250"},
            "kite_api_key": "demo_key",
            "orders": [
                {
                    "key": "IN:RELIANCE", "symbol": "RELIANCE", "name": "Reliance Industries",
                    "yahoo": "RELIANCE.NS", "region": "india", "exchange": "NSE",
                    "currency": "INR", "side": "BUY", "quantity": "10",
                    "reference_price": "1400.00", "notional": "14000.00",
                    "horizon": "short_term", "created_on": "2026-07-31", "fresh": True,
                    "reason": "breakout above 20d high", "stop_loss": "1350.00",
                    "take_profit": "1500.00", "max_holding_days": 10,
                    "trailing_stop_pct": None,
                    # 10 @ 1400: target 1500 → +1,000; stop 1350 → -500; 2:1.
                    "invested": "14000.00", "invested_base": "168.67",
                    "profit_at_target": "1000.00", "profit_at_target_base": "12.05",
                    "profit_at_target_pct": "0.0714",
                    "loss_at_stop": "500.00", "loss_at_stop_base": "6.02",
                    "loss_at_stop_pct": "0.0357", "reward_risk": "2.0",
                    "history": {"trades": 154, "win_rate": 0.44, "median_days_held": 8},
                    "kite": {"exchange": "NSE", "tradingsymbol": "RELIANCE",
                             "transaction_type": "BUY", "quantity": 10,
                             "order_type": "MARKET", "product": "CNC", "readonly": False},
                },
                {
                    "key": "US:AAPL", "symbol": "AAPL", "name": "Apple",
                    "yahoo": "AAPL", "region": "us", "exchange": "NASDAQ",
                    "currency": "USD", "side": "BUY", "quantity": "5",
                    "reference_price": "300.00", "notional": "1500.00",
                    "horizon": "short_term", "created_on": "2026-07-31", "fresh": False,
                    "reason": "pullback", "stop_loss": "285.00", "take_profit": "330.00",
                    "max_holding_days": 10, "trailing_stop_pct": "0.08",
                    "invested": "1500.00", "invested_base": "1500.00",
                    "profit_at_target": "150.00", "profit_at_target_base": "150.00",
                    "profit_at_target_pct": "0.10",
                    "loss_at_stop": "75.00", "loss_at_stop_base": "75.00",
                    "loss_at_stop_pct": "0.05", "reward_risk": "2.0",
                    "history": {"trades": 154, "win_rate": 0.44, "median_days_held": 8},
                    "alpaca": {"symbol": "AAPL", "qty": "5", "side": "buy",
                               "type": "market", "time_in_force": "day"},
                },
            ],
            "positions": [
                {
                    "key": "US:NVDA", "symbol": "NVDA", "name": "NVIDIA", "yahoo": "NVDA",
                    "region": "us", "exchange": "NASDAQ", "currency": "USD",
                    "quantity": "5", "average_cost": "195.04", "last_price": "200.75",
                    "unrealized": "28.55", "opened_on": "2026-07-20",
                    "horizon": "short_term", "stop": "181.14", "take_profit": "233.00",
                    "days_held": 8, "max_holding_days": 15,
                    "unrealized_base": "28.55", "unrealized_pct": "0.0293",
                    "profit_at_target": "161.25", "loss_at_stop": "98.05",
                    "fresh": True,
                },
            ],
            "totals": {
                "signals": {
                    "count": 2, "invested_base": "1668.67",
                    "profit_at_target_base": "162.05", "loss_at_stop_base": "81.02",
                    "profit_at_target_pct": "0.0971", "loss_at_stop_pct": "0.0485",
                },
                "positions": {"count": 1, "invested_base": "1003.75"},
                "open_unrealized_base": "28.55",
            },
        }

    def test_signal_sections_render(self):
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("Today's suggested trades", html)
        self.assertIn("Your paper portfolio", html)
        self.assertIn("RELIANCE", html)
        self.assertIn('data-exec="kite:0"', html)
        self.assertIn('data-exec="us:1"', html)
        self.assertIn('data-quote="NVDA"', html)
        self.assertIn("signals-data", html)
        self.assertIn("STOP HIT", html)  # overlay JS shipped

    def test_stale_orders_are_marked(self):
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("resting", html)

    def test_reason_text_is_escaped(self):
        self.signals["orders"][0]["reason"] = "<script>alert(1)</script>"
        html = render_dashboard(self.report, signals=self.signals)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_json_blob_cannot_break_out_of_script_element(self):
        self.signals["orders"][0]["reason"] = "</script><img src=x>"
        html = render_dashboard(self.report, signals=self.signals)
        blob_start = html.index('id="signals-data"')
        blob_end = html.index("</script>", blob_start)
        blob = html[blob_start:blob_end]
        self.assertNotIn("</script>", blob)
        self.assertIn("\\u003c/script>", blob)

    def test_without_signals_page_is_unchanged_research_dashboard(self):
        html = render_dashboard(self.report)
        self.assertNotIn("Today's signals", html)
        self.assertNotIn("signals-data", html)

    def test_empty_orders_render_the_no_signal_state(self):
        self.signals["orders"] = []
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("Nothing to buy today", html)
        self.assertIn("What to do now", html)

    def test_onboarding_asks_for_the_users_own_amount(self):
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("Start here", html)
        self.assertIn("data-needs-setup", html)
        self.assertIn('data-setting="capital.INR"', html)
        self.assertIn('data-setting="cap.USD"', html)
        self.assertIn("data-settings-save", html)

    def test_quantities_are_labelled_as_the_strategys_until_user_sets_amount(self):
        """Server-rendered sizes belong to the engine and must say so."""
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("Strategy size", html)
        self.assertNotIn(">You invest<", html)

    def test_orders_carry_the_weight_needed_to_resize_them(self):
        self.signals["orders"][0]["weight"] = "0.0965"
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("9.7% of the book", html)
        self.assertIn('data-sigcard="0"', html)

    def test_setup_tab_no_longer_requires_editing_files_for_money(self):
        html = render_dashboard(self.report, signals=self.signals)
        panel = html[html.index('id="panel-setup"'):]
        self.assertIn("Your money", panel)
        self.assertIn('data-setting="capital.INR"', panel)

    def test_money_outcomes_render_per_signal(self):
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("You invest", html)
        self.assertIn("If target hits", html)
        self.assertIn("If stop hits", html)
        self.assertIn("14,000", html)      # invested
        self.assertIn("+1,000", html)      # profit at target
        self.assertIn("500", html)         # loss at stop
        self.assertIn("2.0:1 reward-to-risk", html)
        self.assertIn("within 10 trading days", html)
        self.assertIn("44% of its last 154 trades", html)

    def test_dashboard_money_starts_blank_not_at_the_engines_numbers(self):
        """Headline money is the reader's, filled in by script once they say
        what they have. It must never ship pre-filled with the test book."""
        html = render_dashboard(self.report, signals=self.signals)
        glance = html[html.index('class="glance"'):html.index('class="notice"')]
        self.assertIn('data-cell="today-invest"', glance)
        self.assertIn('data-cell="today-paper"', glance)
        self.assertIn("set your amount to see this", glance)
        # The engine's own equity/cash figures must not appear as the reader's.
        self.assertNotIn("15,2", glance)
        self.assertNotIn("&amp;amp;", html)  # labels must not be double-escaped

    def test_engine_book_is_not_shown_as_the_users_holdings(self):
        """The strategy's test positions belong under the track record."""
        html = render_dashboard(self.report, signals=self.signals)
        invest = html[html.index('id="panel-invest"'):html.index('id="panel-paper"')]
        self.assertNotIn("NVDA", invest)
        self.assertIn("Today's suggested trades", invest)
        performance = html[html.index('id="panel-performance"'):]
        self.assertIn("its own test book", performance)
        self.assertIn("NVDA", performance)

    def test_paper_trading_is_the_primary_action(self):
        """Paper must lead: it is the reversible, no-credential path."""
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn('data-paper-buy="0"', html)
        self.assertIn("Paper buy", html)
        self.assertIn("Your paper portfolio", html)
        self.assertIn('data-tabbtn="paper"', html)
        # Real-broker buttons remain, visually secondary.
        self.assertIn("exec ghost", html)
        self.assertIn('data-exec="kite:0"', html)

    def test_paper_book_gets_the_config_it_needs(self):
        """The paper broker cannot open a book without starting cash and FX."""
        self.signals["starting_cash"] = {"INR": "500000", "USD": "10000"}
        self.signals["usdinr"] = "95.198"
        html = render_dashboard(self.report, signals=self.signals)
        blob_start = html.index('id="signals-data"')
        blob = html[blob_start:html.index("</script>", blob_start)]
        self.assertIn("starting_cash", blob)
        self.assertIn("usdinr", blob)
        self.assertIn("daily_cap", blob)

    def test_paper_state_is_never_baked_into_the_shared_page(self):
        """Paper holdings are per-browser; a static page must not carry them."""
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("data-paper-positions", html)
        self.assertIn("No paper positions yet", html)

    def test_script_written_values_are_never_animated(self):
        """The count-up restores the text it captured when it started, so
        animating a cell that script rewrites can strand a wrong number."""
        html = render_dashboard(self.report, signals=self.signals)
        for dynamic in ("today-invest", "today-upside", "today-downside", "today-paper"):
            marker = f'data-cell="{dynamic}"'
            self.assertIn(marker, html)
            start = html.index(marker)
            element = html[html.rindex("<span", 0, start):html.index(">", start) + 1]
            self.assertNotIn("data-count", element, f"{dynamic} must not be animated")
        # Static figures still get the animation.
        self.assertIn("data-count", html)

    def test_sparkline_plots_the_trades_own_levels(self):
        self.signals["orders"][0]["spark"] = [1360, 1380, 1370, 1395, 1400]
        html = render_dashboard(self.report, signals=self.signals)
        # Assert on markup, not class names — those also appear in the CSS.
        self.assertIn('<div class="sparkwrap">', html)
        self.assertIn('class="sparkline"', html)
        self.assertIn('<line class="sparkstop"', html)
        self.assertIn('<line class="sparktarget"', html)
        self.assertIn("5 sessions", html)

    def test_sparkline_needs_at_least_two_points(self):
        self.signals["orders"][0]["spark"] = [100]
        html = render_dashboard(self.report, signals=self.signals)
        self.assertNotIn('<div class="sparkwrap">', html)

    def test_market_status_is_present_for_both_venues(self):
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn('data-market="india"', html)
        self.assertIn('data-market="us"', html)
        self.assertIn("Asia/Kolkata", html)
        self.assertIn("America/New_York", html)

    def test_cards_sit_in_a_shared_3d_scene(self):
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn('<div class="scene">', html)
        self.assertIn('class="sigcard tilt"', html)
        self.assertIn("perspective:1100px", html)
        self.assertIn("transform-style:preserve-3d", html)
        # Contents ride at different depths, which is what makes it parallax.
        self.assertIn("translateZ(38px)", html)

    def test_tilt_is_limited_to_pointers_that_can_hover(self):
        """A card tilting under a thumb is motion sickness, not delight."""
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("(hover: hover) and (pointer: fine)", html)
        self.assertIn("event.pointerType !== 'mouse'", html)

    def test_tilt_releases_its_frame_handle(self):
        """A handle left set while the page is hidden would kill the tilt for
        the rest of the session."""
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("cancelAnimationFrame(frame)", html)

    def test_odometer_hides_its_digit_strip_from_assistive_tech(self):
        """Each digit carries all ten numerals behind a clip."""
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("wrap.setAttribute('aria-hidden', 'true')", html)
        self.assertIn("node.setAttribute('aria-label', text)", html)

    def test_touch_devices_get_scroll_driven_3d(self):
        """Phones cannot hover, so their depth comes from scroll position."""
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("@media (hover: none), (pointer: coarse)", html)
        self.assertIn("@supports (animation-timeline: view())", html)
        self.assertIn("animation-timeline:view()", html)
        self.assertIn("@keyframes cardturn", html)
        self.assertIn("@keyframes tileturn", html)
        # The rotation must be real 3D, not a fade.
        self.assertIn("rotateX(7deg)", html)
        self.assertIn("rotateX(-7deg)", html)

    def test_3d_collapses_flat_under_reduced_motion(self):
        html = render_dashboard(self.report, signals=self.signals)
        reduced = html[html.index("@media (prefers-reduced-motion:reduce)"):]
        block = reduced[:reduced.index("}\n", reduced.index(".scene"))]
        self.assertIn("perspective:none", block)
        self.assertIn("transform:none !important", block)

    def test_motion_is_disabled_for_reduced_motion_readers(self):
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("prefers-reduced-motion:reduce", html)
        self.assertIn("prefers-reduced-motion: reduce", html)  # the script guard

    def test_negative_amounts_use_a_typographic_minus(self):
        self.signals["positions"][0]["unrealized"] = "-42.50"
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("&minus;42", html)


if __name__ == "__main__":
    unittest.main()
