from __future__ import annotations

import operator
from statistics import mean
from typing import Callable

from .method_models import ThesisAnalysis, ValuationScenarioAnalysis
from .models import FundamentalAnalysis


_OPERATORS: dict[str, Callable[[object, object], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def _valuation_base(valuation: ValuationScenarioAnalysis) -> float | None:
    values = [
        case.fair_value
        for case in valuation.cases
        if case.name == "base" and case.fair_value > 0
    ]
    return mean(values) if values else None


def _conditional_paths(
    upside: list[str],
    downside: list[str],
) -> tuple[str | None, str | None, str | None]:
    if not upside and not downside:
        return None, None, None
    bull = (
        f"If {upside[0]} persists, the upside path remains viable."
        if upside
        else "If the unresolved upside evidence improves, a recovery path may emerge."
    )
    base = "Base path: observed evidence remains conditional and must be re-evaluated as new facts arrive."
    bear = (
        f"If {downside[0]} persists, downside risk remains dominant."
        if downside
        else "If the observed upside evidence fades, the base thesis may weaken."
    )
    return bull, base, bear


def analyze_thesis(
    fundamental: FundamentalAnalysis | None,
    sector_stance: str,
    market_regime: str,
    valuation: ValuationScenarioAnalysis,
    manual: dict[str, object],
    observed_metrics: dict[str, float],
) -> ThesisAnalysis:
    upside: list[str] = []
    downside: list[str] = []
    unresolved: list[str] = []
    triggered_invalidations: list[str] = []

    if fundamental is not None:
        if fundamental.quality is not None and fundamental.quality >= 65:
            upside.append("observed business quality is strong")
        elif fundamental.quality is not None and fundamental.quality < 40:
            downside.append("observed business quality is weak")
        if fundamental.stance in {"cheap", "fair"}:
            upside.append(f"observed fundamental valuation stance is {fundamental.stance}")
        elif fundamental.stance == "expensive":
            downside.append("observed fundamental valuation stance is expensive")

    if sector_stance == "leading":
        upside.append("observed sector leadership is positive")
    elif sector_stance in {"lagging", "sector-weak"}:
        downside.append(f"observed sector stance is {sector_stance}")

    if market_regime == "risk-off":
        downside.append("observed market regime is risk-off")

    base_value = _valuation_base(valuation) if valuation.status == "available" else None
    current_price = observed_metrics.get("current_price")
    if (
        base_value is not None
        and isinstance(current_price, (int, float))
        and not isinstance(current_price, bool)
        and current_price > 0
        and base_value > current_price
    ):
        upside.append("observed valuation base cases exceed the OpenD current price")

    raw_conditions = manual.get("invalidations", []) if isinstance(manual, dict) else []
    conditions = raw_conditions if isinstance(raw_conditions, list) else []
    if raw_conditions and not isinstance(raw_conditions, list):
        unresolved.append("manual invalidations must be a list")
    evaluated_conditions = 0
    for index, raw_condition in enumerate(conditions):
        if not isinstance(raw_condition, dict):
            unresolved.append(f"invalidation[{index}] is not an object")
            continue
        field = raw_condition.get("field")
        operator_name = raw_condition.get("operator")
        reason = raw_condition.get("reason")
        if not isinstance(field, str) or not isinstance(operator_name, str):
            unresolved.append(f"invalidation[{index}] is missing field/operator")
            continue
        comparison = _OPERATORS.get(operator_name)
        if comparison is None:
            unresolved.append(f"invalidation[{index}] uses unsupported operator {operator_name}")
            continue
        if field not in observed_metrics:
            unresolved.append(f"invalidation metric {field} is unavailable")
            continue
        if "value" not in raw_condition:
            unresolved.append(f"invalidation[{index}] is missing value")
            continue
        try:
            invalidated = comparison(observed_metrics[field], raw_condition["value"])
        except TypeError:
            unresolved.append(f"invalidation metric {field} is not comparable")
            continue
        evaluated_conditions += 1
        if invalidated:
            triggered_invalidations.append(
                str(reason) if reason else f"{field} {operator_name} {raw_condition['value']}"
            )

    if triggered_invalidations:
        state = "invalidated"
    elif len(upside) >= 2 and not downside:
        state = "supported"
    elif upside or downside:
        state = "mixed"
    else:
        state = "unknown"
        unresolved.append("no observed causal drivers")

    catalysts = manual.get("catalysts") if isinstance(manual, dict) else None
    if not catalysts:
        unresolved.append("no explicit catalyst evidence")

    rival = downside[0] if upside and downside else None
    bull, base, bear = _conditional_paths(upside, downside)

    available_slots = sum(
        (
            fundamental is not None,
            sector_stance not in {"", "unknown"},
            market_regime in {"risk-on", "neutral", "risk-off"},
            valuation.status == "available",
        )
    )
    total_slots = 4 + len(conditions)
    coverage = round((available_slots + evaluated_conditions) / total_slots, 4)
    return ThesisAnalysis(
        state=state,
        upside_drivers=tuple(upside),
        downside_drivers=tuple(downside),
        bull_path=bull,
        base_path=base,
        bear_path=bear,
        rival_hypothesis=rival,
        invalidations=tuple(triggered_invalidations),
        unresolved=tuple(dict.fromkeys(unresolved)),
        technical_confirmation="not-evaluated",
        coverage=coverage,
        confidence=min(coverage, 1.0),
        notes=("observations are separated from conditional paths",),
    )
