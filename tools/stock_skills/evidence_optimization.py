from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from statistics import mean
from typing import Any


MIN_STRATEGY_BUCKET = 60
INITIAL_TRAIN_SIZE = 40
TEST_SIZE = 20


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _strategy_id(recommendation: dict[str, Any]) -> str:
    direct = recommendation.get("strategy_id")
    if isinstance(direct, str) and direct:
        return direct
    assessment = recommendation.get("strategy_assessment")
    if isinstance(assessment, dict) and isinstance(assessment.get("strategy_id"), str):
        return assessment["strategy_id"]
    schema = str(recommendation.get("schema_version", ""))
    if schema == "recommendation-v2":
        return "structured-exit-foundation-v1"
    return "legacy-baseline-v1"


def _is_leveraged(recommendation: dict[str, Any]) -> bool:
    if isinstance(recommendation.get("leveraged"), bool):
        return recommendation["leveraged"]
    assessment = recommendation.get("strategy_assessment")
    return bool(isinstance(assessment, dict) and assessment.get("leveraged_overlay") is True)


def _decision_policy(recommendation: dict[str, Any]) -> str:
    """Bucket samples by the decision policy that produced them.

    A strategy_id alone does not change when the gate/veto logic evolves (v1 profiles
    ran under several decision policies), so without this key trades produced by
    different decision logic would silently share one optimization bucket.
    """
    assessment = recommendation.get("strategy_assessment")
    if isinstance(assessment, dict):
        policy = assessment.get("decision_policy")
        if isinstance(policy, str) and policy:
            return policy
    return "legacy"


def _phase(strategy_id: str) -> str:
    if strategy_id == "legacy-baseline-v1":
        return "baseline"
    if strategy_id == "structured-exit-foundation-v1":
        return "exit-only"
    if "leveraged-overlay" in strategy_id:
        return "leveraged-overlay"
    return "dual-horizon"


def _is_synthetic(recommendation: dict[str, Any], review: dict[str, Any]) -> bool:
    if review.get("evidence_kind") == "synthetic":
        return True
    if str(review.get("review_window", "")).startswith("md-"):
        return True
    refs = [*recommendation.get("source_refs", []), *review.get("source_refs", [])]
    return any("synt" in str(ref).lower() or "imported-from-md" in str(ref).lower() for ref in refs)


def _metrics(pnl: list[float]) -> dict[str, Any]:
    if not pnl:
        return {"n": 0, "expectancy_pct": None, "maximum_drawdown_pct": None, "win_rate": None}
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in pnl:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return {
        "n": len(pnl),
        "expectancy_pct": round(mean(pnl), 4),
        "maximum_drawdown_pct": round(drawdown, 4),
        "win_rate": round(sum(value > 0 for value in pnl) / len(pnl), 4),
    }


def _observed_pnl(row: dict[str, Any]) -> float | None:
    value = _number(row["review"].get("final_return_pct"))
    if value is None:
        return None
    label = str(row["review"].get("label", row["recommendation"].get("label", "")))
    return -value if label in {"trim-on-strength", "risk-reduce", "avoid"} else value


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def _candidate_weights(base: dict[str, float], delta: float = 0.02) -> list[dict[str, float]]:
    candidates = [dict(base)]
    keys = list(base)
    for target in keys:
        others = [key for key in keys if key != target]
        if not others:
            continue
        for direction in (1.0, -1.0):
            changed = dict(base)
            adjustment = delta * direction
            if changed[target] + adjustment < 0.02:
                continue
            changed[target] += adjustment
            redistribution = adjustment / len(others)
            for key in others:
                changed[key] -= redistribution
            if min(changed.values()) < 0.02:
                continue
            candidates.append(_normalize(changed))
    return candidates


def _score_source(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Return the score mapping a weight set applies to.

    "component" reads the legacy component_scores (the weights the legacy total uses);
    "cluster" reads strategy_assessment.factor_clusters (the strategy-track weights).
    """
    if source == "component":
        scores = row["recommendation"].get("component_scores")
    else:
        assessment = row["recommendation"].get("strategy_assessment")
        scores = assessment.get("factor_clusters") if isinstance(assessment, dict) else None
    return scores if isinstance(scores, dict) else None


def _replayed_strategy_pnl(row: dict[str, Any], weights: dict[str, float]) -> float | None:
    """Replay the current entry policy and allocation under candidate cluster weights.

    Old records that only stored the final cluster scores cannot reproduce gates,
    probes, or risk sizing, so they are deliberately excluded from this track.
    """
    recommendation = row["recommendation"]
    assessment = recommendation.get("strategy_assessment")
    raw_return = _number(row["review"].get("final_return_pct"))
    if not isinstance(assessment, dict) or raw_return is None:
        return None
    decision_inputs = assessment.get("decision_inputs")
    if not isinstance(decision_inputs, dict):
        return None

    # Imported lazily so legacy component reports remain usable in stripped-down
    # offline environments that do not load the strategy engine.
    from .strategy import (
        DECISION_POLICY,
        StrategyEvidence,
        evaluate_strategy,
        get_strategy_profile,
    )

    if assessment.get("decision_policy") != DECISION_POLICY:
        return None
    horizon = assessment.get("horizon", recommendation.get("horizon"))
    if horizon not in {"short", "swing"}:
        return None
    try:
        profile = get_strategy_profile(str(horizon), leveraged=_is_leveraged(recommendation))
        evidence = StrategyEvidence(**decision_inputs)
    except (TypeError, ValueError):
        return None

    stored_strategy_id = assessment.get("strategy_id", recommendation.get("strategy_id"))
    if stored_strategy_id != profile.strategy_id:
        return None
    if set(weights) != set(profile.cluster_weights):
        return None
    numeric_weights = {key: _number(value) for key, value in weights.items()}
    if any(value is None or value < 0.0 for value in numeric_weights.values()):
        return None
    if not math.isclose(sum(numeric_weights.values()), 1.0, abs_tol=1e-9):
        return None
    if _number(evidence.planned_allocation_pct) is None:
        return None

    replayed = evaluate_strategy(
        replace(profile, cluster_weights={key: float(value) for key, value in numeric_weights.items()}),
        evidence,
    )
    if replayed.entry_decision not in {"enter", "probe"}:
        return 0.0
    allocation = _number(replayed.suggested_allocation_pct)
    if allocation is None or allocation <= 0.0:
        return 0.0
    return round(raw_return * allocation / 100.0, 8)


def _weighted_pnl(row: dict[str, Any], weights: dict[str, float], source: str = "component") -> float | None:
    scores = _score_source(row, source)
    raw_return = _number(row["review"].get("final_return_pct"))
    if scores is None or raw_return is None:
        return None
    if source == "cluster":
        return _replayed_strategy_pnl(row, weights)
    present = {
        key: (value, _number(scores.get(key)))
        for key, value in weights.items()
        if _number(scores.get(key)) is not None
    }
    if len(present) < max(3, len(weights) // 2):
        return None
    used_weight = sum(weight for weight, _ in present.values())
    signal = sum(weight * score for weight, score in present.values()) / used_weight
    direction = 1.0 if signal >= 50.0 else -1.0
    return direction * raw_return


def _score_candidate(
    rows: list[dict[str, Any]],
    weights: dict[str, float],
    base: dict[str, float],
    source: str = "component",
) -> float:
    pnl = [value for row in rows if (value := _weighted_pnl(row, weights, source)) is not None]
    metrics = _metrics(pnl)
    if metrics["expectancy_pct"] is None:
        return -math.inf
    regularization = sum((weights[key] - base[key]) ** 2 for key in base)
    drawdown_penalty = metrics["maximum_drawdown_pct"] / max(1, metrics["n"])
    return metrics["expectancy_pct"] - 0.25 * drawdown_penalty - 10.0 * regularization


def _walk_forward(
    rows: list[dict[str, Any]],
    base: dict[str, float],
    source: str = "component",
) -> list[dict[str, Any]]:
    folds: list[dict[str, Any]] = []
    for split in range(INITIAL_TRAIN_SIZE, len(rows) - TEST_SIZE + 1, TEST_SIZE):
        train = rows[:split]
        test = rows[split : split + TEST_SIZE]
        candidates = _candidate_weights(base)
        selected = max(candidates, key=lambda weights: _score_candidate(train, weights, base, source))
        baseline_pnl = [value for row in test if (value := _weighted_pnl(row, base, source)) is not None]
        candidate_pnl = [value for row in test if (value := _weighted_pnl(row, selected, source)) is not None]
        folds.append(
            {
                "train_n": len(train),
                "test_n": len(test),
                "train_start": train[0]["timestamp"],
                "train_end": train[-1]["timestamp"],
                "test_start": test[0]["timestamp"],
                "test_end": test[-1]["timestamp"],
                "selected_weights": {key: round(value, 6) for key, value in selected.items()},
                "out_of_sample": {
                    "baseline": _metrics(baseline_pnl),
                    "candidate": _metrics(candidate_pnl),
                },
            }
        )
    return folds


def _proposal_eligible(folds: list[dict[str, Any]]) -> bool:
    if not folds:
        return False
    baseline_exp = [fold["out_of_sample"]["baseline"]["expectancy_pct"] for fold in folds]
    candidate_exp = [fold["out_of_sample"]["candidate"]["expectancy_pct"] for fold in folds]
    baseline_dd = [fold["out_of_sample"]["baseline"]["maximum_drawdown_pct"] for fold in folds]
    candidate_dd = [fold["out_of_sample"]["candidate"]["maximum_drawdown_pct"] for fold in folds]
    complete = all(value is not None for value in baseline_exp + candidate_exp + baseline_dd + candidate_dd)
    return (
        complete
        and mean(candidate_exp) > mean(baseline_exp)
        and mean(candidate_dd) <= mean(baseline_dd) * 1.10
    )


def _cluster_base_weights(strategy_id: str) -> dict[str, float] | None:
    # Imported lazily to keep report generation usable without the strategy module
    # in stripped-down offline environments.
    from .strategy import SHORT_PROFILE, SWING_PROFILE

    for profile in (SHORT_PROFILE, SWING_PROFILE):
        if strategy_id == profile.strategy_id or strategy_id.startswith(profile.strategy_id + "+"):
            return dict(profile.cluster_weights)
    return None


def build_evidence_report(
    recommendations: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    current_weights: dict[str, float],
) -> dict[str, Any]:
    index = {
        (str(rec.get("code")), str(rec.get("timestamp"))): rec
        for rec in recommendations
        if rec.get("code") is not None and rec.get("timestamp") is not None
    }
    joined: list[dict[str, Any]] = []
    excluded_synthetic = 0
    excluded_incomplete = 0
    unmatched_reviews = 0
    for review in reviews:
        recommendation = index.get((str(review.get("code")), str(review.get("source_timestamp"))))
        if recommendation is None:
            unmatched_reviews += 1
            continue
        timestamp = _timestamp(review.get("source_timestamp"))
        if timestamp is None or _number(review.get("final_return_pct")) is None:
            excluded_incomplete += 1
            continue
        if _is_synthetic(recommendation, review):
            excluded_synthetic += 1
            continue
        if review.get("review_complete") is not True:
            excluded_incomplete += 1
            continue
        trade_id = review.get("trade_id") or recommendation.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id:
            trade_id = f"legacy:{recommendation.get('code')}:{recommendation.get('timestamp')}"
        joined.append(
            {
                "timestamp_value": timestamp,
                "timestamp": timestamp.isoformat(),
                "trade_id": trade_id,
                "strategy_id": _strategy_id(recommendation),
                "decision_policy": _decision_policy(recommendation),
                "leveraged": _is_leveraged(recommendation),
                "recommendation": recommendation,
                "review": review,
            }
        )

    joined_pairs = len(joined) + excluded_synthetic + excluded_incomplete
    joined.sort(key=lambda row: (row["timestamp_value"], row["trade_id"]))
    unique: dict[str, dict[str, Any]] = {}
    for row in joined:
        unique[row["trade_id"]] = row
    deduplicated = len(joined) - len(unique)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(unique.values(), key=lambda item: item["timestamp_value"]):
        instrument_class = "leveraged" if row["leveraged"] else "ordinary"
        grouped[f"{row['strategy_id']}|{row['decision_policy']}|{instrument_class}"].append(row)

    buckets: dict[str, Any] = {}
    for key, rows in sorted(grouped.items()):
        directionally_useful = len(rows) >= MIN_STRATEGY_BUCKET
        folds = _walk_forward(rows, current_weights) if directionally_useful else []
        strategy_id, decision_policy, instrument_class = key.rsplit("|", 2)

        # Parallel advisory track for the strategy-side cluster weights, so evidence
        # feedback reaches the authoritative track instead of only the legacy score.
        cluster_base = _cluster_base_weights(strategy_id)
        cluster_rows = [
            row
            for row in rows
            if cluster_base is not None
            and _weighted_pnl(row, cluster_base, "cluster") is not None
        ]
        cluster_folds = (
            _walk_forward(cluster_rows, cluster_base, "cluster")
            if cluster_base is not None and len(cluster_rows) >= MIN_STRATEGY_BUCKET
            else []
        )
        cluster_notes: list[str] = []
        if cluster_base is None:
            cluster_notes.append("No cluster-weight baseline for this strategy_id; cluster advisory skipped.")
        elif len(cluster_rows) < MIN_STRATEGY_BUCKET:
            cluster_notes.append(
                f"Need {MIN_STRATEGY_BUCKET} closed trades with factor_clusters and replayable "
                "decision_inputs from the current decision policy for a cluster-weight advisory."
            )

        buckets[key] = {
            "phase": _phase(strategy_id),
            "strategy_id": strategy_id,
            "decision_policy": decision_policy,
            "instrument_class": instrument_class,
            "closed_trades": len(rows),
            "minimum_required": MIN_STRATEGY_BUCKET,
            "directionally_useful": directionally_useful,
            "proposal_eligible": _proposal_eligible(folds),
            "advisory_only": True,
            "walk_forward_folds": folds,
            "latest_advisory_weights": folds[-1]["selected_weights"] if folds else None,
            "cluster_walk_forward_folds": cluster_folds,
            "cluster_proposal_eligible": _proposal_eligible(cluster_folds),
            "latest_advisory_cluster_weights": cluster_folds[-1]["selected_weights"] if cluster_folds else None,
            "weights_targets": {
                "walk_forward_folds": "legacy-component-weights",
                "cluster_walk_forward_folds": "strategy-cluster-weights",
            },
            "notes": (
                [] if directionally_useful else [f"Need {MIN_STRATEGY_BUCKET} unique realised closed trades in this exact bucket."]
            ) + cluster_notes,
        }

    phase_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in unique.values():
        phase_rows[_phase(row["strategy_id"])].append(row)
    phase_comparison = {
        phase: _metrics([value for row in sorted(rows, key=lambda item: item["timestamp_value"]) if (value := _observed_pnl(row)) is not None])
        for phase, rows in sorted(phase_rows.items())
    }

    return {
        "schema_version": "evidence-optimization-v3",
        "joined_pairs": joined_pairs,
        "unmatched_reviews": unmatched_reviews,
        "excluded_synthetic": excluded_synthetic,
        "excluded_incomplete": excluded_incomplete,
        "deduplicated_trades": deduplicated,
        "eligible_closed_trades": len(unique),
        "buckets": buckets,
        "phase_comparison": phase_comparison,
        "automatic_apply_allowed": False,
        "notes": [
            "All proposals are advisory; this report never writes weights.",
            "Training selection and out-of-sample evaluation use non-overlapping chronological windows.",
            "walk_forward_folds advise the legacy component weights; cluster_walk_forward_folds advise the strategy cluster weights.",
            "Cluster candidates replay gates, entry/probe decisions, and risk-sized allocation; non-actionable observations contribute zero exposure.",
            "Buckets are keyed by strategy_id, decision_policy, and instrument class so policy changes never share samples.",
        ],
    }
