import unittest

from tools.stock_skills.models import KLineBar
from tools.stock_skills.review import evaluate_recommendation, suggest_weight_adjustments


class ReviewTests(unittest.TestCase):
    def test_review_retains_shadow_method_state_for_calibration(self):
        recommendation = {
            "code": "HK.00700",
            "timestamp": "2026-07-21T16:00:00+08:00",
            "label": "hold",
            "method_assessment": {
                "method_policy": "finance-method-evidence-v1",
                "market_profile_id": "hk-equity-v1",
                "swing_structure": {"stage": "stage-2"},
                "thesis": {"state": "supported"},
                "valuation": {"status": "unavailable"},
                "linkage": {"coverage": 0.5},
                "restrictions": [],
            },
        }
        bars = [
            KLineBar(
                "2026-07-22",
                500.0,
                510.0,
                495.0,
                508.0,
                1_000,
                500_000.0,
            )
        ]

        outcome = evaluate_recommendation(recommendation, 500.0, bars, "1d")

        self.assertEqual(outcome["method_policy"], "finance-method-evidence-v1")
        self.assertEqual(outcome["method_stage"], "stage-2")
        self.assertEqual(outcome["method_restrictions"], [])

    def test_evaluate_recommendation_records_successful_hold(self):
        recommendation = {
            "code": "SZ.002463",
            "label": "hold",
            "timestamp": "2026-06-18T15:00:00+08:00",
            "trade_id": "trade-123",
            "strategy_id": "short-balanced-v1",
            "strategy_version": "v1",
            "horizon": "short",
            "leveraged": False,
            "invalidation_level": 142.8,
            "support_levels": [145.0, 142.8],
            "resistance_levels": [149.9, 150.0],
        }
        future_bars = [
            KLineBar("2026-06-19", 148.0, 151.0, 146.2, 150.8, 90_000_000, 13_000_000_000.0),
            KLineBar("2026-06-22", 150.8, 153.0, 149.5, 152.2, 100_000_000, 15_000_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=147.9, future_bars=future_bars, review_window="3d")

        self.assertEqual(outcome["code"], "SZ.002463")
        self.assertTrue(outcome["directional_success"])
        self.assertFalse(outcome["invalidated"])
        self.assertGreater(outcome["maximum_favorable_pct"], 0)
        self.assertEqual(outcome["trade_id"], "trade-123")
        self.assertEqual(outcome["strategy_id"], "short-balanced-v1")
        self.assertEqual(outcome["evidence_kind"], "realized-ohlc")

    def test_evaluate_recommendation_flags_split_basis_mismatch(self):
        # Reverse split between the call and the fetch: entry recorded at 6.84, bars
        # returned on the post-split basis (~10x). The fake +470% return must be
        # flagged, not blended into realised evidence.
        recommendation = {"code": "US.SOXS", "label": "hold", "timestamp": "2026-06-08T16:00:00-04:00"}
        future_bars = [
            KLineBar("2026-06-09", 68.0, 70.0, 66.0, 69.0, 1_000_000, 68_000_000.0),
            KLineBar("2026-06-10", 69.0, 71.0, 67.0, 70.0, 1_000_000, 69_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=6.84, future_bars=future_bars, review_window="2d")

        self.assertEqual(outcome["evidence_kind"], "basis-mismatch")
        self.assertFalse(outcome["review_complete"])
        self.assertGreater(outcome["basis_ratio"], 2.0)

    def test_evaluate_recommendation_detects_invalidation(self):
        recommendation = {
            "code": "SZ.002463",
            "label": "hold",
            "timestamp": "2026-06-18T15:00:00+08:00",
            "invalidation_level": 142.8,
            "support_levels": [145.0, 142.8],
            "resistance_levels": [149.9, 150.0],
        }
        future_bars = [
            KLineBar("2026-06-19", 147.0, 148.0, 141.9, 142.1, 120_000_000, 16_000_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=147.9, future_bars=future_bars, review_window="1d")

        self.assertFalse(outcome["directional_success"])
        self.assertTrue(outcome["invalidated"])

    def test_evaluate_recommendation_marks_partial_window_incomplete(self):
        recommendation = {
            "code": "SZ.002463",
            "label": "hold",
            "timestamp": "2026-06-18T15:00:00+08:00",
        }
        future_bars = [
            KLineBar("2026-06-19", 147.0, 148.0, 146.0, 147.5, 120_000_000, 16_000_000_000.0),
            KLineBar("2026-06-22", 147.5, 149.0, 147.0, 148.0, 120_000_000, 16_000_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=147.9, future_bars=future_bars, review_window="3d")
        suggestion = suggest_weight_adjustments(
            {"trend": 0.25, "capital_flow": 0.2, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.1},
            [outcome] * 60,
        )

        self.assertEqual(outcome["observed_bar_count"], 2)
        self.assertFalse(outcome["review_complete"])
        self.assertFalse(suggestion["eligible"])
        self.assertEqual(suggestion["sample_size"], 0)

    def test_evaluate_recommendation_uses_only_declared_window_bars(self):
        recommendation = {
            "code": "SZ.002463",
            "label": "hold",
            "timestamp": "2026-06-18T15:00:00+08:00",
        }
        future_bars = [
            KLineBar("2026-06-19", 100.0, 112.0, 99.0, 110.0, 120_000_000, 16_000_000_000.0),
            KLineBar("2026-06-22", 110.0, 111.0, 49.0, 50.0, 120_000_000, 16_000_000_000.0),
            KLineBar("2026-06-23", 50.0, 51.0, 48.0, 49.0, 120_000_000, 16_000_000_000.0),
            KLineBar("2026-06-24", 49.0, 50.0, 47.0, 48.0, 120_000_000, 16_000_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=100.0, future_bars=future_bars, review_window="1d")

        self.assertEqual(outcome["final_close"], 110.0)
        self.assertEqual(outcome["final_return_pct"], 10.0)
        self.assertEqual(outcome["maximum_adverse_pct"], -1.0)

    def test_suggest_weight_adjustments_refuses_small_sample(self):
        current = {"trend": 0.25, "capital_flow": 0.2, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.1}
        reviews = [
            {"directional_success": False, "dominant_failure": "macro_risk", "review_complete": True},
            {"directional_success": False, "dominant_failure": "macro_risk", "review_complete": True},
            {"directional_success": True, "dominant_failure": "none", "review_complete": True},
        ]

        suggestion = suggest_weight_adjustments(current, reviews)

        self.assertEqual(suggestion["weights"], current)
        self.assertFalse(suggestion["eligible"])
        self.assertEqual(suggestion["sample_size"], 3)
        self.assertIn("60", suggestion["notes"][0])

    def test_suggest_weight_adjustments_freezes_legacy_failure_count_changes(self):
        current = {"trend": 0.25, "capital_flow": 0.2, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.1}
        reviews = [
            {"directional_success": False, "dominant_failure": "macro_risk", "review_complete": True}
            for _ in range(40)
        ] + [
            {"directional_success": True, "dominant_failure": "none", "review_complete": True}
            for _ in range(20)
        ]

        suggestion = suggest_weight_adjustments(current, reviews)

        self.assertFalse(suggestion["eligible"])
        self.assertEqual(suggestion["weights"], current)
        self.assertIn("evidence-optimize", suggestion["notes"][0])

    def test_suggest_weight_adjustments_excludes_incomplete_reviews(self):
        current = {"trend": 0.25, "capital_flow": 0.2, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.1}
        reviews = [
            {"directional_success": False, "dominant_failure": "macro_risk", "review_complete": True}
            for _ in range(59)
        ] + [{"directional_success": False, "dominant_failure": "macro_risk", "review_complete": False}]

        suggestion = suggest_weight_adjustments(current, reviews)

        self.assertFalse(suggestion["eligible"])
        self.assertEqual(suggestion["sample_size"], 59)


    def test_failed_bullish_call_is_attributed_to_weakest_component(self):
        recommendation = {
            "code": "SZ.002463",
            "label": "hold",
            "timestamp": "2026-06-18T15:00:00+08:00",
            "invalidation_level": 130.0,
            "component_scores": {
                "trend": 70,
                "capital_flow": 65,
                "sector": 60,
                "cross_market": 40,  # weakest: this warning was overridden
                "macro_risk": 55,
                "position_fit": 75,
            },
        }
        future_bars = [
            KLineBar("2026-06-19", 147.0, 147.5, 143.0, 143.5, 90_000_000, 13_000_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=147.9, future_bars=future_bars, review_window="1d")

        self.assertFalse(outcome["directional_success"])
        self.assertFalse(outcome["invalidated"])
        self.assertEqual(outcome["dominant_failure"], "cross_market")
        self.assertIn("40", outcome["attribution_reason"])

    def test_failure_without_component_scores_uses_fallback(self):
        recommendation = {
            "code": "SZ.002463",
            "label": "hold",
            "timestamp": "2026-06-18T15:00:00+08:00",
            "invalidation_level": 130.0,
        }
        future_bars = [
            KLineBar("2026-06-19", 147.0, 147.5, 143.0, 143.5, 90_000_000, 13_000_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=147.9, future_bars=future_bars, review_window="1d")

        self.assertFalse(outcome["directional_success"])
        self.assertEqual(outcome["dominant_failure"], "macro_risk")


if __name__ == "__main__":
    unittest.main()
