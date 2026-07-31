from __future__ import annotations

from .models import MarketAnalysis, MarketSnapshot


_MARKET_WEIGHTS = {
    "SH.000001": 14,  # SSE Composite
    "SZ.399006": 12,  # ChiNext
    "SZ.399001": 8,   # SZSE Component
    "US.QQQ": 12,
    "US.SPY": 8,
    # HK backdrop: the CLI fetches these for HK.* instruments (see HK_INDEX_CODES);
    # without weights here their snapshots were silently ignored and every HK
    # analysis scored a fake-neutral market regime.
    "HK.800000": 12,  # Hang Seng Index
    "HK.800700": 10,  # Hang Seng TECH
}


# Every market here has a broad/value index and a growth index. Weighting them
# equally makes the regime unable to tell a broad selloff from a rotation: on
# 2026-07-30 ChiNext fell 3.97% while the SSE fell only 0.62%, and the blended
# regime (37.4, risk-off) vetoed new risk in bank and resource names that were
# rising *because of* that rotation. Tilting the blend toward the index that
# actually describes the instrument's cohort fixes that without inventing a new
# factor: a value name is judged mainly by the broad index, a growth name mainly
# by the growth index. The tilt is deliberately mild so a genuine broad selloff
# still reads risk-off for everyone.
_BROAD_INDICES = {"SH.000001", "SZ.399001", "US.SPY", "HK.800000"}
_GROWTH_INDICES = {"SZ.399006", "US.QQQ", "HK.800700"}
_MARKET_GROUPS = {
    "A": ("SH.000001", "SZ.399001", "SZ.399006"),
    "US": ("US.SPY", "US.QQQ"),
    "HK": ("HK.800000", "HK.800700"),
}
_PROFILE_TILTS = {
    "value": {"broad": 1.4, "growth": 0.4},
    "growth": {"broad": 0.6, "growth": 1.4},
    "neutral": {"broad": 1.0, "growth": 1.0},
}


def _tilted_weights(profile: str) -> dict[str, float]:
    """Re-mix each market's indices by profile while preserving its total weight.

    Only the *mix* moves: a market that contributes 26 points of influence still
    contributes 26 after tilting, so the regime's overall sensitivity is unchanged
    and a genuine broad selloff still reads risk-off for every profile. Without
    this normalization, tilting would also amplify how hard the regime swings.
    """
    tilt = _PROFILE_TILTS.get(profile, _PROFILE_TILTS["neutral"])
    weights = {code: float(weight) for code, weight in _MARKET_WEIGHTS.items()}
    if profile not in {"value", "growth"}:
        return weights

    for codes in _MARKET_GROUPS.values():
        members = [code for code in codes if code in weights]
        original_total = sum(weights[code] for code in members)
        if original_total <= 0:
            continue
        tilted = {
            code: weights[code] * (tilt["broad"] if code in _BROAD_INDICES else tilt["growth"])
            for code in members
        }
        tilted_total = sum(tilted.values())
        if tilted_total <= 0:
            continue
        scale = original_total / tilted_total
        for code in members:
            weights[code] = tilted[code] * scale
    return weights


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


def analyze_market(
    index_snapshots: dict[str, MarketSnapshot],
    profile: str = "neutral",
) -> MarketAnalysis:
    """Convert broad-index moves into a market risk regime.

    Pass the relevant index snapshots, e.g. SH.000001 (上证综指) and SZ.399006
    (创业板指) for A-shares, or US.QQQ/US.SPY for the US tape. The index trend
    sets the backdrop: a single stock fighting a falling market deserves less
    confidence than the same stock in a rising one.

    `profile` ("value" / "growth" / "neutral") tilts the blend toward the index
    that describes the instrument's cohort, so a rotation is not misread as a
    broad selloff for the side that is winning it.
    """
    score = 50.0
    notes: list[str] = []
    used = 0
    weights = _tilted_weights(profile)
    if profile in {"value", "growth"}:
        notes.append(f"Index blend tilted for a {profile} instrument.")
    for code, weight in weights.items():
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
