import unittest

from tools.stock_skills.engine import build_recommendation, classify_total_score
from tools.stock_skills.models import (
    CapitalAnalysis,
    ComponentScores,
    CrossMarketAnalysis,
    InstrumentState,
    KLineBar,
    MacroAnalysis,
    MarketSnapshot,
    TrendAnalysis,
)


class EngineTests(unittest.TestCase):
    def test_classify_total_score_respects_extended_resistance(self):
        self.assertEqual(classify_total_score(84, price_location="near_resistance"), "trim-on-strength")
        self.assertEqual(classify_total_score(84, price_location="healthy_pullback"), "strong-watch")
        self.assertEqual(classify_total_score(38, price_location="anywhere"), "risk-reduce")

    def test_build_recommendation_combines_frames(self):
        state = InstrumentState(
            snapshot=MarketSnapshot("SZ.002463", "沪电股份", 147.9, 146.0, 149.36, 142.81, 146.55, 83_679_015, 12_271_729_868.41, "2026-06-18T15:00:00+08:00"),
            daily_bars=[
                KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
                KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83_679_015, 12_271_729_868.41),
            ],
            intraday_bars=[],
            user_context={"last_trim_price": 149.5},
        )
        trend = TrendAnalysis(66, "high-level-consolidation", [145.0, 142.81], [149.9, 150.0], 142.81, ["Price is consolidating high."])
        capital = CapitalAnalysis(58, "stabilizes", ["super-large inflow is offset."])
        macro = MacroAnalysis(35, "risk-off", ["Fed bias points toward higher rates."])
        cross = CrossMarketAnalysis(42, "risk-off", ["US.QQQ is sharply negative."])
        weights = {
            "trend": 0.25,
            "capital_flow": 0.20,
            "sector": 0.15,
            "cross_market": 0.15,
            "macro_risk": 0.15,
            "position_fit": 0.10,
        }

        recommendation = build_recommendation(
            state=state,
            trend=trend,
            capital=capital,
            macro=macro,
            cross_market=cross,
            sector_score=60,
            position_fit_score=70,
            weights=weights,
            source_refs=["data/snapshots/SZ.002463.json"],
        )

        self.assertEqual(recommendation.code, "SZ.002463")
        self.assertIn(recommendation.label, {"hold", "trim-on-strength"})
        self.assertIn("investment hypothesis", recommendation.analyst_hypothesis)
        self.assertIn("invalidation", recommendation.trader_plan)
        self.assertEqual(recommendation.invalidation_level, 142.81)
        self.assertIsInstance(recommendation.component_scores, ComponentScores)


if __name__ == "__main__":
    unittest.main()
