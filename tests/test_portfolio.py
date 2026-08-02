import unittest

from tools.stock_skills.models import KLineBar
from tools.stock_skills.portfolio import (
    Candidate,
    allocate_budget,
    Holding,
    rank_candidates,
    theme_exposure,
    worst_correlation,
)


def _bars(changes, start=100.0):
    """Build a bar series from a list of daily percentage changes."""
    price = start
    out = []
    for index, change in enumerate(changes):
        price = price * (1 + change)
        out.append(KLineBar(f"d{index:03d}", price, price, price, price, 1_000, 1_000.0))
    return out


# One driver, two instruments that follow it, one that moves independently.
_DRIVER = [0.02, -0.01, 0.03, -0.02, 0.01, 0.015, -0.025, 0.005, 0.02, -0.01,
           0.01, -0.005, 0.02, -0.015, 0.01, 0.02, -0.02, 0.005, 0.01, -0.01,
           0.015, -0.01, 0.02, -0.005, 0.01]
_INDEPENDENT = [-0.01, 0.02, -0.005, 0.01, -0.02, 0.005, 0.01, -0.015, -0.01, 0.02,
                -0.02, 0.01, -0.005, 0.02, -0.01, -0.015, 0.01, 0.02, -0.02, 0.005,
                -0.01, 0.015, -0.02, 0.01, -0.005]


class ThemeExposureTests(unittest.TestCase):
    def test_theme_exposure_aggregates_holdings(self):
        holdings = [
            Holding("HK.00522", 7.56, "semiconductor"),
            Holding("SH.601138", 7.51, "semiconductor"),
            Holding("HK.00700", 34.72, "china-internet"),
        ]

        exposure = theme_exposure(holdings, total_value=260.9)

        self.assertAlmostEqual(exposure["semiconductor"], 5.77, places=1)
        self.assertAlmostEqual(exposure["china-internet"], 13.31, places=1)

    def test_zero_book_yields_no_exposure(self):
        self.assertEqual(theme_exposure([Holding("X", 1.0, "t")], total_value=0.0), {})


class CorrelationTests(unittest.TestCase):
    def test_worst_correlation_finds_the_duplicated_holding(self):
        candidate = _bars(_DRIVER)
        holdings = {"DUPLICATE": _bars(_DRIVER), "OTHER": _bars(_INDEPENDENT)}

        correlation, code = worst_correlation(candidate, holdings)

        self.assertEqual(code, "DUPLICATE")
        self.assertGreater(correlation, 0.9)

    def test_no_correlation_without_enough_overlap(self):
        correlation, code = worst_correlation(_bars(_DRIVER[:5]), {"X": _bars(_DRIVER[:5])})

        self.assertIsNone(correlation)
        self.assertIsNone(code)


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.holdings = [Holding("HELD", 20.0, "semiconductor")]
        self.total = 100.0

    def test_a_duplicate_is_demoted_below_a_weaker_but_independent_name(self):
        candidates = [
            Candidate("DUPLICATE", setup_score=70.0, suggested_allocation_pct=3.0, risk_per_share_pct=10.0),
            Candidate("INDEPENDENT", setup_score=62.0, suggested_allocation_pct=3.0, risk_per_share_pct=10.0),
        ]
        bars = {"DUPLICATE": _bars(_DRIVER), "INDEPENDENT": _bars(_INDEPENDENT)}

        ranked = rank_candidates(
            candidates,
            self.holdings,
            total_value=self.total,
            open_risk_budget_pct=6.0,
            open_risk_used_pct=0.0,
            candidate_bars=bars,
            holding_bars={"HELD": _bars(_DRIVER)},
        )

        # Raw evidence favours DUPLICATE (70 > 62); after the correlation discount
        # the independent name wins, which is the whole point of the module.
        self.assertEqual(ranked[0].code, "INDEPENDENT")
        self.assertGreater(ranked[1].correlation_penalty, 0.0)
        self.assertLess(ranked[1].adjusted_score, 70.0)

    def test_risk_budget_caps_the_affordable_size(self):
        # 0.5% of budget left; a position risking 10% of itself can only be 5% of the book.
        candidates = [Candidate("X", setup_score=80.0, suggested_allocation_pct=20.0, risk_per_share_pct=10.0)]

        ranked = rank_candidates(
            candidates,
            self.holdings,
            total_value=self.total,
            open_risk_budget_pct=6.0,
            open_risk_used_pct=5.5,
        )

        self.assertEqual(ranked[0].binding_constraint, "risk-budget")
        self.assertAlmostEqual(ranked[0].affordable_pct, 5.0, places=2)
        self.assertTrue(ranked[0].fundable)

    def test_an_exhausted_budget_leaves_nothing_fundable(self):
        candidates = [Candidate("X", setup_score=90.0, suggested_allocation_pct=5.0, risk_per_share_pct=10.0)]

        ranked = rank_candidates(
            candidates,
            self.holdings,
            total_value=self.total,
            open_risk_budget_pct=6.0,
            open_risk_used_pct=6.0,
        )

        self.assertEqual(ranked[0].affordable_pct, 0.0)
        self.assertFalse(ranked[0].fundable)

    def test_theme_exposure_after_purchase_is_reported(self):
        candidates = [
            Candidate("X", setup_score=70.0, suggested_allocation_pct=5.0,
                      risk_per_share_pct=10.0, theme="semiconductor"),
        ]

        ranked = rank_candidates(
            candidates,
            self.holdings,
            total_value=self.total,
            open_risk_budget_pct=6.0,
            open_risk_used_pct=0.0,
        )

        # 20% held + 5% added = 25% of the book in one theme; must be flagged.
        self.assertEqual(ranked[0].theme_exposure_after_pct, 25.0)
        self.assertTrue(any("semiconductor" in note for note in ranked[0].notes))

    def test_fundable_candidates_outrank_unfundable_stronger_ones(self):
        candidates = [
            Candidate("STRONG_UNFUNDABLE", setup_score=90.0, suggested_allocation_pct=5.0, risk_per_share_pct=0.0),
            Candidate("WEAK_FUNDABLE", setup_score=60.0, suggested_allocation_pct=5.0, risk_per_share_pct=10.0),
        ]

        ranked = rank_candidates(
            candidates,
            self.holdings,
            total_value=self.total,
            open_risk_budget_pct=6.0,
            open_risk_used_pct=0.0,
        )

        self.assertEqual(ranked[0].code, "WEAK_FUNDABLE")



class AllocationTests(unittest.TestCase):
    """The budget is shared, so affordability has to be decided sequentially."""

    def _ranked(self, candidates, budget_used=0.0):
        return rank_candidates(
            candidates,
            [Holding("HELD", 20.0, "t")],
            total_value=100.0,
            open_risk_budget_pct=6.0,
            open_risk_used_pct=budget_used,
        )

    def test_budget_is_spent_down_the_ranked_list(self):
        candidates = [
            Candidate("A", setup_score=80.0, suggested_allocation_pct=5.0, risk_per_share_pct=10.0),
            Candidate("B", setup_score=70.0, suggested_allocation_pct=5.0, risk_per_share_pct=10.0),
            Candidate("C", setup_score=60.0, suggested_allocation_pct=5.0, risk_per_share_pct=10.0),
        ]
        ranked = self._ranked(candidates, budget_used=5.2)   # 0.8% left
        allocations = allocate_budget(ranked, candidates, remaining_budget_pct=0.8)

        # A takes 5% * 10% = 0.5%, leaving 0.3% — enough for B at a reduced 3%.
        self.assertEqual(allocations[0].weight_pct, 5.0)
        self.assertEqual(allocations[0].reason, "funded in full")
        self.assertEqual(allocations[1].weight_pct, 3.0)
        self.assertEqual(allocations[1].reason, "partially funded by remaining budget")
        self.assertFalse(allocations[2].funded)
        self.assertEqual(allocations[2].reason, "risk budget exhausted")

    def test_cumulative_heat_never_exceeds_the_budget(self):
        candidates = [
            Candidate(code, setup_score=70.0, suggested_allocation_pct=4.0, risk_per_share_pct=8.0)
            for code in ("A", "B", "C", "D")
        ]
        ranked = self._ranked(candidates, budget_used=5.5)
        allocations = allocate_budget(ranked, candidates, remaining_budget_pct=0.5)

        self.assertLessEqual(max(a.cumulative_heat_pct for a in allocations), 0.5 + 1e-9)

if __name__ == "__main__":
    unittest.main()
