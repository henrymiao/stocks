from __future__ import annotations

from statistics import mean

from .models import KLineBar, MarketSnapshot, TrendAnalysis


def _round_level(value: float) -> float:
    return round(float(value), 2)


def analyze_trend(snapshot: MarketSnapshot, bars: list[KLineBar]) -> TrendAnalysis:
    if len(bars) < 2:
        return TrendAnalysis(
            score=50,
            status="insufficient-data",
            support_levels=[],
            resistance_levels=[],
            invalidation_level=None,
            notes=["Need at least two bars for trend analysis."],
        )

    recent = bars[-1]
    prior = bars[-2]
    lookback = bars[-6:-1] if len(bars) >= 6 else bars[:-1]
    prior_high = max(bar.high for bar in lookback)
    prior_low = min(bar.low for bar in lookback)
    avg_volume = mean(bar.volume for bar in lookback)
    volume_ratio = recent.volume / avg_volume if avg_volume else 1.0
    close_change = (snapshot.last_price - snapshot.prev_close) / snapshot.prev_close if snapshot.prev_close else 0.0

    score = 50.0
    notes: list[str] = []
    status = "neutral"

    if snapshot.last_price > prior_high and volume_ratio >= 1.15:
        score += 32
        status = "breakout-confirmed"
        notes.append("Price closed above recent resistance with volume expansion.")
    elif snapshot.last_price < prior.low or snapshot.last_price < prior_low or close_change < -0.03:
        score -= 18
        status = "breakdown-risk"
        notes.append("Price closed below recent support area.")
    elif recent.high >= prior_high * 0.995 and snapshot.last_price <= prior_high:
        score += 12
        status = "high-level-consolidation"
        notes.append("Price tested resistance but did not close above it.")
    elif snapshot.last_price > prior.close:
        score += 10
        status = "constructive"
        notes.append("Close improved versus the previous bar.")

    if close_change > 0.03:
        score += 8
        notes.append("Daily gain shows strong demand.")
    elif close_change < -0.03:
        score -= 8
        notes.append("Daily loss shows distribution pressure.")

    if volume_ratio >= 1.3:
        score += 6
        notes.append("Volume is meaningfully above recent average.")
    elif volume_ratio < 0.75 and snapshot.last_price > prior.close:
        score -= 5
        notes.append("Price rise lacks volume confirmation.")

    support_levels = sorted({_round_level(prior.low), _round_level(prior_low), _round_level(recent.low)}, reverse=True)
    resistance_levels = sorted({_round_level(prior.high), _round_level(prior_high), _round_level(recent.high)})
    if status == "high-level-consolidation":
        invalidation_level = _round_level(recent.low)
    else:
        invalidation_level = _round_level(min(prior.low, recent.low))
    score = max(0.0, min(100.0, round(score, 2)))

    return TrendAnalysis(
        score=score,
        status=status,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        invalidation_level=invalidation_level,
        notes=notes,
    )
