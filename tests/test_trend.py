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
        self.assertIn(149.9, result.resistance_levels)

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


if __name__ == "__main__":
    unittest.main()
