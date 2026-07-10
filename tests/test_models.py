import json
import unittest

from tools.stock_skills.models import (
    CapitalSnapshot,
    ComponentScores,
    DataQuality,
    InstrumentState,
    KLineBar,
    MarketSnapshot,
    Recommendation,
)


class ModelTests(unittest.TestCase):
    def test_recommendation_serializes_to_json_ready_dict(self):
        recommendation_fields = dict(
            code="SZ.002463",
            name="沪电股份",
            timestamp="2026-06-18T15:00:00+08:00",
            label="hold",
            total_score=67.4,
            component_scores=ComponentScores(
                trend=70,
                capital_flow=58,
                sector=65,
                cross_market=60,
                macro_risk=55,
                position_fit=75,
            ),
            analyst_hypothesis="AI PCB demand remains the core thesis.",
            trader_plan="Hold above 145; trim failed pushes near 150.",
            support_levels=[145.0, 142.8],
            resistance_levels=[149.9, 150.0],
            invalidation_level=142.8,
            confidence=0.62,
            source_refs=["data/snapshots/SZ.002463.json"],
            user_context={"last_trim_price": 149.5},
        )
        recommendation = Recommendation(
            **recommendation_fields,
            data_quality=DataQuality(
                confidence=0.875,
                available_components=(
                    "trend",
                    "capital_flow",
                    "sector",
                    "cross_market",
                    "macro_risk",
                    "market_regime",
                    "fundamental",
                ),
                missing_components=("position_fit",),
                stale_components=(),
                session_phase="intraday",
                entry_eligible=False,
            ),
        )

        payload = recommendation.to_record()

        self.assertEqual(payload["code"], "SZ.002463")
        self.assertEqual(payload["component_scores"]["trend"], 70)
        self.assertEqual(payload["data_quality"]["confidence"], 0.875)
        self.assertEqual(
            list(payload["data_quality"]["missing_components"]),
            ["position_fit"],
        )
        self.assertEqual(payload["support_levels"], [145.0, 142.8])
        self.assertEqual(payload["user_context"]["last_trim_price"], 149.5)
        json.dumps(payload)

        compatibility_payload = Recommendation(**recommendation_fields).to_record()
        self.assertIsNone(compatibility_payload["data_quality"])

    def test_recommendation_preserves_pre_data_quality_positional_order(self):
        recommendation = Recommendation(
            "SZ.002463",
            "沪电股份",
            "2026-06-18T15:00:00+08:00",
            "hold",
            67.4,
            ComponentScores(70, 58, 65, 60, 55, 75),
            "AI PCB demand remains the core thesis.",
            "Hold above 145; trim failed pushes near 150.",
            [145.0, 142.8],
            [149.9, 150.0],
            142.8,
            0.62,
            ["data/snapshots/SZ.002463.json"],
            147.9,
            {"last_trim_price": 149.5},
        )

        self.assertEqual(recommendation.entry_price, 147.9)
        self.assertEqual(recommendation.user_context, {"last_trim_price": 149.5})
        self.assertIsNone(recommendation.data_quality)

    def test_instrument_state_accepts_snapshot_bars_and_capital(self):
        state = InstrumentState(
            snapshot=MarketSnapshot(
                code="SZ.002463",
                name="沪电股份",
                last_price=147.9,
                open=146.0,
                high=149.36,
                low=142.81,
                prev_close=146.55,
                volume=83679015,
                turnover=12271729868.41,
                timestamp="2026-06-18T15:00:00+08:00",
            ),
            daily_bars=[
                KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99154170, 14460550533.78),
                KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83679015, 12271729868.41),
            ],
            intraday_bars=[],
            capital=CapitalSnapshot(
                net_inflow=24492584.5,
                super_inflow=744236606.14,
                big_inflow=-411741404.48,
                mid_inflow=-210842830.36,
                small_inflow=-97159786.8,
                timestamp="2026-06-18T15:00:00+08:00",
            ),
        )

        self.assertEqual(state.snapshot.code, "SZ.002463")
        self.assertEqual(len(state.daily_bars), 2)
        self.assertGreater(state.capital.super_inflow, 0)


if __name__ == "__main__":
    unittest.main()
