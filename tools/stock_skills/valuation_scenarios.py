from __future__ import annotations

import math
from statistics import mean
from typing import Callable

from .market_profiles import MarketProfile
from .method_models import ValuationCase, ValuationScenarioAnalysis


_CASE_ORDER = ("bear", "base", "bull")


def _number(case: dict[str, object], key: str) -> float:
    if key not in case:
        raise ValueError(f"missing {key}")
    value = case[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{key} must be finite")
    return numeric


def _positive(case: dict[str, object], key: str) -> float:
    value = _number(case, key)
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _earnings_value(case: dict[str, object]) -> float:
    return _positive(case, "eps") * _positive(case, "multiple")


def _sotp_value(case: dict[str, object]) -> float:
    parts = case.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("missing non-empty parts")
    if not all(isinstance(item, dict) for item in parts):
        raise ValueError("each part must be an object")
    gross_value = sum(_positive(item, "value") for item in parts)
    net_debt = _number(case, "net_debt")
    shares = _positive(case, "shares")
    return (gross_value - net_debt) / shares


def _dcf_value(case: dict[str, object]) -> float:
    fcff = _positive(case, "fcff")
    growth = _number(case, "growth_rate")
    raw_years = _positive(case, "years")
    if not raw_years.is_integer():
        raise ValueError("years must be a whole number")
    years = int(raw_years)
    discount = _positive(case, "discount_rate")
    terminal_growth = _number(case, "terminal_growth")
    net_debt = _number(case, "net_debt")
    shares = _positive(case, "shares")
    if not 1 <= years <= 10:
        raise ValueError("years must be between 1 and 10")
    if growth <= -1.0 or terminal_growth <= -1.0:
        raise ValueError("growth rates must be greater than -100%")
    if discount <= terminal_growth:
        raise ValueError("discount_rate must exceed terminal_growth")

    present = 0.0
    terminal_fcff = fcff
    for year in range(1, years + 1):
        terminal_fcff *= 1.0 + growth
        present += terminal_fcff / ((1.0 + discount) ** year)
    terminal = terminal_fcff * (1.0 + terminal_growth) / (discount - terminal_growth)
    present += terminal / ((1.0 + discount) ** years)
    return (present - net_debt) / shares


_CALCULATORS: dict[str, Callable[[dict[str, object]], float]] = {
    "earnings-multiple": _earnings_value,
    "sotp": _sotp_value,
    "dcf": _dcf_value,
}


def _unavailable(*notes: str) -> ValuationScenarioAnalysis:
    return ValuationScenarioAnalysis(
        status="unavailable",
        methods_used=(),
        cases=(),
        sensitivity={},
        method_disagreement_pct=None,
        coverage=0.0,
        confidence=0.0,
        notes=tuple(notes) or ("valuation assumptions unavailable",),
    )


def _method_records(assumptions: dict[str, object] | None) -> list[dict[str, object]]:
    if not assumptions:
        return []
    if not isinstance(assumptions, dict):
        raise TypeError("valuation assumptions must be an object")
    if "methods" not in assumptions:
        if "method" not in assumptions:
            raise ValueError("missing method or methods")
        return [assumptions]
    methods = assumptions["methods"]
    if not isinstance(methods, list) or not methods:
        raise ValueError("methods must be a non-empty list")
    if not all(isinstance(record, dict) for record in methods):
        raise ValueError("each valuation method must be an object")
    return list(methods)


def _earnings_sensitivity(base: dict[str, object]) -> list[dict[str, float]]:
    eps = _positive(base, "eps")
    multiple = _positive(base, "multiple")
    return [
        {
            "eps": round(eps * eps_factor, 4),
            "multiple": round(multiple * multiple_factor, 4),
            "fair_value": round(eps * eps_factor * multiple * multiple_factor, 4),
        }
        for eps_factor in (0.9, 1.0, 1.1)
        for multiple_factor in (0.9, 1.0, 1.1)
    ]


def _dcf_sensitivity(base: dict[str, object]) -> list[dict[str, float]]:
    discount = _positive(base, "discount_rate")
    terminal_growth = _number(base, "terminal_growth")
    rows: list[dict[str, float]] = []
    for discount_delta in (-0.01, 0.0, 0.01):
        for terminal_delta in (-0.005, 0.0, 0.005):
            varied_discount = discount + discount_delta
            varied_terminal = terminal_growth + terminal_delta
            if varied_discount <= varied_terminal or varied_discount <= 0:
                continue
            varied = dict(base)
            varied["discount_rate"] = varied_discount
            varied["terminal_growth"] = varied_terminal
            value = _dcf_value(varied)
            if value <= 0:
                continue
            rows.append(
                {
                    "discount_rate": round(varied_discount, 4),
                    "terminal_growth": round(varied_terminal, 4),
                    "fair_value": round(value, 4),
                }
            )
    return rows


def analyze_valuation_scenarios(
    assumptions: dict[str, object] | None,
    profile: MarketProfile,
) -> ValuationScenarioAnalysis:
    try:
        records = _method_records(assumptions)
    except (TypeError, ValueError, KeyError) as exc:
        return _unavailable(str(exc))
    if not records:
        return _unavailable("valuation assumptions unavailable")

    methods_used: list[str] = []
    cases: list[ValuationCase] = []
    base_values: list[float] = []
    sensitivity: dict[str, object] = {}
    notes: list[str] = []
    seen: set[str] = set()

    for record in records:
        raw_method = record.get("method")
        method = str(raw_method) if raw_method is not None else ""
        if not method:
            notes.append("missing method")
            continue
        if method in seen:
            notes.append(f"{method}: duplicate method")
            continue
        seen.add(method)
        if method not in profile.allowed_valuation_methods:
            notes.append(f"{method}: method not allowed for {profile.profile_id}")
            continue
        calculator = _CALCULATORS.get(method)
        if calculator is None:
            notes.append(f"{method}: unsupported method")
            continue
        raw_cases = record.get("cases")
        if not isinstance(raw_cases, dict):
            notes.append(f"{method}: missing cases object")
            continue
        missing = [name for name in _CASE_ORDER if name not in raw_cases]
        if missing:
            notes.append(f"{method}: missing cases: {', '.join(missing)}")
            continue

        evaluated: list[ValuationCase] = []
        try:
            for name in _CASE_ORDER:
                case = raw_cases[name]
                if not isinstance(case, dict):
                    raise ValueError(f"{name} case must be an object")
                fair_value = calculator(case)
                if not math.isfinite(fair_value) or fair_value <= 0:
                    raise ValueError(f"{name} fair value must be positive and finite")
                evaluated.append(
                    ValuationCase(
                        method=method,
                        name=name,
                        fair_value=round(fair_value, 4),
                        assumptions=dict(case),
                    )
                )
            values = [case.fair_value for case in evaluated]
            if values != sorted(values):
                raise ValueError("fair values must be ordered bear <= base <= bull")
            if method == "earnings-multiple":
                sensitivity[method] = _earnings_sensitivity(raw_cases["base"])
            elif method == "dcf":
                sensitivity[method] = _dcf_sensitivity(raw_cases["base"])
        except (TypeError, ValueError, KeyError) as exc:
            notes.append(f"{method}: {exc}")
            continue

        methods_used.append(method)
        cases.extend(evaluated)
        base_values.append(evaluated[1].fair_value)

    if not methods_used:
        return _unavailable(*notes)

    disagreement = None
    if len(base_values) >= 2:
        disagreement = round(
            (max(base_values) - min(base_values)) / mean(base_values) * 100.0,
            4,
        )
    coverage = round(len(methods_used) / len(records), 4)
    return ValuationScenarioAnalysis(
        status="available",
        methods_used=tuple(methods_used),
        cases=tuple(cases),
        sensitivity=sensitivity,
        method_disagreement_pct=disagreement,
        coverage=coverage,
        confidence=coverage,
        notes=tuple(notes),
    )
