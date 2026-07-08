from __future__ import annotations

from .models import CapitalAnalysis, CapitalSnapshot

# A daily move smaller than this (fraction, e.g. 0.003 = 0.3%) is treated as "flat" — too small
# to call a direction, so no price/flow divergence is asserted.
_DIRECTION_THRESHOLD = 0.003


def analyze_capital(
    capital: CapitalSnapshot | None,
    price_change: float | None = None,
) -> CapitalAnalysis:
    """Score order-flow quality.

    The dominant signal is **main-force** flow (super-large + large orders), not the headline
    net inflow: a rally carried by small/retail orders while the main force sells is *weak*, and
    scores low even when the aggregate net is positive. When ``price_change`` (the instrument's
    same-day return) is supplied, price-vs-main-force **divergence** is graded explicitly:

    - price up but main force *out*  → distribution (bearish); the rally lacks big-money backing.
    - price down but main force *in* → accumulation (bullish); the dip is being absorbed.

    ``price_change`` is optional so the function stays usable offline / in unit tests; without it
    the read is direction-agnostic (main-force magnitude + bucket breadth only).
    """
    if capital is None:
        return CapitalAnalysis(
            score=50,
            stance="missing",
            notes=["Capital-flow data is unavailable; score is neutral."],
        )

    flows = [capital.super_inflow, capital.big_inflow, capital.mid_inflow, capital.small_inflow]
    main = capital.super_inflow + capital.big_inflow  # 主力：特大单 + 大单
    retail = capital.mid_inflow + capital.small_inflow  # 散户：中单 + 小单
    positive_count = sum(1 for value in flows if value > 0)
    negative_count = sum(1 for value in flows if value < 0)
    magnitude = sum(abs(value) for value in flows) or 1.0
    main_ratio = main / magnitude
    net_ratio = capital.net_inflow / magnitude

    notes: list[str] = []

    # Base score: main-force flow dominates; the headline net is only a small secondary nudge.
    # (A retail-driven pump with the main force selling therefore scores near/below neutral.)
    score = 50.0
    score += max(-35.0, min(35.0, main_ratio * 45.0))
    score += max(-6.0, min(6.0, net_ratio * 10.0))

    # Direction-agnostic stance from main-force sign + bucket breadth (used when no price is given,
    # and as the default before any divergence refinement).
    if main > 0 and positive_count >= 3:
        stance = "confirms"
        notes.append("Main force (super+large) net inflow; most order buckets buying.")
    elif main < 0 and negative_count >= 3:
        stance = "contradicts"
        notes.append("Main force net outflow; most order buckets selling.")
    elif capital.super_inflow > 0 and (capital.big_inflow < 0 or capital.mid_inflow < 0):
        stance = "stabilizes"
        notes.append("super-large inflow is offset by large/medium order outflow.")
    elif main > 0:
        stance = "stabilizes"
        notes.append("Main force modestly net-positive.")
    else:
        stance = "contradicts"
        notes.append("Main force net outflow.")

    # Divergence layer: only when we know the day's direction and it is meaningful.
    if price_change is not None and abs(price_change) >= _DIRECTION_THRESHOLD:
        if price_change > 0 and main < 0:
            score -= 12
            stance = "distribution"
            notes.append(
                "Price up but main force (super+large) net OUT — bearish divergence, rally quality suspect."
            )
        elif price_change < 0 and main > 0:
            score += 8
            stance = "accumulation"
            notes.append("Price down but main force net IN — bullish divergence, dip being absorbed.")
        elif price_change > 0 and main > 0:
            stance = "confirms"
            notes.append("Price up and main force buying — healthy volume/price confirmation.")
        elif price_change < 0 and main < 0:
            score -= 4
            stance = "contradicts"
            notes.append("Price down and main force selling — trend-down, no support.")

    # Denoise the single end-of-day reading with the same-day flow direction:
    # late-session acceleration is more trustworthy than a mid-session snapshot.
    if capital.intraday_trend == "accelerating-in":
        score += 4
        notes.append("Inflow accelerated into the close.")
    elif capital.intraday_trend == "accelerating-out":
        score -= 4
        notes.append("Outflow accelerated into the close.")

    # Flag when the by-size net flow came from the full-day distribution fallback rather than
    # the intraday series — the intraday feed had frozen, so this is the corrected reading and
    # no intraday-momentum signal is available.
    if capital.source == "distribution":
        notes.append("Full-day capital distribution used (intraday feed was stale/missing).")

    return CapitalAnalysis(
        score=round(max(0.0, min(100.0, score)), 2),
        stance=stance,
        notes=notes,
    )
