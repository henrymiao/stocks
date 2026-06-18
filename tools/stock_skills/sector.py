from __future__ import annotations

from statistics import median

from .models import SectorAnalysis


def analyze_sector(instrument_change: float | None, constituent_changes: list[float]) -> SectorAnalysis:
    """Score the sector context and the instrument's strength relative to its peers.

    `instrument_change` and `constituent_changes` are same-day percentage changes
    (e.g. 0.03 for +3%). Using the median and the share of advancers denoises the
    read: one or two outlier names cannot move the conclusion the way a single
    stock would.
    """
    usable = [c for c in constituent_changes if c is not None]
    if not usable:
        return SectorAnalysis(
            score=50.0,
            stance="unknown",
            breadth=None,
            median_change=None,
            relative_strength=None,
            notes=["No sector constituent data; sector score is neutral."],
        )

    med = median(usable)
    breadth = sum(1 for c in usable if c > 0) / len(usable)
    notes: list[str] = [
        f"Sector median change {round(med * 100, 2)}% across {len(usable)} names; "
        f"{round(breadth * 100, 1)}% advancing."
    ]

    # Base score from sector health (median move + breadth).
    score = 50.0
    score += max(-20.0, min(20.0, med * 600))
    score += (breadth - 0.5) * 30

    stance = "unknown"
    relative_strength: float | None = None
    if instrument_change is not None:
        relative_strength = round(instrument_change - med, 4)
        if med > 0.005 and relative_strength >= 0:
            stance = "leading"
            score += 8
            notes.append("Instrument is leading a rising sector (resonance).")
        elif med > 0.005 and relative_strength < 0:
            stance = "lagging"
            score -= 6
            notes.append("Sector is rising but the instrument lags (relative weakness).")
        elif med <= -0.005 and instrument_change > 0:
            stance = "leading"
            score += 4
            notes.append("Instrument is bucking a weak sector.")
        elif med <= -0.005:
            stance = "sector-weak"
            score -= 4
            notes.append("Instrument is falling with a weak sector.")
        else:
            stance = "in-line"
            notes.append("Instrument is moving in line with a flat sector.")
    else:
        stance = "leading" if score >= 60 else "sector-weak" if score <= 40 else "in-line"

    return SectorAnalysis(
        score=round(max(0.0, min(100.0, score)), 2),
        stance=stance,
        breadth=round(breadth, 4),
        median_change=round(med, 4),
        relative_strength=relative_strength,
        notes=notes,
    )
