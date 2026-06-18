from __future__ import annotations

from .models import KLineBar, PositionAnalysis


def compute_atr(bars: list[KLineBar], n: int = 14) -> float | None:
    """Average True Range over the last `n` bars. Returns None if there is too little data."""
    if len(bars) < 2:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    window = trs[-n:]
    if not window:
        return None
    return round(sum(window) / len(window), 4)


def analyze_position(
    last_price: float,
    atr: float | None,
    invalidation_level: float | None,
    risk_budget_pct: float = 1.0,
    atr_multiple: float = 2.0,
    last_trim_price: float | None = None,
    cost_basis: float | None = None,
) -> PositionAnalysis:
    """Turn a stop level into a risk-sized position.

    The stop is the *higher* (tighter, but still meaningful) of the technical
    invalidation level and an ATR-based stop (`last_price - atr_multiple*ATR`).
    The suggested position size spends a fixed `risk_budget_pct` of the account
    over the stop distance: a wider stop (more volatile name) yields a smaller
    position, so every trade risks roughly the same amount.
    """
    notes: list[str] = []
    if last_price <= 0:
        return PositionAnalysis(50.0, "wait", None, None, atr, None, ["No usable price; cannot size a position."])

    atr_stop = last_price - atr_multiple * atr if atr else None
    candidates = [lvl for lvl in (invalidation_level, atr_stop) if lvl is not None and 0 < lvl < last_price]
    if candidates:
        stop_price = round(max(candidates), 2)  # tighter of the two valid stops
        notes.append(f"Stop at {stop_price} (tighter of invalidation and {atr_multiple}x ATR).")
    else:
        stop_price = None

    stop_distance_pct: float | None = None
    suggested_size_pct: float | None = None
    if stop_price is not None:
        stop_distance_pct = round((last_price - stop_price) / last_price * 100, 2)
        if stop_distance_pct > 0:
            # size% so that (size% * stop_distance%) == risk_budget%
            suggested_size_pct = round(risk_budget_pct / (stop_distance_pct / 100), 2)
            suggested_size_pct = min(suggested_size_pct, 100.0)
            notes.append(
                f"Risk {risk_budget_pct}% of account over a {stop_distance_pct}% stop → size ~{suggested_size_pct}% of account."
            )

    # Score: a clean, not-too-wide stop is healthier than a very wide one.
    score = 50.0
    if stop_distance_pct is None:
        score = 45.0
        notes.append("No valid stop below price; treat as wait until structure improves.")
    elif stop_distance_pct <= 4:
        score = 72.0
        notes.append("Tight stop — favourable reward-to-risk if the thesis holds.")
    elif stop_distance_pct <= 8:
        score = 60.0
    elif stop_distance_pct <= 14:
        score = 48.0
        notes.append("Wide stop — size down accordingly.")
    else:
        score = 38.0
        notes.append("Very wide stop — volatile; only a small position is justified.")

    # Profit-taking context.
    if last_trim_price is not None and last_price >= last_trim_price:
        score -= 4
        notes.append(f"Already trimmed near {last_trim_price}; avoid rebuilding into strength.")
    if cost_basis is not None and last_price > 0:
        pnl_pct = round((last_price - cost_basis) / cost_basis * 100, 2)
        notes.append(f"Open P&L vs cost {cost_basis}: {pnl_pct}%.")

    # Stance from stop quality.
    if stop_distance_pct is None:
        stance = "wait"
    elif stop_distance_pct <= 4:
        stance = "core-hold"
    elif stop_distance_pct <= 8:
        stance = "trading-position"
    elif stop_distance_pct <= 14:
        stance = "partial-trim"
    else:
        stance = "risk-reduce"

    return PositionAnalysis(
        score=round(max(0.0, min(100.0, score)), 2),
        stance=stance,
        stop_price=stop_price,
        stop_distance_pct=stop_distance_pct,
        atr=atr,
        suggested_size_pct=suggested_size_pct,
        notes=notes,
    )
