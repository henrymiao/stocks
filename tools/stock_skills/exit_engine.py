from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from .models import (
    ExitPlan,
    ExitTarget,
    PositionStateSnapshot,
    RiskSizing,
    TimeStop,
    TrailingRule,
)


ORDINARY_ALLOCATION_CAP_PCT = 25.0
LEVERAGED_ALLOCATION_CAP_PCT = 15.0
ORDINARY_MAX_RISK_BUDGET_PCT = 2.0
LEVERAGED_MAX_RISK_BUDGET_PCT = 1.25
EXIT_EVENTS = {
    "initial-stop",
    "trailing-stop",
    "time-stop",
    "thesis-invalidation",
    "mandatory-event",
}


def _number(name: str, value: object, *, positive: bool = False, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if positive and result <= 0:
        raise ValueError(f"{name} must be positive")
    if non_negative and result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _price(value: float) -> float:
    if value < 1:
        return round(value, 4)
    if value < 10:
        return round(value, 3)
    return round(value, 2)


def build_exit_plan(
    entry_price: float,
    structural_invalidation: float | None,
    atr: float | None,
    *,
    risk_budget_pct: float = 1.0,
    stop_buffer_atr: float = 0.25,
    target_specs: Iterable[tuple[str, float, float]] = (
        ("tp1", 1.0, 0.25),
        ("tp2", 1.8, 0.25),
    ),
    trailing_method: str = "two-bar-low-or-atr",
    trailing_atr_multiple: float = 1.5,
    trailing_activation_r: float | None = None,
    time_stop_progress_r: float = 0.5,
    time_stop_sessions: int = 2,
    maximum_holding_days: int = 3,
    leveraged: bool = False,
    allocation_cap_pct: float | None = None,
    strategy_id: str = "structured-exit-foundation-v1",
) -> ExitPlan:
    """Build a validated long execution plan around structural risk.

    The initial stop sits *beyond* structural invalidation by an ATR buffer. A wider
    structural stop therefore reduces size; the stop is never tightened merely to
    preserve allocation. Inverse ETFs still use long execution geometry because the
    traded instrument itself is bought long.
    """
    entry = _number("entry_price", entry_price, positive=True)
    if structural_invalidation is None:
        raise ValueError("structural_invalidation is required")
    invalidation = _number("structural_invalidation", structural_invalidation, positive=True)
    atr_value = _number("atr", atr, positive=True)
    buffer = _number("stop_buffer_atr", stop_buffer_atr, non_negative=True)
    if invalidation >= entry:
        raise ValueError("structural_invalidation must be below entry_price for a long plan")

    maximum_risk = LEVERAGED_MAX_RISK_BUDGET_PCT if leveraged else ORDINARY_MAX_RISK_BUDGET_PCT
    risk_budget = _number("risk_budget_pct", risk_budget_pct, positive=True)
    if risk_budget > maximum_risk:
        raise ValueError(
            f"risk_budget_pct exceeds the {'leveraged' if leveraged else 'ordinary'} maximum of {maximum_risk}"
        )

    stop = _price(invalidation - buffer * atr_value)
    if stop <= 0 or stop >= entry:
        raise ValueError("ATR-buffered structural stop must be positive and below entry_price")
    risk_per_share = _price(entry - stop)
    if risk_per_share <= 0:
        raise ValueError("risk_per_share must be positive")

    specs = tuple(target_specs)
    if len(specs) != 2:
        raise ValueError("exactly two partial targets are required")
    targets: list[ExitTarget] = []
    previous_r = 0.0
    partial_fraction = 0.0
    for raw_name, raw_r, raw_fraction in specs:
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError("target name must be non-empty")
        r_multiple = _number(f"{raw_name}.r_multiple", raw_r, positive=True)
        fraction = _number(f"{raw_name}.fraction", raw_fraction, positive=True)
        if r_multiple <= previous_r:
            raise ValueError("target R multiples must be strictly increasing")
        if fraction > 1.0:
            raise ValueError("target fraction cannot exceed 1")
        partial_fraction += fraction
        if partial_fraction > 1.0 + 1e-9:
            raise ValueError("partial target fractions cannot exceed 1")
        target_price = _price(entry + risk_per_share * r_multiple)
        if target_price <= entry:
            raise ValueError("long target prices must be above entry_price")
        targets.append(ExitTarget(raw_name, r_multiple, target_price, fraction))
        previous_r = r_multiple

    runner_fraction = round(1.0 - partial_fraction, 6)
    if runner_fraction < 0:
        raise ValueError("runner fraction cannot be negative")

    if trailing_method != "two-bar-low-or-atr":
        raise ValueError(f"Unsupported trailing method: {trailing_method}")
    trailing_multiple = _number("trailing_atr_multiple", trailing_atr_multiple, positive=True)
    activation_r = _number(
        "trailing_activation_r",
        previous_r if trailing_activation_r is None else trailing_activation_r,
        positive=True,
    )
    progress_r = _number("time_stop_progress_r", time_stop_progress_r, non_negative=True)
    sessions = _positive_int("time_stop_sessions", time_stop_sessions)
    max_days = _positive_int("maximum_holding_days", maximum_holding_days)

    stop_distance_pct = (risk_per_share / entry) * 100.0
    uncapped_size_pct = (risk_budget / stop_distance_pct) * 100.0
    cap_default = LEVERAGED_ALLOCATION_CAP_PCT if leveraged else ORDINARY_ALLOCATION_CAP_PCT
    cap = _number(
        "allocation_cap_pct",
        cap_default if allocation_cap_pct is None else allocation_cap_pct,
        positive=True,
    )
    if cap > 100.0:
        raise ValueError("allocation_cap_pct cannot exceed 100")
    suggested_size_pct = min(uncapped_size_pct, cap)
    planned_risk_pct = suggested_size_pct * stop_distance_pct / 100.0
    sizing = RiskSizing(
        stop_distance_pct=round(stop_distance_pct, 4),
        uncapped_size_pct=round(uncapped_size_pct, 2),
        allocation_cap_pct=round(cap, 2),
        suggested_size_pct=round(suggested_size_pct, 2),
        planned_risk_pct=round(planned_risk_pct, 4),
        capped=uncapped_size_pct > cap + 1e-9,
    )

    if not isinstance(strategy_id, str) or not strategy_id:
        raise ValueError("strategy_id must be non-empty")
    return ExitPlan(
        strategy_id=strategy_id,
        side="long",
        entry_price=_price(entry),
        structural_invalidation=_price(invalidation),
        initial_stop=stop,
        risk_per_share=risk_per_share,
        atr=_price(atr_value),
        risk_budget_pct=round(risk_budget, 4),
        targets=tuple(targets),
        runner_fraction=runner_fraction,
        trailing_rule=TrailingRule(
            method=trailing_method,
            activation_r=activation_r,
            atr_multiple=trailing_multiple,
        ),
        time_stop=TimeStop(progress_r=progress_r, sessions=sessions, action="full-exit"),
        maximum_holding_days=max_days,
        gap_handling="exit-at-first-available-price-if-gap-through-stop",
        event_handling="reassess-or-exit-before-unmodelled-major-event",
        risk_sizing=sizing,
    )


def next_trailing_stop(
    *,
    previous_stop: float | None,
    prior_two_bar_low: float,
    highest_close: float,
    atr: float,
    atr_multiple: float,
) -> float:
    two_bar_low = _number("prior_two_bar_low", prior_two_bar_low, positive=True)
    high_close = _number("highest_close", highest_close, positive=True)
    atr_value = _number("atr", atr, positive=True)
    multiple = _number("atr_multiple", atr_multiple, positive=True)
    candidate = max(two_bar_low, high_close - multiple * atr_value)
    if previous_stop is not None:
        candidate = max(_number("previous_stop", previous_stop, positive=True), candidate)
    return _price(candidate)


def transition_position(
    snapshot: PositionStateSnapshot,
    event: str,
    *,
    target_fraction: float | None = None,
    gates_passed: bool = True,
) -> PositionStateSnapshot:
    if not isinstance(event, str) or not event:
        raise ValueError("event must be non-empty")
    if snapshot.last_event == event:
        return snapshot
    if event == "tp1-filled" and "tp1" in snapshot.filled_targets:
        return snapshot
    if event == "tp2-filled" and "tp2" in snapshot.filled_targets:
        return snapshot
    if snapshot.state == "exited":
        raise ValueError("exited positions cannot transition back to an open state")

    if event in EXIT_EVENTS:
        if snapshot.state not in {"entered", "profit-protected", "trend-runner"}:
            raise ValueError(f"Cannot apply {event} while position is {snapshot.state}")
        return replace(
            snapshot,
            state="exited",
            remaining_fraction=0.0,
            last_event=event,
            exit_reason=event,
        )

    if event == "entry-filled":
        if snapshot.state != "flat":
            raise ValueError("entry-filled requires a flat position")
        if not gates_passed:
            raise ValueError("entry gates did not pass")
        return replace(snapshot, state="entered", remaining_fraction=1.0, last_event=event)

    if event == "protection-threshold":
        if snapshot.state != "entered":
            raise ValueError("protection-threshold requires an entered position")
        return replace(snapshot, state="profit-protected", last_event=event)

    if event in {"tp1-filled", "tp2-filled"}:
        required_state = "entered" if event == "tp1-filled" else "profit-protected"
        if snapshot.state != required_state:
            raise ValueError(f"{event} requires a {required_state} position")
        fraction = _number("target_fraction", target_fraction, positive=True)
        if fraction > snapshot.remaining_fraction + 1e-9:
            raise ValueError("target fraction exceeds the remaining position")
        target_name = "tp1" if event == "tp1-filled" else "tp2"
        new_state = "profit-protected" if event == "tp1-filled" else "trend-runner"
        return replace(
            snapshot,
            state=new_state,
            remaining_fraction=round(snapshot.remaining_fraction - fraction, 6),
            filled_targets=snapshot.filled_targets + (target_name,),
            last_event=event,
        )

    raise ValueError(f"Unknown position event: {event}")
