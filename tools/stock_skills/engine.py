from __future__ import annotations

from .models import (
    CapitalAnalysis,
    ComponentScores,
    CrossMarketAnalysis,
    InstrumentState,
    MacroAnalysis,
    Recommendation,
    TrendAnalysis,
)


def classify_total_score(total_score: float, price_location: str) -> str:
    if total_score >= 80:
        return "trim-on-strength" if price_location == "near_resistance" else "strong-watch"
    if total_score >= 70:
        return "low-buy-zone" if price_location == "healthy_pullback" else "hold"
    if total_score >= 60:
        return "hold"
    if total_score >= 45:
        return "trim-on-strength"
    if total_score >= 30:
        return "risk-reduce"
    return "avoid"


def detect_price_location(state: InstrumentState, trend: TrendAnalysis) -> str:
    price = state.snapshot.last_price
    if trend.resistance_levels:
        nearest_resistance = min(trend.resistance_levels, key=lambda level: abs(level - price))
        if nearest_resistance > 0 and abs(price - nearest_resistance) / nearest_resistance <= 0.015:
            return "near_resistance"
    if trend.support_levels:
        nearest_support = min(trend.support_levels, key=lambda level: abs(level - price))
        if nearest_support > 0 and abs(price - nearest_support) / nearest_support <= 0.02:
            return "healthy_pullback"
    return "middle"


def _weighted_total(scores: ComponentScores, weights: dict[str, float]) -> float:
    return round(
        scores.trend * weights["trend"]
        + scores.capital_flow * weights["capital_flow"]
        + scores.sector * weights["sector"]
        + scores.cross_market * weights["cross_market"]
        + scores.macro_risk * weights["macro_risk"]
        + scores.position_fit * weights["position_fit"],
        2,
    )


def build_recommendation(
    state: InstrumentState,
    trend: TrendAnalysis,
    capital: CapitalAnalysis,
    macro: MacroAnalysis,
    cross_market: CrossMarketAnalysis,
    sector_score: float,
    position_fit_score: float,
    weights: dict[str, float],
    source_refs: list[str],
) -> Recommendation:
    component_scores = ComponentScores(
        trend=trend.score,
        capital_flow=capital.score,
        sector=sector_score,
        cross_market=cross_market.score,
        macro_risk=macro.score,
        position_fit=position_fit_score,
    )
    total_score = _weighted_total(component_scores, weights)
    price_location = detect_price_location(state, trend)
    label = classify_total_score(total_score, price_location)
    confidence = round(max(0.1, min(0.95, total_score / 100)), 2)

    support_text = ", ".join(str(level) for level in trend.support_levels) or "unavailable"
    resistance_text = ", ".join(str(level) for level in trend.resistance_levels) or "unavailable"
    invalidation = trend.invalidation_level
    last_trim = state.user_context.get("last_trim_price")
    trim_text = f" Prior partial trim near {last_trim} should reduce chase pressure." if last_trim else ""

    analyst_hypothesis = (
        f"investment hypothesis: {state.snapshot.name} remains worth tracking if sector demand and earnings logic "
        f"continue to support the trade. Trend status is {trend.status}, capital stance is {capital.stance}, "
        f"macro regime is {macro.regime}, and cross-market regime is {cross_market.regime}."
    )
    trader_plan = (
        f"trader plan: current price {state.snapshot.last_price}. Support levels: {support_text}. "
        f"Resistance levels: {resistance_text}. Use invalidation near {invalidation}. "
        f"Action label is {label}; avoid chasing near resistance unless a new volume-confirmed breakout appears."
        f"{trim_text}"
    )

    return Recommendation(
        code=state.snapshot.code,
        name=state.snapshot.name,
        timestamp=state.snapshot.timestamp,
        label=label,
        total_score=total_score,
        component_scores=component_scores,
        analyst_hypothesis=analyst_hypothesis,
        trader_plan=trader_plan,
        support_levels=trend.support_levels,
        resistance_levels=trend.resistance_levels,
        invalidation_level=invalidation,
        confidence=confidence,
        source_refs=source_refs,
        user_context=state.user_context,
    )
