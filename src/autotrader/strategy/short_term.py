"""Short-term book: enter, take the move, exit.

Two setups, chosen because they profit from opposite market behaviours and so
tend not to lose at the same time:

* **Pullback (mean reversion)** — a short-period RSI oversold reading *inside* an
  established uptrend. Buying weakness only when the long-term trend is intact
  is what separates this from catching a falling knife; the trend filter is not
  optional decoration.
* **Breakout (continuation)** — a close above the N-day high with confirmed
  trend strength and a volume expansion. This profits when a range resolves,
  which is exactly when mean reversion loses.

Every entry carries three exits fixed at entry time: an ATR-scaled stop, a
target at a defined reward:risk, and a hard time limit. The time limit is the
one traders most often omit and the one that matters most — capital parked in a
position that has stopped working is capital not available to the next setup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.instrument import Instrument
from ..core.money import to_decimal
from ..data.bars import HistoryWindow
from ..execution.orders import Horizon
from ..indicators.core import adx, atr, donchian, rsi, sma
from ..risk.exits import compute_stop_and_target
from .base import Direction, Signal, Strategy, StrategyContext


@dataclass
class ShortTermConfig:
    """Parameters for the short-term book."""

    # -- pullback setup
    rsi_period: int = 2
    rsi_entry: float = 10.0           # oversold threshold on the short RSI
    rsi_exit: float = 60.0            # exit when the bounce has played out
    trend_ma: int = 200               # regime filter for the pullback setup

    # -- breakout setup
    breakout_period: int = 20
    breakout_adx_period: int = 14
    breakout_min_adx: float = 25.0
    volume_ma: int = 20
    min_volume_ratio: float = 1.2     # require a volume expansion to confirm

    # -- shared risk parameters
    atr_period: int = 14
    stop_atr_multiple: Decimal = Decimal("2.0")
    reward_risk_ratio: Decimal = Decimal("2.0")
    max_holding_days: int = 10
    trailing_stop_pct: Decimal | None = None
    max_concurrent: int = 8
    enable_pullback: bool = True
    enable_breakout: bool = True
    #: Minimum open profit, in units of initial risk, before the RSI-recovery
    #: exit may fire.
    #:
    #: Without this the signal exit is strictly faster than the profit target —
    #: RSI recovers above `rsi_exit` long before price travels
    #: `stop_atr_multiple * reward_risk_ratio` ATRs — so every winner is cut
    #: early while every loser runs the full stop distance. That asymmetry loses
    #: money regardless of how good the entry is: the realised reward:risk ends
    #: up inverted relative to the configured one. Requiring the trade to be at
    #: least 1R onside before honouring the signal exit keeps the mean-reversion
    #: thesis while removing the built-in negative skew. Set to 0 to disable.
    signal_exit_min_r: Decimal = Decimal("1.0")

    def __post_init__(self) -> None:
        self.stop_atr_multiple = to_decimal(self.stop_atr_multiple)
        self.reward_risk_ratio = to_decimal(self.reward_risk_ratio)
        self.signal_exit_min_r = to_decimal(self.signal_exit_min_r)
        if self.trailing_stop_pct is not None:
            self.trailing_stop_pct = to_decimal(self.trailing_stop_pct)
        if self.max_holding_days < 1:
            raise ValueError("max_holding_days must be at least 1")
        if self.reward_risk_ratio <= 0:
            raise ValueError("reward_risk_ratio must be positive")
        if self.signal_exit_min_r < 0:
            raise ValueError("signal_exit_min_r cannot be negative")

    @property
    def required_bars(self) -> int:
        return max(
            self.trend_ma,
            self.breakout_period,
            self.volume_ma,
            self.breakout_adx_period * 3,
            self.atr_period,
            self.rsi_period,
        ) + 2


class ShortTermStrategy(Strategy):
    """Swing entries with predefined stop, target and time exit."""

    name = "short_term_swing"
    horizon = Horizon.SHORT_TERM

    def __init__(self, config: ShortTermConfig | None = None) -> None:
        self.config = config or ShortTermConfig()
        self.warmup_bars = self.config.required_bars

    def generate(
        self,
        as_of: date,
        windows: dict[str, HistoryWindow],
        instruments: dict[str, Instrument],
        context: StrategyContext,
    ) -> list[Signal]:
        cfg = self.config
        entries: list[Signal] = []
        exits: list[Signal] = []

        for key, window in windows.items():
            instrument = instruments.get(key)
            if instrument is None or not self._ready(window):
                continue

            held = context.holds(key)
            if held:
                exit_signal = self._evaluate_exit(key, window, instrument, context)
                if exit_signal is not None:
                    exits.append(exit_signal)
                continue

            if context.entries_halted:
                continue

            signal = self._evaluate_entry(key, window, instrument)
            if signal is not None:
                entries.append(signal)

        # Best setups first; the engine stops once capacity is reached.
        entries.sort(key=lambda s: s.score, reverse=True)
        room = max(0, cfg.max_concurrent - len(context.open_keys))
        return exits + entries[:room]

    # -- entries ----------------------------------------------------------
    def _evaluate_entry(
        self, key: str, window: HistoryWindow, instrument: Instrument
    ) -> Signal | None:
        cfg = self.config
        bars = window.bars(cfg.required_bars)
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        volumes = [b.volume for b in bars]
        price = closes[-1]

        atr_value = atr(highs, lows, closes, cfg.atr_period)[-1]
        if atr_value is None or atr_value <= 0:
            return None
        atr_dec = to_decimal(str(atr_value))

        signal = None
        if cfg.enable_pullback:
            signal = self._pullback(instrument, closes, price, atr_dec)
        if signal is None and cfg.enable_breakout:
            signal = self._breakout(
                instrument, closes, highs, lows, volumes, price, atr_dec
            )
        return signal

    def _pullback(
        self,
        instrument: Instrument,
        closes: list,
        price: Decimal,
        atr_value: Decimal,
    ) -> Signal | None:
        cfg = self.config
        trend = sma(closes, cfg.trend_ma)[-1]
        if trend is None or float(price) <= trend:
            return None   # only buy dips inside an uptrend

        rsi_series = rsi(closes, cfg.rsi_period)
        rsi_value = rsi_series[-1]
        if rsi_value is None or rsi_value > cfg.rsi_entry:
            return None

        stop, target = self._levels(price, atr_value)
        # Deeper oversold readings get more conviction, capped at 1.0.
        strength = min(1.0, (cfg.rsi_entry - rsi_value) / max(cfg.rsi_entry, 1e-9) + 0.5)

        return Signal(
            instrument=instrument,
            direction=Direction.LONG,
            horizon=Horizon.SHORT_TERM,
            strength=strength,
            score=100.0 - rsi_value,
            stop_loss=stop,
            take_profit=target,
            atr_value=atr_value,
            max_holding_days=cfg.max_holding_days,
            trailing_stop_pct=cfg.trailing_stop_pct,
            reason=f"pullback: RSI({cfg.rsi_period}) {rsi_value:.1f} above SMA{cfg.trend_ma}",
            diagnostics={"rsi": rsi_value, "trend_ma": trend, "atr": float(atr_value)},
        )

    def _breakout(
        self,
        instrument: Instrument,
        closes: list,
        highs: list,
        lows: list,
        volumes: list,
        price: Decimal,
        atr_value: Decimal,
    ) -> Signal | None:
        cfg = self.config
        upper, _ = donchian(highs, lows, cfg.breakout_period)
        # Compare against the channel as of the *previous* bar: including today's
        # high would make the breakout condition trivially self-satisfying.
        if len(upper) < 2 or upper[-2] is None:
            return None
        if float(price) <= upper[-2]:
            return None

        adx_series, plus_di, minus_di = adx(highs, lows, closes, cfg.breakout_adx_period)
        adx_value = adx_series[-1]
        if adx_value is None or adx_value < cfg.breakout_min_adx:
            return None
        if plus_di[-1] is None or minus_di[-1] is None or plus_di[-1] <= minus_di[-1]:
            return None

        vol_avg = sma(volumes, cfg.volume_ma)[-1]
        if vol_avg is None or vol_avg <= 0:
            return None
        volume_ratio = float(volumes[-1]) / vol_avg
        if volume_ratio < cfg.min_volume_ratio:
            return None

        stop, target = self._levels(price, atr_value)
        strength = min(1.0, adx_value / 50.0)

        return Signal(
            instrument=instrument,
            direction=Direction.LONG,
            horizon=Horizon.SHORT_TERM,
            strength=strength,
            score=adx_value,
            stop_loss=stop,
            take_profit=target,
            atr_value=atr_value,
            max_holding_days=cfg.max_holding_days,
            trailing_stop_pct=cfg.trailing_stop_pct,
            reason=(
                f"breakout above {cfg.breakout_period}d high, ADX {adx_value:.0f}, "
                f"volume {volume_ratio:.1f}x"
            ),
            diagnostics={
                "adx": adx_value,
                "volume_ratio": volume_ratio,
                "channel_high": upper[-2],
            },
        )

    def _levels(self, price: Decimal, atr_value: Decimal) -> tuple[Decimal, Decimal]:
        return compute_stop_and_target(
            price,
            atr_value,
            is_long=True,
            stop_atr_multiple=self.config.stop_atr_multiple,
            reward_risk_ratio=self.config.reward_risk_ratio,
        )

    # -- exits ------------------------------------------------------------
    def _evaluate_exit(
        self,
        key: str,
        window: HistoryWindow,
        instrument: Instrument,
        context: StrategyContext,
    ) -> Signal | None:
        """Signal-driven exit; hard stops and time limits live in the exit engine.

        The RSI condition alone is not sufficient. It fires far earlier than the
        profit target, so honouring it unconditionally would close every winner
        at a fraction of a risk unit while every loser still ran the full stop
        distance. The trade must be at least ``signal_exit_min_r`` onside first.
        """
        cfg = self.config
        closes = window.closes(cfg.required_bars)
        rsi_value = rsi(closes, cfg.rsi_period)[-1]
        if rsi_value is None or rsi_value < cfg.rsi_exit:
            return None

        price = closes[-1]
        r_multiple = context.r_multiple(key, price)
        if (
            cfg.signal_exit_min_r > 0
            and r_multiple is not None
            and r_multiple < cfg.signal_exit_min_r
        ):
            # Thesis has played out but the move has not paid for its own risk.
            # Hold and let the stop, target or time limit resolve it instead.
            return None

        detail = "" if r_multiple is None else f", {r_multiple:.2f}R"
        return Signal(
            instrument=instrument,
            direction=Direction.FLAT,
            horizon=Horizon.SHORT_TERM,
            reason=f"mean reversion complete: RSI {rsi_value:.1f}{detail}",
            diagnostics={
                "rsi": rsi_value,
                "r_multiple": float(r_multiple) if r_multiple is not None else 0.0,
            },
        )
