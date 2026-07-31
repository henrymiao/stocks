import unittest

from tools.stock_skills.method_models import (
    LinkageAnalysis,
    SwingStructureAnalysis,
    ThesisAnalysis,
    ValuationScenarioAnalysis,
)
from tools.stock_skills.method_policy import apply_method_restrictions, build_method_assessment
from tools.stock_skills.strategy import StrategyEvidence, evaluate_strategy, get_strategy_profile


def _evidence(**overrides):
    base = dict(
        factor_scores={
            "fundamental": 72.0,
            "trend_quality": 55.0,
            "relative_strength": 50.0,
            "volume_accumulation": 55.0,
            "backdrop": 50.0,
            "position_fit": 72.0,
        },
        data_confidence=1.0,
        data_entry_eligible=True,
        exit_plan_valid=True,
        session_phase="after-close",
        trend_regime="downtrend",          # tactical timing is poor...
        relative_strength_positive=False,  # ...on every count
        volume_ratio=0.5,
        trigger_confirmed=False,
        resistance_room_r=0.1,             # pinned right under resistance
        market_regime="neutral",
        liquidity_ok=True,
        weekly_aligned=False,
        event_days=30,
        underlying_confirmed=None,
        portfolio_heat_allowed=True,
        planned_allocation_pct=6.0,
    )
    base.update(overrides)
    return StrategyEvidence(**base)


class CoreProfileTests(unittest.TestCase):
    def test_core_skips_the_tactical_timing_gates(self):
        assessment = evaluate_strategy(get_strategy_profile("core"), _evidence())

        for gate in ("trend-regime", "relative-strength", "volume-confirmation", "entry-trigger", "resistance-room"):
            self.assertNotIn(gate, assessment.gates_failed, gate)
            self.assertNotIn(gate, assessment.gates_missing, gate)

    def test_swing_rejects_the_same_evidence_that_core_allows(self):
        swing = evaluate_strategy(get_strategy_profile("swing"), _evidence())
        core = evaluate_strategy(get_strategy_profile("core"), _evidence())

        self.assertIn("resistance-room", swing.gates_failed)
        self.assertNotEqual(core.entry_decision, "reject")
        self.assertGreater(core.setup_score, swing.setup_score)  # thesis is weighted heavier

    def test_core_still_enforces_the_structural_guards(self):
        blocked = evaluate_strategy(
            get_strategy_profile("core"),
            _evidence(exit_plan_valid=False, liquidity_ok=False, portfolio_heat_allowed=False),
        )

        self.assertEqual(blocked.entry_decision, "reject")
        for gate in ("structured-exit-plan", "liquidity", "portfolio-heat"):
            self.assertIn(gate, blocked.gates_failed)

    def test_core_still_respects_a_known_event_window(self):
        near_earnings = evaluate_strategy(get_strategy_profile("core"), _evidence(event_days=2))

        self.assertIn("event-window", near_earnings.gates_failed)
        self.assertEqual(near_earnings.entry_decision, "reject")

    def test_stage_three_no_longer_vetoes_a_core_add(self):
        # The exact rule that turned GOOGL's `watch` into `reject` on 2026-07-31.
        structure = SwingStructureAnalysis(
            stage="stage-3",
            ma50=None,
            ma150=None,
            ma200=None,
            checklist={},
            pivot=None,
            buy_zone=None,
            contraction_count=0,
            breakout_volume_ratio=None,
            gate_effect="reject-new-risk",
            coverage=1.0,
            confidence=1.0,
        )
        thesis = ThesisAnalysis(
            state="supported",
            upside_drivers=(),
            downside_drivers=(),
            bull_path=None,
            base_path=None,
            bear_path=None,
            rival_hypothesis=None,
            invalidations=(),
            unresolved=(),
            technical_confirmation="neutral",
            coverage=1.0,
            confidence=1.0,
        )
        valuation = ValuationScenarioAnalysis(
            status="available",
            methods_used=(),
            cases=(),
            sensitivity={},
            method_disagreement_pct=None,
            coverage=1.0,
            confidence=1.0,
        )
        linkage = LinkageAnalysis(references=(), coverage=1.0, confidence=1.0)
        methods = build_method_assessment("us-equity-v1", structure, thesis, valuation, linkage)

        swing_profile = get_strategy_profile("swing")
        core_profile = get_strategy_profile("core")
        swing_base = evaluate_strategy(swing_profile, _evidence())
        core_base = evaluate_strategy(core_profile, _evidence())

        swing_final = apply_method_restrictions(swing_base, methods, swing_profile, has_position=True)
        core_final = apply_method_restrictions(core_base, methods, core_profile, has_position=True)

        self.assertEqual(swing_final.entry_decision, "reject")   # swing-stage-3 applies
        self.assertNotEqual(core_final.entry_decision, "reject")  # core is out of its scope


    def test_core_probe_path_drops_the_same_tactical_conditions_as_the_gates(self):
        # The gate list stops asking about relative strength for core, so the probe
        # path must not re-impose it — otherwise the veto returns through the back door.
        core = evaluate_strategy(get_strategy_profile("core"), _evidence())
        swing = evaluate_strategy(get_strategy_profile("swing"), _evidence())

        self.assertIn(core.entry_decision, {"watch", "probe", "enter"})
        self.assertEqual(swing.entry_decision, "reject")


if __name__ == "__main__":
    unittest.main()
