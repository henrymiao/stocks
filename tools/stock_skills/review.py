from __future__ import annotations

from typing import Any

from .models import KLineBar


POSITIVE_LABELS = {"strong-watch", "low-buy-zone", "hold"}
NEGATIVE_LABELS = {"trim-on-strength", "risk-reduce", "avoid"}
MIN_WEIGHT_REVIEW_SAMPLE = 60

# Components ranked by score; the lowest is the strongest warning that was overridden.
_ATTRIBUTABLE_COMPONENTS = ("trend", "capital_flow", "sector", "cross_market", "macro_risk", "market_regime", "fundamental", "position_fit")


def _required_bar_count(review_window: str) -> int | None:
    # Imported markdown reviews use approximate close-only note prices, not a complete
    # daily-bar window. Preserve their reporting path while excluding them from realised
    # evidence used to change mutable signal weights.
    if review_window.startswith("md-") and review_window.endswith("pt"):
        return None
    if not review_window.endswith("d"):
        raise ValueError("review_window must use a positive day suffix, such as '3d'")
    day_count = review_window[:-1]
    if not day_count.isdigit() or int(day_count) <= 0:
        raise ValueError("review_window must use a positive day suffix, such as '3d'")
    return int(day_count)


def _attribute_failure(recommendation: dict[str, Any], invalidated: bool) -> tuple[str, str]:
    """Pick the component most responsible for a failed call, using the scores recorded at the time.

    For a losing bullish call we blame the component that gave the strongest warning
    (the lowest score) yet was overridden by the overall recommendation. This keeps weight
    adjustments evidence-based instead of always crediting one factor.
    """
    scores = recommendation.get("component_scores")
    if isinstance(scores, dict):
        present = {key: scores[key] for key in _ATTRIBUTABLE_COMPONENTS if isinstance(scores.get(key), (int, float))}
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
    required_bar_count = _required_bar_count(review_window)
    evaluation_bars = future_bars if required_bar_count is None else future_bars[:required_bar_count]

    # A first bar at more than double or below half the recorded entry price is a
    # price-basis mismatch — usually a split/reverse-split between the call and this
    # fetch (leveraged ETFs reverse-split routinely). The return arithmetic is then
    # meaningless, so the row is flagged and kept out of realised evidence.
    first_bar = evaluation_bars[0]
    first_reference = first_bar.open if first_bar.open > 0 else first_bar.close
    basis_ratio = round(first_reference / entry_price, 4)
    basis_mismatch = required_bar_count is not None and not (0.5 < basis_ratio < 2.0)

    highest = max(bar.high for bar in evaluation_bars)
    lowest = min(bar.low for bar in evaluation_bars)
    final_close = evaluation_bars[-1].close
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

    methods = recommendation.get("method_assessment")
    methods = methods if isinstance(methods, dict) else {}
    structure = methods.get("swing_structure")
    structure = structure if isinstance(structure, dict) else {}
    thesis = methods.get("thesis")
    thesis = thesis if isinstance(thesis, dict) else {}
    valuation = methods.get("valuation")
    valuation = valuation if isinstance(valuation, dict) else {}
    linkage = methods.get("linkage")
    linkage = linkage if isinstance(linkage, dict) else {}
    raw_restrictions = methods.get("restrictions")
    restrictions = raw_restrictions if isinstance(raw_restrictions, list) else []

    return {
        "code": recommendation.get("code"),
        "source_timestamp": recommendation.get("timestamp"),
        "trade_id": recommendation.get("trade_id"),
        "strategy_id": recommendation.get("strategy_id") or (recommendation.get("strategy_assessment") or {}).get("strategy_id"),
        "strategy_version": recommendation.get("strategy_version"),
        "horizon": recommendation.get("horizon") or (recommendation.get("strategy_assessment") or {}).get("horizon"),
        "leveraged": recommendation.get("leveraged", False),
        "review_window": review_window,
        "label": label,
        "entry_price": entry_price,
        "final_close": final_close,
        "maximum_favorable_pct": maximum_favorable_pct,
        "maximum_adverse_pct": maximum_adverse_pct,
        "final_return_pct": final_return_pct,
        "observed_bar_count": len(future_bars),
        "review_complete": required_bar_count is not None and len(future_bars) >= required_bar_count and not basis_mismatch,
        "evidence_kind": "synthetic" if required_bar_count is None else ("basis-mismatch" if basis_mismatch else "realized-ohlc"),
        "basis_ratio": basis_ratio,
        "invalidated": invalidated,
        "directional_success": directional_success,
        "dominant_failure": dominant_failure,
        "attribution_reason": attribution_reason,
        "method_policy": methods.get("method_policy"),
        "method_profile": methods.get("market_profile_id"),
        "method_stage": structure.get("stage"),
        "thesis_state": thesis.get("state"),
        "valuation_status": valuation.get("status"),
        "linkage_coverage": linkage.get("coverage"),
        "method_restrictions": [
            item.get("code") for item in restrictions if isinstance(item, dict)
        ],
    }


def suggest_weight_adjustments(current_weights: dict[str, float], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [
        review
        for review in reviews
        if review.get("review_complete") is True
        and isinstance(review.get("directional_success"), bool)
    ]
    if len(usable) < MIN_WEIGHT_REVIEW_SAMPLE:
        return {
            "weights": dict(current_weights),
            "eligible": False,
            "sample_size": len(usable),
            "notes": [
                f"Need at least {MIN_WEIGHT_REVIEW_SAMPLE} realised reviews before changing weights; "
                f"received {len(usable)}."
            ],
        }
    return {
        "weights": dict(current_weights),
        "eligible": False,
        "sample_size": len(usable),
        "notes": [
            "Legacy failure-count weight bumps are frozen. Use evidence-optimize for "
            "strategy-versioned chronological walk-forward evaluation; it is advisory only."
        ],
    }
