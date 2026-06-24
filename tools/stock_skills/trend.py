from __future__ import annotations

from statistics import mean

from .models import KLineBar, MarketSnapshot, TrendAnalysis


def _round_level(value: float) -> float:
    return round(float(value), 2)


def _sma(values: list[float], n: int) -> float | None:
    """Simple moving average of the last `n` values, or None if there are too few."""
    if len(values) < n or n <= 0:
        return None
    return round(sum(values[-n:]) / n, 4)


def _trend_regime(
    price: float,
    ma_mid: float | None,
    ma_slow: float | None,
    ma_mid_prev: float | None,
) -> tuple[str, list[str]]:
    """Classify the broader regime from moving-average alignment and slope.

    This is the multi-timeframe backdrop the same-day breakout logic is judged
    against: a breakout inside an uptrend is trustworthy, a "breakout" inside a
    downtrend is usually a bounce / false breakout and deserves less confidence.
    """
    notes: list[str] = []
    if ma_mid is None:
        return "unknown", ["Not enough bars for a moving-average trend read (need >=20)."]

    rising = ma_mid_prev is not None and ma_mid > ma_mid_prev
    falling = ma_mid_prev is not None and ma_mid < ma_mid_prev

    if ma_slow is not None:
        if price > ma_mid > ma_slow and not falling:
            notes.append(f"Price>{ma_mid}(MA20)>{ma_slow}(MA50) and MA20 not falling: uptrend.")
            return "uptrend", notes
        if price < ma_mid < ma_slow and not rising:
            notes.append(f"Price<{ma_mid}(MA20)<{ma_slow}(MA50) and MA20 not rising: downtrend.")
            return "downtrend", notes
        notes.append(f"MA20={ma_mid}, MA50={ma_slow}: mixed/range structure.")
        return "range", notes

    # Only MA20 available: a weaker read.
    if price > ma_mid and not falling:
        notes.append(f"Price above MA20 ({ma_mid}): tentative uptrend.")
        return "uptrend", notes
    if price < ma_mid and not rising:
        notes.append(f"Price below MA20 ({ma_mid}): tentative downtrend.")
        return "downtrend", notes
    notes.append(f"Price near MA20 ({ma_mid}): range.")
    return "range", notes


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

    # ---- Multi-timeframe overlay: judge the same-day move against the MA trend. ----
    closes = [bar.close for bar in bars]
    ma_fast = _sma(closes, 10)
    ma_mid = _sma(closes, 20)
    ma_slow = _sma(closes, 50)
    ma_mid_prev = _sma(closes[:-5], 20) if len(closes) >= 25 else None
    price = snapshot.last_price
    trend_regime, regime_notes = _trend_regime(price, ma_mid, ma_slow, ma_mid_prev)
    notes.extend(regime_notes)

    if trend_regime != "unknown":
        # A breakout against a falling trend is the classic false-breakout trap: keep
        # only part of the breakout credit and label it so the caller stays cautious.
        if status == "breakout-confirmed" and trend_regime == "downtrend":
            score -= 18
            status = "breakout-vs-downtrend"
            notes.append("Breakout fired against a downtrend (MA20<MA50) — high false-breakout risk; confidence cut.")
        elif status == "breakout-confirmed" and trend_regime == "uptrend":
            score += 5
            notes.append("Breakout is aligned with the prevailing uptrend (resonance).")

        # Bounded alignment nudge so the broader trend always colours the read.
        if trend_regime == "uptrend" and price >= (ma_mid or price):
            score += 6
            notes.append("Price holds above a non-falling MA20: trend support.")
        elif trend_regime == "downtrend" and price <= (ma_mid or price):
            score -= 8
            notes.append("Price trapped below a non-rising MA20: trend resistance overhead.")
        elif trend_regime == "downtrend" and status in {"constructive", "high-level-consolidation"}:
            score -= 4
            notes.append("Constructive bar but inside a downtrend — treat as a bounce, not a turn.")

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
        ma_fast=ma_fast,
        ma_mid=ma_mid,
        ma_slow=ma_slow,
        trend_regime=trend_regime,
    )
