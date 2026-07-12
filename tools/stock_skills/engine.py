from __future__ import annotations

from .models import (
    CapitalAnalysis,
    ComponentScores,
    CrossMarketAnalysis,
    DataQuality,
    ExitPlan,
    InstrumentState,
    MacroAnalysis,
    PositionStateSnapshot,
    Recommendation,
    TrendAnalysis,
)


# Inverse / short ETFs (e.g. SOXS, SQQQ, SH) move OPPOSITE to the broad tape, so the
# backdrop factors — which read a long-biased risk-on/off signal — point the wrong way
# for them: a risk-on tape is bearish for an inverse semiconductor ETF, not bullish.
# When an instrument is inverse we reflect the three backdrop scores around 50, leaving
# the instrument's own trend/capital/position scores (computed from its own price/flow)
# untouched. Detection is by name marker or an explicit "inverse" tag/flag.
_INVERSE_NAME_MARKERS = ("bear", "inverse", "ultrashort", "-1x", "-2x", "-3x")
_INVERSE_TAGS = {"inverse", "short", "bear"}


def is_inverse_instrument(name: str | None, tags: list[str] | None = None) -> bool:
    lowered = (name or "").lower()
    if any(marker in lowered for marker in _INVERSE_NAME_MARKERS):
        return True
    return any(str(tag).lower() in _INVERSE_TAGS for tag in (tags or []))


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


# market_regime, cross_market and macro_risk all read the same underlying
# risk-on/off backdrop. Summing them at full weight triple-counts one factor, so a
# single broad-tape move can dominate the score three times over. We instead blend
# the three into one backdrop score and shrink its deviation from neutral toward a
# single-factor influence. The shrink only bites when the three AGREE (a strongly
# off-neutral blend) — when they disagree the blend already sits near 50 and the
# discount changes little. A neutral backdrop still contributes exactly its weight*50,
# so the existing label thresholds stay calibrated.
_BACKDROP_KEYS = ("market_regime", "cross_market", "macro_risk")
_BACKDROP_REDUNDANCY = 0.6  # 1.0 = old triple-count; <1 de-duplicates the shared signal


def backdrop_blend(scores: ComponentScores, weights: dict[str, float]) -> tuple[float, float, float | None]:
    """Return (weighted contribution, total backdrop weight, discounted backdrop score)."""
    component = {
        "market_regime": scores.market_regime,
        "cross_market": scores.cross_market,
        "macro_risk": scores.macro_risk,
    }
    parts = [(component[key], weights.get(key, 0.0)) for key in _BACKDROP_KEYS]
    total_w = sum(w for _, w in parts)
    if total_w <= 0:
        return 0.0, 0.0, None
    avg = sum(score * w for score, w in parts) / total_w
    discounted = 50.0 + (avg - 50.0) * _BACKDROP_REDUNDANCY
    return round(discounted * total_w, 4), total_w, round(discounted, 2)


def _weighted_total(scores: ComponentScores, weights: dict[str, float]) -> float:
    stock_specific = (
        scores.trend * weights["trend"]
        + scores.capital_flow * weights["capital_flow"]
        + scores.sector * weights["sector"]
        + scores.fundamental * weights.get("fundamental", 0.0)
        + scores.position_fit * weights["position_fit"]
    )
    backdrop_contribution, _, _ = backdrop_blend(scores, weights)
    return round(stock_specific + backdrop_contribution, 2)


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
    data_quality: DataQuality,
    market_score: float = 50.0,
    market_regime: str = "neutral",
    sector_stance: str = "unknown",
    fundamental_score: float = 50.0,
    fundamental_stance: str = "unknown",
    position_stop_price: float | None = None,
    position_size_pct: float | None = None,
    position_stance: str = "unknown",
    inverse: bool = False,
    exit_plan: ExitPlan | None = None,
    position_state: PositionStateSnapshot | None = None,
) -> Recommendation:
    # An inverse instrument moves opposite the broad tape, so reflect the three backdrop
    # scores around 50; its own trend/capital/position scores are left as-is.
    backdrop = (lambda s: round(100.0 - s, 4)) if inverse else (lambda s: s)
    component_scores = ComponentScores(
        trend=trend.score,
        capital_flow=capital.score,
        sector=sector_score,
        cross_market=backdrop(cross_market.score),
        macro_risk=backdrop(macro.score),
        position_fit=position_fit_score,
        market_regime=backdrop(market_score),
        fundamental=fundamental_score,
    )
    total_score = _weighted_total(component_scores, weights)
    price_location = detect_price_location(state, trend)
    label = classify_total_score(total_score, price_location)

    support_text = ", ".join(str(level) for level in trend.support_levels) or "unavailable"
    resistance_text = ", ".join(str(level) for level in trend.resistance_levels) or "unavailable"
    invalidation = trend.invalidation_level
    last_trim = state.user_context.get("last_trim_price")
    trim_text = f" Prior partial trim near {last_trim} should reduce chase pressure." if last_trim else ""

    sizing_text = ""
    if exit_plan is not None:
        tp1, tp2 = exit_plan.targets
        sizing = exit_plan.risk_sizing
        cap_label = "capped" if sizing.capped else "uncapped"
        sizing_text = (
            f" Risk plan: stop near {exit_plan.initial_stop}, suggested size "
            f"~{sizing.suggested_size_pct}% of account ({position_stance}, {cap_label})."
            f" Structured exits: TP1 {tp1.price} ({tp1.fraction:.0%}) at {tp1.r_multiple}R; "
            f"TP2 {tp2.price} ({tp2.fraction:.0%}) at {tp2.r_multiple}R; "
            f"runner {exit_plan.runner_fraction:.0%} trails by {exit_plan.trailing_rule.method}."
        )
    elif position_stop_price is not None:
        sizing_text = f" Risk plan: stop near {position_stop_price}"
        if position_size_pct is not None:
            sizing_text += f", suggested size ~{position_size_pct}% of account ({position_stance})."
        else:
            sizing_text += f" ({position_stance})."

    inverse_note = (
        " Note: inverse instrument — backdrop scores are reflected, so a risk-on tape counts against it."
        if inverse else ""
    )
    analyst_hypothesis = (
        f"investment hypothesis: {state.snapshot.name} remains worth tracking if sector demand and earnings logic "
        f"continue to support the trade. Trend status is {trend.status}, capital stance is {capital.stance}, "
        f"sector stance is {sector_stance}, valuation is {fundamental_stance}, market regime is {market_regime}, "
        f"macro regime is {macro.regime}, and cross-market regime is {cross_market.regime}.{inverse_note}"
    )
    trader_plan = (
        f"trader plan: current price {state.snapshot.last_price}. Support levels: {support_text}. "
        f"Resistance levels: {resistance_text}. Use invalidation near {invalidation}. "
        f"Action label is {label}; avoid chasing near resistance unless a new volume-confirmed breakout appears."
        f"{trim_text}{sizing_text}"
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
        confidence=data_quality.confidence,
        source_refs=source_refs,
        entry_price=state.snapshot.last_price,
        user_context=state.user_context,
        data_quality=data_quality,
        schema_version="recommendation-v2",
        position_state=position_state,
        exit_plan=exit_plan,
    )
