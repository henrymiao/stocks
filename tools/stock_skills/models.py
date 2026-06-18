from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarketSnapshot:
    code: str
    name: str
    last_price: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: int
    turnover: float
    timestamp: str


@dataclass(frozen=True)
class KLineBar:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float


@dataclass(frozen=True)
class CapitalSnapshot:
    net_inflow: float
    super_inflow: float
    big_inflow: float
    mid_inflow: float
    small_inflow: float
    timestamp: str


@dataclass(frozen=True)
class InstrumentState:
    snapshot: MarketSnapshot
    daily_bars: list[KLineBar]
    intraday_bars: list[KLineBar]
    capital: CapitalSnapshot | None = None
    sector: str | None = None
    user_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComponentScores:
    trend: float
    capital_flow: float
    sector: float
    cross_market: float
    macro_risk: float
    position_fit: float

    def to_record(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class TrendAnalysis:
    score: float
    status: str
    support_levels: list[float]
    resistance_levels: list[float]
    invalidation_level: float | None
    notes: list[str]


@dataclass(frozen=True)
class CapitalAnalysis:
    score: float
    stance: str
    notes: list[str]


@dataclass(frozen=True)
class MacroAnalysis:
    score: float
    regime: str
    notes: list[str]


@dataclass(frozen=True)
class CrossMarketAnalysis:
    score: float
    regime: str
    notes: list[str]


@dataclass(frozen=True)
class Recommendation:
    code: str
    name: str
    timestamp: str
    label: str
    total_score: float
    component_scores: ComponentScores
    analyst_hypothesis: str
    trader_plan: str
    support_levels: list[float]
    resistance_levels: list[float]
    invalidation_level: float | None
    confidence: float
    source_refs: list[str]
    user_context: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["component_scores"] = self.component_scores.to_record()
        return payload
