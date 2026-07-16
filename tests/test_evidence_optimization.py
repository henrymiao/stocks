import unittest
from datetime import datetime, timedelta, timezone

from tools.stock_skills.evidence_optimization import build_evidence_report


WEIGHTS = {
    "trend": 0.22,
    "capital_flow": 0.12,
    "sector": 0.15,
    "cross_market": 0.09,
    "macro_risk": 0.09,
    "market_regime": 0.10,
    "fundamental": 0.13,
    "position_fit": 0.10,
}


def _pair(
    index,
    *,
    strategy="short-balanced-v1",
    leveraged=False,
    trade_id=None,
    synthetic=False,
    policy=None,
    clusters=False,
):
    timestamp = (datetime(2026, 1, 1, 16, tzinfo=timezone.utc) + timedelta(days=index)).isoformat()
    winning = index % 3 != 0
    recommendation = {
        "code": "US.SOXL" if leveraged else "US.TEST",
        "timestamp": timestamp,
        "trade_id": trade_id or f"trade-{index}",
        "strategy_id": strategy,
        "strategy_version": "v1",
        "horizon": "short",
        "leveraged": leveraged,
        "schema_version": "recommendation-v4",
        "component_scores": {
            "trend": 80 if winning else 20,
            "capital_flow": 55,
            "sector": 55,
            "cross_market": 50,
            "macro_risk": 50,
            "market_regime": 55,
            "fundamental": 50,
            "position_fit": 60,
        },
        "source_refs": ["offline-synthesized"] if synthetic else ["futu:kline:US.TEST"],
    }
    if policy is not None or clusters:
        assessment = {}
        if policy is not None:
            assessment["decision_policy"] = policy
        if clusters:
            assessment["factor_clusters"] = {
                "thesis": 80 if winning else 20,
                "market_behavior": 55,
                "environment": 50,
                "risk_fit": 60,
            }
        recommendation["strategy_assessment"] = assessment
    review = {
        "code": recommendation["code"],
        "source_timestamp": timestamp,
        "trade_id": recommendation["trade_id"],
        "review_complete": True,
        "evidence_kind": "synthetic" if synthetic else "realized-ohlc",
        "review_window": "3d",
        "final_return_pct": 2.0 if winning else -1.0,
        "directional_success": winning,
    }
    return recommendation, review


class EvidenceOptimizationTests(unittest.TestCase):
    def test_insufficient_strategy_bucket_is_report_only(self):
        pairs = [_pair(index) for index in range(12)]
        report = build_evidence_report(
            [pair[0] for pair in pairs],
            [pair[1] for pair in pairs],
            WEIGHTS,
        )

        bucket = report["buckets"]["short-balanced-v1|legacy|ordinary"]
        self.assertEqual(bucket["closed_trades"], 12)
        self.assertFalse(bucket["directionally_useful"])
        self.assertFalse(bucket["proposal_eligible"])
        self.assertEqual(bucket["walk_forward_folds"], [])

    def test_strategy_and_leverage_are_separate_buckets(self):
        ordinary = [_pair(index) for index in range(5)]
        leveraged = [_pair(index + 5, leveraged=True) for index in range(5)]
        report = build_evidence_report(
            [pair[0] for pair in ordinary + leveraged],
            [pair[1] for pair in ordinary + leveraged],
            WEIGHTS,
        )

        self.assertIn("short-balanced-v1|legacy|ordinary", report["buckets"])
        self.assertIn("short-balanced-v1|legacy|leveraged", report["buckets"])
        self.assertEqual(report["buckets"]["short-balanced-v1|legacy|ordinary"]["closed_trades"], 5)
        self.assertEqual(report["buckets"]["short-balanced-v1|legacy|leveraged"]["closed_trades"], 5)

    def test_synthetic_rows_are_excluded_and_trade_ids_are_deduplicated(self):
        first = _pair(0, trade_id="same-trade")
        duplicate = _pair(1, trade_id="same-trade")
        synthetic = _pair(2, synthetic=True)
        report = build_evidence_report(
            [first[0], duplicate[0], synthetic[0]],
            [first[1], duplicate[1], synthetic[1]],
            WEIGHTS,
        )

        self.assertEqual(report["joined_pairs"], 3)
        self.assertEqual(report["excluded_synthetic"], 1)
        self.assertEqual(report["deduplicated_trades"], 1)
        self.assertEqual(report["eligible_closed_trades"], 1)

    def test_sixty_closed_trades_create_chronological_walk_forward_fold(self):
        pairs = [_pair(index) for index in range(60)]
        report = build_evidence_report(
            [pair[0] for pair in pairs],
            [pair[1] for pair in pairs],
            WEIGHTS,
        )

        bucket = report["buckets"]["short-balanced-v1|legacy|ordinary"]
        self.assertTrue(bucket["directionally_useful"])
        self.assertEqual(len(bucket["walk_forward_folds"]), 1)
        fold = bucket["walk_forward_folds"][0]
        self.assertEqual(fold["train_n"], 40)
        self.assertEqual(fold["test_n"], 20)
        self.assertLess(fold["train_end"], fold["test_start"])
        self.assertIn("baseline", fold["out_of_sample"])
        self.assertIn("candidate", fold["out_of_sample"])
        self.assertTrue(bucket["advisory_only"])

    def test_decision_policy_changes_do_not_share_buckets(self):
        v3 = [_pair(index, policy="logic-first-correlation-aware-v3") for index in range(3)]
        v4 = [_pair(index + 3, policy="logic-first-correlation-aware-v4") for index in range(3)]
        report = build_evidence_report(
            [pair[0] for pair in v3 + v4],
            [pair[1] for pair in v3 + v4],
            WEIGHTS,
        )

        self.assertIn("short-balanced-v1|logic-first-correlation-aware-v3|ordinary", report["buckets"])
        self.assertIn("short-balanced-v1|logic-first-correlation-aware-v4|ordinary", report["buckets"])
        self.assertEqual(
            report["buckets"]["short-balanced-v1|logic-first-correlation-aware-v3|ordinary"]["closed_trades"], 3
        )
        self.assertEqual(
            report["buckets"]["short-balanced-v1|logic-first-correlation-aware-v4|ordinary"]["closed_trades"], 3
        )

    def test_cluster_weight_advisory_runs_on_strategy_track_evidence(self):
        pairs = [_pair(index, clusters=True) for index in range(60)]
        report = build_evidence_report(
            [pair[0] for pair in pairs],
            [pair[1] for pair in pairs],
            WEIGHTS,
        )

        bucket = report["buckets"]["short-balanced-v1|legacy|ordinary"]
        self.assertEqual(len(bucket["cluster_walk_forward_folds"]), 1)
        advisory = bucket["latest_advisory_cluster_weights"]
        self.assertEqual(set(advisory), {"thesis", "market_behavior", "environment", "risk_fit"})
        self.assertTrue(bucket["advisory_only"])
        self.assertEqual(
            bucket["weights_targets"]["cluster_walk_forward_folds"], "strategy-cluster-weights"
        )

    def test_cluster_advisory_skipped_without_stored_clusters(self):
        pairs = [_pair(index) for index in range(60)]
        report = build_evidence_report(
            [pair[0] for pair in pairs],
            [pair[1] for pair in pairs],
            WEIGHTS,
        )

        bucket = report["buckets"]["short-balanced-v1|legacy|ordinary"]
        self.assertEqual(bucket["cluster_walk_forward_folds"], [])
        self.assertIsNone(bucket["latest_advisory_cluster_weights"])
        self.assertFalse(bucket["cluster_proposal_eligible"])
        self.assertTrue(any("factor_clusters" in note for note in bucket["notes"]))


if __name__ == "__main__":
    unittest.main()
