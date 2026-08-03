import unittest

from tools.stock_skills.method_models import (
    DeclineAssessment,
    LinkageAnalysis,
    SwingStructureAnalysis,
    ThesisAnalysis,
    ValuationScenarioAnalysis,
)
from tools.stock_skills.method_policy import (
    apply_method_restrictions,
    build_method_assessment,
)
from tools.stock_skills.models import StrategyAssessment
from tools.stock_skills.strategy import get_strategy_profile


def _assessment(entry="enter", setup=75.0, horizon="swing", position=None, allocation=20.0):
    return StrategyAssessment(
        strategy_id=f"{horizon}-balanced-v1",
        horizon=horizon,
        setup_score=setup,
        entry_decision=entry,
        position_decision=position,
        factor_scores={},
        factor_clusters={},
        gates_passed=(),
        gates_failed=(),
        gates_missing=(),
        leveraged_overlay=False,
        suggested_allocation_pct=allocation,
        allocation_rationale="fixture",
        decision_inputs={"planned_allocation_pct": allocation},
    )


def _methods(
    stage="stage-2",
    gate=None,
    thesis_state="supported",
    conflicts=(),
    valuation_disagreement=None,
    valuation_critical=False,
    decline=None,
):
    if gate is None:
        gate = "reject-new-risk" if stage in {"stage-3", "stage-4"} else "none"
    structure = SwingStructureAnalysis(
        stage,
        100.0,
        95.0,
        90.0,
        {},
        110.0,
        (110.0, 113.3),
        2,
        1.2,
        gate,
        1.0,
        1.0,
    )
    thesis = ThesisAnalysis(
        thesis_state,
        ("growth",),
        (),
        "bull",
        "base",
        "bear",
        "rival",
        (),
        (),
        "not-evaluated",
        1.0,
        1.0,
    )
    valuation = ValuationScenarioAnalysis(
        "available" if valuation_disagreement is not None else "unavailable",
        ("earnings-multiple", "sotp") if valuation_disagreement is not None else (),
        (),
        {},
        valuation_disagreement,
        1.0 if valuation_disagreement is not None else 0.0,
        1.0 if valuation_disagreement is not None else 0.0,
    )
    linkage = LinkageAnalysis((), 0.0, 0.0)
    return build_method_assessment(
        "hk-equity-v1",
        structure,
        thesis,
        valuation,
        linkage,
        valuation_critical=valuation_critical,
        source_conflicts=conflicts,
        decline=decline,
    )


class MethodPolicyTests(unittest.TestCase):
    def test_positive_evidence_does_not_change_score_or_upgrade_watch(self):
        original = _assessment(entry="watch", setup=64.0)
        final = apply_method_restrictions(
            original,
            _methods(stage="stage-2"),
            get_strategy_profile("swing"),
            False,
        )
        self.assertEqual(final.setup_score, 64.0)
        self.assertEqual(final.entry_decision, "watch")

    def test_stage_four_rejects_new_swing_risk_but_not_short_setup(self):
        swing = apply_method_restrictions(
            _assessment(entry="enter"),
            _methods(stage="stage-4"),
            get_strategy_profile("swing"),
            False,
        )
        short = apply_method_restrictions(
            _assessment(entry="enter", horizon="short"),
            _methods(stage="stage-4"),
            get_strategy_profile("short"),
            False,
        )
        self.assertEqual(swing.entry_decision, "reject")
        self.assertEqual(short.entry_decision, "enter")

    def test_stage_one_caps_full_swing_entry_to_probe(self):
        original = _assessment(entry="enter", allocation=20.0)
        final = apply_method_restrictions(
            original,
            _methods(stage="stage-1", gate="probe-only"),
            get_strategy_profile("swing"),
            False,
        )
        self.assertEqual(final.entry_decision, "probe")
        self.assertEqual(final.suggested_allocation_pct, 4.0)

    def test_existing_add_is_downgraded_to_hold_not_forced_exit(self):
        original = _assessment(entry="enter", position="add", allocation=20.0)
        final = apply_method_restrictions(
            original,
            _methods(stage="stage-4"),
            get_strategy_profile("swing"),
            True,
        )
        self.assertEqual(final.position_decision, "hold")
        self.assertNotEqual(final.position_decision, "full-exit")

    def test_existing_exit_is_preserved_instead_of_weakened(self):
        original = _assessment(entry="reject", position="full-exit", allocation=None)
        final = apply_method_restrictions(
            original,
            _methods(stage="stage-2"),
            get_strategy_profile("swing"),
            True,
        )
        self.assertEqual(final.entry_decision, "reject")
        self.assertEqual(final.position_decision, "full-exit")

    def test_source_conflict_rejects_short_and_swing(self):
        methods = _methods(conflicts=("last_price:opend!=official-manual",))
        short = apply_method_restrictions(
            _assessment(horizon="short"),
            methods,
            get_strategy_profile("short"),
            False,
        )
        swing = apply_method_restrictions(
            _assessment(),
            methods,
            get_strategy_profile("swing"),
            False,
        )
        self.assertEqual(short.entry_decision, "reject")
        self.assertEqual(swing.entry_decision, "reject")

    def test_evaluated_thesis_invalidation_rejects_only_new_swing_risk(self):
        methods = _methods(thesis_state="invalidated")
        short = apply_method_restrictions(
            _assessment(horizon="short"),
            methods,
            get_strategy_profile("short"),
            False,
        )
        swing = apply_method_restrictions(
            _assessment(),
            methods,
            get_strategy_profile("swing"),
            False,
        )
        self.assertEqual(short.entry_decision, "enter")
        self.assertEqual(swing.entry_decision, "reject")

    def test_valuation_disagreement_restricts_only_when_declared_critical(self):
        ordinary = apply_method_restrictions(
            _assessment(),
            _methods(valuation_disagreement=35.0),
            get_strategy_profile("swing"),
            False,
        )
        critical = apply_method_restrictions(
            _assessment(),
            _methods(valuation_disagreement=35.0, valuation_critical=True),
            get_strategy_profile("swing"),
            False,
        )
        self.assertEqual(ordinary.entry_decision, "enter")
        self.assertEqual(critical.entry_decision, "reject")


if __name__ == "__main__":
    unittest.main()


def _decline(cause, bear=20.0, exhausted=True):
    return DeclineAssessment(
        cause=cause,
        bear_case_loss_pct=bear,
        selling_exhaustion=exhausted,
        as_of="2026-08-03",
        source_ref="manual:review-note",
    )


class DeclineClassificationTests(unittest.TestCase):
    def test_structural_impairment_rejects_at_every_horizon_regardless_of_price(self):
        for horizon in ("short", "swing", "core"):
            with self.subTest(horizon=horizon):
                final = apply_method_restrictions(
                    _assessment(entry="enter", horizon=horizon),
                    _methods(decline=_decline("structural-impairment")),
                    get_strategy_profile(horizon),
                    has_position=False,
                )
                self.assertEqual(final.entry_decision, "reject")
                self.assertIsNone(final.suggested_allocation_pct)

    def test_unconfirmed_cause_caps_a_full_build_down_to_a_probe(self):
        final = apply_method_restrictions(
            _assessment(entry="enter", allocation=20.0),
            _methods(decline=_decline("unconfirmed")),
            get_strategy_profile("swing"),
            has_position=False,
        )
        self.assertEqual(final.entry_decision, "probe")
        self.assertLessEqual(final.suggested_allocation_pct, 5.0)

    def test_unbounded_bear_case_caps_a_full_build_even_for_a_benign_cause(self):
        final = apply_method_restrictions(
            _assessment(entry="enter"),
            _methods(decline=_decline("liquidity", bear=None)),
            get_strategy_profile("swing"),
            has_position=False,
        )
        self.assertEqual(final.entry_decision, "probe")

    def test_benign_and_bounded_decline_adds_no_restriction(self):
        methods = _methods(decline=_decline("bounded-event"))
        self.assertEqual(methods.restrictions, ())
        final = apply_method_restrictions(
            _assessment(entry="enter"),
            methods,
            get_strategy_profile("swing"),
            has_position=False,
        )
        self.assertEqual(final.entry_decision, "enter")

    def test_selling_not_exhausted_caps_to_probe(self):
        final = apply_method_restrictions(
            _assessment(entry="enter"),
            _methods(decline=_decline("liquidity", exhausted=False)),
            get_strategy_profile("swing"),
            has_position=False,
        )
        self.assertEqual(final.entry_decision, "probe")

    def test_absent_assessment_creates_no_restriction_and_no_fake_safety(self):
        methods = _methods(decline=None)
        self.assertIsNone(methods.decline)
        self.assertEqual(methods.restrictions, ())

    def test_contract_rejects_unknown_cause_and_anonymous_claims(self):
        with self.assertRaisesRegex(ValueError, "Unsupported decline cause"):
            DeclineAssessment("cheap", 10.0, True, "2026-08-03", "ref")
        with self.assertRaisesRegex(ValueError, "requires as_of and source_ref"):
            DeclineAssessment("liquidity", 10.0, True, "", "ref")
        with self.assertRaisesRegex(ValueError, "positive loss magnitude"):
            DeclineAssessment("liquidity", -10.0, True, "2026-08-03", "ref")
