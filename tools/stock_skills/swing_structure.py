from __future__ import annotations

from statistics import mean

from .market_profiles import MarketProfile
from .method_models import SwingStructureAnalysis
from .models import KLineBar


def _sma(values: list[float], window: int, end: int | None = None) -> float | None:
    selected = values[:end] if end is not None else values
    if len(selected) < window:
        return None
    return sum(selected[-window:]) / window


def _range_pct(bars: list[KLineBar]) -> float:
    middle = mean(bar.close for bar in bars)
    if middle <= 0:
        return 0.0
    return (max(bar.high for bar in bars) - min(bar.low for bar in bars)) / middle


def analyze_swing_structure(
    bars: list[KLineBar],
    current_price: float,
    profile: MarketProfile,
) -> SwingStructureAnalysis:
    required = profile.minimum_stage_bars
    if len(bars) < required or current_price <= 0:
        return SwingStructureAnalysis(
            "unknown",
            None,
            None,
            None,
            {},
            None,
            None,
            None,
            None,
            "none",
            0.0,
            0.0,
            (f"need at least {required} completed daily bars",),
        )

    closes = [bar.close for bar in bars]
    ma50 = _sma(closes, 50)
    ma150 = _sma(closes, 150)
    ma200 = _sma(closes, 200)
    ma50_prior = _sma(closes, 50, -10)
    ma200_prior = _sma(closes, 200, -20)
    assert None not in {ma50, ma150, ma200, ma50_prior, ma200_prior}

    high_52w = max(bar.high for bar in bars[-220:])
    low_52w = min(bar.low for bar in bars[-220:])
    checklist = {
        "price-above-ma50": current_price > ma50,
        "ma50-above-ma150": ma50 > ma150,
        "ma150-above-ma200": ma150 > ma200,
        "ma200-rising": ma200 > ma200_prior,
        "price-30pct-above-low": current_price >= low_52w * 1.30,
        "price-within-25pct-high": current_price >= high_52w * 0.75,
    }

    if current_price > ma50 > ma150 > ma200 and ma200 > ma200_prior:
        stage = "stage-2"
    elif current_price < ma50 < ma150 < ma200 and ma200 < ma200_prior:
        stage = "stage-4"
    elif current_price < ma50 and ma50 < ma50_prior:
        stage = "stage-3"
    else:
        stage = "stage-1"

    # Task orchestration supplies completed bars only, while current_price is the
    # separate live observation. Keep an older, wider contraction out of the pivot.
    pivot = max(bar.high for bar in bars[-20:])
    windows = (bars[-30:-20], bars[-20:-10], bars[-10:])
    ranges = [_range_pct(window) for window in windows]
    contraction_count = sum(right < left for left, right in zip(ranges, ranges[1:]))
    previous_volume = mean(bar.volume for bar in bars[-21:-1])
    volume_ratio = None if previous_volume <= 0 else bars[-1].volume / previous_volume
    near_pivot = (
        pivot > 0
        and pivot * 0.97 <= current_price <= pivot * (1.0 + profile.buy_zone_extension_pct)
    )
    late_stage_one = stage == "stage-1" and contraction_count == 2 and near_pivot
    gate_effect = (
        "reject-new-risk"
        if stage in {"stage-3", "stage-4"}
        else ("probe-only" if late_stage_one else "none")
    )
    buy_zone = (
        round(pivot, 4),
        round(pivot * (1.0 + profile.buy_zone_extension_pct), 4),
    )
    return SwingStructureAnalysis(
        stage=stage,
        ma50=round(ma50, 4),
        ma150=round(ma150, 4),
        ma200=round(ma200, 4),
        checklist=checklist,
        pivot=round(pivot, 4),
        buy_zone=buy_zone,
        contraction_count=contraction_count,
        breakout_volume_ratio=None if volume_ratio is None else round(volume_ratio, 4),
        gate_effect=gate_effect,
        coverage=1.0,
        confidence=1.0,
        notes=(),
    )
