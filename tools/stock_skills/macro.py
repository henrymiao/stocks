from __future__ import annotations

from .models import CrossMarketAnalysis, MacroAnalysis, MarketSnapshot


def analyze_macro_risk(inputs: dict[str, object]) -> MacroAnalysis:
    score = 50.0
    notes: list[str] = []

    fed_bias = inputs.get("fed_bias")
    if fed_bias == "hike":
        score -= 18
        notes.append("Fed bias points toward higher rates.")
    elif fed_bias == "cut":
        score += 12
        notes.append("Fed bias points toward easier liquidity.")

    if inputs.get("geopolitical_risk") == "elevated":
        score -= 8
        notes.append("Geopolitical risk is elevated.")
    if inputs.get("oil_shock") is True:
        score -= 8
        notes.append("Oil or energy shock may pressure inflation.")
    if inputs.get("dollar_pressure") == "high":
        score -= 6
        notes.append("Dollar or yield pressure is high.")

    score = round(max(0.0, min(100.0, score)), 2)
    if score >= 60:
        regime = "risk-on"
    elif score <= 40:
        regime = "risk-off"
    else:
        regime = "neutral"
    if not notes:
        notes.append("Macro inputs are neutral or missing.")

    return MacroAnalysis(score=score, regime=regime, notes=notes)


# Macro proxies (ETFs that track the underlying when the raw index has no Futu feed),
# with the score impact of a rising proxy. Negative weight = "up is risk-off".
_MACRO_PROXIES = {
    "US.VIXY": (-16, "VIX 恐慌指标"),   # fear up -> risk-off
    "US.UUP": (-10, "美元指数"),        # stronger dollar -> risk-off
    "US.USO": (-8, "原油"),            # oil spike -> inflation/geopolitics risk-off
    "US.GLD": (-4, "黄金"),            # gold bid -> mild risk-off / hedging
    "US.TLT": (10, "长端美债价格"),     # bond price up = yields down -> risk-on for growth
}
_BIG_MOVE = 0.015  # 1.5% is a meaningful one-day move for these proxies


def analyze_macro_from_proxies(snapshots: dict[str, MarketSnapshot]) -> MacroAnalysis:
    """Derive a macro risk regime from live proxy ETFs instead of hand-typed inputs.

    Each proxy nudges the score by its weight, scaled by the size of the move; a
    rising VIX/dollar/oil pushes toward risk-off, a bond-price rally (falling
    yields) toward risk-on. Falls back to neutral when no proxy data is available.
    """
    score = 50.0
    notes: list[str] = []
    used = 0
    for code, (weight, label) in _MACRO_PROXIES.items():
        snapshot = snapshots.get(code)
        if snapshot is None:
            continue
        change = _pct_change(snapshot)
        if change is None:
            continue
        used += 1
        # Scale: a full _BIG_MOVE applies the full weight, capped at 1.5x for larger moves.
        magnitude = max(-1.5, min(1.5, change / _BIG_MOVE))
        score += weight * magnitude
        direction = "up" if change > 0 else "down"
        notes.append(f"{label} ({code}) {direction} {round(change * 100, 2)}%.")

    if used == 0:
        return MacroAnalysis(score=50.0, regime="neutral", notes=["No macro proxy data; macro regime is neutral."])

    score = round(max(0.0, min(100.0, score)), 2)
    if score >= 60:
        regime = "risk-on"
    elif score <= 40:
        regime = "risk-off"
    else:
        regime = "neutral"
    return MacroAnalysis(score=score, regime=regime, notes=notes)


def _pct_change(snapshot: MarketSnapshot) -> float | None:
    if snapshot.prev_close <= 0:
        return None
    return (snapshot.last_price - snapshot.prev_close) / snapshot.prev_close


def analyze_cross_market(snapshots: dict[str, MarketSnapshot]) -> CrossMarketAnalysis:
    score = 50.0
    notes: list[str] = []
    weights = {
        "US.QQQ": 18,
        "US.SPY": 10,
        "US.NVDA": 18,
        "US.SOXL": 12,
        "CC.BTC": 8,
        "CC.ETH": 6,
    }

    for code, weight in weights.items():
        snapshot = snapshots.get(code)
        if snapshot is None:
            continue
        change = _pct_change(snapshot)
        if change is None:
            notes.append(f"{code} has no usable previous close.")
            continue
        if change >= 0.02:
            score += weight * 0.6
            notes.append(f"{code} is strongly positive.")
        elif change > 0:
            score += weight * 0.25
            notes.append(f"{code} is positive.")
        elif change <= -0.02:
            score -= weight * 0.7
            notes.append(f"{code} is sharply negative.")
        else:
            score -= weight * 0.3
            notes.append(f"{code} is negative.")

    score = round(max(0.0, min(100.0, score)), 2)
    if score >= 60:
        regime = "risk-on"
    elif score <= 45:
        regime = "risk-off"
    else:
        regime = "neutral"
    if not notes:
        notes.append("No cross-market snapshots were supplied.")

    return CrossMarketAnalysis(score=score, regime=regime, notes=notes)
