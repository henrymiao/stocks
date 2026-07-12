import unittest

from tools.stock_skills import macro
from tools.stock_skills.macro import analyze_cross_market, analyze_macro_from_proxies, analyze_macro_risk
from tools.stock_skills.models import MarketSnapshot


def snapshot(code, last, prev):
    return MarketSnapshot(code, code, last, last, last, last, prev, 1, 1.0, "2026-06-18T15:00:00+08:00")


class MacroTests(unittest.TestCase):
    def test_cross_market_evidence_requires_recognized_code(self):
        snapshots = {"HK.800700": snapshot("HK.800700", 6_000.0, 5_900.0)}

        self.assertFalse(macro.has_cross_market_evidence(snapshots))

    def test_cross_market_evidence_requires_usable_previous_close(self):
        snapshots = {"US.QQQ": snapshot("US.QQQ", 750.0, 0.0)}

        self.assertFalse(macro.has_cross_market_evidence(snapshots))

    def test_flat_recognized_cross_snapshot_is_evidence(self):
        snapshots = {"US.QQQ": snapshot("US.QQQ", 750.0, 750.0)}

        self.assertTrue(macro.has_cross_market_evidence(snapshots))

    def test_macro_proxy_evidence_requires_recognized_usable_snapshot(self):
        self.assertFalse(
            macro.has_macro_proxy_evidence(
                {"HK.800000": snapshot("HK.800000", 25_000.0, 24_900.0)}
            )
        )
        self.assertFalse(
            macro.has_macro_proxy_evidence(
                {"US.VIXY": snapshot("US.VIXY", 22.0, 0.0)}
            )
        )
        self.assertTrue(
            macro.has_macro_proxy_evidence(
                {"US.VIXY": snapshot("US.VIXY", 22.0, 22.0)}
            )
        )

    def test_macro_input_evidence_accepts_directional_and_explicit_neutral_values(self):
        supported_inputs = (
            {"fed_bias": "hike"},
            {"fed_bias": "neutral"},
            {"geopolitical_risk": "elevated"},
            {"geopolitical_risk": "normal"},
            {"oil_shock": True},
            {"oil_shock": False},
            {"dollar_pressure": "high"},
            {"dollar_pressure": "normal"},
            {"jgb_stress": "elevated"},
            {"jgb_stress": "normal"},
            {"yen_carry_stress": "elevated"},
            {"yen_carry_stress": "normal"},
            {"credit_stress": "elevated"},
            {"credit_stress": "normal"},
        )

        for inputs in supported_inputs:
            with self.subTest(inputs=inputs):
                self.assertTrue(macro.has_macro_input_evidence(inputs))

    def test_macro_input_evidence_rejects_unknown_keys_and_values(self):
        unsupported_inputs = (
            {"weather": "sunny"},
            {"fed_bias": "sideways"},
            {"geopolitical_risk": "severe"},
            {"oil_shock": "false"},
            {"dollar_pressure": "medium"},
        )

        for inputs in unsupported_inputs:
            with self.subTest(inputs=inputs):
                self.assertFalse(macro.has_macro_input_evidence(inputs))

    def test_rate_hike_bias_creates_risk_off_macro(self):
        result = analyze_macro_risk(
            {
                "fed_bias": "hike",
                "geopolitical_risk": "elevated",
                "oil_shock": True,
                "dollar_pressure": "high",
            }
        )

        self.assertLessEqual(result.score, 35)
        self.assertEqual(result.regime, "risk-off")

    def test_neutral_macro_when_inputs_are_missing(self):
        result = analyze_macro_risk({})

        self.assertEqual(result.score, 50)
        self.assertEqual(result.regime, "neutral")

    def test_jgb_yen_carry_and_credit_stress_create_risk_off_macro(self):
        result = analyze_macro_risk(
            {
                "jgb_stress": "elevated",
                "yen_carry_stress": "elevated",
                "credit_stress": "elevated",
            }
        )

        self.assertLessEqual(result.score, 20)
        self.assertEqual(result.regime, "risk-off")
        self.assertTrue(any("JGB" in note for note in result.notes))
        self.assertTrue(any("carry" in note for note in result.notes))

    def test_cross_market_penalizes_weak_us_ai_tape(self):
        result = analyze_cross_market(
            {
                "US.QQQ": snapshot("US.QQQ", 722.51, 729.86),
                "US.SPY": snapshot("US.SPY", 740.96, 750.33),
                "US.NVDA": snapshot("US.NVDA", 204.65, 207.41),
            }
        )

        self.assertLess(result.score, 50)
        self.assertEqual(result.regime, "risk-off")

    def test_cross_market_rewards_strong_ai_tape(self):
        result = analyze_cross_market(
            {
                "US.QQQ": snapshot("US.QQQ", 750.0, 729.86),
                "US.SPY": snapshot("US.SPY", 760.0, 750.33),
                "US.NVDA": snapshot("US.NVDA", 216.0, 207.41),
            }
        )

        self.assertGreater(result.score, 60)
        self.assertEqual(result.regime, "risk-on")

    def test_cross_market_ignores_snapshot_without_previous_close(self):
        result = analyze_cross_market({"US.QQQ": snapshot("US.QQQ", 722.51, 0.0)})

        self.assertEqual(result.score, 50)
        self.assertEqual(result.regime, "neutral")

    def test_macro_proxies_risk_off_when_vix_and_dollar_spike(self):
        result = analyze_macro_from_proxies(
            {
                "US.VIXY": snapshot("US.VIXY", 24.0, 22.0),  # fear up ~9%
                "US.UUP": snapshot("US.UUP", 28.8, 28.0),     # dollar up
                "US.TLT": snapshot("US.TLT", 85.0, 87.0),     # bonds down = yields up
            }
        )

        self.assertLess(result.score, 40)
        self.assertEqual(result.regime, "risk-off")

    def test_macro_proxies_risk_on_when_vix_falls_and_bonds_rally(self):
        result = analyze_macro_from_proxies(
            {
                "US.VIXY": snapshot("US.VIXY", 20.0, 22.7),  # fear down
                "US.TLT": snapshot("US.TLT", 89.0, 86.3),     # bonds up = yields down
                "US.UUP": snapshot("US.UUP", 28.0, 28.2),     # dollar soft
            }
        )

        self.assertGreater(result.score, 60)
        self.assertEqual(result.regime, "risk-on")

    def test_macro_proxies_neutral_without_data(self):
        result = analyze_macro_from_proxies({})

        self.assertEqual(result.score, 50.0)
        self.assertEqual(result.regime, "neutral")

    def test_yen_carry_unwind_and_credit_deterioration_are_risk_off(self):
        result = analyze_macro_from_proxies(
            {
                "US.FXY": snapshot("US.FXY", 57.2, 56.4),
                "US.HYG": snapshot("US.HYG", 79.0, 80.0),
                "US.LQD": snapshot("US.LQD", 107.7, 107.7),
                "US.VIXY": snapshot("US.VIXY", 23.5, 22.0),
            }
        )

        self.assertLess(result.score, 30)
        self.assertEqual(result.regime, "risk-off")
        self.assertTrue(any("套息" in note for note in result.notes))
        self.assertTrue(any("信用" in note for note in result.notes))


if __name__ == "__main__":
    unittest.main()
