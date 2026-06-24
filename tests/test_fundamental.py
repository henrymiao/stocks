import unittest

from tools.stock_skills.fundamental import analyze_fundamental, infer_profile
from tools.stock_skills.models import FundamentalSnapshot


def fund(pe, pb=2.0, eps=1.0, div=0.0, mv=1e10, growth=None):
    return FundamentalSnapshot("SZ.002463", pe, pb, eps, div, mv, growth)


class FundamentalTests(unittest.TestCase):
    def test_infer_profile_from_tags(self):
        self.assertEqual(infer_profile(["a-share", "pcb", "ai-hardware"]), "growth")
        self.assertEqual(infer_profile(["bank", "dividend"]), "value")
        self.assertEqual(infer_profile(["misc"]), "neutral")
        self.assertEqual(infer_profile(None), "neutral")

    def test_growth_tolerates_high_pe_that_value_would_reject(self):
        snap = fund(pe=55.0, pb=8.0)
        growth = analyze_fundamental(snap, profile="growth")
        value = analyze_fundamental(snap, profile="value")

        self.assertGreater(growth.score, value.score)
        self.assertEqual(value.stance, "expensive")

    def test_peg_below_one_rescues_high_pe_growth(self):
        # PE 60 looks rich, but 50% growth → PEG 1.2... use 70% growth → PEG < 1.
        result = analyze_fundamental(fund(pe=60.0, growth=70.0), profile="growth")

        self.assertEqual(result.peg, round(60.0 / 70.0, 2))
        self.assertEqual(result.stance, "cheap")
        self.assertGreater(result.score, 60)

    def test_expensive_growth_without_growth_input_is_flagged(self):
        result = analyze_fundamental(fund(pe=95.0), profile="growth")

        self.assertEqual(result.stance, "expensive")
        self.assertLess(result.score, 45)
        self.assertIsNone(result.peg)
        self.assertTrue(any("EPS growth not supplied" in n for n in result.notes))

    def test_value_rewards_low_pe_and_dividend(self):
        result = analyze_fundamental(fund(pe=10.0, pb=1.2, div=4.0), profile="value")

        self.assertEqual(result.stance, "cheap")
        self.assertGreater(result.score, 60)
        self.assertTrue(any("Dividend" in n for n in result.notes))

    def test_missing_data_is_neutral(self):
        result = analyze_fundamental(None, profile="growth")

        self.assertEqual(result.score, 50.0)
        self.assertEqual(result.stance, "unknown")

    def test_negative_pe_is_not_cheap(self):
        result = analyze_fundamental(fund(pe=-5.0), profile="growth")

        self.assertEqual(result.stance, "unknown")
        self.assertLessEqual(result.score, 50)

    def test_no_quality_inputs_keeps_quality_none(self):
        result = analyze_fundamental(fund(pe=55.0), profile="growth")
        self.assertIsNone(result.quality)

    def test_business_quality_separates_two_names_at_the_same_multiple(self):
        strong = FundamentalSnapshot(
            "X", pe_ttm=60.0, pb=8.0, eps=2.0, dividend_ratio=0.0, market_val=1e10,
            eps_growth=None, revenue_growth=35.0, gross_margin=55.0, net_margin=25.0, roe=22.0,
        )
        weak = FundamentalSnapshot(
            "Y", pe_ttm=60.0, pb=8.0, eps=2.0, dividend_ratio=0.0, market_val=1e10,
            eps_growth=None, revenue_growth=-5.0, gross_margin=18.0, net_margin=2.0, roe=4.0,
        )
        s = analyze_fundamental(strong, profile="growth")
        w = analyze_fundamental(weak, profile="growth")

        self.assertGreater(s.score, w.score)
        self.assertIsNotNone(s.quality)
        self.assertGreater(s.quality, 60)
        self.assertLess(w.quality, 50)

    def test_strong_quality_lifts_an_expensive_multiple_to_fair(self):
        snap = FundamentalSnapshot(
            "X", pe_ttm=95.0, pb=9.0, eps=1.0, dividend_ratio=0.0, market_val=1e10,
            eps_growth=None, revenue_growth=40.0, gross_margin=60.0, net_margin=30.0, roe=25.0,
        )
        result = analyze_fundamental(snap, profile="growth")

        self.assertEqual(result.stance, "fair")  # lifted off "expensive" by quality
        self.assertGreater(result.score, 45)


if __name__ == "__main__":
    unittest.main()
