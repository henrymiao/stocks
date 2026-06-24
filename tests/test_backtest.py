import unittest

from tools.stock_skills.backtest import component_edge, run_backtest, summarize_outcomes


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


if __name__ == "__main__":
    unittest.main()
