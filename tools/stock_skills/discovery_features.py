from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from statistics import fmean
from typing import Any

from .markets import market_close_time
from .models import KLineBar
from .universe import SectorUniverse, market_timezone, normalize_market


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _return_pct(bars: list[KLineBar], sessions: int) -> float | None:
    if len(bars) <= sessions or bars[-sessions - 1].close <= 0:
        return None
    return (bars[-1].close / bars[-sessions - 1].close - 1.0) * 100.0


def _average_volume(bars: list[KLineBar], sessions: int = 20) -> float | None:
    values = [float(bar.volume) for bar in bars[-sessions:] if bar.volume > 0]
    return _mean(values)


def _true_ranges(bars: list[KLineBar]) -> list[float]:
    ranges: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return ranges


def _valid_bar(bar: KLineBar) -> bool:
    values = (bar.open, bar.high, bar.low, bar.close, bar.turnover)
    return (
        all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)
        and bar.volume > 0
        and bar.low > 0
        and bar.high >= max(bar.open, bar.close, bar.low)
        and bar.low <= min(bar.open, bar.close, bar.high)
    )


def completed_daily_bars(
    bars: list[KLineBar],
    *,
    evaluated_at: str,
    market: str,
) -> list[KLineBar]:
    """Return only completed, valid daily bars available at the evaluation time.

    On an intraday evaluation the local current-date daily bar is excluded.  After
    the local close it is eligible.  Future/zero-volume placeholders are always
    excluded, preventing a discovery score from seeing tomorrow's data.
    """

    market = normalize_market(market)
    moment = datetime.fromisoformat(evaluated_at)
    tz = market_timezone(market)
    local = moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)
    include_today = local.time() >= market_close_time(market)
    result: list[KLineBar] = []
    for bar in bars:
        if not _valid_bar(bar):
            continue
        try:
            bar_moment = datetime.fromisoformat(bar.time)
        except ValueError:
            continue
        bar_local = (
            bar_moment.replace(tzinfo=tz)
            if bar_moment.tzinfo is None
            else bar_moment.astimezone(tz)
        )
        if bar_local.date() > local.date():
            continue
        if bar_local.date() == local.date() and not include_today:
            continue
        result.append(bar)
    result.sort(key=lambda bar: bar.time)
    return result


@dataclass(frozen=True)
class FeatureValue:
    score: float | None
    group: str
    note: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.score is not None

    def to_record(self) -> dict[str, Any]:
        return asdict(self) | {"available": self.available}


@dataclass(frozen=True)
class SectorFeatureContext:
    coverage: float
    breadth: float | None
    previous_breadth: float | None
    breadth_change: float | None
    leader_breadth: float | None
    leader_stabilization: float | None
    synchronization: float | None
    notes: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return asdict(self) | {"notes": list(self.notes)}


@dataclass(frozen=True)
class TrackFeatureSet:
    track: str
    score: float
    feature_coverage: float
    supporting_groups: tuple[str, ...]
    group_scores: dict[str, float]
    features: dict[str, FeatureValue]
    trigger_level: float | None
    invalidation_level: float | None
    hard_vetoes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "score": self.score,
            "feature_coverage": self.feature_coverage,
            "supporting_groups": list(self.supporting_groups),
            "group_scores": self.group_scores,
            "features": {name: value.to_record() for name, value in self.features.items()},
            "trigger_level": self.trigger_level,
            "invalidation_level": self.invalidation_level,
            "hard_vetoes": list(self.hard_vetoes),
            "notes": list(self.notes),
        }


def build_sector_context(
    sector: SectorUniverse,
    bars_by_code: dict[str, list[KLineBar]],
) -> SectorFeatureContext:
    constituents = [member for member in sector.members if member.role in {"leader", "constituent"}]
    if not constituents:
        constituents = list(sector.members)
    usable = [member for member in constituents if len(bars_by_code.get(member.code, [])) >= 3]
    coverage = len(usable) / len(constituents) if constituents else 0.0

    current_moves: list[float] = []
    previous_moves: list[float] = []
    leader_moves: list[float] = []
    leader_recoveries: list[float] = []
    for member in usable:
        bars = bars_by_code[member.code]
        if bars[-2].close <= 0 or bars[-3].close <= 0:
            continue
        current = bars[-1].close / bars[-2].close - 1.0
        previous = bars[-2].close / bars[-3].close - 1.0
        current_moves.append(current)
        previous_moves.append(previous)
        if member.role == "leader":
            leader_moves.append(current)
            close_location = (
                (bars[-1].close - bars[-1].low) / (bars[-1].high - bars[-1].low)
                if bars[-1].high > bars[-1].low
                else 0.5
            )
            leader_recoveries.append(_clamp(100.0 * (0.6 * close_location + 0.4 * (current >= 0))))

    breadth = None if not current_moves else sum(move > 0 for move in current_moves) / len(current_moves)
    previous_breadth = (
        None if not previous_moves else sum(move > 0 for move in previous_moves) / len(previous_moves)
    )
    breadth_change = (
        None if breadth is None or previous_breadth is None else breadth - previous_breadth
    )
    leader_breadth = (
        None if not leader_moves else sum(move >= 0 for move in leader_moves) / len(leader_moves)
    )
    leader_stabilization = _mean(leader_recoveries)

    representative = bars_by_code.get(sector.representative, [])
    rep_move = _return_pct(representative, 1)
    synchronization = None
    if rep_move is not None and current_moves:
        constituent_direction = sum(move > 0 for move in current_moves) / len(current_moves)
        direction_agreement = (
            constituent_direction if rep_move >= 0 else 1.0 - constituent_direction
        )
        leader_agreement = 0.5 if leader_breadth is None else (
            leader_breadth if rep_move >= 0 else 1.0 - leader_breadth
        )
        synchronization = _clamp(100.0 * (0.65 * direction_agreement + 0.35 * leader_agreement))

    notes: list[str] = []
    if coverage < 0.7:
        notes.append(f"constituent coverage {coverage:.1%} is below 70%")
    if breadth is None:
        notes.append("breadth unavailable")
    if leader_breadth is None:
        notes.append("leader evidence unavailable")
    return SectorFeatureContext(
        coverage=round(coverage, 4),
        breadth=None if breadth is None else round(breadth, 4),
        previous_breadth=None if previous_breadth is None else round(previous_breadth, 4),
        breadth_change=None if breadth_change is None else round(breadth_change, 4),
        leader_breadth=None if leader_breadth is None else round(leader_breadth, 4),
        leader_stabilization=(
            None if leader_stabilization is None else round(leader_stabilization, 2)
        ),
        synchronization=None if synchronization is None else round(synchronization, 2),
        notes=tuple(notes),
    )


def _relative_strength_feature(
    bars: list[KLineBar], benchmark: list[KLineBar]
) -> FeatureValue:
    relative: list[float] = []
    raw: dict[str, float] = {}
    for sessions in (3, 5, 10):
        local = _return_pct(bars, sessions)
        reference = _return_pct(benchmark, sessions)
        if local is None or reference is None:
            continue
        value = local - reference
        raw[f"rs_{sessions}d_pct"] = round(value, 4)
        relative.append(_clamp(50.0 + value * 5.0))
    if len(relative) < 2:
        return FeatureValue(None, "price", "insufficient relative-strength history", raw)
    slope = raw.get("rs_3d_pct", 0.0) - raw.get("rs_10d_pct", raw.get("rs_5d_pct", 0.0))
    score = 0.8 * fmean(relative) + 0.2 * _clamp(50.0 + slope * 7.5)
    raw["rs_slope_pct"] = round(slope, 4)
    return FeatureValue(round(_clamp(score), 2), "price", "3/5/10-day relative strength", raw)


def _breadth_feature(context: SectorFeatureContext, *, reversal: bool) -> FeatureValue:
    if context.breadth is None:
        return FeatureValue(None, "breadth", "constituent breadth unavailable")
    change = context.breadth_change or 0.0
    if reversal:
        score = 45.0 + (context.breadth - 0.35) * 90.0 + change * 170.0
        note = "breadth stabilization/divergence"
    else:
        score = 45.0 + (context.breadth - 0.5) * 100.0 + change * 130.0
        note = "improving constituent breadth"
    return FeatureValue(
        round(_clamp(score), 2),
        "breadth",
        note,
        {
            "breadth": context.breadth,
            "previous_breadth": context.previous_breadth,
            "breadth_change": context.breadth_change,
        },
    )


def _volume_accumulation_feature(
    bars: list[KLineBar], capital_improvement: float | None
) -> FeatureValue:
    if len(bars) < 6:
        return FeatureValue(None, "flow", "insufficient volume history")
    recent = bars[-5:]
    up_volume = sum(bar.volume for previous, bar in zip(bars[-6:-1], recent) if bar.close >= previous.close)
    total_volume = sum(bar.volume for bar in recent)
    if total_volume <= 0:
        return FeatureValue(None, "flow", "non-positive volume")
    volume_score = 100.0 * up_volume / total_volume
    if capital_improvement is None:
        score = volume_score
        note = "volume accumulation; capital evidence missing"
    else:
        score = 0.7 * volume_score + 0.3 * _clamp(capital_improvement)
        note = "volume accumulation and improving capital evidence"
    return FeatureValue(
        round(_clamp(score), 2),
        "flow",
        note,
        {
            "up_volume_share": round(up_volume / total_volume, 4),
            "capital_improvement": capital_improvement,
        },
    )


def _contraction_feature(bars: list[KLineBar]) -> FeatureValue:
    if len(bars) < 22:
        return FeatureValue(None, "flow", "insufficient contraction history")
    ranges = _true_ranges(bars)
    prior_range = _mean(ranges[-20:-5])
    recent_range = _mean(ranges[-5:])
    prior_volume = _mean([float(bar.volume) for bar in bars[-20:-5]])
    recent_volume = _mean([float(bar.volume) for bar in bars[-5:]])
    if not prior_range or not recent_range or not prior_volume or not recent_volume:
        return FeatureValue(None, "flow", "invalid contraction inputs")
    range_ratio = recent_range / prior_range
    volume_ratio = recent_volume / prior_volume
    score = 100.0 - max(0.0, range_ratio - 0.65) * 80.0 - max(0.0, volume_ratio - 0.75) * 55.0
    if range_ratio > 1.25 or volume_ratio > 1.4:
        score -= 20.0
    return FeatureValue(
        round(_clamp(score), 2),
        "flow",
        "volatility and volume contraction",
        {"range_ratio": round(range_ratio, 4), "volume_ratio": round(volume_ratio, 4)},
    )


def _pivot_feature(bars: list[KLineBar]) -> tuple[FeatureValue, float | None]:
    if len(bars) < 21 or bars[-1].close <= 0:
        return FeatureValue(None, "price", "insufficient pivot history"), None
    pivot = max(bar.high for bar in bars[-21:-1])
    distance = (pivot - bars[-1].close) / bars[-1].close * 100.0
    if distance < -2.0:
        score = 25.0
    else:
        score = 100.0 - abs(distance - 2.0) * 11.0
    return (
        FeatureValue(
            round(_clamp(score), 2),
            "price",
            "distance to valid pivot",
            {"pivot": round(pivot, 4), "distance_pct": round(distance, 4)},
        ),
        pivot,
    )


def _synchronization_feature(context: SectorFeatureContext) -> FeatureValue:
    if context.synchronization is None:
        return FeatureValue(None, "leaders", "ETF/leader synchronization unavailable")
    return FeatureValue(
        context.synchronization,
        "leaders",
        "ETF and leader synchronization",
        {"leader_breadth": context.leader_breadth},
    )


def _drawdown_feature(bars: list[KLineBar]) -> FeatureValue:
    if len(bars) < 21:
        return FeatureValue(None, "price", "insufficient drawdown history")
    window = bars[-60:]
    high = max(bar.high for bar in window)
    low = min(bar.low for bar in bars[-20:])
    if high <= 0 or high <= low:
        return FeatureValue(None, "price", "invalid drawdown range")
    drawdown = (high - bars[-1].close) / high * 100.0
    location = (bars[-1].close - low) / (high - low)
    score = 0.65 * _clamp((drawdown - 5.0) * 5.0) + 0.35 * _clamp((0.45 - location) * 180.0 + 40.0)
    return FeatureValue(
        round(_clamp(score), 2),
        "price",
        "drawdown and oversold location",
        {"drawdown_pct": round(drawdown, 4), "range_location": round(location, 4)},
    )


def _climax_feature(bars: list[KLineBar]) -> FeatureValue:
    if len(bars) < 21:
        return FeatureValue(None, "flow", "insufficient volume-climax history")
    average = _average_volume(bars[:-1], 20)
    if not average:
        return FeatureValue(None, "flow", "invalid average volume")
    ratio = bars[-1].volume / average
    score = 30.0 + max(0.0, ratio - 1.0) * 70.0
    return FeatureValue(
        round(_clamp(score), 2),
        "flow",
        "abnormal volume or turnover climax",
        {"volume_ratio": round(ratio, 4)},
    )


def _failed_low_recovery_feature(bars: list[KLineBar]) -> FeatureValue:
    if len(bars) < 22:
        return FeatureValue(None, "price", "insufficient failed-low history")
    latest = bars[-1]
    previous = bars[-2]
    prior_low = min(bar.low for bar in bars[-21:-1])
    close_location = (
        (latest.close - latest.low) / (latest.high - latest.low)
        if latest.high > latest.low
        else 0.5
    )
    near_new_low = latest.low <= prior_low * 1.005
    non_decline = latest.close >= previous.close
    score = (30.0 if near_new_low else 0.0) + close_location * 50.0 + (20.0 if non_decline else 0.0)
    if not non_decline and close_location < 0.25:
        score = min(score, 25.0)
    return FeatureValue(
        round(_clamp(score), 2),
        "price",
        "failed new low and close-location recovery",
        {
            "near_new_low": near_new_low,
            "close_location": round(close_location, 4),
            "non_decline": non_decline,
        },
    )


def _leader_stabilization_feature(context: SectorFeatureContext) -> FeatureValue:
    if context.leader_stabilization is None:
        return FeatureValue(None, "leaders", "leader stabilization unavailable")
    return FeatureValue(
        context.leader_stabilization,
        "leaders",
        "major constituents stabilizing first",
        {"leader_breadth": context.leader_breadth},
    )


def _capital_feature(capital_improvement: float | None) -> FeatureValue:
    if capital_improvement is None:
        return FeatureValue(None, "flow", "capital improvement missing")
    return FeatureValue(
        round(_clamp(capital_improvement), 2),
        "flow",
        "marginal capital-flow improvement",
        {"capital_improvement": capital_improvement},
    )


def _aggregate_track(
    track: str,
    features: dict[str, FeatureValue],
    weights: dict[str, float],
    *,
    trigger_level: float | None,
    invalidation_level: float | None,
    hard_vetoes: tuple[str, ...] = (),
) -> TrackFeatureSet:
    score = sum(weights[name] * (feature.score or 0.0) for name, feature in features.items())
    coverage = sum(weights[name] for name, feature in features.items() if feature.available)
    grouped: dict[str, list[float]] = {}
    for feature in features.values():
        if feature.score is not None:
            grouped.setdefault(feature.group, []).append(feature.score)
    group_scores = {group: round(fmean(values), 2) for group, values in grouped.items()}
    supporting = tuple(sorted(group for group, value in group_scores.items() if value >= 55.0))
    return TrackFeatureSet(
        track=track,
        score=round(_clamp(score), 2),
        feature_coverage=round(coverage, 4),
        supporting_groups=supporting,
        group_scores=group_scores,
        features=features,
        trigger_level=None if trigger_level is None else round(trigger_level, 4),
        invalidation_level=(
            None if invalidation_level is None else round(invalidation_level, 4)
        ),
        hard_vetoes=hard_vetoes,
    )


def compute_discovery_tracks(
    bars: list[KLineBar],
    benchmark_bars: list[KLineBar],
    context: SectorFeatureContext,
    *,
    capital_improvement: float | None = None,
) -> tuple[TrackFeatureSet, TrackFeatureSet]:
    if len(bars) < 2:
        vetoes = ("insufficient-completed-bars",)
        empty = TrackFeatureSet(
            track="trend-buildup",
            score=0.0,
            feature_coverage=0.0,
            supporting_groups=(),
            group_scores={},
            features={},
            trigger_level=None,
            invalidation_level=None,
            hard_vetoes=vetoes,
        )
        return empty, TrackFeatureSet(**{**empty.__dict__, "track": "oversold-reversal"})

    invalidation = min(bar.low for bar in bars[-10:])
    latest = bars[-1]
    previous = bars[-2]
    close_location = (
        (latest.close - latest.low) / (latest.high - latest.low)
        if latest.high > latest.low
        else 0.5
    )
    average_volume = _average_volume(bars[:-1], 20)
    distribution_veto = bool(
        average_volume
        and latest.volume / average_volume >= 1.5
        and latest.close < previous.close
        and close_location < 0.30
    )
    hard_vetoes = ("high-volume-decline-near-low",) if distribution_veto else ()
    rs = _relative_strength_feature(bars, benchmark_bars)
    trend_breadth = _breadth_feature(context, reversal=False)
    accumulation = _volume_accumulation_feature(bars, capital_improvement)
    contraction = _contraction_feature(bars)
    pivot_feature, pivot = _pivot_feature(bars)
    sync = _synchronization_feature(context)
    trend = _aggregate_track(
        "trend-buildup",
        {
            "relative_strength": rs,
            "breadth": trend_breadth,
            "volume_accumulation": accumulation,
            "contraction": contraction,
            "pivot_distance": pivot_feature,
            "leader_sync": sync,
        },
        {
            "relative_strength": 0.25,
            "breadth": 0.20,
            "volume_accumulation": 0.20,
            "contraction": 0.15,
            "pivot_distance": 0.10,
            "leader_sync": 0.10,
        },
        trigger_level=pivot,
        invalidation_level=invalidation,
        hard_vetoes=hard_vetoes,
    )

    drawdown = _drawdown_feature(bars)
    climax = _climax_feature(bars)
    recovery = _failed_low_recovery_feature(bars)
    reversal_breadth = _breadth_feature(context, reversal=True)
    leaders = _leader_stabilization_feature(context)
    capital = _capital_feature(capital_improvement)
    trigger = max(bar.high for bar in bars[-3:]) if len(bars) >= 3 else bars[-1].high
    reversal = _aggregate_track(
        "oversold-reversal",
        {
            "drawdown": drawdown,
            "volume_climax": climax,
            "failed_low_recovery": recovery,
            "breadth_stabilization": reversal_breadth,
            "leader_stabilization": leaders,
            "capital_improvement": capital,
        },
        {
            "drawdown": 0.15,
            "volume_climax": 0.20,
            "failed_low_recovery": 0.20,
            "breadth_stabilization": 0.20,
            "leader_stabilization": 0.15,
            "capital_improvement": 0.10,
        },
        trigger_level=trigger,
        invalidation_level=invalidation,
        hard_vetoes=hard_vetoes,
    )
    return trend, reversal
