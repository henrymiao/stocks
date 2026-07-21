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
