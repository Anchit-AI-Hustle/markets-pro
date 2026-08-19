"""Cross-sectional screener: rank every name in the universe on the evidence.

Three questions drive the design, matched to how a discretionary screener
would actually be used:

1. **Is this name trending or chopping?** ADX classifies the regime, and the
   regime picks which indicators get to vote. Trend-following tools
   (Supertrend, MACD, a fast/slow SMA cross) lag and whipsaw in a range;
   mean-reversion oscillators (RSI, Bollinger %B) overshoot and get run over
   in a strong trend. Using the same fixed indicator set for both regimes is
   how a screener ends up "confidently wrong" — this picks the tool that
   suits the current regime instead of averaging tools that disagree by
   construction.
2. **How is it doing lately, and how volatile is that move?** Rate-of-change
   over ~1 month and ~1 quarter for recent performance, ATR as a percentage of
   price for a volatility bucket a reader can act on without doing the
   division themselves.
3. **How does that compare to its peers?** A stock's own momentum means little
   without the sector it sits in as a reference point — the composite score
   blends the regime-appropriate technical signal with the stock's momentum
   *relative to its own sector's average*, so a mediocre stock in a hot sector
   does not simply borrow its sector's score, and a genuinely strong stock in
   a weak sector is not buried under sector-wide malaise.

Nothing here places an order or feeds the backtest — this is a read-only,
point-in-time cross-section, run independently of either trading book.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from ..data.bars import HistoryWindow
from ..data.livefeed import LiveFeed, load_livefeed
from ..data.universe import UNIVERSES, UniverseEntry
from ..indicators.core import (
    adx,
    annualised_volatility,
    atr,
    bollinger,
    macd,
    rate_of_change,
    rsi,
    simple_returns,
    sma,
    supertrend,
)

SNAPSHOT_VERSION = 1


@dataclass(frozen=True)
class ScreenerConfig:
    """Every window and threshold the screener uses, in one place.

    Thresholds (``trending_adx``, the volatility buckets, the signal-label
    cutoffs, ``relative_momentum_scale``) are heuristics, not calibrated
    constants — documented as such rather than presented as more precise than
    they are.
    """

    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    sma_fast: int = 50
    sma_slow: int = 200
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    adx_period: int = 14
    atr_period: int = 14
    #: ADX at/above this is classified "trending"; below is "ranging". 25 is
    #: the conventional Wilder threshold for a trend strong enough to trade
    #: (below ~20 is commonly read as no trend / chop).
    trending_adx: float = 25.0
    momentum_short: int = 21  # ~1 month of sessions
    momentum_long: int = 63  # ~1 quarter of sessions
    volatility_lookback: int = 63
    #: ATR/price boundaries bucketing volatility for display and rationale.
    low_vol_atr_pct: float = 0.02
    high_vol_atr_pct: float = 0.045
    #: |signal_strength| below this is reported "neutral" rather than a
    #: direction — avoids reporting a coin-flip-sized signal as a call.
    neutral_band: float = 0.15
    #: Weight on the regime-appropriate technical signal vs. sector-relative
    #: momentum in the final composite score (must sum to 1 with its
    #: complement).
    signal_weight: float = 0.65
    #: A sector-relative momentum gap of this magnitude (e.g. 0.15 = 15
    #: percentage points ahead of/behind the sector average) maps to a full
    #: +/-1 contribution before clipping.
    relative_momentum_scale: float = 0.15

    @property
    def required_bars(self) -> int:
        """Longest lookback any component needs before it can speak."""
        return (
            max(
                self.sma_slow,
                self.momentum_long,
                self.volatility_lookback,
                self.macd_slow + self.macd_signal,
                self.adx_period * 3,
                self.supertrend_period * 3,
            )
            + 1
        )


@dataclass(frozen=True)
class IndicatorReading:
    """The raw indicator values behind one instrument's screen result."""

    price: float
    rsi: float | None
    macd_hist: float | None
    supertrend_direction: int | None  # 1 up, -1 down, None unknown
    sma_fast: float | None
    sma_slow: float | None
    bollinger_pct_b: float | None  # 0.0 = at lower band, 1.0 = at upper band
    adx: float | None
    atr_pct: float | None  # ATR / price
    momentum_short: float | None
    momentum_long: float | None
    annualised_volatility: float | None


@dataclass(frozen=True)
class ScreenResult:
    """One instrument's screen outcome, evidence and all."""

    key: str
    symbol: str
    name: str
    region: str
    sector: str
    regime: str  # "trending" | "ranging" | "unclear"
    signal: str  # "bullish" | "bearish" | "neutral"
    signal_strength: float  # [-1, 1], regime-appropriate indicator blend
    volatility_bucket: str  # "low" | "medium" | "high" | "unknown"
    reading: IndicatorReading
    indicators_used: tuple[str, ...]
    sector_momentum_long: float | None = None  # peer/industry average
    relative_momentum_long: float | None = None  # this stock vs. its peers
    score: float = 0.0
    rationale: str = ""


@dataclass(frozen=True)
class SectorPerformance:
    """One sector's aggregate standing — the "top performing industries" view."""

    sector: str
    count: int
    avg_momentum_long: float | None
    avg_score: float


# --- indicator reading -------------------------------------------------------


def _read_indicators(window: HistoryWindow, cfg: ScreenerConfig) -> IndicatorReading | None:
    if not window.has(cfg.required_bars):
        return None
    bars = window.bars(cfg.required_bars)
    closes = [float(b.close) for b in bars]
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]
    price = closes[-1]
    if price <= 0:
        return None

    rsi_val = rsi(closes, cfg.rsi_period)[-1]
    _, _, macd_hist = macd(closes, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    st_line, st_dir = supertrend(
        highs, lows, closes, cfg.supertrend_period, cfg.supertrend_multiplier
    )
    del st_line  # only direction feeds the composite signal
    sma_fast_val = sma(closes, cfg.sma_fast)[-1]
    sma_slow_val = sma(closes, cfg.sma_slow)[-1]
    _, upper, lower = bollinger(closes, cfg.bollinger_period, cfg.bollinger_std)
    pct_b = None
    if upper[-1] is not None and lower[-1] is not None and upper[-1] != lower[-1]:
        pct_b = (price - lower[-1]) / (upper[-1] - lower[-1])
    adx_series, _, _ = adx(highs, lows, closes, cfg.adx_period)
    adx_val = adx_series[-1]
    atr_val = atr(highs, lows, closes, cfg.atr_period)[-1]
    atr_pct = (atr_val / price) if atr_val is not None else None
    mom_short = rate_of_change(closes, cfg.momentum_short)[-1]
    mom_long = rate_of_change(closes, cfg.momentum_long)[-1]
    returns = simple_returns(closes[-(cfg.volatility_lookback + 1):])
    vol = annualised_volatility(returns) if len(returns) >= 2 else None

    return IndicatorReading(
        price=price,
        rsi=rsi_val,
        macd_hist=macd_hist[-1],
        supertrend_direction=st_dir[-1],
        sma_fast=sma_fast_val,
        sma_slow=sma_slow_val,
        bollinger_pct_b=pct_b,
        adx=adx_val,
        atr_pct=atr_pct,
        momentum_short=mom_short,
        momentum_long=mom_long,
        annualised_volatility=vol,
    )


# --- regime + signal ----------------------------------------------------


def _trend_signal(reading: IndicatorReading) -> float | None:
    """Blend of trend-following indicators, each contributing -1/0/+1."""
    parts: list[float] = []
    if reading.supertrend_direction is not None:
        parts.append(float(reading.supertrend_direction))
    if reading.macd_hist is not None:
        parts.append(
            1.0 if reading.macd_hist > 0 else (-1.0 if reading.macd_hist < 0 else 0.0)
        )
    if reading.sma_fast is not None and reading.sma_slow is not None:
        parts.append(
            1.0
            if reading.sma_fast > reading.sma_slow
            else (-1.0 if reading.sma_fast < reading.sma_slow else 0.0)
        )
    return (sum(parts) / len(parts)) if parts else None


def _range_signal(reading: IndicatorReading) -> float | None:
    """Blend of mean-reversion indicators, each in [-1, 1]."""
    parts: list[float] = []
    if reading.rsi is not None:
        parts.append(max(-1.0, min(1.0, (50.0 - reading.rsi) / 50.0)))
    if reading.bollinger_pct_b is not None:
        parts.append(max(-1.0, min(1.0, (0.5 - reading.bollinger_pct_b) * 2.0)))
    return (sum(parts) / len(parts)) if parts else None


_TREND_INDICATORS = ("supertrend", "macd", "sma_cross")
_RANGE_INDICATORS = ("rsi", "bollinger_pct_b")


def _classify(
    reading: IndicatorReading, cfg: ScreenerConfig
) -> tuple[str, float, tuple[str, ...]]:
    """Pick the regime, then the indicator set that regime says is suitable."""
    trend_sig = _trend_signal(reading)
    range_sig = _range_signal(reading)

    if reading.adx is None:
        # Trend strength itself is undefined (warm-up) — blend both rather
        # than guess a regime with no basis for the guess.
        combined = [s for s in (trend_sig, range_sig) if s is not None]
        strength = (sum(combined) / len(combined)) if combined else 0.0
        return "unclear", strength, _TREND_INDICATORS + _RANGE_INDICATORS

    if reading.adx >= cfg.trending_adx:
        if trend_sig is not None:
            return "trending", trend_sig, _TREND_INDICATORS
        return "trending", (range_sig or 0.0), _RANGE_INDICATORS

    if range_sig is not None:
        return "ranging", range_sig, _RANGE_INDICATORS
    return "ranging", (trend_sig or 0.0), _TREND_INDICATORS


def _signal_label(strength: float, cfg: ScreenerConfig) -> str:
    if strength > cfg.neutral_band:
        return "bullish"
    if strength < -cfg.neutral_band:
        return "bearish"
    return "neutral"


def _volatility_bucket(atr_pct: float | None, cfg: ScreenerConfig) -> str:
    if atr_pct is None:
        return "unknown"
    if atr_pct < cfg.low_vol_atr_pct:
        return "low"
    if atr_pct > cfg.high_vol_atr_pct:
        return "high"
    return "medium"


def _rationale(
    regime: str, indicators: tuple[str, ...], reading: IndicatorReading, cfg: ScreenerConfig
) -> str:
    if regime == "unclear":
        basis = "ADX undefined during warm-up -> blending trend + mean-reversion indicators"
    else:
        adx_str = f"{reading.adx:.0f}" if reading.adx is not None else "n/a"
        basis = f"ADX {adx_str} ({regime}) -> weighting {', '.join(indicators)}"
    parts = [basis]
    if reading.momentum_long is not None:
        parts.append(f"{reading.momentum_long:+.1%} over ~{cfg.momentum_long}d")
    if reading.atr_pct is not None:
        parts.append(f"ATR {reading.atr_pct:.1%} of price")
    return "; ".join(parts)


def screen_instrument(
    key: str,
    window: HistoryWindow,
    entry: UniverseEntry,
    cfg: ScreenerConfig | None = None,
) -> ScreenResult | None:
    """Screen one instrument as of ``window``'s decision date. ``None`` pre-warm-up."""
    cfg = cfg or ScreenerConfig()
    reading = _read_indicators(window, cfg)
    if reading is None:
        return None
    regime, strength, used = _classify(reading, cfg)
    return ScreenResult(
        key=key,
        symbol=entry.symbol,
        name=entry.name,
        region=entry.region,
        sector=entry.sector,
        regime=regime,
        signal=_signal_label(strength, cfg),
        signal_strength=strength,
        volatility_bucket=_volatility_bucket(reading.atr_pct, cfg),
        reading=reading,
        indicators_used=used,
        score=strength,  # provisional; screen_universe applies the peer adjustment
        rationale=_rationale(regime, used, reading, cfg),
    )


def screen_universe(
    feed: LiveFeed, *, as_of: date | None = None, cfg: ScreenerConfig | None = None
) -> list[ScreenResult]:
    """Screen every loaded instrument, then apply the peer/sector adjustment.

    Ranked descending by the final composite ``score``. Instruments without
    enough history yet (warm-up) are silently excluded, matching how the
    trading strategies treat warm-up — a missing reading is not a bearish one.
    """
    cfg = cfg or ScreenerConfig()
    loaded_keys = {i.key for i in feed.instruments}

    if as_of is None:
        days = feed.data.all_days()
        if not days:
            return []
        as_of = days[-1]

    raw: list[ScreenResult] = []
    for entry in feed.entries:
        key = entry.key
        window = feed.data.window(key, as_of)
        if key not in loaded_keys or window is None:
            continue
        result = screen_instrument(key, window, entry, cfg)
        if result is not None:
            raw.append(result)

    by_sector: dict[str, list[ScreenResult]] = {}
    for r in raw:
        by_sector.setdefault(r.sector, []).append(r)

    sector_avg: dict[str, float] = {}
    for sector, members in by_sector.items():
        momenta = [
            m.reading.momentum_long for m in members if m.reading.momentum_long is not None
        ]
        if momenta:
            sector_avg[sector] = sum(momenta) / len(momenta)

    final: list[ScreenResult] = []
    for r in raw:
        peer_avg = sector_avg.get(r.sector)
        relative = None
        score = r.signal_strength
        if peer_avg is not None and r.reading.momentum_long is not None:
            relative = r.reading.momentum_long - peer_avg
            relative_component = max(-1.0, min(1.0, relative / cfg.relative_momentum_scale))
            score = (
                cfg.signal_weight * r.signal_strength
                + (1.0 - cfg.signal_weight) * relative_component
            )
        final.append(
            dataclasses.replace(
                r, sector_momentum_long=peer_avg, relative_momentum_long=relative, score=score
            )
        )

    final.sort(key=lambda r: r.score, reverse=True)
    return final


def sector_performance(results: Sequence[ScreenResult]) -> list[SectorPerformance]:
    """Sectors ranked by average momentum — the "top performing industries" view."""
    by_sector: dict[str, list[ScreenResult]] = {}
    for r in results:
        by_sector.setdefault(r.sector, []).append(r)

    out: list[SectorPerformance] = []
    for sector, members in by_sector.items():
        momenta = [
            m.reading.momentum_long for m in members if m.reading.momentum_long is not None
        ]
        out.append(
            SectorPerformance(
                sector=sector,
                count=len(members),
                avg_momentum_long=(sum(momenta) / len(momenta)) if momenta else None,
                avg_score=sum(m.score for m in members) / len(members),
            )
        )
    out.sort(
        key=lambda s: s.avg_momentum_long if s.avg_momentum_long is not None else float("-inf"),
        reverse=True,
    )
    return out


# --- snapshot / CLI -----------------------------------------------------


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _reading_row(reading: IndicatorReading) -> dict:
    return {
        "price": _round(reading.price, 4),
        "rsi": _round(reading.rsi, 2),
        "macd_hist": _round(reading.macd_hist, 4),
        "supertrend_direction": reading.supertrend_direction,
        "sma_fast": _round(reading.sma_fast, 4),
        "sma_slow": _round(reading.sma_slow, 4),
        "bollinger_pct_b": _round(reading.bollinger_pct_b, 4),
        "adx": _round(reading.adx, 2),
        "atr_pct": _round(reading.atr_pct, 4),
        "momentum_short": _round(reading.momentum_short, 4),
        "momentum_long": _round(reading.momentum_long, 4),
        "annualised_volatility": _round(reading.annualised_volatility, 4),
    }


def _result_row(result: ScreenResult) -> dict:
    return {
        "key": result.key,
        "symbol": result.symbol,
        "name": result.name,
        "region": result.region,
        "sector": result.sector,
        "regime": result.regime,
        "signal": result.signal,
        "signal_strength": _round(result.signal_strength, 4),
        "volatility_bucket": result.volatility_bucket,
        "indicators_used": list(result.indicators_used),
        "sector_momentum_long": _round(result.sector_momentum_long, 4),
        "relative_momentum_long": _round(result.relative_momentum_long, 4),
        "score": _round(result.score, 4),
        "rationale": result.rationale,
        "reading": _reading_row(result.reading),
    }


def build_snapshot(
    results: list[ScreenResult],
    sectors: list[SectorPerformance],
    *,
    generated_at: datetime | None = None,
) -> dict:
    stamp = generated_at or datetime.now(timezone.utc)
    return {
        "version": SNAPSHOT_VERSION,
        "generated_at": stamp.isoformat(timespec="seconds"),
        "count": len(results),
        "top_stocks": [_result_row(r) for r in results[:20]],
        "results": [_result_row(r) for r in results],
        "top_industries": [
            {
                "sector": s.sector,
                "count": s.count,
                "avg_momentum_long": _round(s.avg_momentum_long, 4),
                "avg_score": _round(s.avg_score, 4),
            }
            for s in sectors
        ],
    }


def generate(
    data_root: Path, regions: Sequence[str] = ("india", "us")
) -> tuple[list[ScreenResult], list[SectorPerformance]]:
    """Load the committed cache, screen it, rank sectors. The one entry point."""
    feed = load_livefeed(data_root, regions)
    results = screen_universe(feed)
    sectors = sector_performance(results)
    return results, sectors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen the live universe from the cache")
    parser.add_argument("--data", default="data/live", help="live cache root")
    parser.add_argument(
        "--regions", nargs="+", default=sorted(UNIVERSES), choices=sorted(UNIVERSES)
    )
    parser.add_argument("--out", default=None, help="write snapshot JSON here (default: stdout)")
    args = parser.parse_args(argv)

    results, sectors = generate(Path(args.data), args.regions)
    snapshot = build_snapshot(results, sectors)
    payload = json.dumps(snapshot, indent=1)
    if args.out:
        Path(args.out).write_text(payload + "\n")
    else:
        print(payload)

    bullish = sum(1 for r in results if r.signal == "bullish")
    top_sector = sectors[0].sector if sectors else "n/a"
    print(
        f"\n{len(results)} instrument(s) screened, {bullish} bullish; "
        f"top sector by momentum: {top_sector}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
