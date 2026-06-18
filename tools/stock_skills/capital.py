from __future__ import annotations

from .models import CapitalAnalysis, CapitalSnapshot


def analyze_capital(capital: CapitalSnapshot | None) -> CapitalAnalysis:
    if capital is None:
        return CapitalAnalysis(
            score=50,
            stance="missing",
            notes=["Capital-flow data is unavailable; score is neutral."],
        )

    flows = [capital.super_inflow, capital.big_inflow, capital.mid_inflow, capital.small_inflow]
    positive_count = sum(1 for value in flows if value > 0)
    negative_count = sum(1 for value in flows if value < 0)
    total_abs = sum(abs(value) for value in flows) or 1.0
    net_ratio = capital.net_inflow / total_abs

    score = 50.0
    notes: list[str] = []
    stance = "neutral"

    if capital.net_inflow > 0:
        score += min(18.0, net_ratio * 60)
        notes.append("Total net inflow is positive.")
    elif capital.net_inflow < 0:
        score += max(-18.0, net_ratio * 60)
        notes.append("Total net inflow is negative.")

    if positive_count >= 3 and capital.net_inflow > 0:
        score += 22
        stance = "confirms"
        notes.append("Most order-size buckets show inflow.")
    elif negative_count >= 3 and capital.net_inflow < 0:
        score -= 22
        stance = "contradicts"
        notes.append("Most order-size buckets show outflow.")
    elif capital.super_inflow > 0 and capital.big_inflow < 0 and capital.mid_inflow < 0:
        score += 8
        stance = "stabilizes"
        notes.append("super-large inflow is offset by large and medium order outflow.")
    elif capital.super_inflow < 0 and capital.big_inflow < 0:
        score -= 12
        stance = "contradicts"
        notes.append("super-large and large orders are both flowing out.")

    if stance == "neutral":
        stance = "stabilizes" if score >= 50 else "contradicts"

    return CapitalAnalysis(
        score=round(max(0.0, min(100.0, score)), 2),
        stance=stance,
        notes=notes,
    )
