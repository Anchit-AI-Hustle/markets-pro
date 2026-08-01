"""Row mapping for the Supabase/Postgres store.

Only the pure half is tested here — :func:`report_to_rows` has no network and no
credentials, so it can be verified exhaustively. :class:`SupabaseWriter` is
exercised only for its credential guard; hitting a live database from a unit
test would make the suite non-deterministic and dependent on someone's project.
"""

import json
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from autotrader.core.instrument import AssetClass, Instrument
from autotrader.core.money import Money
from autotrader.engine.metrics import RoundTrip, build_report
from autotrader.persistence.store import (
    ALL_TABLES,
    EQUITY,
    INSTRUMENTS,
    POSITIONS,
    REGION_STATS,
    RUNS,
    TRADES,
    RunMetadata,
    SupabaseWriter,
    new_run_id,
    report_to_rows,
    rows_to_json,
)
from autotrader.portfolio.position import PositionSnapshot


def make_report(trades=None):
    trades = trades if trades is not None else [
        RoundTrip(
            key="IN:RELIANCE", region="IN", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 9),
            entry_price=Decimal("2400"), exit_price=Decimal("2500"),
            quantity=Decimal("100"), gross_pnl=Decimal("10000"),
            costs=Decimal("250"), exit_reason="take_profit",
            currency="INR", base_currency="USD",
            fx_rate=Decimal("1") / Decimal("83"),
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
        days=[date(2024, 1, 1), date(2024, 6, 30), date(2024, 12, 31)],
        equity=[Decimal("100000"), Decimal("104000"), Decimal("108000")],
        trades=trades, base_currency="USD", total_costs=Decimal("312.55"),
        total_fills=8, rejections=2,
    )


META = RunMetadata(
    label="nightly",
    strategy_names=["long_term_momentum", "short_term_swing"],
    regions=["IN", "US"],
    notes="unit test",
    created_at=datetime(2024, 12, 31, 12, 0, tzinfo=timezone.utc),
)


class TestRowMapping(unittest.TestCase):
    def setUp(self):
        self.report = make_report()
        self.run_id = "11111111-2222-3333-4444-555555555555"
        self.tables = report_to_rows(self.report, META, run_id=self.run_id)

    def test_every_table_is_present(self):
        self.assertEqual(set(self.tables), set(ALL_TABLES))

    def test_single_run_row(self):
        self.assertEqual(len(self.tables[RUNS]), 1)

    def test_run_row_fields(self):
        row = self.tables[RUNS][0]
        self.assertEqual(row["id"], self.run_id)
        self.assertEqual(row["label"], "nightly")
        self.assertEqual(row["base_currency"], "USD")
        self.assertEqual(row["start_day"], "2024-01-01")
        self.assertEqual(row["end_day"], "2024-12-31")
        self.assertEqual(row["total_trades"], 2)
        self.assertEqual(row["strategies"], ["long_term_momentum", "short_term_swing"])
        self.assertEqual(row["total_fills"], 8)
        self.assertEqual(row["rejections"], 2)

    def test_run_row_numbers_are_json_safe(self):
        row = self.tables[RUNS][0]
        for key in ("starting_equity", "ending_equity", "total_return", "sharpe"):
            self.assertIsInstance(row[key], float, key)

    def test_equity_rows_match_the_curve(self):
        rows = self.tables[EQUITY]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["day"], "2024-01-01")
        self.assertEqual(rows[0]["equity"], 100000.0)
        self.assertTrue(all(r["run_id"] == self.run_id for r in rows))

    def test_trade_rows(self):
        rows = self.tables[TRADES]
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["instrument_key"], "IN:RELIANCE")
        self.assertEqual(first["region"], "IN")
        self.assertEqual(first["currency"], "INR")
        self.assertEqual(first["exit_reason"], "take_profit")
        self.assertTrue(first["is_win"])

    def test_trade_rows_carry_both_currencies(self):
        first = self.tables[TRADES][0]
        # 9,750 INR net at 1/83 is about 117.47 USD.
        self.assertAlmostEqual(first["net_pnl"], 9750.0, places=6)
        self.assertAlmostEqual(first["net_pnl_base"], 9750 / 83, places=6)
        self.assertEqual(first["base_currency"], "USD")

    def test_losing_trade_is_flagged(self):
        self.assertFalse(self.tables[TRADES][1]["is_win"])
        self.assertLess(self.tables[TRADES][1]["net_pnl"], 0)

    def test_region_stats_rows(self):
        rows = {r["region"]: r for r in self.tables[REGION_STATS]}
        self.assertEqual(set(rows), {"IN", "US"})
        self.assertEqual(rows["IN"]["trades"], 1)
        self.assertEqual(rows["IN"]["win_rate"], 1.0)
        self.assertEqual(rows["US"]["win_rate"], 0.0)

    def test_positions_and_instruments_default_empty(self):
        self.assertEqual(self.tables[POSITIONS], [])
        self.assertEqual(self.tables[INSTRUMENTS], [])

    def test_run_id_is_generated_when_absent(self):
        tables = report_to_rows(self.report, META)
        generated = tables[RUNS][0]["id"]
        self.assertEqual(len(generated), 36)
        self.assertTrue(all(r["run_id"] == generated for r in tables[EQUITY]))

    def test_all_child_rows_share_the_run_id(self):
        for table in (EQUITY, TRADES, REGION_STATS):
            for row in self.tables[table]:
                self.assertEqual(row["run_id"], self.run_id, table)


class TestInfinityHandling(unittest.TestCase):
    """Postgres numeric cannot store infinity; profit factor legitimately can be."""

    def test_infinite_profit_factor_becomes_null(self):
        winner = RoundTrip(
            key="US:A", region="US", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 5),
            entry_price=Decimal("100"), exit_price=Decimal("110"),
            quantity=Decimal("10"), gross_pnl=Decimal("100"), costs=Decimal("0"),
        )
        report = make_report(trades=[winner])
        self.assertEqual(report.profit_factor, float("inf"))
        row = report_to_rows(report, META)[RUNS][0]
        self.assertIsNone(row["profit_factor"])

    def test_rows_serialise_to_valid_json(self):
        report = make_report()
        tables = report_to_rows(report, META)
        parsed = json.loads(rows_to_json(tables))
        self.assertEqual(set(parsed), set(ALL_TABLES))


class TestPositionsAndInstruments(unittest.TestCase):
    def setUp(self):
        self.instrument = Instrument(
            "RELIANCE", "IN", AssetClass.EQUITY, "INR",
            Decimal("0.05"), Decimal("1"), name="Reliance", sector="energy",
        )
        self.snapshot = PositionSnapshot(
            key="IN:RELIANCE", symbol="RELIANCE", region="IN", currency="INR",
            quantity=Decimal("100"), average_cost=Decimal("2400"),
            last_price=Decimal("2500"),
            market_value=Money(Decimal("250000"), "INR"),
            unrealized_pnl=Money(Decimal("10000"), "INR"),
            realized_pnl=Money(Decimal("0"), "INR"),
            opened_on=date(2024, 1, 2), weight=0.12,
        )
        self.tables = report_to_rows(
            make_report(), META,
            positions=[self.snapshot], instruments=[self.instrument],
        )

    def test_position_row(self):
        row = self.tables[POSITIONS][0]
        self.assertEqual(row["instrument_key"], "IN:RELIANCE")
        self.assertEqual(row["quantity"], 100.0)
        self.assertEqual(row["market_value"], 250000.0)
        self.assertEqual(row["unrealized_pnl"], 10000.0)
        self.assertEqual(row["opened_on"], "2024-01-02")
        self.assertAlmostEqual(row["weight"], 0.12, places=8)

    def test_instrument_row(self):
        row = self.tables[INSTRUMENTS][0]
        self.assertEqual(row["key"], "IN:RELIANCE")
        self.assertEqual(row["region"], "IN")
        self.assertEqual(row["asset_class"], "equity")
        self.assertEqual(row["tick_size"], 0.05)
        self.assertEqual(row["sector"], "energy")


class TestWriterGuards(unittest.TestCase):
    def test_missing_credentials_raise(self):
        with self.assertRaises(ValueError):
            SupabaseWriter(url="", key="")

    def test_missing_key_raises(self):
        with self.assertRaises(ValueError):
            SupabaseWriter(url="https://example.supabase.co", key="")

    def test_credentials_are_not_echoed_in_the_error(self):
        try:
            SupabaseWriter(url="", key="")
        except ValueError as exc:
            self.assertNotIn("secret", str(exc).lower())

    def test_table_names_are_all_prefixed(self):
        for table in ALL_TABLES:
            self.assertTrue(table.startswith("mkt_"), table)

    def test_run_ids_are_unique(self):
        self.assertNotEqual(new_run_id(), new_run_id())


if __name__ == "__main__":
    unittest.main()
