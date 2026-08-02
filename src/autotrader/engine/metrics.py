"""Performance measurement.

Reported honestly, which mostly means reporting the uncomfortable numbers with
the same prominence as the flattering ones. Return without drawdown, volatility
and trade count is not a result — a 40% return from three trades is noise, and a
40% return through a 60% drawdown is not investable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

TRADING_DAYS = 252


@dataclass
class RoundTrip:
    """A completed position: entry through to full exit.

    P&L is recorded in the instrument's own currency, because that is what
    actually changed hands. ``fx_rate`` is the rate to the portfolio's base
    currency at exit, and the ``*_base`` properties apply it.

    **Aggregate statistics must use the base-currency values.** Summing raw
    ``net_pnl`` across a portfolio holding rupees, roubles and dollars adds
    numbers that are not denominated in the same thing, producing a total that
    is off by whatever the exchange rates happen to be.
    """

    key: str
    region: str
    horizon: str
    entry_day: date
    exit_day: date
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    costs: Decimal
    exit_reason: str = ""
    currency: str = "USD"
    base_currency: str = "USD"
    #: Multiplier converting one unit of ``currency`` into ``base_currency``.
    fx_rate: Decimal = Decimal("1")

    @property
    def net_pnl(self) -> Decimal:
        """Net P&L in the instrument's own currency."""
        return self.gross_pnl - self.costs

    @property
    def gross_pnl_base(self) -> Decimal:
        return self.gross_pnl * self.fx_rate

    @property
    def costs_base(self) -> Decimal:
        return self.costs * self.fx_rate

    @property
    def net_pnl_base(self) -> Decimal:
        """Net P&L converted to the portfolio's base currency."""
        return self.net_pnl * self.fx_rate

    @property
    def is_win(self) -> bool:
        # FX rates are positive, so the sign is the same in either currency.
        return self.net_pnl > 0

    @property
    def holding_days(self) -> int:
        return (self.exit_day - self.entry_day).days

    @property
    def return_pct(self) -> float:
        basis = abs(self.entry_price * self.quantity)
        return float(self.net_pnl / basis) if basis > 0 else 0.0


# ---------------------------------------------------------------------------
# Return series
# ---------------------------------------------------------------------------

def equity_returns(equity: Sequence[Decimal]) -> list[float]:
    """Period-over-period returns from an equity curve."""
    out: list[float] = []
    for i in range(1, len(equity)):
        prev = float(equity[i - 1])
        out.append(0.0 if prev == 0 else (float(equity[i]) - prev) / prev)
    return out


def drawdown_series(equity: Sequence[Decimal]) -> list[float]:
    """Fractional drawdown from the running peak at each point."""
    out: list[float] = []
    peak = float("-inf")
    for value in equity:
        v = float(value)
        peak = max(peak, v)
        out.append(0.0 if peak <= 0 else (peak - v) / peak)
    return out


def max_drawdown(equity: Sequence[Decimal]) -> float:
    """Largest peak-to-trough decline, as a positive fraction."""
    dd = drawdown_series(equity)
    return max(dd) if dd else 0.0


def max_drawdown_duration(days: Sequence[date], equity: Sequence[Decimal]) -> int:
    """Longest stretch, in calendar days, spent below a prior peak.

    The stretch runs from the peak to the day the curve *recovers* it, so the
    recovery observation closes the stretch out. Stopping at the last underwater
    observation instead would understate every completed drawdown by one
    sampling interval. A curve still underwater at the end is measured to its
    final point.
    """
    if not equity:
        return 0
    peak = float(equity[0])
    peak_day = days[0]
    worst = 0
    underwater = False
    for day, value in zip(days, equity, strict=False):
        v = float(value)
        if v >= peak:
            if underwater:
                worst = max(worst, (day - peak_day).days)
                underwater = False
            peak = v
            peak_day = day
        else:
            underwater = True
            worst = max(worst, (day - peak_day).days)
    return worst


# ---------------------------------------------------------------------------
# Risk-adjusted return
# ---------------------------------------------------------------------------

def cagr(start_equity: Decimal, end_equity: Decimal, years: float) -> float:
    """Compound annual growth rate.

    Returns ``-1.0`` for a total loss and ``0.0`` for a period too short to
    annualise meaningfully, rather than raising or producing a complex number.
    """
    start, end = float(start_equity), float(end_equity)
    if start <= 0 or years <= 0:
        return 0.0
    if end <= 0:
        return -1.0
    return (end / start) ** (1.0 / years) - 1.0


def annualised_return(returns: Sequence[float], periods_per_year: int = TRADING_DAYS) -> float:
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    return mean * periods_per_year


def annualised_volatility(
    returns: Sequence[float], periods_per_year: int = TRADING_DAYS
) -> float:
    """Sample (ddof=1) standard deviation of returns, annualised."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


def sharpe_ratio(
    returns: Sequence[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """Annualised Sharpe ratio. Zero volatility returns 0.0, not infinity."""
    if len(returns) < 2:
        return 0.0
    rf_period = risk_free_rate / periods_per_year
    excess = [r - rf_period for r in returns]
    mean = sum(excess) / len(excess)
    var = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    return (mean / sd) * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: Sequence[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """Like Sharpe but penalising only downside deviation.

    Downside deviation divides by the *full* sample count, not just the losing
    periods — dividing by the losing count inflates the ratio for strategies
    that lose rarely but badly.
    """
    if len(returns) < 2:
        return 0.0
    rf_period = risk_free_rate / periods_per_year
    excess = [r - rf_period for r in returns]
    mean = sum(excess) / len(excess)
    downside = [min(0.0, r) ** 2 for r in excess]
    dd = math.sqrt(sum(downside) / len(excess))
    if dd == 0:
        return 0.0
    return (mean / dd) * math.sqrt(periods_per_year)


def calmar_ratio(cagr_value: float, max_dd: float) -> float:
    """CAGR divided by max drawdown — return per unit of worst-case pain."""
    return 0.0 if max_dd <= 0 else cagr_value / max_dd


# ---------------------------------------------------------------------------
# Trade statistics
# ---------------------------------------------------------------------------

def win_rate(trades: Sequence[RoundTrip]) -> float:
    return sum(1 for t in trades if t.is_win) / len(trades) if trades else 0.0


def profit_factor(trades: Sequence[RoundTrip]) -> float:
    """Gross profit divided by gross loss.

    Returns ``inf`` when there are no losing trades and at least one winner —
    which is a signal that the sample is too small to trust, not a good result.
    """
    gains = sum(float(t.net_pnl_base) for t in trades if t.net_pnl > 0)
    losses = -sum(float(t.net_pnl_base) for t in trades if t.net_pnl < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def expectancy(trades: Sequence[RoundTrip]) -> float:
    """Average net P&L per trade, in the portfolio's base currency."""
    return sum(float(t.net_pnl_base) for t in trades) / len(trades) if trades else 0.0


def average_win(trades: Sequence[RoundTrip]) -> float:
    wins = [float(t.net_pnl_base) for t in trades if t.net_pnl > 0]
    return sum(wins) / len(wins) if wins else 0.0


def average_loss(trades: Sequence[RoundTrip]) -> float:
    """Mean loss as a positive number."""
    losses = [-float(t.net_pnl_base) for t in trades if t.net_pnl < 0]
    return sum(losses) / len(losses) if losses else 0.0


def max_consecutive_losses(trades: Sequence[RoundTrip]) -> int:
    worst = current = 0
    for trade in trades:
        current = 0 if trade.is_win else current + 1
        worst = max(worst, current)
    return worst


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class PerformanceReport:
    """Complete result of a backtest run."""

    start_day: date
    end_day: date
    base_currency: str
    starting_equity: Decimal
    ending_equity: Decimal
    total_return: float
    cagr: float
    annual_volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    max_drawdown_days: int
    calmar: float
    total_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    average_win: float
    average_loss: float
    max_consecutive_losses: int
    total_costs: Decimal
    total_fills: int
    rejections: int
    by_region: dict[str, dict[str, float]] = field(default_factory=dict)
    by_horizon: dict[str, dict[str, float]] = field(default_factory=dict)
    trades: list[RoundTrip] = field(default_factory=list)
    equity_days: list[date] = field(default_factory=list)
    equity_values: list[Decimal] = field(default_factory=list)

    @property
    def years(self) -> float:
        return max((self.end_day - self.start_day).days / 365.25, 1e-9)

    def summary(self) -> str:
        """Plain-text summary, drawdown and trade count included by design."""
        lines = [
            f"Period        : {self.start_day} to {self.end_day} "
            f"({self.years:.2f} years)",
            f"Equity        : {self.starting_equity:,.2f} -> "
            f"{self.ending_equity:,.2f} {self.base_currency}",
            f"Total return  : {self.total_return:+.2%}",
            f"CAGR          : {self.cagr:+.2%}",
            f"Volatility    : {self.annual_volatility:.2%} annualised",
            f"Sharpe        : {self.sharpe:.2f}",
            f"Sortino       : {self.sortino:.2f}",
            f"Max drawdown  : {self.max_drawdown:.2%} "
            f"(underwater {self.max_drawdown_days} days)",
            f"Calmar        : {self.calmar:.2f}",
            f"Trades        : {self.total_trades} "
            f"(win rate {self.win_rate:.1%})",
            f"Profit factor : {self.profit_factor:.2f}",
            f"Expectancy    : {self.expectancy:+,.2f} per trade",
            f"Worst streak  : {self.max_consecutive_losses} consecutive losses",
            f"Costs paid    : {self.total_costs:,.2f} {self.base_currency}",
            f"Fills         : {self.total_fills}  Rejections: {self.rejections}",
        ]
        return "\n".join(lines)


def build_report(
    *,
    days: Sequence[date],
    equity: Sequence[Decimal],
    trades: Sequence[RoundTrip],
    base_currency: str,
    total_costs: Decimal,
    total_fills: int,
    rejections: int,
    risk_free_rate: float = 0.0,
) -> PerformanceReport:
    """Assemble a :class:`PerformanceReport` from an equity curve and trades."""
    if not days or not equity:
        raise ValueError("cannot build a report from an empty equity curve")

    returns = equity_returns(equity)
    start_equity, end_equity = equity[0], equity[-1]
    years = max((days[-1] - days[0]).days / 365.25, 1e-9)
    total_return = (
        float(end_equity / start_equity) - 1.0 if float(start_equity) > 0 else 0.0
    )
    growth = cagr(start_equity, end_equity, years)
    mdd = max_drawdown(equity)

    by_region: dict[str, dict[str, float]] = {}
    for trade in trades:
        bucket = by_region.setdefault(
            trade.region, {"trades": 0.0, "net_pnl": 0.0, "wins": 0.0}
        )
        bucket["trades"] += 1
        bucket["net_pnl"] += float(trade.net_pnl_base)
        bucket["wins"] += 1 if trade.is_win else 0
    for bucket in by_region.values():
        bucket["win_rate"] = (
            bucket["wins"] / bucket["trades"] if bucket["trades"] else 0.0
        )

    by_horizon: dict[str, dict[str, float]] = {}
    for trade in trades:
        bucket = by_horizon.setdefault(
            trade.horizon, {"trades": 0.0, "net_pnl": 0.0, "wins": 0.0}
        )
        bucket["trades"] += 1
        bucket["net_pnl"] += float(trade.net_pnl_base)
        bucket["wins"] += 1 if trade.is_win else 0
    for bucket in by_horizon.values():
        bucket["win_rate"] = (
            bucket["wins"] / bucket["trades"] if bucket["trades"] else 0.0
        )

    return PerformanceReport(
        start_day=days[0],
        end_day=days[-1],
        base_currency=base_currency,
        starting_equity=start_equity,
        ending_equity=end_equity,
        total_return=total_return,
        cagr=growth,
        annual_volatility=annualised_volatility(returns),
        sharpe=sharpe_ratio(returns, risk_free_rate),
        sortino=sortino_ratio(returns, risk_free_rate),
        max_drawdown=mdd,
        max_drawdown_days=max_drawdown_duration(days, equity),
        calmar=calmar_ratio(growth, mdd),
        total_trades=len(trades),
        win_rate=win_rate(trades),
        profit_factor=profit_factor(trades),
        expectancy=expectancy(trades),
        average_win=average_win(trades),
        average_loss=average_loss(trades),
        max_consecutive_losses=max_consecutive_losses(trades),
        total_costs=total_costs,
        total_fills=total_fills,
        rejections=rejections,
        by_region=by_region,
        by_horizon=by_horizon,
        trades=list(trades),
        equity_days=list(days),
        equity_values=list(equity),
    )
