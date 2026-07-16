import unittest

from tools.stock_skills.models import KLineBar, MarketSnapshot
from tools.stock_skills.trend import analyze_trend


class TrendTests(unittest.TestCase):
    def test_clean_breakout_scores_high(self):
        bars = [
            KLineBar("2026-06-15", 128.5, 134.0, 122.22, 133.76, 99_418_986, 12_861_198_025.68),
            KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 152.0, 145.4, 151.4, 135_000_000, 20_000_000_000.0),
        ]
        snapshot = MarketSnapshot("SZ.002463", "沪电股份", 151.4, 146.0, 152.0, 145.4, 146.55, 135_000_000, 20_000_000_000.0, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertGreaterEqual(result.score, 80)
        self.assertEqual(result.status, "breakout-confirmed")
        # 149.9 was cleared by the breakout, so it is retest support now; only
        # levels above the live price may appear as resistance.
        self.assertIn(149.9, result.support_levels)
        self.assertNotIn(149.9, result.resistance_levels)
        self.assertTrue(all(level > snapshot.last_price for level in result.resistance_levels))
        self.assertTrue(all(level < snapshot.last_price for level in result.support_levels))

    def test_failed_breakout_near_resistance_scores_mid(self):
        bars = [
            KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83_679_015, 12_271_729_868.41),
        ]
        snapshot = MarketSnapshot("SZ.002463", "沪电股份", 147.9, 146.0, 149.36, 142.81, 146.55, 83_679_015, 12_271_729_868.41, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertGreaterEqual(result.score, 55)
        self.assertLess(result.score, 75)
        self.assertEqual(result.status, "high-level-consolidation")
        self.assertEqual(result.invalidation_level, 142.81)

    def test_breakdown_scores_low(self):
        bars = [
            KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 148.0, 141.0, 141.5, 120_000_000, 17_000_000_000.0),
        ]
        snapshot = MarketSnapshot("SZ.002463", "沪电股份", 141.5, 146.0, 148.0, 141.0, 146.55, 120_000_000, 17_000_000_000.0, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertLessEqual(result.score, 45)
        self.assertEqual(result.status, "breakdown-risk")

    def test_breakdown_takes_priority_over_failed_resistance_test(self):
        bars = [
            KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 149.4, 141.0, 141.5, 120_000_000, 17_000_000_000.0),
        ]
        snapshot = MarketSnapshot("SZ.002463", "沪电股份", 141.5, 146.0, 149.4, 141.0, 146.55, 120_000_000, 17_000_000_000.0, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertEqual(result.status, "breakdown-risk")

    def test_short_history_leaves_regime_unknown_and_does_not_alter_scores(self):
        # 4 bars: no MA20/50, so the overlay must not touch the legacy breakout result.
        bars = [
            KLineBar("2026-06-15", 128.5, 134.0, 122.22, 133.76, 99_418_986, 12_861_198_025.68),
            KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 152.0, 145.4, 151.4, 135_000_000, 20_000_000_000.0),
        ]
        snapshot = MarketSnapshot("SZ.002463", "沪电股份", 151.4, 146.0, 152.0, 145.4, 146.55, 135_000_000, 20_000_000_000.0, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertEqual(result.trend_regime, "unknown")
        self.assertIsNone(result.ma_mid)
        self.assertEqual(result.status, "breakout-confirmed")
        self.assertGreaterEqual(result.score, 80)

    def test_breakout_against_downtrend_is_demoted(self):
        # A long decline (MA20<MA50, price below MA20) with a one-day pop above the
        # recent 5-day high: a textbook false-breakout setup. The overlay should
        # demote it rather than report a clean breakout.
        closes = [200.0 - i * 1.8 for i in range(54)]  # falling from 200 to ~104.6
        bars = [
            KLineBar(f"d{i}", c, c + 1.0, c - 1.0, c, 1_000_000, c * 1_000_000.0)
            for i, c in enumerate(closes)
        ]
        prev_close = closes[-1]
        last_price = 118.0  # > prior 5-day high (~112.8) but < MA20 (~121) → still in the downtrend
        bars.append(KLineBar("d54", prev_close, last_price, prev_close - 1.0, last_price, 2_400_000, last_price * 2_400_000.0))
        snapshot = MarketSnapshot("X.TEST", "Test", last_price, prev_close, last_price, prev_close - 1.0, prev_close, 2_400_000, last_price * 2_400_000.0, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertEqual(result.trend_regime, "downtrend")
        self.assertEqual(result.status, "breakout-vs-downtrend")
        self.assertLess(result.score, 75)  # demoted from the ~90 a clean breakout would earn
        self.assertIsNotNone(result.ma_mid)
        self.assertLess(result.ma_mid, result.ma_slow)

    def test_breakout_with_uptrend_scores_higher_than_same_breakout_in_downtrend(self):
        closes = [100.0 + i * 1.8 for i in range(54)]  # rising from 100 to ~195
        bars = [
            KLineBar(f"d{i}", c, c + 1.0, c - 1.0, c, 1_000_000, c * 1_000_000.0)
            for i, c in enumerate(closes)
        ]
        prev_close = closes[-1]
        last_price = prev_close + 6.0  # break above the recent high, in line with the uptrend
        bars.append(KLineBar("d54", prev_close, last_price, prev_close, last_price, 2_400_000, last_price * 2_400_000.0))
        snapshot = MarketSnapshot("X.TEST", "Test", last_price, prev_close, last_price, prev_close, prev_close, 2_400_000, last_price * 2_400_000.0, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertEqual(result.trend_regime, "uptrend")
        self.assertEqual(result.status, "breakout-confirmed")
        self.assertGreaterEqual(result.score, 85)
        self.assertGreater(result.ma_mid, result.ma_slow)


if __name__ == "__main__":
    unittest.main()
