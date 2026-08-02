"""Portfolio-level allocation: which ONE of the authorized candidates to actually buy.

`strategy.py` authorizes candidates one instrument at a time, which is correct for
evidence but silent about the book. On 2026-07-31 six names cleared their gates for
a combined 21.8% while the open-risk budget allowed 0.86% — every one individually
approved, all of them together impossible. Worse, four of them were the same
semiconductor bet and three shared one AI narrative, which per-instrument scoring
cannot see.

This module adds the missing step: rank authorized candidates by evidence *after*
discounting for how much they duplicate risk already on the book, then cut the list
at what the risk budget can actually fund.

It allocates nothing by itself and never places orders — it produces a ranked,
budget-feasible shortlist for a human to act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .linkage import _correlation, _returns_by_time
from .models import KLineBar


# A candidate perfectly correlated with an existing holding adds concentration, not
# diversification, so its evidence is discounted by this much at |rho| = 1. The
# penalty is linear in |rho| and deliberately capped below 1.0: heavy duplication
# should demote a name, never veto it outright — that is the gates' job, not this
# module's.
MAX_CORRELATION_PENALTY = 0.60
# Below this, two instruments are treated as independent and carry no penalty.
CORRELATION_FLOOR = 0.30


@dataclass(frozen=True)
class Holding:
    code: str
    value: float
    theme: str | None = None


@dataclass(frozen=True)
class Candidate:
    code: str
    setup_score: float
    suggested_allocation_pct: float
    risk_per_share_pct: float
    theme: str | None = None


@dataclass(frozen=True)
class RankedCandidate:
    code: str
    setup_score: float
    max_correlation: float | None
    correlated_with: str | None
    correlation_penalty: float
    adjusted_score: float
    authorized_pct: float
    affordable_pct: float
    binding_constraint: str
    theme_exposure_after_pct: float | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def fundable(self) -> bool:
        return self.affordable_pct > 0.0


def theme_exposure(holdings: list[Holding], total_value: float) -> dict[str, float]:
    """Percentage of the book committed to each theme — the concentration the caps miss."""
    if total_value <= 0:
        return {}
    exposure: dict[str, float] = {}
    for holding in holdings:
        if not holding.theme:
            continue
        exposure[holding.theme] = exposure.get(holding.theme, 0.0) + holding.value
    return {theme: round(value / total_value * 100, 2) for theme, value in sorted(exposure.items())}


def _penalty(correlation: float | None) -> float:
    if correlation is None:
        return 0.0
    magnitude = abs(correlation)
    if magnitude <= CORRELATION_FLOOR:
        return 0.0
    span = 1.0 - CORRELATION_FLOOR
    return round(MAX_CORRELATION_PENALTY * (magnitude - CORRELATION_FLOOR) / span, 4)


def worst_correlation(
    candidate_bars: list[KLineBar],
    holding_bars: dict[str, list[KLineBar]],
    window: int = 60,
) -> tuple[float | None, str | None]:
    """Correlation with the single most-duplicated holding — the binding one."""
    candidate_returns = _returns_by_time(candidate_bars)
    worst: float | None = None
    worst_code: str | None = None
    for code in sorted(holding_bars):
        reference = _returns_by_time(holding_bars[code])
        times = sorted(set(candidate_returns) & set(reference))[-window:]
        if len(times) < 20:
            continue
        correlation = _correlation(
            [candidate_returns[time] for time in times],
            [reference[time] for time in times],
        )
        if correlation is None:
            continue
        if worst is None or abs(correlation) > abs(worst):
            worst, worst_code = correlation, code
    return (round(worst, 4) if worst is not None else None), worst_code


def rank_candidates(
    candidates: list[Candidate],
    holdings: list[Holding],
    *,
    total_value: float,
    open_risk_budget_pct: float,
    open_risk_used_pct: float,
    position_cap_pct: float = 25.0,
    candidate_bars: dict[str, list[KLineBar]] | None = None,
    holding_bars: dict[str, list[KLineBar]] | None = None,
) -> list[RankedCandidate]:
    """Rank authorized candidates by correlation-adjusted evidence, cut to budget.

    `open_risk_budget_pct` / `open_risk_used_pct` are portfolio-heat figures: the
    remaining headroom is what any new position's stop distance must fit inside.
    """
    remaining_budget = max(0.0, open_risk_budget_pct - open_risk_used_pct)
    exposure = theme_exposure(holdings, total_value)
    held_value = {holding.code: holding.value for holding in holdings}
    ranked: list[RankedCandidate] = []

    for candidate in candidates:
        notes: list[str] = []
        correlation: float | None = None
        correlated_with: str | None = None
        if candidate_bars and holding_bars:
            bars = candidate_bars.get(candidate.code)
            others = {
                code: series
                for code, series in holding_bars.items()
                if code != candidate.code
            }
            if bars and others:
                correlation, correlated_with = worst_correlation(bars, others)
        penalty = _penalty(correlation)
        if penalty > 0 and correlated_with:
            notes.append(
                f"duplicates {correlated_with} (rho={correlation}); evidence discounted {penalty:.0%}"
            )

        # What the risk budget can fund. A position of weight W% whose stop sits R%
        # below entry contributes W*R/100 percentage points of portfolio heat, so the
        # largest weight the remaining budget supports is budget*100/R.
        if candidate.risk_per_share_pct > 0:
            budget_pct = remaining_budget * 100.0 / candidate.risk_per_share_pct
        else:
            budget_pct = 0.0
        existing_weight = (
            held_value.get(candidate.code, 0.0) / total_value * 100.0 if total_value > 0 else 0.0
        )
        cap_room = max(0.0, position_cap_pct - existing_weight)
        affordable = min(candidate.suggested_allocation_pct, budget_pct, cap_room)

        if affordable >= candidate.suggested_allocation_pct:
            binding = "authorized-size"
        elif budget_pct <= cap_room:
            binding = "risk-budget"
            notes.append(
                f"risk budget funds only {budget_pct:.2f}% of the {candidate.suggested_allocation_pct:.2f}% authorized"
            )
        else:
            binding = "position-cap"

        after = None
        if candidate.theme:
            after = round(exposure.get(candidate.theme, 0.0) + affordable, 2)
            if after >= 20.0:
                notes.append(f"theme {candidate.theme} would reach {after:.1f}% of the book")

        ranked.append(
            RankedCandidate(
                code=candidate.code,
                setup_score=candidate.setup_score,
                max_correlation=correlation,
                correlated_with=correlated_with,
                correlation_penalty=penalty,
                adjusted_score=round(candidate.setup_score * (1.0 - penalty), 2),
                authorized_pct=candidate.suggested_allocation_pct,
                affordable_pct=round(max(0.0, affordable), 2),
                binding_constraint=binding,
                theme_exposure_after_pct=after,
                notes=tuple(notes),
            )
        )

    ranked.sort(key=lambda row: (row.fundable, row.adjusted_score), reverse=True)
    return ranked


@dataclass(frozen=True)
class Allocation:
    code: str
    weight_pct: float
    heat_pct: float
    cumulative_heat_pct: float
    funded: bool
    reason: str


def allocate_budget(
    ranked: list[RankedCandidate],
    candidates: list[Candidate],
    remaining_budget_pct: float,
) -> list[Allocation]:
    """Walk the ranked list top-down, spending the shared risk budget as it goes.

    `rank_candidates` sizes every candidate against the *whole* remaining budget,
    which answers "could I afford this one?" but not "how many can I afford?" —
    the budget is shared, so the answer has to be sequential. Each name consumes
    weight * stop_distance / 100 percentage points of heat; once the budget is
    spent the rest are reported unfunded rather than silently dropped.

    Sizing the tail: a name that only partially fits is funded at the reduced
    weight the leftover budget supports, not skipped.
    """
    risk_by_code = {candidate.code: candidate.risk_per_share_pct for candidate in candidates}
    spent = 0.0
    out: list[Allocation] = []
    for row in ranked:
        risk = risk_by_code.get(row.code, 0.0)
        if not row.fundable or risk <= 0:
            out.append(Allocation(row.code, 0.0, 0.0, round(spent, 4), False, "not fundable"))
            continue
        headroom = remaining_budget_pct - spent
        if headroom <= 0:
            out.append(Allocation(row.code, 0.0, 0.0, round(spent, 4), False, "risk budget exhausted"))
            continue
        wanted_heat = row.affordable_pct * risk / 100.0
        if wanted_heat <= headroom:
            weight, heat, reason = row.affordable_pct, wanted_heat, "funded in full"
        else:
            weight = headroom * 100.0 / risk
            heat, reason = headroom, "partially funded by remaining budget"
        spent += heat
        out.append(
            Allocation(row.code, round(weight, 2), round(heat, 4), round(spent, 4), True, reason)
        )
    return out
