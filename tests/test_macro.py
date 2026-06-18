import unittest

from tools.stock_skills.macro import analyze_cross_market, analyze_macro_from_proxies, analyze_macro_risk
from tools.stock_skills.models import MarketSnapshot


def snapshot(code, last, prev):
    return MarketSnapshot(code, code, last, last, last, last, prev, 1, 1.0, "2026-06-18T15:00:00+08:00")


class MacroTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
