import unittest

from tools.stock_skills.engine import (
    backdrop_blend,
    build_recommendation,
    classify_total_score,
    is_inverse_instrument,
)
from tools.stock_skills.models import (
    CapitalAnalysis,
    ComponentScores,
    CrossMarketAnalysis,
    DataQuality,
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
        data_quality = DataQuality(
            confidence=0.875,
            available_components=("trend", "capital_flow"),
            missing_components=("sector",),
            stale_components=(),
            session_phase="after-close",
            entry_eligible=True,
        )

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
            data_quality=data_quality,
        )

        self.assertEqual(recommendation.code, "SZ.002463")
        self.assertIn(recommendation.label, {"hold", "trim-on-strength"})
        self.assertIn("investment hypothesis", recommendation.analyst_hypothesis)
        self.assertIn("invalidation", recommendation.trader_plan)
        self.assertEqual(recommendation.invalidation_level, 142.81)
        self.assertIsInstance(recommendation.component_scores, ComponentScores)
        self.assertEqual(recommendation.confidence, 0.875)
        self.assertEqual(recommendation.data_quality, data_quality)


    def test_is_inverse_instrument_detects_name_and_tags(self):
        self.assertTrue(is_inverse_instrument("Direxion Daily Semiconductor Bear 3x Shares ETF"))
        self.assertTrue(is_inverse_instrument("ProShares UltraShort QQQ"))
        self.assertTrue(is_inverse_instrument("Anything", tags=["inverse"]))
        self.assertFalse(is_inverse_instrument("Direxion Daily Semiconductor Bull 3x Shares ETF"))
        self.assertFalse(is_inverse_instrument("NVIDIA", tags=["semiconductor"]))

    def test_inverse_reflects_backdrop_scores_only(self):
        state = InstrumentState(
            snapshot=MarketSnapshot("US.SOXS", "Direxion Daily Semiconductor Bear 3x Shares ETF", 4.0, 4.1, 4.2, 3.9, 4.05, 1_000, 4_000.0, "2026-06-23T16:00:00-04:00"),
            daily_bars=[
                KLineBar("2026-06-22", 4.2, 4.3, 3.9, 4.05, 1_000, 4_050.0),
                KLineBar("2026-06-23", 4.1, 4.2, 3.9, 4.0, 1_100, 4_400.0),
            ],
            intraday_bars=[],
        )
        trend = TrendAnalysis(40, "downtrend", [3.8], [4.2], 3.8, [])
        capital = CapitalAnalysis(45, "contradicts", [])
        macro = MacroAnalysis(90, "risk-on", ["VIX falling."])
        cross = CrossMarketAnalysis(70, "risk-on", ["QQQ green."])
        weights = dict(BACKDROP_WEIGHTS)

        common = dict(
            state=state, trend=trend, capital=capital, macro=macro, cross_market=cross,
            sector_score=50, position_fit_score=60, weights=weights, source_refs=["x"],
            market_score=60.0,
            data_quality=DataQuality(
                confidence=0.75,
                available_components=("trend",),
                missing_components=("cross_market",),
                stale_components=(),
                session_phase="intraday",
                entry_eligible=False,
            ),
        )
        rec_long = build_recommendation(**common, inverse=False)
        rec_inv = build_recommendation(**common, inverse=True)

        # Long: backdrop scores pass through unchanged.
        self.assertEqual(rec_long.component_scores.macro_risk, 90)
        self.assertEqual(rec_long.component_scores.cross_market, 70)
        self.assertEqual(rec_long.component_scores.market_regime, 60)
        # Inverse: the three backdrop scores are reflected around 50.
        self.assertEqual(rec_inv.component_scores.macro_risk, 10)
        self.assertEqual(rec_inv.component_scores.cross_market, 30)
        self.assertEqual(rec_inv.component_scores.market_regime, 40)
        # The instrument's own trend/capital are untouched by inversion.
        self.assertEqual(rec_inv.component_scores.trend, rec_long.component_scores.trend)
        self.assertEqual(rec_inv.component_scores.capital_flow, rec_long.component_scores.capital_flow)
        # A risk-on backdrop should now count AGAINST the inverse ETF.
        self.assertLess(rec_inv.total_score, rec_long.total_score)
        self.assertIn("inverse instrument", rec_inv.analyst_hypothesis)


if __name__ == "__main__":
    unittest.main()
