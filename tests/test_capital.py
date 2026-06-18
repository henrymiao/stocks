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

    def test_intraday_acceleration_tilts_score(self):
        base = dict(net_inflow=24_492_584.5, super_inflow=744_236_606.14, big_inflow=-411_741_404.48, mid_inflow=-210_842_830.36, small_inflow=-97_159_786.8, timestamp="2026-06-18T15:00:00+08:00")
        flat = analyze_capital(CapitalSnapshot(**base, intraday_trend="flat"))
        accel_in = analyze_capital(CapitalSnapshot(**base, intraday_trend="accelerating-in"))
        accel_out = analyze_capital(CapitalSnapshot(**base, intraday_trend="accelerating-out"))

        self.assertGreater(accel_in.score, flat.score)
        self.assertLess(accel_out.score, flat.score)
        self.assertTrue(any("into the close" in note for note in accel_in.notes))


if __name__ == "__main__":
    unittest.main()
