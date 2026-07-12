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


SHORT_PROFILE = StrategyProfile(
    strategy_id="short-balanced-v1",
    horizon="short",
    factor_weights={
        "price_volume": 0.30,
        "relative_strength": 0.20,
        "market_regime": 0.15,
        "capital_flow": 0.15,
        "liquidity_event": 0.10,
        "position_fit": 0.10,
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
)


SWING_PROFILE = StrategyProfile(
    strategy_id="swing-balanced-v1",
    horizon="swing",
    factor_weights={
        "trend_quality": 0.25,
        "relative_strength": 0.20,
        "fundamental": 0.20,
        "backdrop": 0.15,
        "volume_accumulation": 0.10,
        "position_fit": 0.10,
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


def _setup_score(profile: StrategyProfile, scores: dict[str, float]) -> tuple[float, dict[str, float]]:
    used: dict[str, float] = {}
    total = 0.0
    for name, weight in profile.factor_weights.items():
        score = _finite_score(name, scores.get(name))
        used[name] = round(score, 2)
        total += score * weight
    return round(total, 2), used


def evaluate_strategy(
    profile: StrategyProfile,
    evidence: StrategyEvidence,
    *,
    has_position: bool = False,
    legacy_label: str | None = None,
) -> StrategyAssessment:
    setup_score, factor_scores = _setup_score(profile, evidence.factor_scores)
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

    if failed:
        entry_decision = "reject"
    elif missing:
        entry_decision = "watch"
    elif setup_score >= 65.0:
        entry_decision = "enter"
    elif setup_score >= 50.0:
        entry_decision = "watch"
    else:
        entry_decision = "reject"

    position_decision: str | None = None
    if has_position:
        if legacy_label in {"avoid", "risk-reduce"}:
            position_decision = "full-exit"
        elif legacy_label == "trim-on-strength":
            position_decision = "partial-exit"
        else:
            position_decision = "hold"

    notes = (
        "Setup score and entry decision are horizon-specific; legacy total_score is unchanged.",
    )
    return StrategyAssessment(
        strategy_id=profile.strategy_id,
        horizon=profile.horizon,
        setup_score=setup_score,
        entry_decision=entry_decision,
        position_decision=position_decision,
        factor_scores=factor_scores,
        gates_passed=tuple(passed),
        gates_failed=tuple(failed),
        gates_missing=tuple(missing),
        leveraged_overlay=profile.leveraged_overlay,
        notes=notes,
    )
