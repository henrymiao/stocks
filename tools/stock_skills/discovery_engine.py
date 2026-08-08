from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time, timedelta
from typing import Any, Callable

from .discovery_features import (
    SectorFeatureContext,
    TrackFeatureSet,
    build_sector_context,
    completed_daily_bars,
    compute_discovery_tracks,
)
from .models import KLineBar
from .universe import MarketUniverse, SectorUniverse, market_timezone, normalize_market


DISCOVERY_SCHEMA = "opportunity-discovery-v1"
DISCOVERY_STATES = {"forming", "armed", "triggered", "invalidated", "expired"}

# Median daily turnover, in each market's own currency, below which an instrument is not
# investable and therefore cannot be an opportunity. A bad setup and an untradable listing
# are different refusals: the first is a veto on the setup, this is a veto on the name.
# `analyze` already refuses these downstream, so without the same floor here discovery
# spends its alert budget on names that could never be traded -- on 2026-08-07, 36 of the
# 65 armed HK candidates turned over less than HK$100m and the top-scoring one was a shell.
MINIMUM_MEDIAN_TURNOVER = {"CN": 2.0e8, "HK": 1.0e8, "US": 2.0e7}


@dataclass(frozen=True)
class DiscoveryConfig:
    forming_score: float = 55.0
    armed_score: float = 65.0
    minimum_sector_coverage: float = 0.70
    minimum_feature_coverage: float = 0.70
    minimum_supporting_groups: int = 2
    minimum_armed_breadth: float = 0.35
    short_valid_sessions: int = 3
    swing_valid_sessions: int = 10
    trigger_breadth: float = 0.55
    trigger_leader_breadth: float = 0.50
    invalidation_breadth: float = 0.30
    invalidation_capital_improvement: float = 20.0
    maximum_intraday_bar_age_minutes: int = 10
    liquidity_sessions: int = 20
    liquidity_floor: float | None = None  # overrides the per-market table below


@dataclass(frozen=True)
class DiscoveryCandidate:
    discovery_id: str
    market: str
    sector: str
    sector_name: str
    code: str
    name: str
    representative: str
    benchmark: str
    track: str
    horizon: str
    score: float
    evidence_clusters: tuple[str, ...]
    feature_snapshot: dict[str, Any]
    state: str
    first_seen_at: str
    updated_at: str
    expires_at: str
    trigger_level: float
    structural_invalidation: float
    data_coverage: float
    provenance: dict[str, Any]
    transition_history: tuple[dict[str, Any], ...] = ()
    armed_at: str | None = None
    triggered_at: str | None = None
    invalidated_at: str | None = None
    expired_at: str | None = None
    deep_analysis: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.state not in DISCOVERY_STATES:
            raise ValueError(f"Unknown discovery state: {self.state!r}")
        if self.horizon not in {"short", "swing"}:
            raise ValueError(f"Unknown discovery horizon: {self.horizon!r}")
        if self.trigger_level <= 0 or self.structural_invalidation <= 0:
            raise ValueError("Discovery trigger and invalidation must be positive")

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_clusters"] = list(self.evidence_clusters)
        payload["transition_history"] = list(self.transition_history)
        return payload


def candidate_from_record(payload: dict[str, Any]) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        discovery_id=str(payload["discovery_id"]),
        market=normalize_market(str(payload["market"])),
        sector=str(payload["sector"]),
        sector_name=str(payload.get("sector_name") or payload["sector"]),
        code=str(payload["code"]),
        name=str(payload.get("name") or payload["code"]),
        representative=str(payload["representative"]),
        benchmark=str(payload["benchmark"]),
        track=str(payload["track"]),
        horizon=str(payload.get("horizon", "short")),
        score=float(payload["score"]),
        evidence_clusters=tuple(payload.get("evidence_clusters", ())),
        feature_snapshot=dict(payload.get("feature_snapshot", {})),
        state=str(payload["state"]),
        first_seen_at=str(payload["first_seen_at"]),
        updated_at=str(payload["updated_at"]),
        expires_at=str(payload["expires_at"]),
        trigger_level=float(payload["trigger_level"]),
        structural_invalidation=float(payload["structural_invalidation"]),
        data_coverage=float(payload.get("data_coverage", 0.0)),
        provenance=dict(payload.get("provenance", {})),
        transition_history=tuple(payload.get("transition_history", ())),
        armed_at=payload.get("armed_at"),
        triggered_at=payload.get("triggered_at"),
        invalidated_at=payload.get("invalidated_at"),
        expired_at=payload.get("expired_at"),
        deep_analysis=payload.get("deep_analysis"),
    )


def _parse_local(value: str, market: str) -> datetime:
    moment = datetime.fromisoformat(value)
    tz = market_timezone(market)
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)


def _add_trading_sessions(
    moment: str,
    market: str,
    sessions: int,
    trading_sessions: tuple[str, ...] | None = None,
) -> str:
    current = _parse_local(moment, market)
    if trading_sessions is not None:
        available = sorted(
            {
                datetime.fromisoformat(value).date()
                for value in trading_sessions
                if datetime.fromisoformat(value).date() > current.date()
            }
        )
        if len(available) < sessions:
            raise ValueError(
                f"Trading calendar has {len(available)} future sessions; need {sessions}"
            )
        expiry = available[sessions - 1]
        return current.replace(
            year=expiry.year,
            month=expiry.month,
            day=expiry.day,
        ).isoformat(timespec="seconds")
    remaining = sessions
    cursor = current
    while remaining > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor.isoformat(timespec="seconds")


def _discovery_id(
    market: str,
    sector: str,
    code: str,
    track: str,
    first_seen_at: str,
) -> str:
    local_date = _parse_local(first_seen_at, market).date().isoformat()
    raw = f"{market}|{sector}|{code}|{track}|{local_date}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{market.lower()}-{track[:3]}-{digest}"


def _transition(
    candidate: DiscoveryCandidate,
    state: str,
    at: str,
    reason: str,
    **changes: Any,
) -> DiscoveryCandidate:
    if state not in DISCOVERY_STATES:
        raise ValueError(f"Unknown discovery state: {state!r}")
    if state == candidate.state:
        return replace(candidate, updated_at=at, **changes)
    history = candidate.transition_history + (
        {"from": candidate.state, "to": state, "at": at, "reason": reason},
    )
    timestamps: dict[str, Any] = {}
    if state == "armed":
        timestamps["armed_at"] = at
    elif state == "triggered":
        timestamps["triggered_at"] = at
    elif state == "invalidated":
        timestamps["invalidated_at"] = at
    elif state == "expired":
        timestamps["expired_at"] = at
    return replace(
        candidate,
        state=state,
        updated_at=at,
        transition_history=history,
        **timestamps,
        **changes,
    )


def _median_turnover(bars: list[KLineBar], sessions: int) -> float | None:
    values = sorted(bar.turnover for bar in bars[-sessions:] if bar.turnover > 0)
    if not values:
        return None
    middle = len(values) // 2
    return (
        values[middle]
        if len(values) % 2
        else (values[middle - 1] + values[middle]) / 2.0
    )


def _initial_state(
    track: TrackFeatureSet,
    context: SectorFeatureContext,
    config: DiscoveryConfig,
) -> str | None:
    """Score and evidence decide `forming` vs `armed`; sector strength only gates.

    Arming counts `instrument_supporting_groups`, not every supporting group. `breadth` is
    a required gate here, and `breadth` and `leaders` are both computed from the sector, so
    counting them toward the two-group minimum let a hot sector satisfy the whole evidence
    requirement on its own -- the gate doubled as one of the two votes it was gating. On
    2026-08-07 that armed 34 of 35 resources names and 33 of 35 innovative-medicine names
    in CN, 57% of the universe, with the price and flow groups never consulted.
    """

    if track.score < config.forming_score:
        return None
    can_arm = (
        track.score >= config.armed_score
        and len(track.instrument_supporting_groups) >= config.minimum_supporting_groups
        and "breadth" in track.supporting_groups
        and context.breadth is not None
        and context.breadth >= config.minimum_armed_breadth
        and track.feature_coverage >= config.minimum_feature_coverage
        and context.coverage >= config.minimum_sector_coverage
        and not track.hard_vetoes
    )
    return "armed" if can_arm else "forming"


def _member_name(sector: SectorUniverse, code: str) -> str:
    for member in sector.members:
        if member.code == code:
            return member.name
    return code


def _sector_opportunity_record(
    sector: SectorUniverse,
    candidates: list[DiscoveryCandidate],
) -> dict[str, Any]:
    ranked = sorted(candidates, key=lambda candidate: (-candidate.score, candidate.code))
    best = ranked[0]
    representative = next(
        (candidate for candidate in ranked if candidate.code == sector.representative),
        None,
    )
    leader_codes = {
        member.code for member in sector.members if member.role == "leader"
    }
    leaders: list[DiscoveryCandidate] = []
    seen_leaders: set[str] = set()
    for candidate in ranked:
        if candidate.code not in leader_codes or candidate.code in seen_leaders:
            continue
        leaders.append(candidate)
        seen_leaders.add(candidate.code)
        if len(leaders) == 3:
            break
    return {
        "sector": sector.key,
        "sector_name": sector.name,
        "score": best.score,
        "state": best.state,
        "track": best.track,
        "best_candidate": best.to_record(),
        "representative": (
            representative.to_record()
            if representative is not None
            else {
                "code": sector.representative,
                "name": _member_name(sector, sector.representative),
                "state": "not-qualified",
            }
        ),
        "leaders": [candidate.to_record() for candidate in leaders],
    }


def _build_candidate(
    universe: MarketUniverse,
    sector: SectorUniverse,
    code: str,
    track: TrackFeatureSet,
    context: SectorFeatureContext,
    evaluated_at: str,
    horizon: str,
    state: str,
    config: DiscoveryConfig,
    trading_sessions: tuple[str, ...] | None,
) -> DiscoveryCandidate:
    validity = (
        config.short_valid_sessions
        if horizon == "short"
        else config.swing_valid_sessions
    )
    coverage = min(context.coverage, track.feature_coverage)
    transition = {
        "from": None,
        "to": state,
        "at": evaluated_at,
        "reason": "score-and-evidence-threshold",
    }
    return DiscoveryCandidate(
        discovery_id=_discovery_id(universe.market, sector.key, code, track.track, evaluated_at),
        market=universe.market,
        sector=sector.key,
        sector_name=sector.name,
        code=code,
        name=_member_name(sector, code),
        representative=sector.representative,
        benchmark=sector.benchmark,
        track=track.track,
        horizon=horizon,
        score=track.score,
        evidence_clusters=track.supporting_groups,
        feature_snapshot={
            "track": track.to_record(),
            "sector": context.to_record(),
        },
        state=state,
        first_seen_at=evaluated_at,
        updated_at=evaluated_at,
        expires_at=_add_trading_sessions(
            evaluated_at,
            universe.market,
            validity,
            trading_sessions,
        ),
        trigger_level=float(track.trigger_level),
        structural_invalidation=float(track.invalidation_level),
        data_coverage=round(coverage, 4),
        provenance={
            "universe_source": universe.source,
            "universe_as_of": universe.as_of,
            "evaluation_timestamp": evaluated_at,
            "bars": "OpenD-or-offline-completed-daily",
            "coverage": round(coverage, 4),
        },
        transition_history=(transition,),
        armed_at=evaluated_at if state == "armed" else None,
    )


def _merge_existing(
    candidate: DiscoveryCandidate,
    existing: DiscoveryCandidate | None,
    at: str,
) -> DiscoveryCandidate:
    if existing is None or existing.state in {"invalidated", "expired"}:
        return candidate
    target_state = candidate.state
    merged = replace(
        candidate,
        discovery_id=existing.discovery_id,
        state=existing.state,
        first_seen_at=existing.first_seen_at,
        transition_history=existing.transition_history,
        armed_at=existing.armed_at,
        triggered_at=existing.triggered_at,
    )
    if existing.state == "triggered" and target_state in {"forming", "armed"}:
        return replace(merged, state="triggered")
    if existing.state == target_state:
        return replace(merged, updated_at=at)
    return _transition(merged, target_state, at, "after-close-score-refresh")


def discover_universe(
    universe: MarketUniverse,
    bars_by_code: dict[str, list[KLineBar]],
    *,
    evaluated_at: str,
    capital_improvement: dict[str, float] | None = None,
    horizon: str = "short",
    existing: dict[tuple[str, str, str], DiscoveryCandidate] | None = None,
    config: DiscoveryConfig | None = None,
    trading_sessions: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run deterministic after-close opportunity discovery.

    The function emits candidates only.  It never calls the executable strategy
    assessment and therefore cannot produce `probe` or `enter`.
    """

    if horizon not in {"short", "swing"}:
        raise ValueError("horizon must be short or swing")
    config = config or DiscoveryConfig()
    market = normalize_market(universe.market)
    capital_improvement = capital_improvement or {}
    existing = existing or {}
    completed = {
        code: completed_daily_bars(bars, evaluated_at=evaluated_at, market=market)
        for code, bars in bars_by_code.items()
    }
    candidates: list[DiscoveryCandidate] = []
    disabled_sectors: list[dict[str, Any]] = []
    floor = (
        config.liquidity_floor
        if config.liquidity_floor is not None
        else MINIMUM_MEDIAN_TURNOVER.get(market, 0.0)
    )
    # Funds are exempt. Daily turnover is the right liquidity proxy for an ordinary stock,
    # but an ETF is quoted by market makers against the basket it holds, so its own tape
    # understates what can be traded. Applying the stock floor to them excluded the
    # innovative-medicine and ev-battery representatives at CNY 174m and 144m a day --
    # both perfectly tradable, and both the safest way to express a view on their sector.
    priced_as_stock = {
        member.code
        for sector in universe.sectors
        for member in sector.members
        if member.role not in {"etf", "index"}
    }
    illiquid: dict[str, float] = {}
    for code in sorted(priced_as_stock):
        turnover = _median_turnover(completed.get(code, []), config.liquidity_sessions)
        # Unknown turnover is not a refusal: the fixture and offline paths carry bars
        # without it, and silently dropping every name there would hide the whole universe.
        if turnover is not None and turnover < floor:
            illiquid[code] = turnover

    for sector in universe.sectors:
        context = build_sector_context(sector, completed)
        if context.coverage < config.minimum_sector_coverage:
            disabled_sectors.append(
                {
                    "sector": sector.key,
                    "reason": "constituent-coverage-below-70pct",
                    "coverage": context.coverage,
                }
            )
        benchmark = completed.get(sector.benchmark, [])
        for member in sector.members:
            if member.role == "index":
                continue
            bars = completed.get(member.code, [])
            trend, reversal = compute_discovery_tracks(
                bars,
                benchmark,
                context,
                capital_improvement=capital_improvement.get(member.code),
            )
            for track in (trend, reversal):
                state = _initial_state(track, context, config)
                previous = existing.get((sector.key, member.code, track.track))
                if member.code in illiquid:
                    # Never a new candidate, and an active one is retired with its reason
                    # rather than dropped, so the store never keeps a stale armed row.
                    if previous is not None and previous.state in {
                        "forming",
                        "armed",
                        "triggered",
                    }:
                        candidates.append(
                            _transition(
                                previous,
                                "invalidated",
                                evaluated_at,
                                "below-liquidity-floor",
                            )
                        )
                    continue
                if (
                    previous is not None
                    and previous.state in {"forming", "armed"}
                    and _parse_local(evaluated_at, market)
                    > _parse_local(previous.expires_at, market)
                ):
                    candidates.append(
                        _transition(
                            previous,
                            "expired",
                            evaluated_at,
                            "validity-window-ended",
                        )
                    )
                    previous = None

                evidence_coverage_sufficient = (
                    context.coverage >= config.minimum_sector_coverage
                    and track.feature_coverage >= config.minimum_feature_coverage
                )
                if (
                    previous is not None
                    and previous.state in {"forming", "armed", "triggered"}
                    and not evidence_coverage_sufficient
                ):
                    candidates.append(previous)
                    continue
                if (
                    previous is not None
                    and previous.state in {"forming", "armed", "triggered"}
                    and evidence_coverage_sufficient
                    and track.hard_vetoes
                ):
                    candidates.append(
                        _transition(
                            previous,
                            "invalidated",
                            evaluated_at,
                            "hard-discovery-veto",
                        )
                    )
                    continue

                if (
                    state is not None
                    and track.trigger_level is not None
                    and track.invalidation_level is not None
                ):
                    candidate = _build_candidate(
                        universe,
                        sector,
                        member.code,
                        track,
                        context,
                        evaluated_at,
                        horizon,
                        state,
                        config,
                        trading_sessions,
                    )
                    candidates.append(
                        _merge_existing(candidate, previous, evaluated_at)
                    )
                elif previous is None or previous.state not in {
                    "forming",
                    "armed",
                    "triggered",
                }:
                    continue
                # A score collapse or hard veto clears a previously active
                # discovery, but missing/low-coverage evidence preserves it.
                elif (
                    evidence_coverage_sufficient
                    and track.score < config.forming_score
                ):
                    candidates.append(
                        _transition(
                            previous,
                            "invalidated",
                            evaluated_at,
                            "material-score-collapse",
                        )
                    )
                else:
                    candidates.append(previous)

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.sector, candidate.code))
    sector_candidates: dict[str, list[DiscoveryCandidate]] = {}
    for candidate in candidates:
        if candidate.state not in {"forming", "armed"}:
            continue
        sector_candidates.setdefault(candidate.sector, []).append(candidate)
    sector_by_key = {sector.key: sector for sector in universe.sectors}
    sectors = sorted(
        (
            _sector_opportunity_record(sector_by_key[key], rows)
            for key, rows in sector_candidates.items()
        ),
        key=lambda row: (-float(row["score"]), str(row["sector"])),
    )
    def unique_instruments(
        rows: list[DiscoveryCandidate], limit: int
    ) -> list[DiscoveryCandidate]:
        selected: list[DiscoveryCandidate] = []
        seen: set[str] = set()
        for row in rows:
            if row.code in seen:
                continue
            selected.append(row)
            seen.add(row.code)
            if len(selected) == limit:
                break
        return selected

    armed = unique_instruments(
        [candidate for candidate in candidates if candidate.state == "armed"], 10
    )
    forming = unique_instruments(
        [candidate for candidate in candidates if candidate.state == "forming"], 5
    )
    return {
        "schema_version": DISCOVERY_SCHEMA,
        "mode": "after-close-discovery",
        "market": market,
        "market_timezone": str(market_timezone(market)),
        "evaluated_at": evaluated_at,
        "horizon": horizon,
        "sector_opportunities": sectors[:5],
        "armed": [candidate.to_record() for candidate in armed],
        "forming": [candidate.to_record() for candidate in forming],
        "candidates": [candidate.to_record() for candidate in candidates],
        "disabled_sectors": disabled_sectors,
        "liquidity_floor": {
            "minimum_median_turnover": floor,
            "sessions": config.liquidity_sessions,
            "excluded": [
                {"code": code, "median_turnover": round(value, 2)}
                for code, value in sorted(illiquid.items(), key=lambda row: -row[1])
            ],
        },
        "limits": {"sector_opportunities": 5, "armed": 10, "forming": 5},
        "entry_recommendation": None,
        "notes": [
            "Discovery scores promote analysis candidates only; they are not entry scores.",
            "A triggered candidate must still pass the existing deep strategy assessment.",
        ],
    }


def _latest_completed_five_minute(
    bars: list[KLineBar],
    evaluated_at: str,
    market: str,
    *,
    maximum_age: timedelta,
) -> KLineBar | None:
    if not bars:
        return None
    local = _parse_local(evaluated_at, market)
    usable: list[tuple[datetime, KLineBar]] = []
    for bar in bars:
        try:
            moment = _parse_local(bar.time, market)
        except ValueError:
            continue
        values = (bar.open, bar.high, bar.low, bar.close, bar.turnover)
        valid = (
            all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)
            and bar.volume > 0
            and bar.low > 0
            and bar.high >= max(bar.open, bar.close, bar.low)
            and bar.low <= min(bar.open, bar.close, bar.high)
        )
        # OpenD K-line timestamps identify the start of the interval.  A 09:50
        # candle is therefore usable at 09:55, never at 09:52.
        completed_at = moment + timedelta(minutes=5)
        age = local - completed_at
        if valid and timedelta(0) <= age <= maximum_age:
            usable.append((moment, bar))
    return max(usable, key=lambda item: item[0])[1] if usable else None


DeepAnalyzer = Callable[[DiscoveryCandidate], dict[str, Any]]


def _inside(value: time, start: time, end: time) -> bool:
    return start <= value < end


def _confirmation_session_is_open(
    evaluated_at: str,
    market: str,
    trading_sessions: tuple[str, ...] | None,
) -> bool:
    local = _parse_local(evaluated_at, market)
    if trading_sessions is None:
        if local.weekday() >= 5:
            return False
    elif local.date().isoformat() not in set(trading_sessions):
        return False
    current = local.time()
    if market == "US":
        return _inside(current, time(9, 45), time(16))
    if market == "HK":
        return _inside(current, time(9, 45), time(12)) or _inside(
            current, time(13), time(16)
        )
    return _inside(current, time(9, 45), time(11, 30)) or _inside(
        current, time(13), time(15)
    )


def _analysis_needs_retry(candidate: DiscoveryCandidate) -> bool:
    analysis = candidate.deep_analysis
    return analysis is None or bool(analysis.get("retryable")) or bool(analysis.get("error"))


def _invoke_deep_analysis(
    candidate: DiscoveryCandidate,
    analyzer: DeepAnalyzer,
    *,
    evaluated_at: str,
    retry: bool,
) -> tuple[DiscoveryCandidate, dict[str, Any]]:
    try:
        analysis = analyzer(candidate)
    except Exception as exc:  # isolate transient child-analysis failures
        analysis = {
            "entry_decision": "defer",
            "error": f"{type(exc).__name__}: {exc}",
            "retryable": True,
        }
    changed = replace(candidate, updated_at=evaluated_at, deep_analysis=analysis)
    return changed, {
        "discovery_id": changed.discovery_id,
        "code": changed.code,
        "deep_analysis_invoked": True,
        "retry": retry,
        "strategy_result": analysis,
    }


def confirm_discoveries(
    candidates: list[DiscoveryCandidate],
    intraday_bars: dict[str, list[KLineBar]],
    sector_confirmation: dict[str, dict[str, float]],
    *,
    evaluated_at: str,
    instrument_confirmation: dict[str, dict[str, float]] | None = None,
    analyzer: DeepAnalyzer | None = None,
    config: DiscoveryConfig | None = None,
    trading_sessions: tuple[str, ...] | None = None,
    market_states: dict[str, str] | None = None,
) -> dict[str, Any]:
    config = config or DiscoveryConfig()
    instrument_confirmation = instrument_confirmation or {}
    updated: list[DiscoveryCandidate] = []
    transitions: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []

    for candidate in candidates:
        if candidate.state not in {"armed", "triggered"}:
            updated.append(candidate)
            continue
        if not _confirmation_session_is_open(
            evaluated_at, candidate.market, trading_sessions
        ):
            updated.append(candidate)
            continue
        if market_states is not None and market_states.get(candidate.code) not in {
            "MORNING",
            "AFTERNOON",
        }:
            updated.append(candidate)
            continue
        if candidate.state == "armed" and _parse_local(
            evaluated_at, candidate.market
        ) > _parse_local(
            candidate.expires_at, candidate.market
        ):
            changed = _transition(candidate, "expired", evaluated_at, "validity-window-ended")
            updated.append(changed)
            transitions.append(changed.transition_history[-1])
            continue

        latest = _latest_completed_five_minute(
            intraday_bars.get(candidate.code, []),
            evaluated_at,
            candidate.market,
            maximum_age=timedelta(
                minutes=config.maximum_intraday_bar_age_minutes
            ),
        )
        if latest is None:
            changed = candidate
            if (
                candidate.state == "triggered"
                and analyzer is not None
                and _analysis_needs_retry(candidate)
            ):
                changed, handoff = _invoke_deep_analysis(
                    candidate,
                    analyzer,
                    evaluated_at=evaluated_at,
                    retry=True,
                )
                handoffs.append(handoff)
            updated.append(changed)
            continue
        evidence = sector_confirmation.get(candidate.sector, {})
        breadth = evidence.get("breadth")
        leader_breadth = evidence.get("leader_breadth")
        coverage = evidence.get("coverage")
        capital_improvement = instrument_confirmation.get(candidate.code, {}).get(
            "capital_improvement"
        )
        if latest.close < candidate.structural_invalidation:
            changed = _transition(
                candidate,
                "invalidated",
                evaluated_at,
                "structural-invalidation-broken",
            )
        elif breadth is not None and breadth < config.invalidation_breadth:
            changed = _transition(
                candidate,
                "invalidated",
                evaluated_at,
                "sector-breadth-deteriorated",
            )
        elif (
            capital_improvement is not None
            and capital_improvement < config.invalidation_capital_improvement
        ):
            changed = _transition(
                candidate,
                "invalidated",
                evaluated_at,
                "material-capital-divergence",
            )
        elif (
            candidate.state == "armed"
            and latest.close >= candidate.trigger_level
            and breadth is not None
            and breadth >= config.trigger_breadth
            and leader_breadth is not None
            and leader_breadth >= config.trigger_leader_breadth
            and coverage is not None
            and coverage >= config.minimum_sector_coverage
        ):
            changed = _transition(
                candidate,
                "triggered",
                evaluated_at,
                "local-price-breadth-and-leaders-confirmed",
            )
            if analyzer is not None:
                changed, handoff = _invoke_deep_analysis(
                    changed,
                    analyzer,
                    evaluated_at=evaluated_at,
                    retry=False,
                )
                handoffs.append(handoff)
            else:
                handoffs.append(
                    {
                        "discovery_id": changed.discovery_id,
                        "code": changed.code,
                        "deep_analysis_invoked": False,
                        "retry": False,
                        "strategy_result": None,
                    }
                )
        elif (
            candidate.state == "triggered"
            and analyzer is not None
            and _analysis_needs_retry(candidate)
        ):
            changed, handoff = _invoke_deep_analysis(
                candidate,
                analyzer,
                evaluated_at=evaluated_at,
                retry=True,
            )
            handoffs.append(handoff)
        else:
            changed = replace(candidate, updated_at=evaluated_at)
        updated.append(changed)
        if changed.state != candidate.state:
            transitions.append(changed.transition_history[-1])

    updated.sort(key=lambda candidate: (-candidate.score, candidate.sector, candidate.code))
    return {
        "schema_version": DISCOVERY_SCHEMA,
        "mode": "intraday-confirmation",
        "evaluated_at": evaluated_at,
        "candidates": [candidate.to_record() for candidate in updated],
        "transitions": transitions,
        "deep_analysis_handoffs": handoffs,
        "entry_recommendation": None,
    }


def review_discovery(
    candidate: DiscoveryCandidate,
    future_bars: list[KLineBar],
) -> dict[str, Any]:
    """Measure discovery alert quality separately from trade P&L."""

    entry = candidate.trigger_level
    if entry <= 0 or not future_bars:
        raise ValueError("review requires a positive trigger and future bars")
    windows = (1, 3, 5, 10)
    metrics: dict[str, dict[str, float] | None] = {}
    for sessions in windows:
        selected = future_bars[:sessions]
        if len(selected) < sessions:
            metrics[f"{sessions}d"] = None
            continue
        highest = max(bar.high for bar in selected)
        lowest = min(bar.low for bar in selected)
        ending = selected[-1].close
        metrics[f"{sessions}d"] = {
            "mfe_pct": round((highest / entry - 1.0) * 100.0, 4),
            "mae_pct": round((lowest / entry - 1.0) * 100.0, 4),
            "return_pct": round((ending / entry - 1.0) * 100.0, 4),
        }
    return {
        "schema_version": "opportunity-discovery-review-v1",
        "discovery_id": candidate.discovery_id,
        "market": candidate.market,
        "sector": candidate.sector,
        "code": candidate.code,
        "track": candidate.track,
        "horizon": candidate.horizon,
        "triggered_at": candidate.triggered_at,
        "trigger_level": candidate.trigger_level,
        "metrics": metrics,
    }
