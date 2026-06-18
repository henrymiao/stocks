from __future__ import annotations

from collections import Counter
from typing import Any

from .models import KLineBar


POSITIVE_LABELS = {"strong-watch", "low-buy-zone", "hold"}
NEGATIVE_LABELS = {"trim-on-strength", "risk-reduce", "avoid"}

# Components ranked by score; the lowest is the strongest warning that was overridden.
_ATTRIBUTABLE_COMPONENTS = ("trend", "capital_flow", "sector", "cross_market", "macro_risk", "market_regime", "fundamental", "position_fit")


def _attribute_failure(recommendation: dict[str, Any], invalidated: bool) -> tuple[str, str]:
    """Pick the component most responsible for a failed call, using the scores recorded at the time.

    For a losing bullish call we blame the component that gave the strongest warning
    (the lowest score) yet was overridden by the overall recommendation. This keeps weight
    adjustments evidence-based instead of always crediting one factor.
    """
    scores = recommendation.get("component_scores")
    if isinstance(scores, dict):
        present = {key: scores[key] for key in _ATTRIBUTABLE_COMPONENTS if isinstance(scores.get(key), int | float)}
        if present:
            weakest, value = min(present.items(), key=lambda item: item[1])
            return weakest, f"{weakest} gave the lowest component score ({value}) at recommendation time."
    # Fallback when no scores were recorded: keep the original coarse heuristic.
    if invalidated:
        return "trend", "No component scores recorded; defaulted to trend after invalidation."
    return "macro_risk", "No component scores recorded; defaulted to macro_risk."


def evaluate_recommendation(
    recommendation: dict[str, Any],
    entry_price: float,
    future_bars: list[KLineBar],
    review_window: str,
) -> dict[str, Any]:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if not future_bars:
        raise ValueError("future_bars must not be empty")

    highest = max(bar.high for bar in future_bars)
    lowest = min(bar.low for bar in future_bars)
    final_close = future_bars[-1].close
    maximum_favorable_pct = round((highest - entry_price) / entry_price * 100, 4)
    maximum_adverse_pct = round((lowest - entry_price) / entry_price * 100, 4)
    final_return_pct = round((final_close - entry_price) / entry_price * 100, 4)
    invalidation_level = recommendation.get("invalidation_level")
    invalidated = bool(invalidation_level is not None and lowest <= float(invalidation_level))
    label = str(recommendation.get("label", ""))

    if label in POSITIVE_LABELS:
        directional_success = final_return_pct >= 0 and not invalidated
    elif label in NEGATIVE_LABELS:
        directional_success = final_return_pct <= 0 or invalidated
    else:
        directional_success = not invalidated

    if directional_success:
        dominant_failure = "none"
        attribution_reason = "Call was directionally successful."
    else:
        dominant_failure, attribution_reason = _attribute_failure(recommendation, invalidated)

    return {
        "code": recommendation.get("code"),
        "source_timestamp": recommendation.get("timestamp"),
        "review_window": review_window,
        "label": label,
        "entry_price": entry_price,
        "final_close": final_close,
        "maximum_favorable_pct": maximum_favorable_pct,
        "maximum_adverse_pct": maximum_adverse_pct,
        "final_return_pct": final_return_pct,
        "invalidated": invalidated,
        "directional_success": directional_success,
        "dominant_failure": dominant_failure,
        "attribution_reason": attribution_reason,
    }


def suggest_weight_adjustments(current_weights: dict[str, float], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    if not reviews:
        return {"weights": dict(current_weights), "notes": ["No reviews supplied; weights unchanged."]}

    failures = [review.get("dominant_failure") for review in reviews if review.get("directional_success") is False]
    counter = Counter(str(failure) for failure in failures if failure and failure != "none")
    weights = dict(current_weights)
    notes: list[str] = []

    if counter:
        top_failure, count = counter.most_common(1)[0]
        if top_failure in weights:
            weights[top_failure] += 0.02
            notes.append(f"Increased {top_failure} by 0.02 after {count} failed review(s).")
            reducible = [key for key in weights if key != top_failure and weights[key] > 0.05]
            if reducible:
                reduction = 0.02 / len(reducible)
                for key in reducible:
                    weights[key] -= reduction
    else:
        notes.append("No recurring failure factor found; weights unchanged.")

    total = sum(weights.values())
    normalized = {key: round(value / total, 6) for key, value in weights.items()}
    drift = round(1.0 - sum(normalized.values()), 6)
    first_key = next(iter(normalized))
    normalized[first_key] = round(normalized[first_key] + drift, 6)

    return {"weights": normalized, "notes": notes}
