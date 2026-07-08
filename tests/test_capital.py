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

    def test_price_up_but_main_force_out_is_distribution(self):
        # Retail (small) buying carries a rising tape while the main force (super+large) sells:
        # a bearish divergence — must score below a naive "positive aggregate" read and be labelled.
        capital = CapitalSnapshot(
            net_inflow=30_000_000,
            super_inflow=-40_000_000,
            big_inflow=-20_000_000,
            mid_inflow=10_000_000,
            small_inflow=80_000_000,
            timestamp="2026-07-08T11:30:00+08:00",
        )
        without = analyze_capital(capital)
        result = analyze_capital(capital, price_change=0.02)
        self.assertEqual(result.stance, "distribution")
        self.assertLess(result.score, without.score)
        self.assertLess(result.score, 50)
        self.assertTrue(any("bearish divergence" in note for note in result.notes))

    def test_price_up_and_main_force_in_confirms(self):
        # Main force leads the buying on an up day — healthy confirmation, high score.
        capital = CapitalSnapshot(
            net_inflow=47_000_000,
            super_inflow=20_000_000,
            big_inflow=1_400_000,
            mid_inflow=12_000_000,
            small_inflow=13_600_000,
            timestamp="2026-07-08T11:30:00+08:00",
        )
        result = analyze_capital(capital, price_change=0.06)
        self.assertEqual(result.stance, "confirms")
        self.assertGreater(result.score, 55)

    def test_price_down_but_main_force_in_is_accumulation(self):
        # Price falls while the main force absorbs — bullish divergence, scored above the
        # direction-agnostic read.
        capital = CapitalSnapshot(
            net_inflow=5_000_000,
            super_inflow=30_000_000,
            big_inflow=5_000_000,
            mid_inflow=-10_000_000,
            small_inflow=-20_000_000,
            timestamp="2026-07-08T11:30:00+08:00",
        )
        without = analyze_capital(capital)
        result = analyze_capital(capital, price_change=-0.02)
        self.assertEqual(result.stance, "accumulation")
        self.assertGreater(result.score, without.score)

    def test_distribution_source_is_flagged_in_notes(self):
        # When the reading came from the full-day distribution fallback (intraday feed was
        # stale), the analysis should say so for traceability.
        capital = CapitalSnapshot(900_000_000, 400_000_000, 250_000_000, 150_000_000, 100_000_000, "2026-06-18T15:00:00+08:00", source="distribution")
        result = analyze_capital(capital)
        self.assertTrue(any("distribution" in note for note in result.notes))


if __name__ == "__main__":
    unittest.main()
