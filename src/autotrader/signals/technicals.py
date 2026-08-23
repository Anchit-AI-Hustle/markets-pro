"""The technical block a reader coming from Moneycontrol or ET expects.

Those pages set the floor for what an Indian retail investor considers a
complete stock page: moving averages at six periods, an oscillator panel,
three flavours of pivot level, and a handful of traded-value figures. This
app already computed most of the underlying indicators for its strategies and
simply never showed them; this module assembles them into the shape the
detail page renders.

What is deliberately absent is as important as what is here. Everything below
is derived from OHLCV bars this app already holds, so every figure can be
recomputed from the cache and checked. Moneycontrol also shows P/E, book
value, ROE, promoter holding and analyst estimates, none of which are
derivable from price — for Indian listings there is no free source for them
(the SEC covers US filings only, and the exchanges refuse automated access).
Those are reported as unavailable with the reason rather than estimated,
because a fabricated ratio on a page someone invests from is worse than a
missing one.
"""

from __future__ import annotations

from ..indicators.core import (
    adx,
    annualised_volatility,
    atr,
    bollinger,
    ema,
    macd,
    rate_of_change,
    rsi,
    simple_returns,
    sma,
    supertrend,
)

#: The periods every Indian broker and portal quotes. Five and ten matter to
#: short-term traders, fifty and two hundred to everyone else.
MA_PERIODS = (5, 10, 20, 50, 100, 200)


def _last(result) -> float | None:
    """The most recent defined value of an indicator series."""
    values = getattr(result, "values", result)
    for value in reversed(list(values)):
        if value is not None:
            return float(value)
    return None


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(float(value), places)


def moving_averages(closes: list[float]) -> dict:
    """Each period's simple and exponential average, and which side price is on.

    The verdict per period is what these pages actually lead with — a column
    of numbers means little next to "price is above eleven of twelve", which
    is the summary a reader is really after.
    """
    last = closes[-1]
    rows, above = [], 0
    for period in MA_PERIODS:
        if len(closes) < period:
            rows.append({"period": period, "sma": None, "ema": None, "verdict": None})
            continue
        simple = _last(sma(closes, period))
        exponential = _last(ema(closes, period))
        for value in (simple, exponential):
            if value is not None and last > value:
                above += 1
        rows.append({
            "period": period,
            "sma": _round(simple),
            "ema": _round(exponential),
            "verdict": None if simple is None else ("above" if last > simple else "below"),
        })
    counted = sum(1 for r in rows if r["sma"] is not None) * 2
    return {
        "rows": rows,
        "above": above,
        "counted": counted,
        # Named the way the portals name it, because that is the vocabulary a
        # reader arrives with.
        "bias": (
            "bullish" if counted and above >= counted * 0.7
            else "bearish" if counted and above <= counted * 0.3
            else "neutral"
        ),
    }


def crossovers(closes: list[float]) -> list[dict]:
    """Golden and death crosses on the pairs these pages watch."""
    out = []
    for fast, slow in ((5, 20), (20, 50), (50, 200)):
        if len(closes) < slow + 2:
            continue
        quick, steady = sma(closes, fast), sma(closes, slow)
        now_fast, now_slow = _last(quick), _last(steady)
        if now_fast is None or now_slow is None:
            continue
        out.append({
            "pair": f"{fast}/{slow}",
            "state": "above" if now_fast > now_slow else "below",
            # The 50/200 pair is the one with the folk names attached.
            "label": ("Golden cross" if (fast, slow) == (50, 200) and now_fast > now_slow
                      else "Death cross" if (fast, slow) == (50, 200)
                      else f"{fast}-day {'over' if now_fast > now_slow else 'under'} {slow}-day"),
        })
    return out


def oscillators(highs: list[float], lows: list[float], closes: list[float]) -> dict:
    """RSI, MACD, ADX, ATR, Bollinger and Supertrend, each with a reading.

    The reading matters more than the number. "RSI 71" means nothing to most
    readers; "overbought" is the thing they came for, and stating both keeps
    the page honest with the ones who do read the number.
    """
    out: dict = {}

    value = _last(rsi(closes, 14))
    out["rsi"] = {
        "value": _round(value),
        "reading": None if value is None else (
            "overbought" if value >= 70 else "oversold" if value <= 30 else "neutral"),
    }

    if len(closes) >= 35:
        line, signal, histogram = macd(closes)
        line_v, signal_v, hist_v = _last(line), _last(signal), _last(histogram)
        out["macd"] = {
            "value": _round(line_v, 3), "signal": _round(signal_v, 3),
            "histogram": _round(hist_v, 3),
            "reading": None if hist_v is None else ("bullish" if hist_v > 0 else "bearish"),
        }

    if len(closes) >= 30:
        strength, plus_di, minus_di = adx(highs, lows, closes, 14)
        value = _last(strength)
        up, down = _last(plus_di), _last(minus_di)
        out["adx"] = {
            "value": _round(value),
            "plus_di": _round(up), "minus_di": _round(down),
            "reading": None if value is None else (
                "strong trend" if value >= 25 else "weak or ranging"),
            "direction": None if up is None or down is None else (
                "up" if up > down else "down"),
        }

    value = _last(atr(highs, lows, closes, 14))
    out["atr"] = {
        "value": _round(value),
        "percent": None if value is None else _round(value / closes[-1] * 100),
    }

    if len(closes) >= 20:
        # (middle, upper, lower) is the order this returns; unpacking it
        # as (upper, middle, lower) swaps the bands and reports nonsense.
        middle, upper, lower = bollinger(closes, 20, 2.0)
        top, mid, bottom = _last(upper), _last(middle), _last(lower)
        if top is not None and bottom is not None and top > bottom:
            position = (closes[-1] - bottom) / (top - bottom) * 100
            out["bollinger"] = {
                "upper": _round(top), "middle": _round(mid), "lower": _round(bottom),
                "percent_b": _round(position),
                "reading": ("above the band" if position > 100
                            else "below the band" if position < 0
                            else "inside the band"),
            }

    if len(closes) >= 20:
        line, direction = supertrend(highs, lows, closes)
        level, way = _last(line), None
        trend = [d for d in getattr(direction, "values", direction) if d is not None]
        if trend:
            way = "bullish" if trend[-1] > 0 else "bearish"
        out["supertrend"] = {"value": _round(level), "reading": way}

    for period, name in ((21, "1 month"), (63, "3 months"), (252, "1 year")):
        if len(closes) > period:
            out.setdefault("momentum", []).append({
                "window": name,
                "percent": _round((_last(rate_of_change(closes, period)) or 0) * 100),
            })

    returns = simple_returns(closes[-253:]) if len(closes) > 30 else []
    if returns:
        out["volatility"] = _round(annualised_volatility(returns) * 100)
    return out


def pivots(high: float, low: float, close: float) -> dict:
    """Classic, Fibonacci and Camarilla levels from the last completed session.

    All three, because the portals show all three and traders are partisan
    about which one they use. They are pure arithmetic on yesterday's range —
    no fitting, no parameters, nothing to get wrong beyond the formula.
    """
    span = high - low
    classic_pp = (high + low + close) / 3
    classic = {
        "pp": classic_pp,
        "r1": 2 * classic_pp - low, "s1": 2 * classic_pp - high,
        "r2": classic_pp + span, "s2": classic_pp - span,
        "r3": high + 2 * (classic_pp - low), "s3": low - 2 * (high - classic_pp),
    }
    fib = {
        "pp": classic_pp,
        "r1": classic_pp + 0.382 * span, "s1": classic_pp - 0.382 * span,
        "r2": classic_pp + 0.618 * span, "s2": classic_pp - 0.618 * span,
        "r3": classic_pp + span, "s3": classic_pp - span,
    }
    camarilla = {
        "pp": classic_pp,
        "r1": close + span * 1.1 / 12, "s1": close - span * 1.1 / 12,
        "r2": close + span * 1.1 / 6, "s2": close - span * 1.1 / 6,
        "r3": close + span * 1.1 / 4, "s3": close - span * 1.1 / 4,
    }
    return {
        name: {k: _round(v) for k, v in levels.items()}
        for name, levels in (("classic", classic), ("fibonacci", fib),
                             ("camarilla", camarilla))
    }


def beta(stock_series: dict[str, float], index_series: dict[str, float]) -> float | None:
    """Covariance with the market over their *common sessions*, market variance.

    Aligned on date, not position. A stock and its index do not share a bar
    count — holidays, listing dates and suspensions all shift one against the
    other — and zipping two return series by index pairs Tuesday's stock move
    with Thursday's market move. The result is a beta near zero for a name
    that plainly moves with the market, which is how this was caught.

    Measured against the instrument's own regional index: an Indian listing's
    beta against the S&P would describe time zones more than the company.
    """
    days = sorted(set(stock_series) & set(index_series))
    if len(days) < 60:
        return None
    stock = simple_returns([stock_series[d] for d in days])
    market = simple_returns([index_series[d] for d in days])
    span = min(len(stock), len(market))
    if span < 30:
        return None
    stock, market = stock[:span], market[:span]
    mean_s = sum(stock) / span
    mean_m = sum(market) / span
    # strict=False deliberately: both were just trimmed to `span`, and a
    # length mismatch here should truncate rather than raise mid-render.
    covariance = sum((s - mean_s) * (m - mean_m)
                     for s, m in zip(stock, market, strict=False)) / span
    variance = sum((m - mean_m) ** 2 for m in market) / span
    return None if variance == 0 else _round(covariance / variance)


#: What these portals show that price data cannot produce, and why. Rendered
#: on the page verbatim: a reader comparing against Moneycontrol deserves to
#: know which gaps are deliberate rather than assuming the page is broken.
UNAVAILABLE = {
    "india": [
        ("P/E, P/B, EPS, book value, ROE, ROCE, margins",
         "no free source carries fundamentals for NSE listings — the SEC covers "
         "US filings only, and the exchanges refuse automated access"),
        ("Promoter holding, pledge, FII/DII holding",
         "shareholding filings are not available through any free feed"),
        ("Analyst ratings and earnings estimates",
         "licensed broker research, not public data"),
        ("Delivery percentage, circuit limits, VWAP",
         "exchange-published intraday data; this app holds daily bars only"),
    ],
    "us": [
        ("Promoter/insider holding and pledge",
         "not part of the SEC company-facts feed this app reads"),
        ("Delivery percentage and VWAP",
         "intraday data; this app holds daily bars only"),
    ],
}


def build(bars: list[dict], *, index_series: dict[str, float] | None = None,
          region: str = "india") -> dict:
    """The whole technical block for one instrument.

    ``bars`` are the cached daily rows, oldest first. Returns an empty dict
    when there is not enough history to say anything, rather than a block of
    nulls that renders as a wall of dashes.
    """
    if len(bars) < 30:
        return {}
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close"]) for b in bars]
    volumes = [float(b.get("volume") or 0) for b in bars]

    last_bar = bars[-1]
    window = closes[-252:] if len(closes) >= 252 else closes
    block = {
        "moving_averages": moving_averages(closes),
        "crossovers": crossovers(closes),
        "oscillators": oscillators(highs, lows, closes),
        "pivots": pivots(highs[-1], lows[-1], closes[-1]),
        "session": {
            "open": _round(float(last_bar["open"])),
            "high": _round(highs[-1]),
            "low": _round(lows[-1]),
            "previous_close": _round(closes[-2]) if len(closes) > 1 else None,
            # Average traded price for the session. True VWAP needs tick data;
            # this is the typical-price convention the portals label ATP.
            "atp": _round((highs[-1] + lows[-1] + closes[-1]) / 3),
            "volume": int(volumes[-1]),
            # Turnover in the instrument's own currency.
            "turnover": _round(volumes[-1] * closes[-1], 0),
            "volume_vs_20d": (
                _round(volumes[-1] / (sum(volumes[-21:-1]) / 20)) if len(volumes) > 21
                and sum(volumes[-21:-1]) > 0 else None
            ),
        },
        "range": {
            # Labelled by the window actually held, not called "all time":
            # this cache is two years deep and an all-time high it has never
            # seen would be a lie told confidently.
            "window_sessions": len(window),
            "high": _round(max(window)),
            "low": _round(min(window)),
        },
        "unavailable": [
            {"what": what, "why": why} for what, why in UNAVAILABLE.get(region, [])
        ],
    }
    if index_series:
        block["beta"] = beta(
            {str(b["day"]): float(b["close"]) for b in bars}, index_series
        )
    return block
