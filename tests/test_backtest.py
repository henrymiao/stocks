import unittest

from tools.stock_skills.backtest import (
    component_edge,
    independent_reviews,
    run_backtest,
    summarize_outcomes,
)


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.reviews = [
            {"code": "A", "source_timestamp": "t1", "label": "hold", "final_return_pct": 5.0,
             "directional_success": True, "maximum_favorable_pct": 7.0, "maximum_adverse_pct": -1.0, "invalidated": False},
            {"code": "A", "source_timestamp": "t2", "label": "hold", "final_return_pct": -3.0,
             "directional_success": False, "maximum_favorable_pct": 1.0, "maximum_adverse_pct": -4.0, "invalidated": True},
            {"code": "B", "source_timestamp": "t3", "label": "avoid", "final_return_pct": -2.0,
             "directional_success": True, "maximum_favorable_pct": 0.5, "maximum_adverse_pct": -3.0, "invalidated": False},
        ]
        self.recommendations = [
            {"code": "A", "timestamp": "t1", "component_scores": {"trend": 80, "macro_risk": 40}},
            {"code": "A", "timestamp": "t2", "component_scores": {"trend": 30, "macro_risk": 60}},
        ]

    def test_summarize_outcomes_computes_win_rate_and_expectancy(self):
        summary = summarize_outcomes(self.reviews)

        self.assertEqual(summary["reviewed"], 3)
        self.assertEqual(summary["wins"], 2)
        self.assertEqual(summary["losses"], 1)
        self.assertEqual(summary["invalidated"], 1)
        self.assertEqual(summary["win_rate"], round(2 / 3, 4))
        self.assertEqual(summary["avg_return_pct"], 0.0)  # raw mean(5, -3, -2)
        # Direction-aware: the 'avoid' winner (price -2%) counts as +2% P&L.
        self.assertEqual(summary["avg_win_pct"], 3.5)     # mean(+5, +2)
        self.assertEqual(summary["avg_loss_pct"], -3.0)
        self.assertEqual(summary["expectancy_pct"], round(4 / 3, 4))  # mean(+5, -3, +2)
        self.assertIn("hold", summary["by_label"])
        self.assertEqual(summary["by_label"]["hold"]["n"], 2)
        self.assertEqual(summary["by_code"]["A"]["n"], 2)

    def test_summarize_handles_empty(self):
        self.assertEqual(summarize_outcomes([])["reviewed"], 0)

    def test_component_edge_flags_predictive_and_antipredictive_factors(self):
        edge = component_edge(self.recommendations, self.reviews)

        self.assertEqual(edge["joined"], 2)
        # trend was high before the winner and low before the loser → perfect edge.
        self.assertEqual(edge["components"]["trend"]["edge"], 1.0)
        # macro_risk pointed the wrong way → negative edge (it was not earning its weight here).
        self.assertEqual(edge["components"]["macro_risk"]["edge"], -1.0)

    def test_run_backtest_bundles_both_sections(self):
        report = run_backtest(self.recommendations, self.reviews)
        self.assertIn("summary", report)
        self.assertIn("component_edge", report)

    def test_synthetic_backfill_is_separated_from_realized_stats(self):
        excluded = [
            {"code": "C", "source_timestamp": "t9", "label": "hold", "final_return_pct": -8.0,
             "directional_success": False, "review_window": "md-3pt", "invalidated": False},
            {"code": "D", "source_timestamp": "t8", "label": "hold", "final_return_pct": 4.0,
             "directional_success": True, "evidence_kind": "synthetic", "review_window": "5d", "invalidated": False},
            # Split-basis mismatch: a fake +470% that must never enter the stats.
            {"code": "A", "source_timestamp": "t1", "label": "hold", "final_return_pct": 470.9,
             "directional_success": True, "evidence_kind": "basis-mismatch", "review_window": "5d", "invalidated": False},
        ]

        summary = summarize_outcomes(self.reviews + excluded)
        # Realised stats are identical to an exclusion-free run...
        self.assertEqual(summary["reviewed"], 3)
        self.assertEqual(summary["win_rate"], round(2 / 3, 4))
        # ...while the backfill is counted and summarised on the side.
        self.assertEqual(summary["synthetic_excluded"], 2)
        self.assertEqual(summary["synthetic_summary"]["reviewed"], 2)
        self.assertEqual(summary["basis_mismatch_excluded"], 1)

        edge = component_edge(self.recommendations, self.reviews + excluded)
        self.assertEqual(edge["joined"], 2)
        self.assertEqual(edge["synthetic_excluded"], 2)
        self.assertEqual(edge["basis_mismatch_excluded"], 1)


if __name__ == "__main__":
    unittest.main()


class IndependentSampleTests(unittest.TestCase):
    """Daily reviewing counts one price path many times over.

    On 2026-08-07 the journal held 95 realised rows from 29 codes, with 36 adjacent pairs
    closer together than the 5-day window is long -- three CRCL rows on a single day. The
    headline `reviewed` therefore claimed a sample size the evidence did not support.
    """

    def _review(self, code, day, ret, win, window="5d"):
        return {
            "code": code,
            "source_timestamp": f"2026-07-{day:02d}T15:00:00+08:00",
            "review_window": window,
            "label": "hold",
            "final_return_pct": ret,
            "directional_success": win,
            "maximum_favorable_pct": abs(ret),
            "maximum_adverse_pct": -abs(ret),
            "invalidated": False,
            "evidence_kind": "realized-ohlc",
        }

    def test_windows_that_overlap_are_counted_once(self):
        reviews = [
            self._review("A", 1, 5.0, True),
            self._review("A", 2, 5.0, True),   # 1 day later, 5d window: overlaps
            self._review("A", 3, 5.0, True),   # overlaps too
        ]
        self.assertEqual(len(independent_reviews(reviews)), 1)

    def test_a_gap_wider_than_the_window_keeps_both(self):
        reviews = [self._review("A", 1, 5.0, True), self._review("A", 15, -2.0, False)]
        kept = independent_reviews(reviews)
        self.assertEqual([r["source_timestamp"][8:10] for r in kept], ["01", "15"])

    def test_different_instruments_never_crowd_each_other_out(self):
        reviews = [self._review("A", 1, 5.0, True), self._review("B", 1, 5.0, True)]
        self.assertEqual(len(independent_reviews(reviews)), 2)

    def test_the_summary_reports_the_independent_sample_alongside_the_raw_one(self):
        reviews = [
            self._review("A", 1, 5.0, True),
            self._review("A", 2, 5.0, True),
            self._review("A", 3, 5.0, True),
        ]
        summary = summarize_outcomes(reviews)
        self.assertEqual(summary["reviewed"], 3)
        self.assertEqual(summary["independent"]["reviewed"], 1)
        self.assertEqual(summary["independent"]["overlapping_dropped"], 2)

    def test_a_row_without_a_known_window_is_not_silently_counted_as_independent(self):
        reviews = [self._review("A", 1, 5.0, True, window="md-backfill")]
        self.assertEqual(independent_reviews(reviews), [])
