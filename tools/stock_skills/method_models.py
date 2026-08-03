from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceValue:
    value: Any
    source: str
    as_of: str | None
    freshness: str
    confidence: float
    source_ref: str | None = None

    def __post_init__(self) -> None:
        if self.source not in {"opend", "official-manual"}:
            raise ValueError(f"Unsupported evidence source: {self.source}")
        if self.freshness not in {"live", "current", "stale", "unknown"}:
            raise ValueError(f"Unsupported freshness: {self.freshness}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class SwingStructureAnalysis:
    stage: str
    ma50: float | None
    ma150: float | None
    ma200: float | None
    checklist: dict[str, bool | None]
    pivot: float | None
    buy_zone: tuple[float, float] | None
    contraction_count: int | None
    breakout_volume_ratio: float | None
    gate_effect: str
    coverage: float
    confidence: float
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinkageReferenceAnalysis:
    code: str
    correlation_20d: float | None
    correlation_60d: float | None
    beta_60d: float | None
    downside_correlation: float | None
    stability: str
    stance: str
    observations: int


@dataclass(frozen=True)
class LinkageAnalysis:
    references: tuple[LinkageReferenceAnalysis, ...]
    coverage: float
    confidence: float
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValuationCase:
    method: str
    name: str
    fair_value: float
    assumptions: dict[str, Any]


@dataclass(frozen=True)
class ValuationScenarioAnalysis:
    status: str
    methods_used: tuple[str, ...]
    cases: tuple[ValuationCase, ...]
    sensitivity: dict[str, Any]
    method_disagreement_pct: float | None
    coverage: float
    confidence: float
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThesisAnalysis:
    state: str
    upside_drivers: tuple[str, ...]
    downside_drivers: tuple[str, ...]
    bull_path: str | None
    base_path: str | None
    bear_path: str | None
    rival_hypothesis: str | None
    invalidations: tuple[str, ...]
    unresolved: tuple[str, ...]
    technical_confirmation: str
    coverage: float
    confidence: float
    notes: tuple[str, ...] = ()


DECLINE_CAUSES = frozenset(
    {
        "liquidity",              # market/sector-wide forced or passive selling
        "bounded-event",          # a one-off with an estimable ceiling on the damage
        "valuation-reset",        # excessive expectations repricing to a new equilibrium
        "structural-impairment",  # durable earnings power is gone
        "unconfirmed",            # the move is observed, the cause is not established
    }
)


@dataclass(frozen=True)
class DeclineAssessment:
    """Why a security fell, recorded before its price is used as evidence of a bottom.

    A drawdown is not a discount. The same -30% is a recoverable liquidity flush, a bounded
    one-off, a permanent repricing, or a broken business, and those four have incompatible
    implications for whether a "low" exists at all. Classifying the cause first is what stops
    the framework from averaging into structural impairment, which is the single most
    expensive mistake this input exists to prevent. It is manual, opt-in evidence: absence
    means unassessed, never "safe".
    """

    cause: str
    bear_case_loss_pct: float | None
    selling_exhaustion: bool | None
    as_of: str
    source_ref: str
    drawdown_pct: float | None = None
    source: str = "official-manual"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.cause not in DECLINE_CAUSES:
            raise ValueError(f"Unsupported decline cause: {self.cause!r}")
        if self.source != "official-manual":
            raise ValueError("Decline assessment is a manual judgement: source must be official-manual")
        if not self.as_of or not self.source_ref:
            raise ValueError("Decline assessment requires as_of and source_ref")
        if self.bear_case_loss_pct is not None and self.bear_case_loss_pct <= 0:
            raise ValueError("bear_case_loss_pct is a positive loss magnitude in percent")
        if self.drawdown_pct is not None and self.drawdown_pct <= 0:
            raise ValueError("drawdown_pct is a positive magnitude in percent")

    @property
    def bear_case_estimable(self) -> bool:
        return self.bear_case_loss_pct is not None


@dataclass(frozen=True)
class MethodRestriction:
    code: str
    effect: str
    horizons: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class MethodAssessment:
    market_profile_id: str
    swing_structure: SwingStructureAnalysis
    thesis: ThesisAnalysis
    valuation: ValuationScenarioAnalysis
    linkage: LinkageAnalysis
    coverage: float
    confidence: float
    restrictions: tuple[MethodRestriction, ...]
    source_conflicts: tuple[str, ...] = ()
    method_policy: str = "finance-method-evidence-v1"
    errors: dict[str, str] = field(default_factory=dict)
    decline: DeclineAssessment | None = None
