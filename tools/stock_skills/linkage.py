from __future__ import annotations

import math
from statistics import mean

from .method_models import LinkageAnalysis, LinkageReferenceAnalysis
from .models import KLineBar


def _returns_by_time(bars: list[KLineBar]) -> dict[str, float]:
    ordered = sorted(bars, key=lambda bar: bar.time)
    result: dict[str, float] = {}
    for previous, current in zip(ordered, ordered[1:]):
        if previous.close > 0:
            result[current.time] = current.close / previous.close - 1.0
    return result


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = mean(left), mean(right)
    left_sum = sum((value - left_mean) ** 2 for value in left)
    right_sum = sum((value - right_mean) ** 2 for value in right)
    if left_sum <= 0 or right_sum <= 0:
        return None
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    return numerator / math.sqrt(left_sum * right_sum)


def _beta(target: list[float], reference: list[float]) -> float | None:
    if len(target) != len(reference) or len(target) < 2:
        return None
    target_mean, reference_mean = mean(target), mean(reference)
    variance = sum((value - reference_mean) ** 2 for value in reference)
    if variance <= 0:
        return None
    covariance = sum(
        (target_value - target_mean) * (reference_value - reference_mean)
        for target_value, reference_value in zip(target, reference)
    )
    return covariance / variance


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def analyze_linkage(
    target_bars: list[KLineBar],
    reference_bars: dict[str, list[KLineBar]],
) -> LinkageAnalysis:
    target_returns = _returns_by_time(target_bars)
    rows: list[LinkageReferenceAnalysis] = []
    confidence_parts: list[float] = []
    usable = 0

    for code in sorted(reference_bars):
        reference_returns = _returns_by_time(reference_bars[code])
        times = sorted(set(target_returns) & set(reference_returns))[-60:]
        target = [target_returns[time] for time in times]
        reference = [reference_returns[time] for time in times]

        corr20 = _correlation(target[-20:], reference[-20:]) if len(times) >= 20 else None
        corr60 = _correlation(target, reference) if len(times) >= 60 else None
        beta60 = _beta(target, reference) if len(times) >= 60 else None
        downside_pairs = [
            (target_return, reference_return)
            for target_return, reference_return in zip(target, reference)
            if reference_return < 0
        ]
        downside = (
            _correlation(
                [pair[0] for pair in downside_pairs],
                [pair[1] for pair in downside_pairs],
            )
            if len(downside_pairs) >= 5
            else None
        )
        first = _correlation(target[:30], reference[:30]) if len(times) >= 60 else None
        second = _correlation(target[-30:], reference[-30:]) if len(times) >= 60 else None
        stability = (
            "unstable"
            if first is not None and second is not None and abs(second - first) >= 0.35
            else ("stable" if corr60 is not None else "unknown")
        )
        if stability == "unstable":
            stance = "unstable"
        elif corr60 is not None and corr60 >= 0.40 and target and reference:
            stance = "confirming" if target[-1] * reference[-1] >= 0 else "diverging"
        else:
            stance = "unknown"

        if corr60 is not None:
            usable += 1
        confidence_parts.append(min(len(times) / 60.0, 1.0))
        rows.append(
            LinkageReferenceAnalysis(
                code=code,
                correlation_20d=_rounded(corr20),
                correlation_60d=_rounded(corr60),
                beta_60d=_rounded(beta60),
                downside_correlation=_rounded(downside),
                stability=stability,
                stance=stance,
                observations=len(times),
            )
        )

    requested = len(reference_bars)
    return LinkageAnalysis(
        references=tuple(rows),
        coverage=0.0 if requested == 0 else round(usable / requested, 4),
        confidence=0.0 if not confidence_parts else round(mean(confidence_parts), 4),
        notes=() if requested else ("no reference histories",),
    )
