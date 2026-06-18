import unittest

from tools.stock_skills.models import KLineBar
from tools.stock_skills.position import analyze_position, compute_atr


class PositionTests(unittest.TestCase):
    def test_compute_atr_uses_true_range(self):
        bars = [
            KLineBar("d1", 100, 105, 99, 104, 1, 1.0),
            KLineBar("d2", 104, 108, 103, 107, 1, 1.0),
            KLineBar("d3", 107, 110, 105, 106, 1, 1.0),
        ]
        atr = compute_atr(bars, n=14)
        self.assertIsNotNone(atr)
        self.assertGreater(atr, 0)

    def test_atr_none_with_too_few_bars(self):
        self.assertIsNone(compute_atr([KLineBar("d1", 1, 1, 1, 1, 1, 1.0)]))

    def test_position_size_scales_inverse_to_stop_distance(self):
        # 1% risk budget, stop 5% away → ~20% position.
        result = analyze_position(last_price=100.0, atr=2.5, invalidation_level=95.0, risk_budget_pct=1.0, atr_multiple=2.0)

        self.assertEqual(result.stop_price, 95.0)  # invalidation (95) tighter than ATR stop (95.0 too)
        self.assertEqual(result.stop_distance_pct, 5.0)
        self.assertEqual(result.suggested_size_pct, 20.0)
        self.assertEqual(result.stance, "trading-position")

    def test_wider_stop_yields_smaller_size(self):
        tight = analyze_position(100.0, atr=1.0, invalidation_level=97.0, risk_budget_pct=1.0)
        wide = analyze_position(100.0, atr=6.0, invalidation_level=85.0, risk_budget_pct=1.0)

        self.assertGreater(tight.suggested_size_pct, wide.suggested_size_pct)
        self.assertGreater(tight.score, wide.score)

    def test_uses_tighter_of_invalidation_and_atr_stop(self):
        # ATR stop = 100 - 2*4 = 92; invalidation 88 → tighter (higher) is 92.
        result = analyze_position(100.0, atr=4.0, invalidation_level=88.0, atr_multiple=2.0)
        self.assertEqual(result.stop_price, 92.0)

    def test_no_valid_stop_is_wait(self):
        result = analyze_position(100.0, atr=None, invalidation_level=None)
        self.assertEqual(result.stance, "wait")
        self.assertIsNone(result.suggested_size_pct)

    def test_prior_trim_dampens_score(self):
        base = analyze_position(100.0, atr=2.0, invalidation_level=96.0, risk_budget_pct=1.0)
        trimmed = analyze_position(100.0, atr=2.0, invalidation_level=96.0, risk_budget_pct=1.0, last_trim_price=98.0)
        self.assertLess(trimmed.score, base.score)
        self.assertTrue(any("trimmed" in n for n in trimmed.notes))


if __name__ == "__main__":
    unittest.main()
