from __future__ import annotations

from collections import Counter
from typing import Any

from .models import KLineBar


POSITIVE_LABELS = {"strong-watch", "low-buy-zone", "hold"}
NEGATIVE_LABELS = {"trim-on-strength", "risk-reduce", "avoid"}


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

    if invalidated:
        dominant_failure = "trend"
    elif final_return_pct < 0 and label in POSITIVE_LABELS:
        dominant_failure = "macro_risk"
    else:
        dominant_failure = "none"

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
