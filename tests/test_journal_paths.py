import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.journal_paths import forward_bars, scenarios_from_journal
from tools.stock_skills.models import KLineBar
from tools.stock_skills.store import MarketStore


def _bar(day, close):
    return KLineBar(
        time=f"2026-07-{day:02d}", open=close, high=close + 1.0, low=close - 1.0,
        close=close, volume=1_000_000, turnover=close * 1_000_000,
    )


def _plan(**overrides):
    plan = {
        "strategy_id": "swing-balanced-v1", "side": "long", "entry_price": 100.0,
        "structural_invalidation": 90.0, "initial_stop": 92.0, "risk_per_share": 8.0,
        "atr": 4.0, "risk_budget_pct": 1.0,
        "targets": [{"name": "tp1", "r_multiple": 1.5, "price": 112.0, "fraction": 0.4}],
        "runner_fraction": 0.6,
        "trailing_rule": {"method": "two-bar-low-or-atr", "activation_r": 1.0,
                          "atr_multiple": 2.0, "current_stop": None},
        "time_stop": {"progress_r": 0.5, "sessions": 5, "action": "full-exit"},
        "maximum_holding_days": 20, "gap_handling": "exit-at-first-available-price-if-gap-through-stop",
        "event_handling": "reassess-or-exit-before-unmodelled-major-event",
        "risk_sizing": {"planned_risk_pct": 1.0, "stop_distance_pct": 8.0,
                        "suggested_size_pct": 12.5, "uncapped_size_pct": 12.5,
                        "allocation_cap_pct": 25.0, "capped": False},
    }
    plan.update(overrides)
    return plan


class JournalPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self._tmp.name) / "market.db")
        self.store.upsert_bars("A", "1d", [_bar(d, 100.0 + d) for d in range(1, 15)])

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_the_entry_session_itself_is_never_replayed(self):
        # The call was made from that session's data; settling on it would trade a bar the
        # recommendation had already seen.
        bars = forward_bars(self.store, "A", "2026-07-05", 20)
        self.assertTrue(bars)
        self.assertEqual(min(bar.time for bar in bars), "2026-07-06")

    def test_a_recommendation_without_an_exit_plan_is_reported_not_dropped(self):
        payload, report = scenarios_from_journal(
            [{"code": "A", "timestamp": "2026-07-05T15:00:00+08:00"}], self.store
        )
        self.assertEqual(payload["trades"], [])
        self.assertEqual(report["skipped"], {"no-exit-plan": 1})

    def test_the_same_position_re_journalled_the_same_day_is_replayed_once(self):
        rec = {"code": "A", "timestamp": "2026-07-05T15:00:00+08:00", "exit_plan": _plan()}
        payload, report = scenarios_from_journal([rec, dict(rec)], self.store)
        self.assertEqual(len(payload["trades"]), 1)
        self.assertEqual(report["skipped"], {"duplicate-entry-session": 1})

    def test_the_payload_survives_the_scenario_validator_unchanged(self):
        from tools.stock_skills.path_backtest import run_path_backtest, scenarios_from_record

        payload, report = scenarios_from_journal(
            [{"code": "A", "timestamp": "2026-07-02T15:00:00+08:00",
              "exit_plan": _plan(), "trade_id": "a-1"}],
            self.store,
        )
        self.assertEqual(report["replayed"], 1)
        result = run_path_backtest(scenarios_from_record(payload))
        self.assertEqual(result["summary"]["trades"], 1)

    def test_holding_horizon_caps_the_bars_handed_to_the_replay(self):
        payload, _ = scenarios_from_journal(
            [{"code": "A", "timestamp": "2026-07-01T15:00:00+08:00",
              "exit_plan": _plan(maximum_holding_days=3)}],
            self.store,
        )
        self.assertEqual(len(payload["trades"][0]["bars"]), 3)


if __name__ == "__main__":
    unittest.main()
