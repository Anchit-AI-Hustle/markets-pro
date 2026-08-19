"""Indicator known-answer tests.

Expected values are computed by hand from each indicator's definition, not by
comparing against another implementation. Comparing two implementations only
proves they agree; it does not prove either is right.
"""

import math
import unittest

from autotrader.indicators.core import (
    adx,
    annualised_volatility,
    atr,
    bollinger,
    crossed_above,
    crossed_below,
    donchian,
    ema,
    log_returns,
    macd,
    rate_of_change,
    rolling_std,
    rsi,
    simple_returns,
    sma,
    supertrend,
    true_range,
    wilder_rma,
    zscore,
)


class TestSMA(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_period_one_is_identity(self):
        self.assertEqual(sma([4, 7, 2], 1), [4.0, 7.0, 2.0])

    def test_warmup_is_none_and_length_preserved(self):
        result = sma([1, 2, 3, 4, 5], 3)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[:2], [None, None])

    def test_insufficient_data_all_none(self):
        self.assertEqual(sma([1, 2], 5), [None, None])

    def test_rolling_window_does_not_drift(self):
        # Incremental sum must match a fresh sum at every step.
        values = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
        result = sma(values, 4)
        for i in range(3, len(values)):
            expected = sum(values[i - 3: i + 1]) / 4
            self.assertAlmostEqual(result[i], expected, places=12)

    def test_invalid_period(self):
        with self.assertRaises(ValueError):
            sma([1, 2, 3], 0)


class TestEMA(unittest.TestCase):
    def test_seeded_with_sma_then_smoothed(self):
        # period 3 -> alpha 0.5; seed = SMA(1,2,3) = 2
        # e[3] = 0.5*4 + 0.5*2 = 3 ; e[4] = 0.5*5 + 0.5*3 = 4
        self.assertEqual(ema([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_alpha_is_two_over_n_plus_one(self):
        values = [10, 20, 30, 40]
        result = ema(values, 2)          # alpha = 2/3
        seed = (10 + 20) / 2             # 15
        e2 = (2 / 3) * 30 + (1 / 3) * seed
        e3 = (2 / 3) * 40 + (1 / 3) * e2
        self.assertAlmostEqual(result[1], seed, places=12)
        self.assertAlmostEqual(result[2], e2, places=12)
        self.assertAlmostEqual(result[3], e3, places=12)

    def test_constant_series_stays_constant(self):
        result = ema([5] * 10, 4)
        for value in result[3:]:
            self.assertAlmostEqual(value, 5.0, places=12)


class TestWilderRMA(unittest.TestCase):
    def test_known_values(self):
        # seed = (1+2+3)/3 = 2; then (prev*2 + x)/3
        result = wilder_rma([1, 2, 3, 4, 5, 6], 3)
        self.assertAlmostEqual(result[2], 2.0, places=12)
        self.assertAlmostEqual(result[3], (2 * 2 + 4) / 3, places=12)
        self.assertAlmostEqual(result[4], ((2 * 2 + 4) / 3 * 2 + 5) / 3, places=12)

    def test_smooths_slower_than_ema_of_same_period(self):
        values = [1] * 10 + [100] * 10
        rma = wilder_rma(values, 5)
        exp = ema(values, 5)
        # Wilder alpha (1/n) < EMA alpha (2/(n+1)), so RMA reacts less.
        self.assertLess(rma[-1], exp[-1])


class TestRollingStd(unittest.TestCase):
    def test_population_std(self):
        # [2,4,6]: mean 4, population var = (4+0+4)/3 = 8/3
        result = rolling_std([2, 4, 6], 3, ddof=0)
        self.assertAlmostEqual(result[2], math.sqrt(8 / 3), places=12)

    def test_sample_std(self):
        # same data, sample var = 8/2 = 4 -> sd 2
        result = rolling_std([2, 4, 6], 3, ddof=1)
        self.assertAlmostEqual(result[2], 2.0, places=12)

    def test_constant_series_has_zero_std(self):
        self.assertAlmostEqual(rolling_std([7, 7, 7, 7], 3)[3], 0.0, places=12)

    def test_ddof_cannot_exceed_period(self):
        with self.assertRaises(ValueError):
            rolling_std([1, 2, 3], 1, ddof=1)


class TestZScore(unittest.TestCase):
    def test_known_value(self):
        # [2,4,6]: mean 4, pop sd sqrt(8/3); z of 6 = 2/sqrt(8/3)
        result = zscore([2, 4, 6], 3)
        self.assertAlmostEqual(result[2], 2 / math.sqrt(8 / 3), places=12)

    def test_zero_variance_yields_none(self):
        self.assertIsNone(zscore([5, 5, 5], 3)[2])


class TestBollinger(unittest.TestCase):
    def test_known_bands(self):
        mid, upper, lower = bollinger([2, 4, 6], 3, 1.0)
        sd = math.sqrt(8 / 3)
        self.assertAlmostEqual(mid[2], 4.0, places=12)
        self.assertAlmostEqual(upper[2], 4.0 + sd, places=12)
        self.assertAlmostEqual(lower[2], 4.0 - sd, places=12)

    def test_bands_are_symmetric_about_the_mean(self):
        mid, upper, lower = bollinger([3, 1, 4, 1, 5, 9, 2, 6], 4, 2.0)
        for m, u, l in zip(mid, upper, lower, strict=False):
            if m is None:
                continue
            self.assertAlmostEqual(u - m, m - l, places=12)


class TestRSI(unittest.TestCase):
    def test_monotonic_rise_is_100(self):
        self.assertAlmostEqual(rsi(list(range(1, 30)), 14)[-1], 100.0, places=10)

    def test_monotonic_fall_is_zero(self):
        self.assertAlmostEqual(rsi(list(range(30, 1, -1)), 14)[-1], 0.0, places=10)

    def test_equal_gains_and_losses_is_fifty(self):
        # Alternating +1/-1 gives avg_gain == avg_loss, so RS = 1 and RSI = 50.
        values = [100 + (i % 2) for i in range(20)]
        self.assertAlmostEqual(rsi(values, 14)[14], 50.0, places=10)

    def test_first_defined_index_is_period(self):
        result = rsi(list(range(1, 30)), 14)
        self.assertIsNone(result[13])
        self.assertIsNotNone(result[14])

    def test_bounded_zero_to_hundred(self):
        values = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9, 3, 2, 3, 8, 4, 6, 2, 6]
        for value in rsi(values, 14):
            if value is not None:
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 100.0)

    def test_flat_series_returns_fifty(self):
        # No gains and no losses is neutral, not a division by zero.
        self.assertAlmostEqual(rsi([50] * 20, 14)[-1], 50.0, places=10)

    def test_insufficient_data(self):
        self.assertEqual(rsi([1, 2, 3], 14), [None, None, None])


class TestTrueRangeATR(unittest.TestCase):
    def test_true_range_first_bar_has_no_prior_close(self):
        tr = true_range([10, 11], [9, 10], [9.5, 10.5])
        self.assertAlmostEqual(tr[0], 1.0, places=12)

    def test_true_range_uses_prior_close_gaps(self):
        # Gap up: high 11, low 10, prior close 9.5 -> max(1, 1.5, 0.5) = 1.5
        tr = true_range([10, 11], [9, 10], [9.5, 10.5])
        self.assertAlmostEqual(tr[1], 1.5, places=12)

    def test_atr_known_values(self):
        highs, lows, closes = [10, 11, 12], [9, 10, 11], [9.5, 10.5, 11.5]
        result = atr(highs, lows, closes, 2)
        # TR = [1.0, 1.5, 1.5]; seed = 1.25; next = (1.25*1 + 1.5)/2 = 1.375
        self.assertAlmostEqual(result[1], 1.25, places=12)
        self.assertAlmostEqual(result[2], 1.375, places=12)

    def test_atr_is_never_negative(self):
        highs = [10, 12, 9, 14, 11, 13, 15, 12]
        lows = [8, 9, 7, 10, 9, 10, 12, 10]
        closes = [9, 11, 8, 13, 10, 12, 14, 11]
        for value in atr(highs, lows, closes, 3):
            if value is not None:
                self.assertGreaterEqual(value, 0.0)

    def test_mismatched_lengths_rejected(self):
        with self.assertRaises(ValueError):
            true_range([1, 2], [1], [1, 2])


class TestMACD(unittest.TestCase):
    def setUp(self):
        self.values = [float(100 + i) for i in range(60)]

    def test_alignment_of_macd_line(self):
        line, _, _ = macd(self.values, 12, 26, 9)
        self.assertIsNone(line[24])
        self.assertIsNotNone(line[25])   # slow EMA becomes defined at index 25

    def test_alignment_of_signal_line(self):
        _, signal, _ = macd(self.values, 12, 26, 9)
        # Signal is a 9-EMA of the MACD line, which starts at 25 -> 25 + 8 = 33.
        self.assertIsNone(signal[32])
        self.assertIsNotNone(signal[33])

    def test_histogram_is_line_minus_signal(self):
        line, signal, hist = macd(self.values, 12, 26, 9)
        for i in range(len(hist)):
            if hist[i] is None:
                continue
            self.assertAlmostEqual(hist[i], line[i] - signal[i], places=12)

    def test_rising_series_has_positive_macd(self):
        line, _, _ = macd(self.values, 12, 26, 9)
        self.assertGreater(line[-1], 0.0)

    def test_fast_must_be_shorter_than_slow(self):
        with self.assertRaises(ValueError):
            macd(self.values, 26, 12, 9)


class TestADX(unittest.TestCase):
    def setUp(self):
        n = 60
        self.highs = [100 + i * 1.5 for i in range(n)]
        self.lows = [98 + i * 1.5 for i in range(n)]
        self.closes = [99 + i * 1.5 for i in range(n)]

    def test_uptrend_has_plus_di_above_minus_di(self):
        _, plus_di, minus_di = adx(self.highs, self.lows, self.closes, 14)
        self.assertGreater(plus_di[-1], minus_di[-1])

    def test_downtrend_has_minus_di_above_plus_di(self):
        highs = list(reversed(self.highs))
        lows = list(reversed(self.lows))
        closes = list(reversed(self.closes))
        _, plus_di, minus_di = adx(highs, lows, closes, 14)
        self.assertGreater(minus_di[-1], plus_di[-1])

    def test_adx_bounded(self):
        values, _, _ = adx(self.highs, self.lows, self.closes, 14)
        for value in values:
            if value is not None:
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 100.0)

    def test_strong_trend_produces_high_adx(self):
        values, _, _ = adx(self.highs, self.lows, self.closes, 14)
        self.assertGreater(values[-1], 40.0)

    def test_insufficient_data_returns_all_none(self):
        values, plus_di, minus_di = adx([1, 2], [0, 1], [1, 2], 14)
        self.assertEqual(values, [None, None])
        self.assertEqual(plus_di, [None, None])


class TestDonchian(unittest.TestCase):
    def test_channel_bounds(self):
        highs = [5, 7, 6, 9, 4]
        lows = [1, 3, 2, 4, 0]
        upper, lower = donchian(highs, lows, 3)
        self.assertEqual(upper[2], 7)     # max(5,7,6)
        self.assertEqual(lower[2], 1)     # min(1,3,2)
        self.assertEqual(upper[3], 9)     # max(7,6,9)
        self.assertEqual(lower[3], 2)     # min(3,2,4)

    def test_warmup_is_none(self):
        upper, lower = donchian([1, 2, 3], [0, 1, 2], 3)
        self.assertEqual(upper[:2], [None, None])
        self.assertEqual(lower[:2], [None, None])


class TestSupertrend(unittest.TestCase):
    """Traced by hand with ``period=1`` so ATR equals True Range exactly
    (Wilder smoothing with period 1 reduces to the identity), which makes the
    recursive final-band and flip logic checkable step by step.

    Bars (H, L, C): (10,8,9), (11,9,10), (9,6,7), (20,18,19).
    TR = [2, 2, 4, 13] -> ATR(1) = [2, 2, 4, 13] (identity).

    Day 0: mid=9,  upper=9+3*2=15,  lower=9-3*2=3.  seed: close 9 <= 15 -> down,
           line = final_upper = 15.
    Day 1: mid=10, upper=16, lower=4. final_upper unchanged (16 not < 15, and
           prior close 9 not > 15) -> stays 15. final_lower tightens to 4
           (4 > 3). Trend stays down (close 10 not > 15). line = 15.
    Day 2: mid=7.5, upper=19.5, lower=-4.5. Both finals unchanged (prior close
           10 doesn't break either band). Trend stays down (close 7 not > 15).
           line = 15.
    Day 3: mid=19, upper=58, lower=-20. Both finals still unchanged. Trend
           flips: close 19 > final_upper 15 -> up. line = final_lower = 4.
    """

    HIGHS = [10, 11, 9, 20]
    LOWS = [8, 9, 6, 18]
    CLOSES = [9, 10, 7, 19]

    def test_hand_traced_line_and_direction(self):
        line, direction = supertrend(self.HIGHS, self.LOWS, self.CLOSES, period=1, multiplier=3.0)
        for value, expected in zip(line, [15.0, 15.0, 15.0, 4.0], strict=True):
            self.assertAlmostEqual(value, expected, places=12)
        self.assertEqual(direction, [-1, -1, -1, 1])

    def test_warmup_is_none_and_length_preserved(self):
        # ATR (Wilder RMA) first defines at index period-1, matching sma/ema's
        # own warm-up convention — so period=3 leaves indices 0-1 undefined.
        line, direction = supertrend(self.HIGHS, self.LOWS, self.CLOSES, period=3, multiplier=3.0)
        self.assertEqual(len(line), 4)
        self.assertEqual(len(direction), 4)
        self.assertEqual(line[:2], [None, None])
        self.assertEqual(direction[:2], [None, None])
        self.assertIsNotNone(line[2])
        self.assertIn(direction[2], (1, -1))

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            supertrend([1, 2], [1], [1, 2], period=1)

    def test_invalid_multiplier_raises(self):
        with self.assertRaises(ValueError):
            supertrend(self.HIGHS, self.LOWS, self.CLOSES, period=1, multiplier=0)

    def test_invalid_period_raises(self):
        with self.assertRaises(ValueError):
            supertrend(self.HIGHS, self.LOWS, self.CLOSES, period=0)


class TestReturns(unittest.TestCase):
    def test_simple_returns(self):
        self.assertEqual(simple_returns([100, 110]), [0.1])
        self.assertAlmostEqual(simple_returns([100, 110, 99])[1], -0.1, places=12)

    def test_simple_returns_length(self):
        self.assertEqual(len(simple_returns([1, 2, 3, 4])), 3)

    def test_log_returns(self):
        self.assertAlmostEqual(log_returns([100, 110])[0], math.log(1.1), places=12)

    def test_log_return_of_double_is_ln2(self):
        self.assertAlmostEqual(log_returns([50, 100])[0], math.log(2), places=12)

    def test_rate_of_change(self):
        result = rate_of_change([100, 105, 110], 2)
        self.assertIsNone(result[1])
        self.assertAlmostEqual(result[2], 0.10, places=12)

    def test_annualised_volatility(self):
        returns = [0.01, -0.01, 0.01, -0.01]
        # mean 0; sample var = 4*0.0001/3; sd = sqrt(that); annualised * sqrt(252)
        expected = math.sqrt(4 * 0.0001 / 3) * math.sqrt(252)
        self.assertAlmostEqual(annualised_volatility(returns), expected, places=12)

    def test_volatility_of_single_return_is_zero(self):
        self.assertEqual(annualised_volatility([0.01]), 0.0)


class TestCrossings(unittest.TestCase):
    def test_cross_above_detected_once(self):
        fast = [1.0, 2.0, 3.0]
        slow = [2.0, 2.0, 2.0]
        self.assertFalse(crossed_above(fast, slow, 1))   # equal, not above
        self.assertTrue(crossed_above(fast, slow, 2))

    def test_cross_below_detected(self):
        fast = [3.0, 2.0, 1.0]
        slow = [2.0, 2.0, 2.0]
        self.assertTrue(crossed_below(fast, slow, 2))

    def test_none_values_do_not_signal(self):
        self.assertFalse(crossed_above([None, 2.0], [1.0, 1.0], 1))

    def test_index_zero_never_crosses(self):
        self.assertFalse(crossed_above([1.0], [0.0], 0))


if __name__ == "__main__":
    unittest.main()
