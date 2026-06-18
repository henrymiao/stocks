import unittest

from tools.stock_skills.sector import analyze_sector


class SectorTests(unittest.TestCase):
    def test_leading_a_rising_sector_scores_high(self):
        result = analyze_sector(instrument_change=0.05, constituent_changes=[0.03, 0.02, 0.04, 0.01, 0.025])

        self.assertGreater(result.score, 60)
        self.assertEqual(result.stance, "leading")
        self.assertGreaterEqual(result.breadth, 0.8)
        self.assertGreater(result.relative_strength, 0)

    def test_lagging_a_rising_sector_is_relative_weakness(self):
        result = analyze_sector(instrument_change=0.002, constituent_changes=[0.03, 0.025, 0.04, 0.02, 0.03])

        self.assertEqual(result.stance, "lagging")
        self.assertLess(result.relative_strength, 0)

    def test_weak_sector_drags_score_down(self):
        result = analyze_sector(instrument_change=-0.03, constituent_changes=[-0.02, -0.03, -0.01, -0.04, -0.02])

        self.assertLess(result.score, 45)
        self.assertEqual(result.stance, "sector-weak")

    def test_missing_constituents_is_neutral(self):
        result = analyze_sector(instrument_change=0.01, constituent_changes=[])

        self.assertEqual(result.score, 50.0)
        self.assertEqual(result.stance, "unknown")
        self.assertIsNone(result.breadth)


if __name__ == "__main__":
    unittest.main()
