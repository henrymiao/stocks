import math
import unittest

from tools.stock_skills.exit_engine import (
    build_exit_plan,
    next_trailing_stop,
)


class ExitPlanTests(unittest.TestCase):
    def test_builds_structural_stop_targets_and_runner(self):
        plan = build_exit_plan(
            entry_price=100.0,
            structural_invalidation=95.0,
            atr=4.0,
            risk_budget_pct=1.0,
            stop_buffer_atr=0.25,
            target_specs=(("tp1", 1.0, 0.25), ("tp2", 1.8, 0.25)),
        )

        self.assertEqual(plan.initial_stop, 94.0)
        self.assertEqual(plan.risk_per_share, 6.0)
        self.assertEqual(plan.targets[0].price, 106.0)
        self.assertEqual(plan.targets[1].price, 110.8)
        self.assertEqual(plan.runner_fraction, 0.5)
        self.assertEqual(plan.risk_sizing.suggested_size_pct, 16.67)
        self.assertFalse(plan.risk_sizing.capped)

    def test_wider_structural_stop_reduces_size_instead_of_tightening_stop(self):
        narrow = build_exit_plan(100.0, 97.0, 2.0, risk_budget_pct=1.0)
        wide = build_exit_plan(100.0, 88.0, 4.0, risk_budget_pct=1.0)

        self.assertLess(wide.initial_stop, narrow.initial_stop)
        self.assertLess(wide.risk_sizing.suggested_size_pct, narrow.risk_sizing.suggested_size_pct)

    def test_tiny_stop_is_capped_for_ordinary_and_leveraged_instruments(self):
        ordinary = build_exit_plan(
            100.0, 99.5, 1.0, risk_budget_pct=2.0, stop_buffer_atr=0.0,
        )
        leveraged = build_exit_plan(
            100.0, 99.5, 1.0, risk_budget_pct=1.25, stop_buffer_atr=0.0,
            leveraged=True,
        )

        self.assertEqual(ordinary.risk_sizing.uncapped_size_pct, 400.0)
        self.assertEqual(ordinary.risk_sizing.suggested_size_pct, 25.0)
        self.assertTrue(ordinary.risk_sizing.capped)
        self.assertEqual(leveraged.risk_sizing.suggested_size_pct, 15.0)
        self.assertTrue(leveraged.risk_sizing.capped)

    def test_rejects_missing_or_invalid_stop_inputs(self):
        invalid = (
            dict(entry_price=0.0, structural_invalidation=95.0, atr=4.0),
            dict(entry_price=100.0, structural_invalidation=None, atr=4.0),
            dict(entry_price=100.0, structural_invalidation=100.0, atr=4.0),
            dict(entry_price=100.0, structural_invalidation=95.0, atr=None),
            dict(entry_price=100.0, structural_invalidation=95.0, atr=0.0),
            dict(entry_price=100.0, structural_invalidation=1.0, atr=10.0, stop_buffer_atr=1.0),
        )

        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_exit_plan(**kwargs)

    def test_rejects_invalid_target_specs_and_risk_budgets(self):
        invalid_specs = (
            (("tp1", 0.0, 0.25), ("tp2", 1.8, 0.25)),
            (("tp1", 1.0, 0.25), ("tp2", 1.0, 0.25)),
            (("tp1", 1.0, 0.75), ("tp2", 1.8, 0.50)),
        )
        for specs in invalid_specs:
            with self.subTest(specs=specs), self.assertRaises(ValueError):
                build_exit_plan(100.0, 95.0, 4.0, target_specs=specs)

        for risk in (True, 0.0, -1.0, math.inf, math.nan, 2.01):
            with self.subTest(risk=risk), self.assertRaises(ValueError):
                build_exit_plan(100.0, 95.0, 4.0, risk_budget_pct=risk)

        with self.assertRaises(ValueError):
            build_exit_plan(100.0, 95.0, 4.0, risk_budget_pct=1.26, leveraged=True)

    def test_rejects_invalid_trailing_and_time_rules(self):
        with self.assertRaises(ValueError):
            build_exit_plan(100.0, 95.0, 4.0, trailing_method="widen-at-will")
        for sessions in (True, 0, -1):
            with self.subTest(sessions=sessions), self.assertRaises(ValueError):
                build_exit_plan(100.0, 95.0, 4.0, time_stop_sessions=sessions)
        for days in (True, 0, -1):
            with self.subTest(days=days), self.assertRaises(ValueError):
                build_exit_plan(100.0, 95.0, 4.0, maximum_holding_days=days)

    def test_inverse_etf_keeps_long_execution_geometry(self):
        plan = build_exit_plan(
            10.0, 9.5, 0.2, risk_budget_pct=1.0, leveraged=True,
        )
        self.assertLess(plan.initial_stop, plan.entry_price)
        self.assertTrue(all(target.price > plan.entry_price for target in plan.targets))


class TrailingStopTests(unittest.TestCase):
    def test_two_bar_or_atr_trailing_stop_is_monotonic(self):
        first = next_trailing_stop(
            previous_stop=None,
            prior_two_bar_low=107.0,
            highest_close=112.0,
            atr=2.0,
            atr_multiple=1.5,
        )
        unchanged = next_trailing_stop(
            previous_stop=first,
            prior_two_bar_low=106.0,
            highest_close=111.0,
            atr=2.0,
            atr_multiple=1.5,
        )
        raised = next_trailing_stop(
            previous_stop=first,
            prior_two_bar_low=111.0,
            highest_close=113.0,
            atr=1.0,
            atr_multiple=1.5,
        )

        self.assertEqual(first, 109.0)
        self.assertEqual(unchanged, 109.0)
        self.assertEqual(raised, 111.5)


if __name__ == "__main__":
    unittest.main()
