import unittest

from tools.stock_skills.method_models import (
    ValuationCase,
    ValuationScenarioAnalysis,
)
from tools.stock_skills.models import FundamentalAnalysis
from tools.stock_skills.thesis import analyze_thesis


UNKNOWN_VALUATION = ValuationScenarioAnalysis(
    "unavailable",
    (),
    (),
    {},
    None,
    0.0,
    0.0,
    ("no assumptions",),
)


class ThesisTests(unittest.TestCase):
    def test_no_observed_driver_stays_unknown(self):
        result = analyze_thesis(None, "unknown", "neutral", UNKNOWN_VALUATION, {}, {})
        self.assertEqual(result.state, "unknown")
        self.assertTrue(result.unresolved)

    def test_growth_and_sector_leadership_create_observed_upside_drivers(self):
        fundamental = FundamentalAnalysis(
            75.0,
            "fair",
            "growth",
            1.1,
            ["EPS growth 30%"],
            quality=80.0,
        )
        result = analyze_thesis(
            fundamental,
            "leading",
            "risk-on",
            UNKNOWN_VALUATION,
            {},
            {},
        )
        self.assertEqual(result.state, "supported")
        self.assertTrue(any("business quality" in item for item in result.upside_drivers))
        self.assertTrue(any("sector" in item for item in result.upside_drivers))
        self.assertNotIn("breakout", " ".join(result.upside_drivers).lower())

    def test_only_evaluated_manual_condition_can_invalidate(self):
        manual = {
            "invalidations": [
                {
                    "field": "revenue_growth",
                    "operator": "<",
                    "value": 0.0,
                    "reason": "growth thesis failed",
                }
            ]
        }
        result = analyze_thesis(
            None,
            "unknown",
            "neutral",
            UNKNOWN_VALUATION,
            manual,
            {"revenue_growth": -5.0},
        )
        self.assertEqual(result.state, "invalidated")
        self.assertEqual(result.invalidations, ("growth thesis failed",))

    def test_missing_invalidation_metric_stays_unresolved(self):
        manual = {
            "invalidations": [
                {
                    "field": "revenue_growth",
                    "operator": "<",
                    "value": 0.0,
                    "reason": "growth thesis failed",
                }
            ]
        }
        result = analyze_thesis(
            None,
            "unknown",
            "neutral",
            UNKNOWN_VALUATION,
            manual,
            {},
        )
        self.assertNotEqual(result.state, "invalidated")
        self.assertTrue(any("revenue_growth" in item for item in result.unresolved))

    def test_manual_current_price_cannot_create_valuation_support(self):
        valuation = ValuationScenarioAnalysis(
            "available",
            ("earnings-multiple",),
            (ValuationCase("earnings-multiple", "base", 50.0, {}),),
            {},
            None,
            1.0,
            1.0,
        )
        ignored = analyze_thesis(
            None,
            "unknown",
            "neutral",
            valuation,
            {"current_price": 1.0},
            {},
        )
        observed = analyze_thesis(
            None,
            "unknown",
            "neutral",
            valuation,
            {"current_price": 1.0},
            {"current_price": 40.0},
        )
        self.assertFalse(any("valuation" in item for item in ignored.upside_drivers))
        self.assertTrue(any("valuation" in item for item in observed.upside_drivers))


if __name__ == "__main__":
    unittest.main()
