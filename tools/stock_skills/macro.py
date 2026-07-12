from __future__ import annotations

from collections.abc import Collection

from .models import CrossMarketAnalysis, MacroAnalysis, MarketSnapshot


_MACRO_INPUT_VALUES = {
    "fed_bias": ("hike", "cut", "neutral"),
    "geopolitical_risk": ("elevated", "normal"),
    "oil_shock": (True, False),
    "dollar_pressure": ("high", "normal"),
    "jgb_stress": ("elevated", "normal"),
    "yen_carry_stress": ("elevated", "normal"),
    "credit_stress": ("elevated", "normal"),
}


def _is_supported_macro_value(key: str, value: object) -> bool:
    return any(
        type(value) is type(supported) and value == supported
        for supported in _MACRO_INPUT_VALUES.get(key, ())
    )


def _supported_macro_value(inputs: dict[str, object], key: str) -> object | None:
    value = inputs.get(key)
    return value if key in inputs and _is_supported_macro_value(key, value) else None


def has_macro_input_evidence(inputs: dict[str, object]) -> bool:
    return any(
        key in inputs and _is_supported_macro_value(key, inputs[key])
        for key in _MACRO_INPUT_VALUES
    )


def analyze_macro_risk(inputs: dict[str, object]) -> MacroAnalysis:
    score = 50.0
    notes: list[str] = []

    fed_bias = _supported_macro_value(inputs, "fed_bias")
    if fed_bias == "hike":
        score -= 18
        notes.append("Fed bias points toward higher rates.")
    elif fed_bias == "cut":
        score += 12
        notes.append("Fed bias points toward easier liquidity.")

    if _supported_macro_value(inputs, "geopolitical_risk") == "elevated":
        score -= 8
        notes.append("Geopolitical risk is elevated.")
    if _supported_macro_value(inputs, "oil_shock") is True:
        score -= 8
        notes.append("Oil or energy shock may pressure inflation.")
    if _supported_macro_value(inputs, "dollar_pressure") == "high":
        score -= 6
        notes.append("Dollar or yield pressure is high.")
    if _supported_macro_value(inputs, "jgb_stress") == "elevated":
        score -= 10
        notes.append("JGB yield stress is elevated.")
    if _supported_macro_value(inputs, "yen_carry_stress") == "elevated":
        score -= 12
        notes.append("Yen carry-trade unwind risk is elevated.")
    if _supported_macro_value(inputs, "credit_stress") == "elevated":
        score -= 10
        notes.append("Credit-market stress is elevated.")

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
    "US.FXY": (-14, "日元价格代理"),     # yen up -> carry unwind / forced deleveraging risk
    "US.HYG": (10, "高收益信用债"),      # junk credit up -> easier risk conditions
    "US.LQD": (4, "投资级信用债"),       # investment-grade credit up -> mildly risk-on
}
_BIG_MOVE = 0.015  # 1.5% is a meaningful one-day move for these proxies
_YEN_STRESS_MOVE = 0.01
_CREDIT_RELATIVE_STRESS = -0.0075
_FEAR_STRESS_MOVE = 0.03


def _has_snapshot_evidence(
    snapshots: dict[str, MarketSnapshot],
    recognized_codes: Collection[str],
) -> bool:
    return any(
        snapshot is not None and _pct_change(snapshot) is not None
        for code in recognized_codes
        if (snapshot := snapshots.get(code)) is not None
    )


def has_macro_proxy_evidence(snapshots: dict[str, MarketSnapshot]) -> bool:
    return _has_snapshot_evidence(snapshots, _MACRO_PROXIES)


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

    yen_change = _snapshot_change(snapshots, "US.FXY")
    fear_change = _snapshot_change(snapshots, "US.VIXY")
    hyg_change = _snapshot_change(snapshots, "US.HYG")
    lqd_change = _snapshot_change(snapshots, "US.LQD")
    credit_relative = (
        hyg_change - lqd_change
        if hyg_change is not None and lqd_change is not None
        else None
    )
    if yen_change is not None and yen_change >= _YEN_STRESS_MOVE:
        notes.append("日元单日明显升值，套息交易平仓风险上升。")
        if fear_change is not None and fear_change >= _FEAR_STRESS_MOVE:
            score -= 8
            notes.append("日元升值与恐慌指标同步上升，去杠杆信号形成共振。")
        if credit_relative is not None and credit_relative <= _CREDIT_RELATIVE_STRESS:
            score -= 8
            notes.append("日元升值且高收益债弱于投资级债，套息与信用压力形成共振。")
    if credit_relative is not None and credit_relative <= _CREDIT_RELATIVE_STRESS:
        notes.append(
            "信用风险偏好恶化：高收益债相对投资级债落后"
            f" {round(abs(credit_relative) * 100, 2)} 个百分点。"
        )

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


def _snapshot_change(
    snapshots: dict[str, MarketSnapshot],
    code: str,
) -> float | None:
    snapshot = snapshots.get(code)
    return _pct_change(snapshot) if snapshot is not None else None


def _pct_change(snapshot: MarketSnapshot) -> float | None:
    if snapshot.prev_close <= 0:
        return None
    return (snapshot.last_price - snapshot.prev_close) / snapshot.prev_close


_CROSS_MARKET_WEIGHTS = {
    "US.QQQ": 18,
    "US.SPY": 10,
    "US.NVDA": 18,
    "US.SOXL": 12,
    "CC.BTC": 8,
    "CC.ETH": 6,
}


def has_cross_market_evidence(snapshots: dict[str, MarketSnapshot]) -> bool:
    return _has_snapshot_evidence(snapshots, _CROSS_MARKET_WEIGHTS)


def analyze_cross_market(snapshots: dict[str, MarketSnapshot]) -> CrossMarketAnalysis:
    score = 50.0
    notes: list[str] = []
    for code, weight in _CROSS_MARKET_WEIGHTS.items():
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
