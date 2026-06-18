from __future__ import annotations

from .models import FundamentalAnalysis, FundamentalSnapshot

# PE-TTM thresholds differ by stock profile: a growth name tolerates a far higher
# multiple than a value name, because the multiple is meant to be paid down by growth.
_PE_BANDS = {
    "growth": {"cheap": 30.0, "fair": 60.0, "rich": 90.0},
    "value": {"cheap": 12.0, "fair": 20.0, "rich": 30.0},
    "neutral": {"cheap": 18.0, "fair": 35.0, "rich": 55.0},
}

GROWTH_TAGS = {"ai", "ai-hardware", "ai-infrastructure", "semiconductor", "pcb", "growth-proxy", "crypto-equity", "stablecoin"}
VALUE_TAGS = {"bank", "brokerage", "utility", "dividend", "value", "insurance"}


def infer_profile(tags: list[str] | None) -> str:
    """Classify a name as growth / value / neutral from its watchlist tags."""
    if not tags:
        return "neutral"
    lowered = {str(t).lower() for t in tags}
    if lowered & GROWTH_TAGS:
        return "growth"
    if lowered & VALUE_TAGS:
        return "value"
    return "neutral"


def analyze_fundamental(snapshot: FundamentalSnapshot | None, profile: str = "neutral") -> FundamentalAnalysis:
    """Score valuation in the context of the stock's profile.

    Growth names are judged mainly on PEG (PE relative to EPS growth) with a high PE
    tolerance; value names are judged on a low PE, low PB, and a real dividend. Absolute
    PE alone is never decisive — a high multiple is only expensive if growth does not
    justify it.
    """
    if snapshot is None or snapshot.pe_ttm is None:
        return FundamentalAnalysis(
            score=50.0,
            stance="unknown",
            profile=profile,
            peg=None,
            notes=["No fundamental data; score is neutral."],
        )

    if profile not in _PE_BANDS:
        profile = "neutral"
    bands = _PE_BANDS[profile]
    pe = snapshot.pe_ttm
    notes: list[str] = [f"Profile={profile}. PE-TTM={round(pe, 1)}."]
    score = 50.0
    peg: float | None = None

    # Negative or absurd PE = loss-making or distorted; treat cautiously, not as "cheap".
    if pe <= 0:
        notes.append("PE is negative (loss-making or distorted); valuation unreliable.")
        score -= 10
        stance = "unknown"
    else:
        if pe <= bands["cheap"]:
            score += 16
            stance = "cheap"
            notes.append(f"PE at or below the {profile} cheap band ({bands['cheap']}).")
        elif pe <= bands["fair"]:
            score += 4
            stance = "fair"
            notes.append(f"PE within the {profile} fair band ({bands['cheap']}-{bands['fair']}).")
        elif pe <= bands["rich"]:
            score -= 8
            stance = "expensive"
            notes.append(f"PE in the {profile} rich band ({bands['fair']}-{bands['rich']}).")
        else:
            score -= 18
            stance = "expensive"
            notes.append(f"PE above the {profile} rich ceiling ({bands['rich']}).")

        # PEG: only meaningful with a positive growth input. For growth names it can
        # rescue a high PE; PEG<1 is cheap-for-growth, PEG>2 is expensive-for-growth.
        if snapshot.eps_growth is not None and snapshot.eps_growth > 0:
            peg = round(pe / snapshot.eps_growth, 2)
            notes.append(f"PEG={peg} (PE / EPS growth {snapshot.eps_growth}%).")
            if peg < 1.0:
                score += 16
                stance = "cheap"
                notes.append("PEG < 1: growth more than justifies the multiple.")
            elif peg <= 1.5:
                score += 6
            elif peg <= 2.0:
                score -= 4
            else:
                score -= 12
                notes.append("PEG > 2: multiple is rich even after growth.")
        elif profile == "growth":
            notes.append("EPS growth not supplied; growth name judged on PE band only (pass --eps-growth for PEG).")

    # PB matters most for value names; extreme PB is a flag for any profile.
    if snapshot.pb is not None and snapshot.pb > 0:
        pb_penalty_weight = 1.6 if profile == "value" else 0.6
        if snapshot.pb > 10:
            score -= 6 * pb_penalty_weight
            notes.append(f"PB={round(snapshot.pb, 1)} is very high.")
        elif snapshot.pb < 1.5 and profile == "value":
            score += 6
            notes.append(f"PB={round(snapshot.pb, 1)} is low for a value name.")

    # Dividend yield rewards value names; growth names are not penalised for paying little.
    if snapshot.dividend_ratio is not None and snapshot.dividend_ratio > 0:
        if profile == "value" and snapshot.dividend_ratio >= 3.0:
            score += 8
            notes.append(f"Dividend yield {snapshot.dividend_ratio}% supports a value thesis.")
        elif snapshot.dividend_ratio >= 1.0:
            score += 3
            notes.append(f"Dividend yield {snapshot.dividend_ratio}%.")

    return FundamentalAnalysis(
        score=round(max(0.0, min(100.0, score)), 2),
        stance=stance,
        profile=profile,
        peg=peg,
        notes=notes,
    )
