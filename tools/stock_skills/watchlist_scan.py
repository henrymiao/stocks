from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import asdict
from typing import Any, Protocol

from .data_quality import detect_stale_components
from .models import MarketSnapshot
from .session import classify_session_phase


class SnapshotFetcher(Protocol):
    def get_snapshots(self, codes: list[str]) -> list[MarketSnapshot]: ...


DeepAnalyzer = Callable[[dict[str, Any], str, dict[str, MarketSnapshot]], dict[str, Any]]


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _change_pct(snapshot: MarketSnapshot | None) -> float | None:
    if snapshot is None or snapshot.prev_close <= 0:
        return None
    return (snapshot.last_price - snapshot.prev_close) / snapshot.prev_close * 100.0


def _liquidity_score(snapshot: MarketSnapshot) -> float:
    if snapshot.turnover <= 0:
        return 0.0
    return _clamp((math.log10(snapshot.turnover) - 4.0) * 20.0)


# Tags that describe where a name trades or what we currently hold of it, rather than
# what it is. A theme has to survive a position being opened or closed.
_NON_THEME_TAGS = frozenset(
    {
        "us", "hk", "a-share", "china", "hk-focus", "broad-screen",
        "holding", "exited-watch", "wait-reentry", "oversold-watch", "probe",
        "core", "core-thesis", "etf", "index", "leveraged", "hedge", "macro",
        "growth", "value", "defensive", "cyclical", "high-volatility", "momentum",
    }
)


def _entry_theme(entry: dict[str, Any]) -> str:
    """Theme bucket used for the per-theme deep-analysis quota.

    Prefers an explicit ``theme`` field; otherwise takes the first tag that names a
    business, not a market or a position state. Momentum ranking alone will crowd whole
    sectors out of the analysis queue indefinitely -- a defensive name that moves 0.2% a
    day can never place in a Top-N or Bottom-N by daily change -- so the quota needs a
    grouping that is stable across days.
    """

    explicit = entry.get("theme")
    if isinstance(explicit, str) and explicit:
        return explicit
    for tag in entry.get("tags", []):
        if isinstance(tag, str) and tag and tag not in _NON_THEME_TAGS:
            return tag
    return "unclassified"


def _entry_scan_policy(entry: dict[str, Any]) -> str:
    policy = entry.get("scan_policy")
    if isinstance(policy, str):
        return policy
    if entry["tier"] == "core":
        return "always"
    if entry["tier"] in {"proxy", "discovery"}:
        return "snapshot-only"
    return "ranked"


def _cheap_score(
    entry: dict[str, Any],
    snapshot: MarketSnapshot,
    benchmark: MarketSnapshot | None,
    horizon: str,
) -> tuple[float, float | None, float | None]:
    change = _change_pct(snapshot)
    benchmark_change = _change_pct(benchmark)
    relative_strength = None if change is None or benchmark_change is None else change - benchmark_change
    momentum = _clamp(50.0 + (change or 0.0) * (6.0 if horizon == "short" else 3.0))
    relative = _clamp(50.0 + (relative_strength or 0.0) * (6.0 if horizon == "short" else 4.0))
    liquidity = _liquidity_score(snapshot)
    priority = float(entry["priority"])
    if horizon == "short":
        score = momentum * 0.38 + relative * 0.32 + liquidity * 0.20 + priority * 0.10
    else:
        score = momentum * 0.22 + relative * 0.28 + liquidity * 0.20 + priority * 0.30
    return round(score, 2), change, relative_strength


def _snapshot_codes(entries: Iterable[dict[str, Any]], context_codes: Iterable[str] = ()) -> list[str]:
    codes: list[str] = []
    for entry in entries:
        for code in (entry["code"], entry.get("benchmark"), entry.get("underlying_proxy")):
            if code and code not in codes:
                codes.append(code)
    for code in context_codes:
        if code and code not in codes:
            codes.append(code)
    return codes


def _candidate_record(entry: dict[str, Any], snapshots: dict[str, MarketSnapshot]) -> dict[str, Any]:
    snapshot = snapshots.get(entry["code"])
    reasons: list[str] = []
    session_phase = "unknown"
    stale_components: frozenset[str] = frozenset()
    if snapshot is None:
        reasons.append("missing-snapshot")
    else:
        session_phase = classify_session_phase(snapshot.code, snapshot.captured_at or snapshot.timestamp)
        stale_components = detect_stale_components(snapshot, None, session_phase)
        if snapshot.last_price <= 0 or snapshot.prev_close <= 0:
            reasons.append("invalid-price")
        if snapshot.turnover <= 0 and entry.get("asset_type") != "crypto":
            reasons.append("non-positive-turnover")
        if "trend" in stale_components:
            reasons.append("stale-snapshot")

    record: dict[str, Any] = {
        "code": entry["code"],
        "name": entry["name"],
        "tier": entry["tier"],
        "priority": entry["priority"],
        "strategy_profiles": entry["strategy_profiles"],
        "position_status": entry.get("position_status", "watch"),
        "scan_policy": _entry_scan_policy(entry),
        "filter_status": "rejected" if reasons else "eligible",
        "rejection_reasons": reasons,
        "treatment": "snapshot-only" if entry["tier"] in {"proxy", "discovery"} else "rank-only",
    }
    if snapshot is None:
        record.update(
            snapshot=None,
            session_phase="unknown",
            snapshot_confidence=0.0,
            stale_components=[],
            scores={},
        )
        return record

    benchmark = snapshots.get(entry.get("benchmark"))
    scores: dict[str, float] = {}
    change = _change_pct(snapshot)
    benchmark_change = _change_pct(benchmark)
    relative_strength = None if change is None or benchmark_change is None else change - benchmark_change
    if not reasons:
        for horizon in entry["strategy_profiles"]:
            score, _, _ = _cheap_score(entry, snapshot, benchmark, horizon)
            scores[horizon] = score
    available = 2 + int(benchmark is not None)
    record.update(
        snapshot=asdict(snapshot),
        session_phase=session_phase,
        snapshot_confidence=round(max(0.0, available / 3.0 - 0.25 * len(stale_components)), 2),
        stale_components=sorted(stale_components),
        change_pct=None if change is None else round(change, 3),
        relative_strength_pct=None if relative_strength is None else round(relative_strength, 3),
        scores=scores,
    )
    return record


def run_watchlist_scan(
    entries: list[dict[str, Any]],
    fetcher: SnapshotFetcher,
    *,
    analyzer: DeepAnalyzer | None = None,
    deep_top: int = 10,
    deep_bottom: int = 5,
    deep_per_theme: int = 0,
    deep_horizons: tuple[str, ...] = ("short",),
    context_codes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Batch-filter a validated watchlist and promote only core/top thematic names.

    This is a promotion scanner, not a trading model. Cheap snapshot scores only decide
    which names deserve the expensive strategy analysis; rejected and snapshot-only rows
    never receive a recommendation.
    """
    if deep_top < 0:
        raise ValueError("deep_top must be non-negative")
    if deep_bottom < 0:
        raise ValueError("deep_bottom must be non-negative")
    if deep_per_theme < 0:
        raise ValueError("deep_per_theme must be non-negative")
    invalid_horizons = set(deep_horizons) - {"short", "swing"}
    if invalid_horizons:
        raise ValueError(f"Invalid deep horizons: {sorted(invalid_horizons)}")

    codes = _snapshot_codes(entries, context_codes)
    snapshot_list = fetcher.get_snapshots(codes)
    snapshots = {snapshot.code: snapshot for snapshot in snapshot_list}
    candidates = [_candidate_record(entry, snapshots) for entry in entries]
    by_code = {entry["code"]: entry for entry in entries}

    rankings: dict[str, list[dict[str, Any]]] = {}
    for horizon in ("short", "swing"):
        ranked = [
            row for row in candidates
            if row["tier"] == "thematic"
            and _entry_scan_policy(by_code[row["code"]]) == "ranked"
            and row["filter_status"] == "eligible"
            and horizon in row["scores"]
        ]
        ranked.sort(key=lambda row: (-row["scores"][horizon], -row["priority"], row["code"]))
        rankings[horizon] = [
            {"rank": index, "code": row["code"], "score": row["scores"][horizon]}
            for index, row in enumerate(ranked, start=1)
        ]

    selected: dict[str, set[str]] = {"short": set(), "swing": set()}
    selections: dict[str, list[dict[str, Any]]] = {"short": [], "swing": []}
    for horizon in deep_horizons:
        reasons_by_code: dict[str, set[str]] = {}
        for row in candidates:
            if (
                row["filter_status"] == "eligible"
                and horizon in row["strategy_profiles"]
                and _entry_scan_policy(by_code[row["code"]]) == "always"
            ):
                reasons_by_code.setdefault(row["code"], set()).add("always")

        for item in rankings[horizon][:deep_top]:
            reasons_by_code.setdefault(item["code"], set()).add("top")

        bottom_candidates = [
            row
            for row in candidates
            if row["tier"] == "thematic"
            and _entry_scan_policy(by_code[row["code"]]) == "ranked"
            and row["filter_status"] == "eligible"
            and horizon in row["scores"]
        ]
        bottom_candidates.sort(
            key=lambda row: (
                math.inf if row.get("change_pct") is None else row["change_pct"],
                math.inf if row.get("relative_strength_pct") is None else row["relative_strength_pct"],
                row["code"],
            )
        )
        for row in bottom_candidates[:deep_bottom]:
            reasons_by_code.setdefault(row["code"], set()).add("bottom")

        # Momentum ranking is not a neutral filter: it systematically starves whole themes.
        # Banks, staples and energy move a fraction of what a semiconductor moves, so they
        # can never place in a Top-N or Bottom-N by daily change and are never scored at
        # all -- which reads as "nothing there qualifies" when nothing there was tested.
        # The quota guarantees each theme reaches the gates on its own best-ranked names.
        if deep_per_theme:
            by_theme: dict[str, list[dict[str, Any]]] = {}
            rank_of = {item["code"]: item["rank"] for item in rankings[horizon]}
            for row in candidates:
                if (
                    row["tier"] == "thematic"
                    and _entry_scan_policy(by_code[row["code"]]) == "ranked"
                    and row["filter_status"] == "eligible"
                    and horizon in row["scores"]
                ):
                    by_theme.setdefault(_entry_theme(by_code[row["code"]]), []).append(row)
            for theme, rows in sorted(by_theme.items()):
                already = sum(1 for row in rows if row["code"] in reasons_by_code)
                if already >= deep_per_theme:
                    continue
                rows.sort(key=lambda row: (rank_of.get(row["code"], math.inf), row["code"]))
                for row in rows:
                    if already >= deep_per_theme:
                        break
                    if row["code"] in reasons_by_code:
                        continue
                    reasons_by_code.setdefault(row["code"], set()).add("theme-quota")
                    already += 1

        ordered_codes = sorted(
            reasons_by_code,
            key=lambda code: (
                min(
                    {"always": 0, "top": 1, "bottom": 2, "theme-quota": 3}[reason]
                    for reason in reasons_by_code[code]
                ),
                -by_code[code]["priority"],
                code,
            ),
        )
        selected[horizon] = set(ordered_codes)
        selections[horizon] = [
            {
                "code": code,
                "selection_reasons": sorted(reasons_by_code[code]),
            }
            for code in ordered_codes
        ]

    candidate_by_code = {row["code"]: row for row in candidates}
    deep_analysis: list[dict[str, Any]] = []
    if analyzer is not None:
        for horizon in deep_horizons:
            ordered = sorted(
                selected[horizon],
                key=lambda code: (
                    0 if by_code[code]["tier"] == "core" else 1,
                    -by_code[code]["priority"],
                    code,
                ),
            )
            for code in ordered:
                recommendation = analyzer(by_code[code], horizon, snapshots)
                deep_analysis.append({"code": code, "horizon": horizon, "recommendation": recommendation})
                candidate_by_code[code]["treatment"] = "deep-analysis"

    missing_codes = [code for code in codes if code not in snapshots]
    return {
        "schema_version": "watchlist-scan-v2",
        "snapshot_request_count": len(codes),
        "snapshot_received_count": len(snapshots),
        "missing_snapshot_codes": missing_codes,
        "rankings": rankings,
        "selections": selections,
        "candidates": candidates,
        "deep_analysis": deep_analysis,
    }
