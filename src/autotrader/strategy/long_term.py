"""Long-term book: cross-sectional momentum inside a trend filter.

The construction is deliberately conventional, because the conventional version
is the one with decades of out-of-sample evidence behind it:

* **Trend filter** — only hold instruments above their long moving average, with
  the fast average above the slow one. This is what keeps the book out of
  sustained bear markets; it does not avoid drawdowns, it truncates them.
* **Cross-sectional momentum** — rank the survivors by 12-month return skipping
  the most recent month. The skip matters: the last month exhibits short-term
  reversal, and including it measurably degrades the signal.
* **Trend-strength gate** — require a minimum ADX so capital is not committed to
  instruments drifting sideways.
* **Inverse-volatility weighting** — allocate so each holding contributes
  similar risk, rather than equal capital.

Rebalanced monthly. Positions exit when the trend filter fails or the name drops
out of the selected set — there is no hard stop, because a stop on a monthly
horizon converts ordinary volatility into realised losses.

None of this guarantees a profit. It is a risk-managed expression of a
documented risk premium, and it has historically had multi-year losing stretches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.instrument import Instrument
from ..core.money import to_decimal
from ..data.bars import HistoryWindow
from ..execution.orders import Horizon
from ..indicators.core import adx, annualised_volatility, atr, simple_returns, sma
from .base import Direction, Signal, Strategy, StrategyContext, is_month_boundary


@dataclass
class LongTermConfig:
    """Parameters for the long-term book."""

    fast_ma: int = 50
    slow_ma: int = 200
    momentum_lookback: int = 252      # ~12 months of sessions
    momentum_skip: int = 21           # skip the most recent month
    adx_period: int = 14
    min_adx: float = 20.0
    atr_period: int = 14
    max_holdings: int = 10
    #: Total fraction of equity the long-term book may deploy.
    total_allocation: Decimal = Decimal("0.60")
    #: Volatility window for inverse-vol weighting.
    vol_lookback: int = 63
    #: Names must clear this momentum to be eligible at all.
    min_momentum: float = 0.0
    #: Exit when the name falls below this rank (hysteresis against churn).
    exit_rank_buffer: int = 5

    def __post_init__(self) -> None:
        self.total_allocation = to_decimal(self.total_allocation)
        if self.fast_ma >= self.slow_ma:
            raise ValueError("fast_ma must be shorter than slow_ma")
        if self.max_holdings < 1:
            raise ValueError("max_holdings must be at least 1")

    @property
    def required_bars(self) -> int:
        """Longest lookback any component needs before it can speak."""
        return max(
            self.slow_ma,
            self.momentum_lookback + self.momentum_skip,
            self.vol_lookback,
            self.adx_period * 3,
        ) + 1


@dataclass
class Candidate:
    """A ranked instrument with the evidence behind its ranking."""

    key: str
    instrument: Instrument
    momentum: float
    adx_value: float
    volatility: float
    price: Decimal
    atr_value: Decimal
    score: float


class LongTermStrategy(Strategy):
    """Monthly-rebalanced trend + momentum portfolio."""

    name = "long_term_momentum"
    horizon = Horizon.LONG_TERM

    def __init__(self, config: LongTermConfig | None = None) -> None:
        self.config = config or LongTermConfig()
        self.warmup_bars = self.config.required_bars
        self._last_rebalance: date | None = None

    def should_run(self, as_of: date, context: StrategyContext) -> bool:
        """Rebalance on the first session of each month."""
        return is_month_boundary(as_of, self._last_rebalance)

    # -- signal generation ------------------------------------------------
    def generate(
        self,
        as_of: date,
        windows: dict[str, HistoryWindow],
        instruments: dict[str, Instrument],
        context: StrategyContext,
    ) -> list[Signal]:
        self._last_rebalance = as_of
        cfg = self.config

        candidates = [
            c for key, window in windows.items()
            if (c := self._evaluate(key, window, instruments.get(key))) is not None
        ]
        candidates.sort(key=lambda c: c.score, reverse=True)

        selected = candidates[: cfg.max_holdings]
        selected_keys = {c.key for c in selected}
        # Hysteresis: a holding that has slipped only slightly is retained, which
        # avoids paying round-trip costs to swap near-identical ranks.
        keep_rank = cfg.max_holdings + cfg.exit_rank_buffer
        tolerated = {c.key for c in candidates[:keep_rank]}

        weights = self._inverse_vol_weights(selected)
        signals: list[Signal] = []

        for candidate in selected:
            signals.append(
                Signal(
                    instrument=candidate.instrument,
                    direction=Direction.LONG,
                    horizon=Horizon.LONG_TERM,
                    strength=1.0,
                    score=candidate.score,
                    target_weight=weights[candidate.key],
                    atr_value=candidate.atr_value,
                    reason=(
                        f"momentum {candidate.momentum:+.1%}, ADX "
                        f"{candidate.adx_value:.0f}, vol {candidate.volatility:.1%}"
                    ),
                    diagnostics={
                        "momentum": candidate.momentum,
                        "adx": candidate.adx_value,
                        "volatility": candidate.volatility,
                        "target_weight": float(weights[candidate.key]),
                    },
                )
            )

        # Exit anything held that no longer qualifies.
        for key in context.open_keys:
            if key in selected_keys or key in tolerated:
                continue
            instrument = instruments.get(key)
            if instrument is None:
                continue
            signals.append(
                Signal(
                    instrument=instrument,
                    direction=Direction.FLAT,
                    horizon=Horizon.LONG_TERM,
                    reason="dropped out of momentum ranking or trend filter",
                )
            )
        return signals

    # -- internals --------------------------------------------------------
    def _evaluate(
        self, key: str, window: HistoryWindow, instrument: Instrument | None
    ) -> Candidate | None:
        """Score one instrument, or return ``None`` if it fails any filter."""
        cfg = self.config
        if instrument is None or not self._ready(window):
            return None

        bars = window.bars(cfg.required_bars)
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        price = closes[-1]

        fast = sma(closes, cfg.fast_ma)[-1]
        slow = sma(closes, cfg.slow_ma)[-1]
        if fast is None or slow is None:
            return None

        # Trend filter: price above the slow average and fast above slow.
        if not (float(price) > slow and fast > slow):
            return None

        # 12-1 momentum: return over the lookback, ending one month ago.
        momentum = self._skip_momentum(closes, cfg.momentum_lookback, cfg.momentum_skip)
        if momentum is None or momentum <= cfg.min_momentum:
            return None

        adx_series, _, _ = adx(highs, lows, closes, cfg.adx_period)
        adx_value = adx_series[-1]
        if adx_value is None or adx_value < cfg.min_adx:
            return None

        returns = simple_returns(closes[-(cfg.vol_lookback + 1):])
        volatility = annualised_volatility(returns)
        if volatility <= 0:
            return None

        atr_value = atr(highs, lows, closes, cfg.atr_period)[-1]
        if atr_value is None or atr_value <= 0:
            return None

        # Risk-adjusted momentum: reward trend strength, penalise volatility.
        score = momentum / volatility

        return Candidate(
            key=key,
            instrument=instrument,
            momentum=momentum,
            adx_value=adx_value,
            volatility=volatility,
            price=price,
            atr_value=to_decimal(str(atr_value)),
            score=score,
        )

    @staticmethod
    def _skip_momentum(closes: list, lookback: int, skip: int) -> float | None:
        """Return over ``lookback`` bars ending ``skip`` bars ago."""
        needed = lookback + skip + 1
        if len(closes) < needed:
            return None
        end = float(closes[-(skip + 1)])
        start = float(closes[-(skip + lookback + 1)])
        if start <= 0:
            return None
        return (end - start) / start

    def _inverse_vol_weights(
        self, candidates: list[Candidate]
    ) -> dict[str, Decimal]:
        """Allocate ``total_allocation`` inversely to volatility.

        Equal *capital* weighting would let the most volatile holding dominate
        realised portfolio risk. Inverse-vol weighting equalises the risk
        contribution instead, which is what the allocation is meant to express.
        """
        if not candidates:
            return {}
        inverses = {c.key: 1.0 / c.volatility for c in candidates if c.volatility > 0}
        total = sum(inverses.values())
        if total <= 0:
            equal = self.config.total_allocation / Decimal(len(candidates))
            return {c.key: equal for c in candidates}
        return {
            key: self.config.total_allocation * to_decimal(str(inv / total))
            for key, inv in inverses.items()
        }
