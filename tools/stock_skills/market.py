from __future__ import annotations

from .models import MarketAnalysis, MarketSnapshot


_MARKET_WEIGHTS = {
    "SH.000001": 14,  # SSE Composite
    "SZ.399006": 12,  # ChiNext
    "SZ.399001": 8,   # SZSE Component
    "US.QQQ": 12,
    "US.SPY": 8,
}


def _pct_change(snapshot: MarketSnapshot) -> float | None:
    if snapshot.prev_close <= 0:
        return None
    return (snapshot.last_price - snapshot.prev_close) / snapshot.prev_close


def has_market_evidence(index_snapshots: dict[str, MarketSnapshot]) -> bool:
    return any(
        snapshot is not None and _pct_change(snapshot) is not None
        for code in _MARKET_WEIGHTS
        if (snapshot := index_snapshots.get(code)) is not None
    )


def analyze_market(index_snapshots: dict[str, MarketSnapshot]) -> MarketAnalysis:
    """Convert broad-index moves into a market risk regime.

    Pass the relevant index snapshots, e.g. SH.000001 (上证综指) and SZ.399006
    (创业板指) for A-shares, or US.QQQ/US.SPY for the US tape. The index trend
    sets the backdrop: a single stock fighting a falling market deserves less
    confidence than the same stock in a rising one.
    """
    score = 50.0
    notes: list[str] = []
    used = 0
    for code, weight in _MARKET_WEIGHTS.items():
        snapshot = index_snapshots.get(code)
        if snapshot is None:
            continue
        change = _pct_change(snapshot)
        if change is None:
            continue
        used += 1
        if change >= 0.01:
            score += weight * 0.6
            notes.append(f"{code} is firmly higher ({round(change * 100, 2)}%).")
        elif change > 0:
            score += weight * 0.25
            notes.append(f"{code} is modestly higher ({round(change * 100, 2)}%).")
        elif change <= -0.01:
            score -= weight * 0.7
            notes.append(f"{code} is sharply lower ({round(change * 100, 2)}%).")
        else:
            score -= weight * 0.3
            notes.append(f"{code} is modestly lower ({round(change * 100, 2)}%).")

    score = round(max(0.0, min(100.0, score)), 2)
    if used == 0:
        return MarketAnalysis(score=50.0, regime="neutral", notes=["No index snapshots supplied; market regime is neutral."])

    if score >= 60:
        regime = "risk-on"
    elif score <= 42:
        regime = "risk-off"
    else:
        regime = "neutral"
    return MarketAnalysis(score=score, regime=regime, notes=notes)
