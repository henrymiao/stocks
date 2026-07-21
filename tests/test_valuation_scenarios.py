import unittest

from tools.stock_skills.market_profiles import resolve_market_profile
from tools.stock_skills.valuation_scenarios import analyze_valuation_scenarios


class ValuationScenarioTests(unittest.TestCase):
    def test_earnings_multiple_cases_are_explicit_and_ordered(self):
        assumptions = {
            "method": "earnings-multiple",
            "cases": {
                "bear": {"eps": 2.0, "multiple": 15.0},
                "base": {"eps": 2.4, "multiple": 20.0},
                "bull": {"eps": 2.8, "multiple": 25.0},
            },
        }
        result = analyze_valuation_scenarios(
            assumptions,
            resolve_market_profile("HK.00700"),
        )
        self.assertEqual([case.fair_value for case in result.cases], [30.0, 48.0, 70.0])
        self.assertTrue(all(case.method == "earnings-multiple" for case in result.cases))
        self.assertEqual(result.status, "available")
        self.assertIn("earnings-multiple", result.sensitivity)

    def test_incomplete_dcf_is_refused_without_defaults(self):
        result = analyze_valuation_scenarios(
            {"method": "dcf", "cases": {"base": {"fcff": 100.0}}},
            resolve_market_profile("US.NVDA"),
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.cases, ())
        self.assertIn("missing", result.notes[0])

    def test_complete_dcf_requires_discount_rate_above_terminal_growth(self):
        invalid = {
            "method": "dcf",
            "cases": {
                name: {
                    "fcff": 100.0,
                    "growth_rate": 0.08,
                    "years": 5,
                    "discount_rate": 0.03,
                    "terminal_growth": 0.03,
                    "net_debt": 20.0,
                    "shares": 10.0,
                }
                for name in ("bear", "base", "bull")
            },
        }
        result = analyze_valuation_scenarios(
            invalid,
            resolve_market_profile("SH.600309"),
        )
        self.assertEqual(result.status, "unavailable")

    def test_complete_dcf_is_available_and_exposes_sensitivity(self):
        assumptions = {
            "method": "dcf",
            "cases": {
                "bear": {
                    "fcff": 80.0,
                    "growth_rate": 0.02,
                    "years": 5,
                    "discount_rate": 0.11,
                    "terminal_growth": 0.02,
                    "net_debt": 100.0,
                    "shares": 100.0,
                },
                "base": {
                    "fcff": 100.0,
                    "growth_rate": 0.05,
                    "years": 5,
                    "discount_rate": 0.10,
                    "terminal_growth": 0.03,
                    "net_debt": 80.0,
                    "shares": 100.0,
                },
                "bull": {
                    "fcff": 120.0,
                    "growth_rate": 0.08,
                    "years": 5,
                    "discount_rate": 0.09,
                    "terminal_growth": 0.04,
                    "net_debt": 60.0,
                    "shares": 100.0,
                },
            },
        }
        result = analyze_valuation_scenarios(
            assumptions,
            resolve_market_profile("US.NVDA"),
        )
        self.assertEqual(result.status, "available")
        self.assertEqual(len(result.cases), 3)
        self.assertIn("dcf", result.sensitivity)
        self.assertGreater(len(result.sensitivity["dcf"]), 0)

    def test_invalid_case_order_is_rejected(self):
        result = analyze_valuation_scenarios(
            {
                "method": "earnings-multiple",
                "cases": {
                    "bear": {"eps": 2.0, "multiple": 15.0},
                    "base": {"eps": 1.0, "multiple": 20.0},
                    "bull": {"eps": 2.8, "multiple": 25.0},
                },
            },
            resolve_market_profile("HK.00700"),
        )
        self.assertEqual(result.status, "unavailable")
        self.assertTrue(any("ordered" in note for note in result.notes))

    def test_two_valid_methods_report_base_case_disagreement(self):
        earnings = {
            "method": "earnings-multiple",
            "cases": {
                "bear": {"eps": 2.0, "multiple": 15.0},
                "base": {"eps": 2.4, "multiple": 20.0},
                "bull": {"eps": 2.8, "multiple": 25.0},
            },
        }
        sotp = {
            "method": "sotp",
            "cases": {
                "bear": {"parts": [{"value": 350.0}], "net_debt": 50.0, "shares": 10.0},
                "base": {"parts": [{"value": 550.0}], "net_debt": 50.0, "shares": 10.0},
                "bull": {"parts": [{"value": 750.0}], "net_debt": 50.0, "shares": 10.0},
            },
        }
        result = analyze_valuation_scenarios(
            {"methods": [earnings, sotp]},
            resolve_market_profile("HK.00700"),
        )
        self.assertEqual(result.methods_used, ("earnings-multiple", "sotp"))
        self.assertIsNotNone(result.method_disagreement_pct)


if __name__ == "__main__":
    unittest.main()
