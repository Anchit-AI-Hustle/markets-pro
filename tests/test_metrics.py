"""Performance metrics.

Expected values are derived by hand from each definition. Where the arithmetic
is not clean, the derivation is written out in the comment so the literal can be
re-checked without rerunning the code.
"""

import unittest
from datetime import date
from decimal import Decimal

from autotrader.engine.metrics import (
    RoundTrip,
    annualised_volatility,
    average_loss,
    average_win,
    build_report,
    cagr,
    calmar_ratio,
    drawdown_series,
    equity_returns,
    expectancy,
    max_consecutive_losses,
    max_drawdown,
    max_drawdown_duration,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)

RETURNS = [0.02, -0.01, 0.03, -0.02]
# mean = 0.005 ; sample sd = sqrt(0.0017/3) = 0.0238047614...
SHARPE = 3.334313581357267
SORTINO = 7.099295739719539
ANN_VOL = 0.37788887255382375


def trade(net, *, region="US", horizon="short_term", entry=100, exit_=110, qty=10):
    """Build a RoundTrip whose net P&L is exactly ``net`` (costs set to zero)."""
    return RoundTrip(
        key=f"{region}:T", region=region, horizon=horizon,
        entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 10),
        entry_price=Decimal(str(entry)), exit_price=Decimal(str(exit_)),
        quantity=Decimal(str(qty)), gross_pnl=Decimal(str(net)), costs=Decimal("0"),
    )


class TestReturnSeries(unittest.TestCase):
    def test_equity_returns(self):
        result = equity_returns([Decimal("100"), Decimal("110"), Decimal("99")])
        self.assertAlmostEqual(result[0], 0.10, places=12)
        self.assertAlmostEqual(result[1], -0.10, places=12)

    def test_length_is_one_less_than_the_curve(self):
        self.assertEqual(len(equity_returns([Decimal(x) for x in (1, 2, 3, 4)])), 3)

    def test_empty_curve(self):
        self.assertEqual(equity_returns([]), [])


class TestDrawdown(unittest.TestCase):
    def test_max_drawdown(self):
        # Peak 120, trough 60 -> (120-60)/120 = 0.5
        equity = [Decimal(x) for x in (100, 120, 60, 80)]
        self.assertAlmostEqual(max_drawdown(equity), 0.5, places=12)

    def test_monotonic_rise_has_no_drawdown(self):
        self.assertEqual(max_drawdown([Decimal(x) for x in (100, 110, 120)]), 0.0)

    def test_drawdown_series_tracks_the_running_peak(self):
        series = drawdown_series([Decimal(x) for x in (100, 120, 60, 80, 130)])
        self.assertAlmostEqual(series[0], 0.0, places=12)
        self.assertAlmostEqual(series[1], 0.0, places=12)
        self.assertAlmostEqual(series[2], 0.5, places=12)
        self.assertAlmostEqual(series[3], 1 / 3, places=12)
        self.assertAlmostEqual(series[4], 0.0, places=12)   # new high

    def test_drawdown_is_never_negative(self):
        for value in drawdown_series([Decimal(x) for x in (100, 90, 110, 105, 130)]):
            self.assertGreaterEqual(value, 0.0)

    def test_drawdown_duration_counts_calendar_days_underwater(self):
        days = [date(2024, 1, 1), date(2024, 1, 11), date(2024, 1, 21), date(2024, 1, 31)]
        equity = [Decimal(x) for x in (100, 90, 80, 120)]
        # Peak on Jan 1; the curve stays below it until Jan 31 -> 30 days.
        self.assertEqual(max_drawdown_duration(days, equity), 30)

    def test_no_drawdown_duration_when_always_rising(self):
        days = [date(2024, 1, 1), date(2024, 1, 2)]
        self.assertEqual(max_drawdown_duration(days, [Decimal("100"), Decimal("110")]), 0)

    def test_empty_equity(self):
        self.assertEqual(max_drawdown([]), 0.0)
        self.assertEqual(max_drawdown_duration([], []), 0)


class TestCAGR(unittest.TestCase):
    def test_known_value(self):
        # 100 -> 121 over 2 years is 10% a year.
        self.assertAlmostEqual(cagr(Decimal("100"), Decimal("121"), 2.0), 0.10, places=10)

    def test_flat_is_zero(self):
        self.assertAlmostEqual(cagr(Decimal("100"), Decimal("100"), 3.0), 0.0, places=12)

    def test_total_loss_is_minus_one(self):
        self.assertEqual(cagr(Decimal("100"), Decimal("0"), 1.0), -1.0)

    def test_zero_years_returns_zero(self):
        self.assertEqual(cagr(Decimal("100"), Decimal("200"), 0.0), 0.0)

    def test_zero_start_returns_zero(self):
        self.assertEqual(cagr(Decimal("0"), Decimal("200"), 1.0), 0.0)


class TestRiskAdjusted(unittest.TestCase):
    def test_annualised_volatility(self):
        self.assertAlmostEqual(annualised_volatility(RETURNS), ANN_VOL, places=12)

    def test_sharpe_known_value(self):
        self.assertAlmostEqual(sharpe_ratio(RETURNS), SHARPE, places=10)

    def test_sharpe_falls_when_the_risk_free_rate_rises(self):
        self.assertLess(sharpe_ratio(RETURNS, risk_free_rate=0.05), sharpe_ratio(RETURNS))

    def test_zero_volatility_returns_zero_not_infinity(self):
        self.assertEqual(sharpe_ratio([0.01, 0.01, 0.01]), 0.0)

    def test_sharpe_of_a_single_return_is_zero(self):
        self.assertEqual(sharpe_ratio([0.05]), 0.0)

    def test_negative_mean_gives_negative_sharpe(self):
        self.assertLess(sharpe_ratio([-0.02, -0.01, -0.03, 0.01]), 0.0)

    def test_sortino_known_value(self):
        self.assertAlmostEqual(sortino_ratio(RETURNS), SORTINO, places=10)

    def test_sortino_exceeds_sharpe_when_downside_is_the_smaller_half(self):
        self.assertGreater(sortino_ratio(RETURNS), sharpe_ratio(RETURNS))

    def test_sortino_with_no_losses_returns_zero(self):
        # No downside deviation at all: the ratio is undefined, reported as 0.
        self.assertEqual(sortino_ratio([0.01, 0.02, 0.03]), 0.0)

    def test_calmar(self):
        self.assertAlmostEqual(calmar_ratio(0.20, 0.10), 2.0, places=12)

    def test_calmar_with_no_drawdown_is_zero(self):
        self.assertEqual(calmar_ratio(0.20, 0.0), 0.0)


class TestTradeStatistics(unittest.TestCase):
    def setUp(self):
        self.trades = [trade(100), trade(50), trade(-75)]

    def test_win_rate(self):
        self.assertAlmostEqual(win_rate(self.trades), 2 / 3, places=12)

    def test_win_rate_of_no_trades_is_zero(self):
        self.assertEqual(win_rate([]), 0.0)

    def test_profit_factor(self):
        # gross profit 150 / gross loss 75 = 2.0
        self.assertAlmostEqual(profit_factor(self.trades), 2.0, places=12)

    def test_profit_factor_with_no_losses_is_infinite(self):
        self.assertEqual(profit_factor([trade(100)]), float("inf"))

    def test_profit_factor_with_no_trades_is_zero(self):
        self.assertEqual(profit_factor([]), 0.0)

    def test_expectancy(self):
        # (100 + 50 - 75) / 3 = 25
        self.assertAlmostEqual(expectancy(self.trades), 25.0, places=12)

    def test_average_win_and_loss(self):
        self.assertAlmostEqual(average_win(self.trades), 75.0, places=12)
        self.assertAlmostEqual(average_loss(self.trades), 75.0, places=12)

    def test_average_loss_is_reported_positive(self):
        self.assertGreater(average_loss([trade(-50), trade(-100)]), 0)

    def test_max_consecutive_losses(self):
        trades = [trade(10), trade(-1), trade(-1), trade(-1), trade(5), trade(-1)]
        self.assertEqual(max_consecutive_losses(trades), 3)

    def test_no_losses_gives_zero_streak(self):
        self.assertEqual(max_consecutive_losses([trade(1), trade(2)]), 0)

    def test_costs_reduce_net_pnl(self):
        t = RoundTrip(
            key="US:T", region="US", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 5),
            entry_price=Decimal("100"), exit_price=Decimal("110"),
            quantity=Decimal("10"), gross_pnl=Decimal("100"), costs=Decimal("30"),
        )
        self.assertEqual(t.net_pnl, Decimal("70"))
        self.assertTrue(t.is_win)

    def test_costs_can_turn_a_gross_win_into_a_net_loss(self):
        t = RoundTrip(
            key="US:T", region="US", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 5),
            entry_price=Decimal("100"), exit_price=Decimal("101"),
            quantity=Decimal("10"), gross_pnl=Decimal("10"), costs=Decimal("30"),
        )
        self.assertFalse(t.is_win)
        self.assertEqual(t.net_pnl, Decimal("-20"))

    def test_holding_days_and_return_pct(self):
        t = trade(100, entry=100, qty=10)
        self.assertEqual(t.holding_days, 8)
        self.assertAlmostEqual(t.return_pct, 0.1, places=12)   # 100 / (100*10)


class TestMultiCurrencyAggregation(unittest.TestCase):
    """Aggregates must convert to base currency before summing.

    Regression guard: summing a rupee trade and a dollar trade as raw numbers
    produces a total inflated by the exchange rate. A 1,000 INR gain is about
    12 USD, not 1,000.
    """

    def setUp(self):
        self.usd = RoundTrip(
            key="US:A", region="US", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 5),
            entry_price=Decimal("100"), exit_price=Decimal("110"),
            quantity=Decimal("10"), gross_pnl=Decimal("100"), costs=Decimal("0"),
            currency="USD", base_currency="USD", fx_rate=Decimal("1"),
        )
        # 8,300 INR at 1/83 = 100 USD — the same economic result as above.
        self.inr = RoundTrip(
            key="IN:B", region="IN", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 5),
            entry_price=Decimal("2000"), exit_price=Decimal("2083"),
            quantity=Decimal("100"), gross_pnl=Decimal("8300"), costs=Decimal("0"),
            currency="INR", base_currency="USD",
            fx_rate=Decimal("1") / Decimal("83"),
        )

    def test_local_and_base_pnl_differ(self):
        self.assertEqual(self.inr.net_pnl, Decimal("8300"))
        self.assertAlmostEqual(float(self.inr.net_pnl_base), 100.0, places=8)

    def test_expectancy_is_in_base_currency(self):
        # Both trades are worth 100 USD, so expectancy is 100 — not 4,200.
        self.assertAlmostEqual(expectancy([self.usd, self.inr]), 100.0, places=6)

    def test_region_breakdown_is_in_base_currency(self):
        report = build_report(
            days=[date(2024, 1, 2), date(2024, 1, 5)],
            equity=[Decimal("100000"), Decimal("100200")],
            trades=[self.usd, self.inr], base_currency="USD",
            total_costs=Decimal("0"), total_fills=4, rejections=0,
        )
        self.assertAlmostEqual(report.by_region["IN"]["net_pnl"], 100.0, places=6)
        self.assertAlmostEqual(report.by_region["US"]["net_pnl"], 100.0, places=6)

    def test_profit_factor_converts_before_dividing(self):
        loser = RoundTrip(
            key="IN:C", region="IN", horizon="short_term",
            entry_day=date(2024, 1, 2), exit_day=date(2024, 1, 5),
            entry_price=Decimal("2000"), exit_price=Decimal("1958.5"),
            quantity=Decimal("100"), gross_pnl=Decimal("-4150"), costs=Decimal("0"),
            currency="INR", base_currency="USD",
            fx_rate=Decimal("1") / Decimal("83"),
        )
        # Gains 200 USD, loss 50 USD -> 4.0
        self.assertAlmostEqual(
            profit_factor([self.usd, self.inr, loser]), 4.0, places=6
        )

    def test_win_flag_is_unaffected_by_conversion(self):
        self.assertTrue(self.inr.is_win)

    def test_default_fx_rate_is_identity(self):
        plain = trade(100)
        self.assertEqual(plain.fx_rate, Decimal("1"))
        self.assertEqual(plain.net_pnl_base, plain.net_pnl)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.days = [date(2024, 1, 1), date(2024, 6, 30), date(2024, 12, 31)]
        self.equity = [Decimal("100000"), Decimal("90000"), Decimal("110000")]
        self.trades = [trade(100, region="US"), trade(-50, region="IN")]
        self.report = build_report(
            days=self.days, equity=self.equity, trades=self.trades,
            base_currency="USD", total_costs=Decimal("250"),
            total_fills=10, rejections=3,
        )

    def test_total_return(self):
        self.assertAlmostEqual(self.report.total_return, 0.10, places=12)

    def test_max_drawdown_recorded(self):
        self.assertAlmostEqual(self.report.max_drawdown, 0.10, places=12)

    def test_endpoints(self):
        self.assertEqual(self.report.start_day, date(2024, 1, 1))
        self.assertEqual(self.report.end_day, date(2024, 12, 31))
        self.assertEqual(self.report.ending_equity, Decimal("110000"))

    def test_trade_counts(self):
        self.assertEqual(self.report.total_trades, 2)
        self.assertAlmostEqual(self.report.win_rate, 0.5, places=12)

    def test_region_breakdown(self):
        self.assertEqual(self.report.by_region["US"]["trades"], 1)
        self.assertEqual(self.report.by_region["US"]["net_pnl"], 100.0)
        self.assertEqual(self.report.by_region["IN"]["net_pnl"], -50.0)
        self.assertEqual(self.report.by_region["IN"]["win_rate"], 0.0)

    def test_horizon_breakdown(self):
        self.assertEqual(self.report.by_horizon["short_term"]["trades"], 2)

    def test_costs_and_fills_carried_through(self):
        self.assertEqual(self.report.total_costs, Decimal("250"))
        self.assertEqual(self.report.total_fills, 10)
        self.assertEqual(self.report.rejections, 3)

    def test_summary_reports_drawdown_and_trade_count(self):
        text = self.report.summary()
        self.assertIn("Max drawdown", text)
        self.assertIn("Trades", text)
        self.assertIn("Costs paid", text)

    def test_empty_curve_rejected(self):
        with self.assertRaises(ValueError):
            build_report(
                days=[], equity=[], trades=[], base_currency="USD",
                total_costs=Decimal("0"), total_fills=0, rejections=0,
            )


if __name__ == "__main__":
    unittest.main()
