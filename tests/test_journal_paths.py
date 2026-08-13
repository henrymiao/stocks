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
        # A same-day repeat is now caught by the broader non-overlapping rule.
        self.assertEqual(report["skipped"], {"overlapping-holding-window": 1})

    def test_a_held_position_re_journalled_on_a_later_session_is_not_replayed_twice(self):
        """The same price path must not be weighted once per session it was reviewed.

        Keying on the entry date alone dropped only same-day repeats, so a position
        re-journalled while still held was replayed again over an overlapping window at a
        later entry price -- `baba-09988-20260718` went in three times at 112.6, 116.8 and
        125.2. Whichever position was reviewed most often then dominated expectancy.
        """

        recs = [
            {"code": "A", "timestamp": f"2026-07-{d:02d}T15:00:00+08:00", "exit_plan": _plan()}
            for d in (2, 3, 6)
        ]
        payload, report = scenarios_from_journal(recs, self.store)

        self.assertEqual(len(payload["trades"]), 1)
        self.assertEqual(report["skipped"], {"overlapping-holding-window": 2})
        # The first call of the window is the one kept.
        self.assertTrue(payload["trades"][0]["trade_id"].endswith("@2026-07-02"))

    def test_a_new_window_after_the_holding_period_is_replayed_again(self):
        # Non-overlapping is the rule, not one-replay-per-code: a genuinely separate
        # entry must still count.
        self.store.upsert_bars("A", "1d", [
            KLineBar(time=f"2026-08-{d:02d}", open=120.0, high=121.0, low=119.0,
                     close=120.0, volume=1_000_000, turnover=1.2e8)
            for d in range(1, 6)
        ])
        recs = [
            {"code": "A", "timestamp": "2026-07-02T15:00:00+08:00",
             "exit_plan": _plan(maximum_holding_days=3)},
            {"code": "A", "timestamp": "2026-07-10T15:00:00+08:00",
             "exit_plan": _plan(maximum_holding_days=3)},
        ]
        payload, report = scenarios_from_journal(recs, self.store)

        self.assertEqual(len(payload["trades"]), 2)
        self.assertEqual(report["skipped"], {})

    def test_a_call_the_store_no_longer_covers_is_skipped_not_replayed_later(self):
        """A stale call must not be settled against a window that starts weeks later.

        Bars are synced with a bounded `num`, so a recommendation older than the store's
        coverage would be replayed with the original `entry_price` against a much later
        path -- typically an instant gap-stop and a fabricated ~-1R, counted as
        `closed_by_plan`.
        """

        payload, report = scenarios_from_journal(
            [{"code": "A", "timestamp": "2026-06-01T15:00:00+08:00", "exit_plan": _plan()}],
            self.store,
        )

        self.assertEqual(payload["trades"], [])
        self.assertEqual(report["skipped"], {"insufficient-forward-bars": 1})

    def test_a_weekend_gap_before_the_first_bar_is_still_adjacent(self):
        # Friday call, Monday bar: the guard must not reject an ordinary weekend.
        self.assertTrue(forward_bars(self.store, "A", "2026-07-03", 20))

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


class ReplayPairingTests(unittest.TestCase):
    """`run_path_backtest` drops repeated trade_ids, which would misalign the pairing.

    Scenario results are matched back to their scenarios by position to decide which
    trades the plan actually closed. A position id such as `xpeng-09868-core83` recurs
    across entry sessions, so reusing it as the scenario id shortened the results list and
    paired every later trade with the wrong scenario -- silently, and in the direction of
    reporting open trades as closed.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self._tmp.name) / "market.db")
        self.store.upsert_bars("A", "1d", [_bar(d, 100.0 + d) for d in range(1, 26)])

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_one_position_entered_twice_yields_two_distinct_scenarios(self):
        from tools.stock_skills.journal_paths import replay_journal

        recs = [
            {"code": "A", "timestamp": f"2026-07-{day:02d}T15:00:00+08:00",
             "trade_id": "same-position", "exit_plan": _plan(maximum_holding_days=3)}
            for day in (2, 9)
        ]
        payload, report = scenarios_from_journal(recs, self.store)
        ids = [t["trade_id"] for t in payload["trades"]]
        self.assertEqual(len(set(ids)), 2, ids)
        self.assertEqual(report["replayed"], 2)
        # And the replay must survive its own alignment assertion.
        replay_journal(recs, self.store)

    def test_a_trade_the_plan_never_closed_is_reported_open_not_counted(self):
        from tools.stock_skills.journal_paths import replay_journal

        # Rising bars that never reach the target and never hit the stop: the replay runs
        # out of data with the position still open.
        recs = [{"code": "A", "timestamp": "2026-07-20T15:00:00+08:00",
                 "exit_plan": _plan(maximum_holding_days=20)}]
        report = replay_journal(recs, self.store)
        self.assertEqual(report["journal_coverage"]["still_open"], 1)
        self.assertEqual(report["journal_coverage"]["closed_by_plan"], 0)
        self.assertEqual(report["summary"]["trades"], 0)
