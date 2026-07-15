from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .exit_engine import build_exit_plan
from .models import ExitPlan, StrategyAssessment


@dataclass(frozen=True)
class StrategyProfile:
    strategy_id: str
    horizon: str
    factor_weights: dict[str, float]
    factor_clusters: dict[str, tuple[str, ...]]
    cluster_weights: dict[str, float]
    stop_buffer_atr: float
    target_specs: tuple[tuple[str, float, float], ...]
    trailing_atr_multiple: float
    trailing_activation_r: float
    time_stop_progress_r: float
    time_stop_sessions: int
    maximum_holding_days: int
    minimum_resistance_r: float
    minimum_volume_ratio: float
    allocation_cap_pct: float
    probe_score_threshold: float
    probe_allocation_fraction: float
    probe_allocation_cap_pct: float
    leveraged_overlay: bool = False


@dataclass(frozen=True)
class StrategyEvidence:
    factor_scores: dict[str, float]
    data_confidence: float
    data_entry_eligible: bool
    exit_plan_valid: bool
    session_phase: str
    trend_regime: str
    relative_strength_positive: bool | None
    volume_ratio: float | None
    trigger_confirmed: bool | None
    resistance_room_r: float | None
    market_regime: str
    liquidity_ok: bool | None
    weekly_aligned: bool | None
    event_days: int | None
    underlying_confirmed: bool | None
    portfolio_heat_allowed: bool | None = None
    data_probe_eligible: bool = False
    planned_allocation_pct: float | None = None


SHORT_PROFILE = StrategyProfile(
    strategy_id="short-balanced-v1",
    horizon="short",
    factor_weights={
        "fundamental": 1.00,
        "price_volume": 0.40,
        "relative_strength": 0.30,
        "capital_flow": 0.30,
        "market_regime": 0.60,
        "liquidity_event": 0.40,
        "position_fit": 1.00,
    },
    factor_clusters={
        "thesis": ("fundamental",),
        "market_behavior": ("price_volume", "relative_strength", "capital_flow"),
        "environment": ("market_regime", "liquidity_event"),
        "risk_fit": ("position_fit",),
    },
    cluster_weights={
        "thesis": 0.20,
        "market_behavior": 0.40,
        "environment": 0.20,
        "risk_fit": 0.20,
    },
    stop_buffer_atr=0.25,
    target_specs=(("tp1", 1.0, 0.25), ("tp2", 1.8, 0.25)),
    trailing_atr_multiple=1.5,
    trailing_activation_r=1.8,
    time_stop_progress_r=0.5,
    time_stop_sessions=2,
    maximum_holding_days=3,
    minimum_resistance_r=1.8,
    minimum_volume_ratio=1.2,
    allocation_cap_pct=25.0,
    probe_score_threshold=58.0,
    probe_allocation_fraction=0.25,
    probe_allocation_cap_pct=5.0,
)


SWING_PROFILE = StrategyProfile(
    strategy_id="swing-balanced-v1",
    horizon="swing",
    factor_weights={
        "fundamental": 1.00,
        "trend_quality": 0.35,
        "relative_strength": 0.35,
        "volume_accumulation": 0.30,
        "backdrop": 1.00,
        "position_fit": 1.00,
    },
    factor_clusters={
        "thesis": ("fundamental",),
        "market_behavior": ("trend_quality", "relative_strength", "volume_accumulation"),
        "environment": ("backdrop",),
        "risk_fit": ("position_fit",),
    },
    cluster_weights={
        "thesis": 0.30,
        "market_behavior": 0.35,
        "environment": 0.20,
        "risk_fit": 0.15,
    },
    stop_buffer_atr=0.5,
    target_specs=(("tp1", 1.5, 0.20), ("tp2", 2.5, 0.20)),
    trailing_atr_multiple=2.5,
    trailing_activation_r=2.5,
    time_stop_progress_r=0.5,
    time_stop_sessions=5,
    maximum_holding_days=20,
    minimum_resistance_r=2.5,
    minimum_volume_ratio=1.0,
    allocation_cap_pct=25.0,
    probe_score_threshold=62.0,
    probe_allocation_fraction=0.20,
    probe_allocation_cap_pct=5.0,
)


def get_strategy_profile(horizon: str, leveraged: bool = False) -> StrategyProfile:
    if horizon == "short":
        profile = SHORT_PROFILE
    elif horizon == "swing":
        profile = SWING_PROFILE
    else:
        raise ValueError(f"Unknown strategy horizon: {horizon}")
    if not leveraged:
        return profile
    return replace(
        profile,
        strategy_id=f"{profile.strategy_id}+leveraged-overlay-v1",
        target_specs=(("tp1", 0.9, 0.25), ("tp2", 1.5, 0.25)),
        trailing_atr_multiple=1.2,
        trailing_activation_r=1.5,
        allocation_cap_pct=15.0,
        probe_allocation_fraction=0.20,
        probe_allocation_cap_pct=3.0,
        leveraged_overlay=True,
    )


def build_profile_exit_plan(
    profile: StrategyProfile,
    entry_price: float,
    structural_invalidation: float | None,
    atr: float | None,
    *,
    risk_budget_pct: float,
    stop_buffer_atr: float | None = None,
) -> ExitPlan:
    return build_exit_plan(
        entry_price=entry_price,
        structural_invalidation=structural_invalidation,
        atr=atr,
        risk_budget_pct=risk_budget_pct,
        stop_buffer_atr=profile.stop_buffer_atr if stop_buffer_atr is None else stop_buffer_atr,
        target_specs=profile.target_specs,
        trailing_atr_multiple=profile.trailing_atr_multiple,
        trailing_activation_r=profile.trailing_activation_r,
        time_stop_progress_r=profile.time_stop_progress_r,
        time_stop_sessions=profile.time_stop_sessions,
        maximum_holding_days=profile.maximum_holding_days,
        leveraged=profile.leveraged_overlay,
        allocation_cap_pct=profile.allocation_cap_pct,
        strategy_id=profile.strategy_id,
    )


def _finite_score(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Missing or invalid factor score: {name}")
    return max(0.0, min(100.0, float(value)))


def _setup_score(
    profile: StrategyProfile,
    scores: dict[str, float],
) -> tuple[float, dict[str, float], dict[str, float]]:
    """Aggregate correlated factors once through independent evidence clusters."""
    used: dict[str, float] = {}
    for name in profile.factor_weights:
        score = _finite_score(name, scores.get(name))
        used[name] = round(score, 2)

    cluster_names = set(profile.factor_clusters)
    if cluster_names != set(profile.cluster_weights):
        raise ValueError("factor_clusters and cluster_weights must use the same cluster names")
    if not math.isclose(sum(profile.cluster_weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("cluster_weights must sum to 1")

    clustered_factors = [
        factor
        for members in profile.factor_clusters.values()
        for factor in members
    ]
    if len(clustered_factors) != len(set(clustered_factors)):
        raise ValueError("Each factor may belong to only one correlation cluster")
    if set(clustered_factors) != set(profile.factor_weights):
        raise ValueError("Every weighted factor must belong to exactly one correlation cluster")

    cluster_scores: dict[str, float] = {}
    total = 0.0
    for cluster, members in profile.factor_clusters.items():
        if not members:
            raise ValueError(f"Empty factor cluster: {cluster}")
        within_weights = [profile.factor_weights[name] for name in members]
        within_total = sum(within_weights)
        if within_total <= 0:
            raise ValueError(f"Factor cluster has no positive weight: {cluster}")
        cluster_score = sum(
            used[name] * profile.factor_weights[name] for name in members
        ) / within_total
        cluster_scores[cluster] = round(cluster_score, 2)
        total += cluster_score * profile.cluster_weights[cluster]
    return round(total, 2), used, cluster_scores


def evaluate_strategy(
    profile: StrategyProfile,
    evidence: StrategyEvidence,
    *,
    has_position: bool = False,
    legacy_label: str | None = None,
    position_stage: str | None = None,
) -> StrategyAssessment:
    setup_score, factor_scores, factor_clusters = _setup_score(profile, evidence.factor_scores)
    passed: list[str] = []
    failed: list[str] = []
    missing: list[str] = []

    def gate(name: str, result: bool | None) -> None:
        if result is None:
            missing.append(name)
        elif result:
            passed.append(name)
        else:
            failed.append(name)

    gate(
        "data-confidence",
        evidence.data_entry_eligible and evidence.data_confidence >= 0.80,
    )
    gate("structured-exit-plan", evidence.exit_plan_valid)
    if evidence.session_phase in {"pre-open", "closed"}:
        gate("session-ready", None)
    else:
        gate("session-ready", True)

    gate("trend-regime", evidence.trend_regime == "uptrend")
    gate("relative-strength", evidence.relative_strength_positive)
    gate(
        "volume-confirmation",
        None if evidence.volume_ratio is None else evidence.volume_ratio >= profile.minimum_volume_ratio,
    )
    gate("entry-trigger", evidence.trigger_confirmed)
    gate(
        "resistance-room",
        None
        if evidence.resistance_room_r is None
        else evidence.resistance_room_r >= profile.minimum_resistance_r,
    )
    gate("market-regime", evidence.market_regime != "risk-off")
    gate("liquidity", evidence.liquidity_ok)
    gate("portfolio-heat", evidence.portfolio_heat_allowed)

    if profile.horizon == "swing":
        gate("weekly-alignment", evidence.weekly_aligned)
        gate(
            "event-window",
            None if evidence.event_days is None else evidence.event_days >= 5,
        )
    if profile.leveraged_overlay:
        # Missing confirmation is a rejection, not a neutral observation.
        gate("underlying-confirmation", evidence.underlying_confirmed is True)

    # Trader-style opportunity layer: only failures that make a trade
    # unexecutable are hard vetoes.  Confirmation failures may still permit a
    # tightly-sized probe when leadership and capital evidence are strong.
    hard_failed = {
        name
        for name in failed
        if name in {"structured-exit-plan", "liquidity", "portfolio-heat", "event-window"}
    }
    if "data-confidence" in failed and not evidence.data_probe_eligible:
        hard_failed.add("data-confidence")
    if profile.leveraged_overlay and "underlying-confirmation" in set(failed + missing):
        hard_failed.add("underlying-confirmation")

    capital_score = factor_scores.get("capital_flow", factor_scores.get("volume_accumulation", 0.0))
    price_volume_score = factor_scores.get("price_volume", factor_scores.get("trend_quality", 0.0))
    risk_off_probe_ok = (
        evidence.market_regime != "risk-off"
        or (setup_score >= 68.0 and capital_score >= 70.0)
    )
    horizon_probe_ok = profile.horizon == "short" or evidence.weekly_aligned is True
    probe_qualifies = (
        not hard_failed
        and evidence.data_probe_eligible
        and evidence.exit_plan_valid
        and evidence.liquidity_ok is True
        and evidence.portfolio_heat_allowed is not False
        and evidence.relative_strength_positive is True
        and evidence.trigger_confirmed is not False
        and capital_score >= 60.0
        and price_volume_score >= 55.0
        and setup_score >= profile.probe_score_threshold
        and risk_off_probe_ok
        and horizon_probe_ok
    )

    if hard_failed:
        entry_decision = "reject"
    elif not failed and not missing and setup_score >= 65.0:
        entry_decision = "enter"
    elif probe_qualifies:
        entry_decision = "probe"
    elif missing:
        entry_decision = "watch"
    elif failed:
        entry_decision = "reject"
    elif setup_score >= 50.0:
        entry_decision = "watch"
    else:
        entry_decision = "reject"

    suggested_allocation_pct: float | None = None
    allocation_rationale: str | None = None
    if evidence.planned_allocation_pct is not None:
        planned = max(0.0, float(evidence.planned_allocation_pct))
        if entry_decision == "enter":
            suggested_allocation_pct = round(planned, 2)
            allocation_rationale = "All confirmation gates passed; use the risk-sized planned allocation."
        elif entry_decision == "probe":
            suggested_allocation_pct = round(
                min(planned * profile.probe_allocation_fraction, profile.probe_allocation_cap_pct),
                2,
            )
            allocation_rationale = (
                "Opportunity probe only: cap exposure until trigger, volume, trend, and resistance-room "
                "confirmation improve."
            )

    position_decision: str | None = None
    if has_position:
        if legacy_label in {"avoid", "risk-reduce"}:
            position_decision = "full-exit"
        elif position_stage == "probe" and entry_decision == "enter":
            position_decision = "add"
        elif position_stage == "probe" and entry_decision in {"probe", "watch"}:
            position_decision = "hold-probe"
        elif legacy_label == "trim-on-strength":
            position_decision = "partial-exit"
        else:
            position_decision = "hold"

    notes = (
        "Setup score and entry decision are horizon-specific; legacy total_score is unchanged.",
        "Decision policy logic-first-correlation-aware-v3 separates hard vetoes from confirmation gates.",
        "Correlated price, relative-strength, and capital evidence is aggregated once as market_behavior.",
    )
    return StrategyAssessment(
        strategy_id=profile.strategy_id,
        horizon=profile.horizon,
        setup_score=setup_score,
        entry_decision=entry_decision,
        position_decision=position_decision,
        factor_scores=factor_scores,
        factor_clusters=factor_clusters,
        gates_passed=tuple(passed),
        gates_failed=tuple(failed),
        gates_missing=tuple(missing),
        leveraged_overlay=profile.leveraged_overlay,
        decision_policy="logic-first-correlation-aware-v3",
        suggested_allocation_pct=suggested_allocation_pct,
        allocation_rationale=allocation_rationale,
        notes=notes,
    )
