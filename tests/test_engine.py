import unittest

from tools.stock_skills.engine import backdrop_blend, build_recommendation, classify_total_score
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

BACKDROP_WEIGHTS = {
    "trend": 0.22,
    "capital_flow": 0.12,
    "sector": 0.15,
    "cross_market": 0.09,
    "macro_risk": 0.09,
    "market_regime": 0.10,
    "fundamental": 0.13,
    "position_fit": 0.10,
}


def _scores(market_regime=50.0, cross_market=50.0, macro_risk=50.0):
    return ComponentScores(
        trend=50.0,
        capital_flow=50.0,
        sector=50.0,
        cross_market=cross_market,
        macro_risk=macro_risk,
        position_fit=50.0,
        market_regime=market_regime,
        fundamental=50.0,
    )


class EngineTests(unittest.TestCase):
    def test_backdrop_neutral_is_unchanged(self):
        contribution, total_w, discounted = backdrop_blend(_scores(), BACKDROP_WEIGHTS)
        self.assertAlmostEqual(total_w, 0.28)
        self.assertEqual(discounted, 50.0)
        self.assertAlmostEqual(contribution, 50.0 * 0.28)  # neutral backdrop unaffected

    def test_backdrop_discounts_three_agreeing_bearish_signals(self):
        # All three say "risk-off 20". Triple-counting would dock 20*0.28; the
        # redundancy discount pulls the shared signal back toward neutral so the
        # penalty is smaller (contribution higher) — counted ~once, not three times.
        contribution, _, discounted = backdrop_blend(_scores(20.0, 20.0, 20.0), BACKDROP_WEIGHTS)
        self.assertEqual(discounted, 32.0)  # 50 + (20-50)*0.6
        self.assertGreater(contribution, 20.0 * 0.28)
        self.assertLess(discounted, 50.0)  # still bearish, just not triple-bearish

    def test_backdrop_disagreement_stays_near_neutral(self):
        # Bullish index vs bearish macro: independent info that cancels — the blend
        # sits near neutral and the discount barely matters.
        _, _, discounted = backdrop_blend(_scores(70.0, 70.0, 20.0), BACKDROP_WEIGHTS)
        self.assertGreater(discounted, 45.0)
        self.assertLess(discounted, 55.0)

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
