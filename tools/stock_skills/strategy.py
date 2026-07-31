from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace

from .exit_engine import build_exit_plan
from .models import DECISION_POLICY, ExitPlan, StrategyAssessment


# ---- Decision thresholds (setup_score is on a 0-100 scale) ----------------------
# Collected here so tuning and sensitivity analysis touch one block instead of
# hunting literals through the decision logic.
ENTER_MIN_SETUP = 65.0            # all gates passed and setup at least this -> enter
WATCH_MIN_SETUP = 50.0            # below this with no missing evidence -> reject
SUPPORTING_CLUSTER_MIN_SCORE = 60.0  # inclusive: a cluster at 60 counts as support
ENTER_MIN_SUPPORTING_CLUSTERS = 2  # full entry/add needs independent confirmation
PROBE_MIN_SUPPORTING_CLUSTERS = 1  # one live cluster may justify a small early probe
PROBE_MIN_CAPITAL_SCORE = 60.0    # probe needs real capital sponsorship...
PROBE_MIN_PRICE_VOLUME_SCORE = 55.0  # ...and at least neutral price/volume behaviour
RISK_OFF_PROBE_MIN_SETUP = 68.0   # risk-off tape: probe only for clear leadership...
RISK_OFF_PROBE_MIN_CAPITAL = 70.0  # ...with strong capital confirmation
POSITION_FULL_EXIT_MAX_SETUP = 45.0  # held position below this setup -> full exit
POSITION_TRIM_MAX_SETUP = 55.0    # held position below this setup -> partial exit
POSITION_TRIM_ON_STRENGTH_MIN_SETUP = 80.0  # strong setup pinned at resistance -> trim


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


# Multi-quarter thesis holdings. SKILL.md has always said these sit outside both
# tactical profiles, but until now there was no track for them, so they were run as
# `swing` and every add was vetoed by one-to-four-week timing gates while the
# business thesis was intact. Core weights the thesis heavily, keeps the structural
# guards (exit plan, liquidity, portfolio heat, position cap) and drops the timing
# gates. Its exits are wider because a core position is not managed off a daily bar.
CORE_PROFILE = StrategyProfile(
    strategy_id="core-thesis-v1",
    horizon="core",
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
        "thesis": 0.50,          # the reason you own it dominates
        "market_behavior": 0.15,  # price action informs, it does not decide
        "environment": 0.15,
        "risk_fit": 0.20,
    },
    stop_buffer_atr=1.0,
    target_specs=(("tp1", 2.5, 0.15), ("tp2", 4.0, 0.15)),
    trailing_atr_multiple=4.0,
    trailing_activation_r=4.0,
    # A core position is not on a two-day clock, but "hold forever" is not a plan
    # either: the time stop becomes a thesis-review trigger. If roughly two quarters
    # pass without 0.5R of progress, the thesis gets re-argued rather than assumed.
    time_stop_progress_r=0.5,
    time_stop_sessions=120,
    maximum_holding_days=750,
    minimum_resistance_r=0.0,     # gate skipped for core
    minimum_volume_ratio=0.0,     # gate skipped for core
    allocation_cap_pct=25.0,
    probe_score_threshold=55.0,
    probe_allocation_fraction=0.30,
    probe_allocation_cap_pct=8.0,
)


def get_strategy_profile(horizon: str, leveraged: bool = False) -> StrategyProfile:
    if horizon == "short":
        profile = SHORT_PROFILE
    elif horizon == "swing":
        profile = SWING_PROFILE
    elif horizon == "core":
        profile = CORE_PROFILE
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
    supporting_clusters = tuple(
        name
        for name, score in factor_clusters.items()
        if score >= SUPPORTING_CLUSTER_MIN_SCORE
    )
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

    # Tactical timing gates. A multi-quarter core holding is not timed off a
    # one-to-four-week chart, so the core track skips them: judging a thesis-driven
    # position by today's resistance is a category error that blocks every add
    # while the thesis and the valuation are still intact.
    if profile.horizon != "core":
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
    if len(supporting_clusters) >= ENTER_MIN_SUPPORTING_CLUSTERS:
        passed.append("independent-clusters")
    elif len(supporting_clusters) >= PROBE_MIN_SUPPORTING_CLUSTERS:
        # One cluster is incomplete confirmation, not contradictory evidence. This
        # keeps the fast probe path available without authorising a full position.
        missing.append("independent-clusters")
    else:
        failed.append("independent-clusters")

    if profile.horizon == "swing":
        gate("weekly-alignment", evidence.weekly_aligned)
    if profile.horizon in {"swing", "core"}:
        # Core adds still respect a known event: sizing into an earnings gap is a
        # variance decision, not an edge decision, whatever the holding period.
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
        or (setup_score >= RISK_OFF_PROBE_MIN_SETUP and capital_score >= RISK_OFF_PROBE_MIN_CAPITAL)
    )
    horizon_probe_ok = profile.horizon in {"short", "core"} or evidence.weekly_aligned is True
    # The core track drops the tactical timing gates, so its probe path must drop the
    # same conditions — otherwise relative strength and price/volume would veto through
    # the back door what the gate list deliberately stopped asking about.
    tactical_probe_ok = profile.horizon == "core" or (
        evidence.relative_strength_positive is True
        and evidence.trigger_confirmed is not False
        and capital_score >= PROBE_MIN_CAPITAL_SCORE
        and price_volume_score >= PROBE_MIN_PRICE_VOLUME_SCORE
    )
    probe_qualifies = (
        not hard_failed
        and evidence.data_probe_eligible
        and evidence.exit_plan_valid
        and evidence.liquidity_ok is True
        and evidence.portfolio_heat_allowed is not False
        and tactical_probe_ok
        and len(supporting_clusters) >= PROBE_MIN_SUPPORTING_CLUSTERS
        and setup_score >= profile.probe_score_threshold
        and risk_off_probe_ok
        and horizon_probe_ok
    )

    if hard_failed:
        entry_decision = "reject"
    elif not failed and not missing and setup_score >= ENTER_MIN_SETUP:
        entry_decision = "enter"
    elif probe_qualifies:
        entry_decision = "probe"
    elif missing:
        entry_decision = "watch"
    elif failed:
        entry_decision = "reject"
    elif setup_score >= WATCH_MIN_SETUP:
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

    # Position management reads the same strategy-track evidence as entries so the
    # two tracks cannot drift apart; `legacy_label` is accepted for API compatibility
    # but no longer drives any decision.
    position_decision: str | None = None
    if has_position:
        trend_broken = evidence.trend_regime == "downtrend" and evidence.trigger_confirmed is False
        if setup_score < POSITION_FULL_EXIT_MAX_SETUP or trend_broken:
            position_decision = "full-exit"
        elif position_stage == "probe" and entry_decision == "reject":
            position_decision = "full-exit"
        elif position_stage == "probe" and entry_decision == "enter":
            position_decision = "add"
        elif position_stage == "probe" and entry_decision in {"probe", "watch"}:
            position_decision = "hold-probe"
        elif setup_score < POSITION_TRIM_MAX_SETUP or (
            "resistance-room" in failed and setup_score >= POSITION_TRIM_ON_STRENGTH_MIN_SETUP
        ):
            position_decision = "partial-exit"
        else:
            position_decision = "hold"

    notes = (
        "Setup score and entry decision are horizon-specific; legacy total_score is unchanged.",
        f"Decision policy {DECISION_POLICY} separates hard vetoes from confirmation gates.",
        "Correlated price, relative-strength, and capital evidence is aggregated once as market_behavior.",
        "Full entry/add needs two independent clusters at or above 60; one cluster can only support a capped probe.",
        "Position decisions read strategy-track evidence (setup bands, trend break, resistance room), not the legacy label.",
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
        decision_policy=DECISION_POLICY,
        suggested_allocation_pct=suggested_allocation_pct,
        allocation_rationale=allocation_rationale,
        decision_inputs=asdict(evidence),
        notes=notes,
    )
