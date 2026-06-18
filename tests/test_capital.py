import unittest

from tools.stock_skills.capital import analyze_capital
from tools.stock_skills.models import CapitalSnapshot


class CapitalTests(unittest.TestCase):
    def test_broad_inflow_confirms_trend(self):
        capital = CapitalSnapshot(900_000_000, 400_000_000, 250_000_000, 150_000_000, 100_000_000, "2026-06-18T15:00:00+08:00")

        result = analyze_capital(capital)

        self.assertGreaterEqual(result.score, 80)
        self.assertEqual(result.stance, "confirms")

    def test_super_inflow_but_large_mid_outflow_is_divergent(self):
        capital = CapitalSnapshot(24_492_584.5, 744_236_606.14, -411_741_404.48, -210_842_830.36, -97_159_786.8, "2026-06-18T15:00:00+08:00")

        result = analyze_capital(capital)

        self.assertGreaterEqual(result.score, 50)
        self.assertLess(result.score, 70)
        self.assertEqual(result.stance, "stabilizes")
        self.assertTrue(any("super-large" in note for note in result.notes))

    def test_broad_outflow_contradicts_trend(self):
        capital = CapitalSnapshot(-600_000_000, -100_000_000, -200_000_000, -200_000_000, -100_000_000, "2026-06-18T15:00:00+08:00")

        result = analyze_capital(capital)

        self.assertLessEqual(result.score, 35)
        self.assertEqual(result.stance, "contradicts")


if __name__ == "__main__":
    unittest.main()
