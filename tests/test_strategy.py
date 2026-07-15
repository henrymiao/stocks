import unittest

from tools.stock_skills.strategy import (
    StrategyEvidence,
    build_profile_exit_plan,
    evaluate_strategy,
    get_strategy_profile,
)


def _good_evidence(**overrides):
    values = dict(
        factor_scores={
            "price_volume": 80.0,
            "relative_strength": 75.0,
            "market_regime": 70.0,
            "capital_flow": 70.0,
            "liquidity_event": 70.0,
            "position_fit": 70.0,
            "trend_quality": 80.0,
            "fundamental": 70.0,
            "backdrop": 70.0,
            "volume_accumulation": 70.0,
        },
        data_confidence=1.0,
        data_entry_eligible=True,
        exit_plan_valid=True,
        session_phase="after-close",
        trend_regime="uptrend",
        relative_strength_positive=True,
        volume_ratio=1.3,
        trigger_confirmed=True,
        resistance_room_r=3.0,
        market_regime="risk-on",
        liquidity_ok=True,
        weekly_aligned=True,
        event_days=10,
        underlying_confirmed=True,
        portfolio_heat_allowed=True,
        data_probe_eligible=True,
        planned_allocation_pct=20.0,
    )
    values.update(overrides)
    return StrategyEvidence(**values)


class StrategyProfileTests(unittest.TestCase):
    def test_short_and_swing_profiles_have_distinct_exit_policies(self):
        short = get_strategy_profile("short")
        swing = get_strategy_profile("swing")

        self.assertEqual(short.strategy_id, "short-balanced-v1")
        self.assertEqual(swing.strategy_id, "swing-balanced-v1")
        self.assertEqual(short.stop_buffer_atr, 0.25)
        self.assertEqual(swing.stop_buffer_atr, 0.5)
        self.assertEqual(short.target_specs[0], ("tp1", 1.0, 0.25))
        self.assertEqual(swing.target_specs[0], ("tp1", 1.5, 0.20))
        self.assertEqual(short.maximum_holding_days, 3)
        self.assertEqual(swing.maximum_holding_days, 20)

    def test_leveraged_overlay_changes_targets_trailing_and_cap(self):
        profile = get_strategy_profile("short", leveraged=True)

        self.assertIn("leveraged-overlay-v1", profile.strategy_id)
        self.assertEqual(profile.target_specs[0], ("tp1", 0.9, 0.25))
        self.assertEqual(profile.target_specs[1], ("tp2", 1.5, 0.25))
        self.assertEqual(profile.trailing_atr_multiple, 1.2)
        self.assertEqual(profile.allocation_cap_pct, 15.0)

    def test_profile_exit_plan_uses_horizon_policy(self):
        short_plan = build_profile_exit_plan(
            get_strategy_profile("short"), 100.0, 95.0, 4.0, risk_budget_pct=1.0,
        )
        swing_plan = build_profile_exit_plan(
            get_strategy_profile("swing"), 100.0, 95.0, 4.0, risk_budget_pct=1.0,
        )

        self.assertEqual(short_plan.initial_stop, 94.0)
        self.assertEqual(swing_plan.initial_stop, 93.0)
        self.assertEqual(short_plan.targets[0].r_multiple, 1.0)
        self.assertEqual(swing_plan.targets[0].r_multiple, 1.5)


class StrategyGateTests(unittest.TestCase):
    def test_complete_short_and_swing_setups_can_enter(self):
        short = evaluate_strategy(get_strategy_profile("short"), _good_evidence())
        swing = evaluate_strategy(get_strategy_profile("swing"), _good_evidence())

        self.assertEqual(short.entry_decision, "enter")
        self.assertEqual(swing.entry_decision, "enter")
        self.assertEqual(short.suggested_allocation_pct, 20.0)
        self.assertGreater(short.setup_score, 65.0)
        self.assertGreater(swing.setup_score, 65.0)
        self.assertEqual(short.decision_policy, "logic-first-correlation-aware-v3")
        self.assertIn("market_behavior", short.factor_clusters)

    def test_correlated_tape_factors_are_aggregated_once(self):
        scores = dict(_good_evidence().factor_scores)
        scores.update(
            fundamental=50.0,
            price_volume=100.0,
            relative_strength=100.0,
            capital_flow=100.0,
            market_regime=50.0,
            liquidity_event=50.0,
            position_fit=50.0,
        )
        result = evaluate_strategy(
            get_strategy_profile("short"),
            _good_evidence(factor_scores=scores),
        )

        self.assertEqual(result.factor_clusters["market_behavior"], 100.0)
        self.assertEqual(result.setup_score, 70.0)

    def test_independent_thesis_cluster_changes_short_setup(self):
        scores = dict(_good_evidence().factor_scores)
        for key in scores:
            scores[key] = 50.0
        scores["fundamental"] = 100.0

        result = evaluate_strategy(
            get_strategy_profile("short"),
            _good_evidence(factor_scores=scores),
        )

        self.assertEqual(result.factor_clusters["thesis"], 100.0)
        self.assertEqual(result.setup_score, 60.0)

    def test_low_confidence_or_missing_exit_plan_rejects_entry(self):
        profile = get_strategy_profile("short")
        low_confidence = evaluate_strategy(
            profile,
            _good_evidence(
                data_confidence=0.50,
                data_entry_eligible=False,
                data_probe_eligible=False,
            ),
        )
        no_plan = evaluate_strategy(profile, _good_evidence(exit_plan_valid=False))

        self.assertEqual(low_confidence.entry_decision, "reject")
        self.assertIn("data-confidence", low_confidence.gates_failed)
        self.assertEqual(no_plan.entry_decision, "reject")
        self.assertIn("structured-exit-plan", no_plan.gates_failed)

    def test_short_profile_uses_probe_for_strong_risk_off_or_missing_trigger_setup(self):
        profile = get_strategy_profile("short")
        risk_off = evaluate_strategy(profile, _good_evidence(market_regime="risk-off"))
        missing_trigger = evaluate_strategy(profile, _good_evidence(trigger_confirmed=None))

        self.assertEqual(risk_off.entry_decision, "probe")
        self.assertIn("market-regime", risk_off.gates_failed)
        self.assertEqual(missing_trigger.entry_decision, "probe")
        self.assertIn("entry-trigger", missing_trigger.gates_missing)
        self.assertEqual(missing_trigger.suggested_allocation_pct, 5.0)

    def test_swing_profile_requires_weekly_and_event_evidence(self):
        profile = get_strategy_profile("swing")
        missing_weekly = evaluate_strategy(profile, _good_evidence(weekly_aligned=None))
        imminent_event = evaluate_strategy(profile, _good_evidence(event_days=3))

        self.assertEqual(missing_weekly.entry_decision, "watch")
        self.assertIn("weekly-alignment", missing_weekly.gates_missing)
        self.assertEqual(imminent_event.entry_decision, "reject")
        self.assertIn("event-window", imminent_event.gates_failed)

    def test_leveraged_entry_requires_underlying_confirmation(self):
        profile = get_strategy_profile("short", leveraged=True)
        missing = evaluate_strategy(profile, _good_evidence(underlying_confirmed=None))
        contradicted = evaluate_strategy(profile, _good_evidence(underlying_confirmed=False))
        confirmed = evaluate_strategy(profile, _good_evidence(underlying_confirmed=True))

        self.assertEqual(missing.entry_decision, "reject")
        self.assertEqual(contradicted.entry_decision, "reject")
        self.assertEqual(confirmed.entry_decision, "enter")
        self.assertIn("underlying-confirmation", missing.gates_failed)

    def test_missing_heat_caps_probe_and_exhausted_heat_rejects(self):
        profile = get_strategy_profile("short")
        missing = evaluate_strategy(profile, _good_evidence(portfolio_heat_allowed=None))
        exhausted = evaluate_strategy(profile, _good_evidence(portfolio_heat_allowed=False))

        self.assertEqual(missing.entry_decision, "probe")
        self.assertIn("portfolio-heat", missing.gates_missing)
        self.assertEqual(missing.suggested_allocation_pct, 5.0)
        self.assertEqual(exhausted.entry_decision, "reject")
        self.assertIn("portfolio-heat", exhausted.gates_failed)

    def test_existing_position_gets_separate_position_decision(self):
        assessment = evaluate_strategy(
            get_strategy_profile("short"),
            _good_evidence(),
            has_position=True,
            legacy_label="trim-on-strength",
        )
        self.assertEqual(assessment.position_decision, "partial-exit")

    def test_confirmed_probe_can_become_add_candidate(self):
        confirmed = evaluate_strategy(
            get_strategy_profile("short"),
            _good_evidence(),
            has_position=True,
            legacy_label="hold",
            position_stage="probe",
        )
        still_incomplete = evaluate_strategy(
            get_strategy_profile("short"),
            _good_evidence(trigger_confirmed=None),
            has_position=True,
            legacy_label="hold",
            position_stage="probe",
        )

        self.assertEqual(confirmed.position_decision, "add")
        self.assertEqual(still_incomplete.position_decision, "hold-probe")


if __name__ == "__main__":
    unittest.main()
