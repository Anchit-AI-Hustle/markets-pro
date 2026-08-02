"""Signal extraction and the snapshot contract every consumer relies on."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from autotrader.data.universe import universe
from autotrader.data.yahoo import DailyRow, write_cache
from autotrader.engine.metrics import build_report
from autotrader.signals.live import (
    DEFAULT_LIVE_CONFIG,
    generate,
    load_live_config,
)
from autotrader.web.render import render_dashboard


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
                },
            ],
        }

    def test_signal_sections_render(self):
        html = render_dashboard(self.report, signals=self.signals)
        self.assertIn("Today's signals", html)
        self.assertIn("Open positions", html)
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
        self.assertIn("No new orders today", html)


if __name__ == "__main__":
    unittest.main()
