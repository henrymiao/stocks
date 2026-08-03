from __future__ import annotations

from dataclasses import replace

from .method_models import DeclineAssessment, MethodAssessment, MethodRestriction
from .models import StrategyAssessment
from .strategy import StrategyProfile


METHOD_POLICY = "finance-method-evidence-v1"
VALUATION_DISAGREEMENT_REJECT_PCT = 30.0


ALL_HORIZONS = ("short", "swing", "core")


def _decline_restrictions(decline: DeclineAssessment) -> list[MethodRestriction]:
    """Turn the classified cause of a decline into entry restrictions.

    Only downgrades are possible here — a favourable classification never authorises
    anything on its own, exactly like the rest of the method sidecar.
    """

    restrictions: list[MethodRestriction] = []
    if decline.cause == "structural-impairment":
        restrictions.append(
            MethodRestriction(
                "decline-structural-impairment",
                "reject-new-risk",
                ALL_HORIZONS,
                "durable earnings power is impaired — no price is a low",
            )
        )
        return restrictions
    if decline.cause == "unconfirmed":
        restrictions.append(
            MethodRestriction(
                "decline-cause-unconfirmed",
                "probe-only",
                ALL_HORIZONS,
                "cause of the decline is not established — capped probe at most",
            )
        )
    if not decline.bear_case_estimable:
        restrictions.append(
            MethodRestriction(
                "decline-bear-case-unbounded",
                "probe-only",
                ALL_HORIZONS,
                "bear-case loss is not estimable — a full build cannot be sized",
            )
        )
    if decline.selling_exhaustion is False:
        restrictions.append(
            MethodRestriction(
                "decline-selling-not-exhausted",
                "probe-only",
                ALL_HORIZONS,
                "marginal selling has not exhausted",
            )
        )
    return restrictions


def build_method_assessment(
    profile_id,
    structure,
    thesis,
    valuation,
    linkage,
    *,
    valuation_critical=False,
    source_conflicts=(),
    errors=None,
    decline=None,
):
    restrictions: list[MethodRestriction] = []
    if decline is not None:
        restrictions.extend(_decline_restrictions(decline))
    if source_conflicts:
        restrictions.append(
            MethodRestriction(
                "source-conflict",
                "reject-new-risk",
                ("short", "swing", "core"),
                "material source conflict",
            )
        )
    if structure.gate_effect == "reject-new-risk":
        restrictions.append(
            MethodRestriction(
                f"swing-{structure.stage}",
                "reject-new-risk",
                ("swing",),
                f"{structure.stage} blocks new swing risk",
            )
        )
    elif structure.gate_effect == "probe-only":
        restrictions.append(
            MethodRestriction(
                "swing-stage-1-probe",
                "probe-only",
                ("swing",),
                "late Stage 1 permits only a capped probe",
            )
        )
    if thesis.state == "invalidated":
        restrictions.append(
            MethodRestriction(
                "thesis-invalidated",
                "reject-new-risk",
                ("swing",),
                "evaluated thesis invalidation",
            )
        )
    if (
        valuation_critical
        and valuation.method_disagreement_pct is not None
        and valuation.method_disagreement_pct >= VALUATION_DISAGREEMENT_REJECT_PCT
    ):
        restrictions.append(
            MethodRestriction(
                "valuation-method-disagreement",
                "reject-new-risk",
                ("swing",),
                f"critical valuation methods disagree by {valuation.method_disagreement_pct}%",
            )
        )

    coverages = [
        structure.coverage,
        thesis.coverage,
        valuation.coverage,
        linkage.coverage,
    ]
    confidences = [
        structure.confidence,
        thesis.confidence,
        valuation.confidence,
        linkage.confidence,
    ]
    return MethodAssessment(
        market_profile_id=profile_id,
        swing_structure=structure,
        thesis=thesis,
        valuation=valuation,
        linkage=linkage,
        coverage=round(sum(coverages) / 4.0, 4),
        confidence=round(sum(confidences) / 4.0, 4),
        restrictions=tuple(restrictions),
        source_conflicts=tuple(source_conflicts),
        method_policy=METHOD_POLICY,
        errors={} if errors is None else dict(errors),
        decline=decline,
    )


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def apply_method_restrictions(
    assessment: StrategyAssessment,
    methods: MethodAssessment,
    profile: StrategyProfile,
    has_position: bool,
) -> StrategyAssessment:
    applicable = [
        restriction
        for restriction in methods.restrictions
        if assessment.horizon in restriction.horizons
    ]
    reject = any(restriction.effect == "reject-new-risk" for restriction in applicable)
    probe_only = any(restriction.effect == "probe-only" for restriction in applicable)
    entry = assessment.entry_decision
    position = assessment.position_decision
    allocation = assessment.suggested_allocation_pct

    if reject and entry in {"enter", "probe", "watch"}:
        entry = "reject"
        allocation = None
    elif probe_only and entry == "enter":
        entry = "probe"
        planned = _numeric(assessment.decision_inputs.get("planned_allocation_pct"))
        if planned is None:
            planned = _numeric(allocation)
        allocation = (
            None
            if planned is None
            else round(
                min(
                    planned,
                    planned * profile.probe_allocation_fraction,
                    profile.probe_allocation_cap_pct,
                ),
                2,
            )
        )

    if has_position and position == "add" and (reject or probe_only):
        position = "hold"

    notes = assessment.notes + tuple(
        f"method restriction: {restriction.code} — {restriction.reason}"
        for restriction in applicable
    )
    inputs = dict(assessment.decision_inputs)
    inputs.update(
        method_policy=methods.method_policy,
        base_entry_decision=assessment.entry_decision,
    )
    return replace(
        assessment,
        entry_decision=entry,
        position_decision=position,
        suggested_allocation_pct=allocation,
        decision_inputs=inputs,
        notes=notes,
    )
