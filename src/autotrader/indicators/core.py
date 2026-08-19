"""Technical indicators.

Every function returns a list the *same length as its input*, with ``None`` in
the warm-up region where the indicator is not yet defined. This is deliberate:
the common alternative — returning a shortened list — forces callers to do index
arithmetic to re-align, and getting that arithmetic wrong is a silent
off-by-one that shifts signals forward in time and manufactures profit.

Statistics run in ``float``. These values drive signals, not the ledger; money
arithmetic stays in ``Decimal`` (see :mod:`autotrader.core.money`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

Number = float | int | Decimal
Series = Sequence[Number]
Result = list[float | None]


def _f(values: Series) -> list[float]:
    return [float(v) for v in values]


def _check_period(period: int, name: str) -> None:
    if period < 1:
        raise ValueError(f"{name} period must be >= 1, got {period}")


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(values: Series, period: int) -> Result:
    """Simple moving average."""
    _check_period(period, "sma")
    v = _f(values)
    out: Result = [None] * len(v)
    if len(v) < period:
        return out
    window = sum(v[:period])
    out[period - 1] = window / period
    for i in range(period, len(v)):
        window += v[i] - v[i - period]
        out[i] = window / period
    return out


def ema(values: Series, period: int) -> Result:
    """Exponential moving average, seeded with the SMA of the first ``period``.

    Uses the standard smoothing factor ``2 / (period + 1)``. Seeding with an SMA
    (rather than the first observation) is what most charting packages do, and
    keeps the series comparable with them.
    """
    _check_period(period, "ema")
    v = _f(values)
    out: Result = [None] * len(v)
    if len(v) < period:
        return out
    alpha = 2.0 / (period + 1)
    prev = sum(v[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(v)):
        prev = alpha * v[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def wilder_rma(values: Series, period: int) -> Result:
    """Wilder's smoothing (RMA) — the average used inside RSI, ATR and ADX.

    Equivalent to an EMA with ``alpha = 1 / period``.
    """
    _check_period(period, "wilder_rma")
    v = _f(values)
    out: Result = [None] * len(v)
    if len(v) < period:
        return out
    prev = sum(v[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(v)):
        prev = (prev * (period - 1) + v[i]) / period
        out[i] = prev
    return out


# ---------------------------------------------------------------------------
# Dispersion
# ---------------------------------------------------------------------------

def rolling_std(values: Series, period: int, ddof: int = 0) -> Result:
    """Rolling standard deviation.

    ``ddof=0`` (population) matches the Bollinger Band convention; ``ddof=1``
    (sample) is correct for estimating return volatility.
    """
    _check_period(period, "rolling_std")
    if period - ddof <= 0:
        raise ValueError("period must exceed ddof")
    v = _f(values)
    out: Result = [None] * len(v)
    for i in range(period - 1, len(v)):
        window = v[i - period + 1: i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / (period - ddof)
        out[i] = math.sqrt(var)
    return out


def zscore(values: Series, period: int) -> Result:
    """How many standard deviations the latest value sits from its mean."""
    v = _f(values)
    means = sma(v, period)
    stds = rolling_std(v, period, ddof=0)
    out: Result = [None] * len(v)
    for i in range(len(v)):
        m, s = means[i], stds[i]
        if m is None or s is None or s == 0:
            continue
        out[i] = (v[i] - m) / s
    return out


def bollinger(
    values: Series, period: int = 20, num_std: float = 2.0
) -> tuple[Result, Result, Result]:
    """Bollinger Bands as ``(middle, upper, lower)``."""
    mid = sma(values, period)
    sd = rolling_std(values, period, ddof=0)
    upper: Result = [None] * len(mid)
    lower: Result = [None] * len(mid)
    for i, (m, s) in enumerate(zip(mid, sd, strict=False)):
        if m is None or s is None:
            continue
        upper[i] = m + num_std * s
        lower[i] = m - num_std * s
    return mid, upper, lower


# ---------------------------------------------------------------------------
# Oscillators
# ---------------------------------------------------------------------------

def rsi(values: Series, period: int = 14) -> Result:
    """Wilder's Relative Strength Index, bounded to ``[0, 100]``.

    An all-up window gives RSI 100 (no losses to divide by); an all-down window
    gives 0. Both are handled explicitly rather than by division guard.
    """
    _check_period(period, "rsi")
    v = _f(values)
    out: Result = [None] * len(v)
    if len(v) <= period:
        return out

    gains = [0.0] * len(v)
    losses = [0.0] * len(v)
    for i in range(1, len(v)):
        change = v[i] - v[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)

    avg_gain = sum(gains[1: period + 1]) / period
    avg_loss = sum(losses[1: period + 1]) / period
    out[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period + 1, len(v)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Result, Result, Result]:
    """MACD as ``(macd_line, signal_line, histogram)``.

    The signal line is an EMA of the MACD line computed over the MACD's *defined*
    region only, then re-aligned — averaging over leading ``None``s would bias
    the first few signal values.
    """
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be shorter than slow ({slow})")
    v = _f(values)
    fast_ema = ema(v, fast)
    slow_ema = ema(v, slow)

    line: Result = [None] * len(v)
    for i in range(len(v)):
        if fast_ema[i] is None or slow_ema[i] is None:
            continue
        line[i] = fast_ema[i] - slow_ema[i]

    defined = [x for x in line if x is not None]
    offset = len(v) - len(defined)
    sig_defined = ema(defined, signal) if defined else []

    sig: Result = [None] * len(v)
    for j, val in enumerate(sig_defined):
        sig[offset + j] = val

    hist: Result = [None] * len(v)
    for i in range(len(v)):
        if line[i] is None or sig[i] is None:
            continue
        hist[i] = line[i] - sig[i]
    return line, sig, hist


# ---------------------------------------------------------------------------
# Range / volatility
# ---------------------------------------------------------------------------

def true_range(
    highs: Series, lows: Series, closes: Series
) -> list[float]:
    """Wilder's True Range. The first element has no prior close, so it is H-L."""
    h, l, c = _f(highs), _f(lows), _f(closes)
    if not (len(h) == len(l) == len(c)):
        raise ValueError("high/low/close series must be the same length")
    if not h:
        return []
    out = [h[0] - l[0]]
    for i in range(1, len(h)):
        prev_close = c[i - 1]
        out.append(
            max(h[i] - l[i], abs(h[i] - prev_close), abs(l[i] - prev_close))
        )
    return out


def atr(highs: Series, lows: Series, closes: Series, period: int = 14) -> Result:
    """Average True Range (Wilder smoothing) — the volatility unit used for sizing."""
    return wilder_rma(true_range(highs, lows, closes), period)


def adx(
    highs: Series, lows: Series, closes: Series, period: int = 14
) -> tuple[Result, Result, Result]:
    """Average Directional Index as ``(adx, plus_di, minus_di)``.

    ADX measures trend *strength* without direction, which is what gates the
    long-term trend strategy away from choppy, mean-reverting regimes.
    """
    _check_period(period, "adx")
    h, l, c = _f(highs), _f(lows), _f(closes)
    n = len(h)
    empty: Result = [None] * n
    if n <= period:
        return empty, list(empty), list(empty)

    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up = h[i] - h[i - 1]
        down = l[i - 1] - l[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0

    tr = true_range(h, l, c)
    # Wilder's smoothing starts at index `period`, using bars 1..period so that
    # the seed excludes index 0 (which has no directional movement defined).
    atr_s = _wilder_from_index1(tr, period)
    plus_s = _wilder_from_index1(plus_dm, period)
    minus_s = _wilder_from_index1(minus_dm, period)

    plus_di: Result = [None] * n
    minus_di: Result = [None] * n
    dx: list[float] = []
    dx_index: list[int] = []
    for i in range(n):
        a, p, m = atr_s[i], plus_s[i], minus_s[i]
        if a is None or p is None or m is None or a == 0:
            continue
        pdi = 100.0 * p / a
        mdi = 100.0 * m / a
        plus_di[i] = pdi
        minus_di[i] = mdi
        total = pdi + mdi
        dx.append(0.0 if total == 0 else 100.0 * abs(pdi - mdi) / total)
        dx_index.append(i)

    adx_out: Result = [None] * n
    smoothed = wilder_rma(dx, period)
    for j, val in enumerate(smoothed):
        if val is not None:
            adx_out[dx_index[j]] = val
    return adx_out, plus_di, minus_di


def _wilder_from_index1(values: Sequence[float], period: int) -> Result:
    """Wilder smoothing seeded from ``values[1:period+1]`` (ADX convention)."""
    n = len(values)
    out: Result = [None] * n
    if n <= period:
        return out
    prev = sum(values[1: period + 1])
    out[period] = prev / period
    for i in range(period + 1, n):
        prev = prev - (prev / period) + values[i]
        out[i] = prev / period
    return out


def donchian(
    highs: Series, lows: Series, period: int = 20
) -> tuple[Result, Result]:
    """Donchian channel ``(upper, lower)`` — the breakout reference."""
    _check_period(period, "donchian")
    h, l = _f(highs), _f(lows)
    n = len(h)
    upper: Result = [None] * n
    lower: Result = [None] * n
    for i in range(period - 1, n):
        upper[i] = max(h[i - period + 1: i + 1])
        lower[i] = min(l[i - period + 1: i + 1])
    return upper, lower


# ---------------------------------------------------------------------------
# Trend following
# ---------------------------------------------------------------------------

def supertrend(
    highs: Series, lows: Series, closes: Series, period: int = 10, multiplier: float = 3.0
) -> tuple[Result, list[int | None]]:
    """Supertrend as ``(line, direction)``.

    ``direction`` is ``1`` while the line trails *below* price (uptrend), ``-1``
    while it trails *above* (downtrend), and ``None`` during ATR's warm-up.

    The seed bar (the first with a defined ATR) picks its side by comparing
    close against that bar's own upper band. Every bar after that follows the
    standard flip rule: each band only ever tightens toward price, never widens
    away from it, while the trend holds, and the trend itself only switches
    when price closes through the band on the *opposite* side.
    """
    _check_period(period, "supertrend")
    if multiplier <= 0:
        raise ValueError(f"supertrend multiplier must be > 0, got {multiplier}")
    h, l, c = _f(highs), _f(lows), _f(closes)
    n = len(h)
    if not (len(l) == n and len(c) == n):
        raise ValueError("high/low/close series must be the same length")

    atr_s = atr(h, l, c, period)
    line: Result = [None] * n
    direction: list[int | None] = [None] * n

    final_upper = final_lower = 0.0
    seeded = False
    for i in range(n):
        a = atr_s[i]
        if a is None:
            continue
        mid = (h[i] + l[i]) / 2.0
        basic_upper = mid + multiplier * a
        basic_lower = mid - multiplier * a

        if not seeded:
            final_upper, final_lower = basic_upper, basic_lower
            direction[i] = -1 if c[i] <= final_upper else 1
            line[i] = final_lower if direction[i] == 1 else final_upper
            seeded = True
            continue

        prev_close = c[i - 1]
        final_upper = (
            basic_upper
            if (basic_upper < final_upper or prev_close > final_upper)
            else final_upper
        )
        final_lower = (
            basic_lower
            if (basic_lower > final_lower or prev_close < final_lower)
            else final_lower
        )

        prev_dir = direction[i - 1]
        if prev_dir == -1 and c[i] > final_upper:
            direction[i] = 1
        elif prev_dir == 1 and c[i] < final_lower:
            direction[i] = -1
        else:
            direction[i] = prev_dir
        line[i] = final_lower if direction[i] == 1 else final_upper

    return line, direction


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------

def simple_returns(values: Series) -> list[float]:
    """Period-over-period simple returns; length is ``len(values) - 1``."""
    v = _f(values)
    out: list[float] = []
    for i in range(1, len(v)):
        prev = v[i - 1]
        out.append(0.0 if prev == 0 else (v[i] - prev) / prev)
    return out


def log_returns(values: Series) -> list[float]:
    v = _f(values)
    out: list[float] = []
    for i in range(1, len(v)):
        if v[i - 1] <= 0 or v[i] <= 0:
            out.append(0.0)
        else:
            out.append(math.log(v[i] / v[i - 1]))
    return out


def rate_of_change(values: Series, period: int) -> Result:
    """Percentage change over ``period`` bars, expressed as a fraction."""
    _check_period(period, "rate_of_change")
    v = _f(values)
    out: Result = [None] * len(v)
    for i in range(period, len(v)):
        base = v[i - period]
        out[i] = 0.0 if base == 0 else (v[i] - base) / base
    return out


def annualised_volatility(returns: Sequence[float], periods_per_year: int = 252) -> float:
    """Sample standard deviation of returns, scaled by ``sqrt(periods)``."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


def crossed_above(series: Result, reference: Result, index: int) -> bool:
    """True when ``series`` crosses strictly above ``reference`` at ``index``."""
    if index < 1:
        return False
    a_now, a_prev = series[index], series[index - 1]
    b_now, b_prev = reference[index], reference[index - 1]
    if None in (a_now, a_prev, b_now, b_prev):
        return False
    return a_prev <= b_prev and a_now > b_now


def crossed_below(series: Result, reference: Result, index: int) -> bool:
    """True when ``series`` crosses strictly below ``reference`` at ``index``."""
    if index < 1:
        return False
    a_now, a_prev = series[index], series[index - 1]
    b_now, b_prev = reference[index], reference[index - 1]
    if None in (a_now, a_prev, b_now, b_prev):
        return False
    return a_prev >= b_prev and a_now < b_now
