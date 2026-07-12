import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from tools.stock_skills.cli import main
from tools.stock_skills.exit_engine import build_exit_plan
from tools.stock_skills.models import KLineBar
from tools.stock_skills.path_backtest import (
    AddOnRule,
    ExecutionCosts,
    assess_portfolio_heat,
    run_path_backtest,
    simulate_exit_plan,
)


def _bar(day, open_, high, low, close):
    return KLineBar(day, open_, high, low, close, 1_000_000, close * 1_000_000)


def _plan():
    return build_exit_plan(
        100.0,
        95.0,
        4.0,
        risk_budget_pct=1.0,
        stop_buffer_atr=0.25,
    )


class PathSimulationTests(unittest.TestCase):
    def test_profitable_add_on_uses_completed_close_without_increasing_open_risk(self):
        result = simulate_exit_plan(
            _plan(),
            [
                _bar("d1", 100, 104, 99, 104),
                _bar("d2", 104, 110, 103, 110),
            ],
            add_ons=[AddOnRule(trigger_r=0.5, fraction=0.25, stop_after_add=100.0)],
        )

        self.assertEqual(len(result.add_ons), 1)
        self.assertEqual(result.add_ons[0].bar_time, "d1")
        self.assertLessEqual(result.add_ons[0].open_risk_r, 1.0)
        self.assertAlmostEqual(result.realized_r, 1.75, places=4)
        self.assertLessEqual(result.mfe_capture_ratio, 1.0)

    def test_add_on_is_rejected_when_raised_stop_still_increases_risk(self):
        with self.assertRaisesRegex(ValueError, "increase open risk"):
            simulate_exit_plan(
                _plan(),
                [_bar("d1", 100, 104, 99, 104), _bar("d2", 104, 110, 103, 110)],
                add_ons=[AddOnRule(trigger_r=0.5, fraction=0.25, stop_after_add=94.0)],
            )
    def test_same_bar_stop_and_target_uses_conservative_stop_first(self):
        result = simulate_exit_plan(_plan(), [_bar("d1", 100, 107, 93, 105)])

        self.assertEqual(result.exit_reason, "initial-stop")
        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].price, 94.0)
        self.assertEqual(result.realized_r, -1.0)

    def test_gap_through_stop_fills_at_open(self):
        result = simulate_exit_plan(_plan(), [_bar("d1", 90, 95, 88, 92)])

        self.assertEqual(result.exit_reason, "gap-stop")
        self.assertEqual(result.fills[0].price, 90.0)
        self.assertAlmostEqual(result.realized_r, -1.6667, places=4)

    def test_first_partial_then_initial_stop_weights_realized_r(self):
        result = simulate_exit_plan(
            _plan(),
            [
                _bar("d1", 100, 107, 99, 106),
                _bar("d2", 105, 106, 93, 94),
            ],
        )

        self.assertEqual([fill.reason for fill in result.fills], ["tp1", "initial-stop"])
        self.assertAlmostEqual(result.realized_r, -0.5, places=4)

    def test_both_partials_then_runner_trailing_exit(self):
        result = simulate_exit_plan(
            _plan(),
            [
                _bar("d1", 100, 107, 99, 106),
                _bar("d2", 106, 112, 105, 111),
                _bar("d3", 110, 113, 104, 105),
            ],
        )

        self.assertEqual([fill.reason for fill in result.fills], ["tp1", "tp2", "trailing-stop"])
        self.assertEqual(result.fills[-1].price, 105.0)
        self.assertAlmostEqual(result.realized_r, 1.1167, places=4)
        self.assertEqual(result.exit_reason, "trailing-stop")

    def test_time_stop_exits_when_progress_is_insufficient(self):
        result = simulate_exit_plan(
            _plan(),
            [
                _bar("d1", 100, 102, 99, 101),
                _bar("d2", 101, 102, 100, 101),
            ],
        )

        self.assertEqual(result.exit_reason, "time-stop")
        self.assertEqual(result.fills[-1].price, 101.0)
        self.assertAlmostEqual(result.realized_r, 0.1667, places=4)

    def test_execution_costs_reduce_realized_r(self):
        bars = [_bar("d1", 100, 107, 99, 106), _bar("d2", 105, 106, 93, 94)]
        free = simulate_exit_plan(_plan(), bars)
        costly = simulate_exit_plan(
            _plan(), bars,
            costs=ExecutionCosts(commission_bps=5, spread_bps=10, slippage_bps=10),
        )

        self.assertLess(costly.realized_r, free.realized_r)
        self.assertGreater(costly.total_cost, 0)

    def test_leveraged_default_costs_are_more_conservative(self):
        bars = [_bar("d1", 100, 107, 99, 106), _bar("d2", 105, 106, 93, 94)]
        ordinary = simulate_exit_plan(_plan(), bars)
        leveraged = simulate_exit_plan(_plan(), bars, leveraged=True)

        self.assertLess(leveraged.realized_r, ordinary.realized_r)
        self.assertGreater(leveraged.total_cost, ordinary.total_cost)


class PortfolioHeatTests(unittest.TestCase):
    def test_exact_heat_boundary_is_allowed(self):
        decision = assess_portfolio_heat(
            proposed_risk_pct=2.0,
            portfolio_open_risk_pct=4.0,
            theme_open_risk_pct=1.0,
        )
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.scaled)
        self.assertEqual(decision.allowed_risk_pct, 2.0)

    def test_heat_scales_to_remaining_headroom(self):
        decision = assess_portfolio_heat(
            proposed_risk_pct=2.0,
            portfolio_open_risk_pct=5.0,
            theme_open_risk_pct=2.5,
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.scaled)
        self.assertEqual(decision.allowed_risk_pct, 0.5)

    def test_exhausted_heat_rejects_trade(self):
        decision = assess_portfolio_heat(
            proposed_risk_pct=1.0,
            portfolio_open_risk_pct=6.0,
            theme_open_risk_pct=1.0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.allowed_risk_pct, 0.0)


class PathAggregateTests(unittest.TestCase):
    def test_repeated_trade_id_is_not_counted_as_an_independent_trade(self):
        scenario = {"trade_id": "trade-1", "exit_plan": _plan(), "bars": [_bar("d1", 100, 101, 93, 94)]}

        report = run_path_backtest([scenario, dict(scenario)])

        self.assertEqual(report["summary"]["trades"], 1)
        self.assertEqual(report["deduplicated_trades"], 1)

    def test_report_contains_r_metrics_drawdown_and_capture(self):
        winning = {
            "exit_plan": _plan(),
            "bars": [
                _bar("d1", 100, 107, 99, 106),
                _bar("d2", 106, 112, 105, 111),
                _bar("d3", 110, 113, 104, 105),
            ],
        }
        losing = {"exit_plan": _plan(), "bars": [_bar("d1", 100, 101, 93, 94)]}

        report = run_path_backtest([winning, losing])

        self.assertEqual(report["summary"]["trades"], 2)
        self.assertEqual(report["summary"]["win_rate"], 0.5)
        self.assertIn("expectancy_r", report["summary"])
        self.assertIn("profit_factor", report["summary"])
        self.assertIn("maximum_drawdown_r", report["summary"])
        self.assertIn("mfe_capture_ratio", report["summary"])

    def test_cli_replays_serialized_scenarios(self):
        scenario = {
            "trades": [
                {
                    "exit_plan": asdict(_plan()),
                    "bars": [asdict(_bar("d1", 100, 101, 93, 94))],
                    "costs": {"commission_bps": 1, "spread_bps": 2, "slippage_bps": 2},
                    "add_ons": [{"trigger_r": 0.5, "fraction": 0.25, "stop_after_add": 100.0}],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "scenario.json"
            output = Path(tmpdir) / "report.json"
            source.write_text(json.dumps(scenario), encoding="utf-8")

            exit_code = main(["path-backtest", "--scenario", str(source), "--output", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["summary"]["trades"], 1)
        self.assertEqual(report["trades"][0]["exit_reason"], "initial-stop")
        self.assertEqual(report["trades"][0]["add_ons"], [])


if __name__ == "__main__":
    unittest.main()
