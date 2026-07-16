from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# Single source of truth for the record schema every writer emits. Readers keep
# accepting older versions found in stored journals.
SCHEMA_VERSION = "recommendation-v5"


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
    captured_at: str | None = None


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
    # Intraday momentum derived from the same-day flow series, used to denoise a single reading:
    # "accelerating-in" / "accelerating-out" / "flat" / None (unknown).
    intraday_trend: str | None = None
    # Where the by-size net flow came from: "intraday" (live cumulative flow series) or
    # "distribution" (full-day capital distribution, used as a fallback when the intraday
    # feed froze mid-session). Distribution carries no time series, so intraday_trend is None.
    source: str = "intraday"


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
    market_regime: float = 50.0
    fundamental: float = 50.0

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
    # Multi-timeframe context (None when there are too few bars to compute the MA).
    ma_fast: float | None = None   # e.g. MA10
    ma_mid: float | None = None    # e.g. MA20
    ma_slow: float | None = None   # e.g. MA50
    trend_regime: str = "unknown"  # uptrend / downtrend / range / unknown


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
class SectorAnalysis:
    score: float
    stance: str  # leading / in-line / lagging / sector-weak / unknown
    breadth: float | None  # share of constituents up, 0..1
    median_change: float | None
    relative_strength: float | None  # instrument change minus sector median
    notes: list[str]


@dataclass(frozen=True)
class MarketAnalysis:
    score: float
    regime: str  # risk-on / neutral / risk-off
    notes: list[str]


@dataclass(frozen=True)
class ExtendedHoursSnapshot:
    """Pre-market and after-hours price/change (US instruments).

    Read from the Futu market snapshot's pre_*/after_* columns. Fields are None
    outside the relevant session, or for markets without extended-hours trading.
    """
    code: str
    prev_close: float | None          # regular-session close, the change reference
    pre_price: float | None           # pre-market last price
    pre_change_rate: float | None     # pre-market % vs prev close
    pre_volume: float | None
    after_price: float | None         # after-hours last price
    after_change_rate: float | None   # after-hours % vs prev close
    after_volume: float | None


@dataclass(frozen=True)
class FundamentalSnapshot:
    code: str
    pe_ttm: float | None
    pb: float | None
    eps: float | None
    dividend_ratio: float | None  # trailing dividend yield, percent (e.g. 0.34 = 0.34%)
    market_val: float | None
    eps_growth: float | None = None  # YoY EPS growth, percent (e.g. 35.0 = +35%); optional
    # Business-quality inputs (optional; percent units). When present they let the
    # fundamental score look past raw valuation to growth and profitability.
    revenue_growth: float | None = None  # YoY revenue growth, percent
    gross_margin: float | None = None    # gross margin, percent
    net_margin: float | None = None      # net margin, percent
    roe: float | None = None             # return on equity, percent


@dataclass(frozen=True)
class FinancialsSnapshot:
    """Quality metrics distilled from the latest income statement + revenue breakdown.

    Used to auto-fill the business-quality inputs of FundamentalSnapshot so analyze no
    longer needs hand-typed --revenue-growth/--gross-margin/--net-margin flags. All
    margins/growth are percent; growth is YoY for the latest reported period.
    """
    code: str
    period: str | None  # e.g. "2026/Q1"
    revenue_growth: float | None = None
    eps_growth: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    revenue_breakdown: list[tuple[str, float]] = field(default_factory=list)  # (segment, percent)


@dataclass(frozen=True)
class FundamentalAnalysis:
    score: float
    stance: str  # cheap / fair / expensive / unknown
    profile: str  # growth / value / neutral
    peg: float | None
    notes: list[str]
    quality: float | None = None  # 0..100 business-quality sub-score (None when no quality inputs)


@dataclass(frozen=True)
class PositionAnalysis:
    score: float
    stance: str  # core-hold / trading-position / partial-trim / wait / risk-reduce
    stop_price: float | None
    stop_distance_pct: float | None  # how far the stop sits below entry, percent
    atr: float | None
    suggested_size_pct: float | None  # position size as % of account from the risk budget
    notes: list[str]


@dataclass(frozen=True)
class ExitTarget:
    name: str
    r_multiple: float
    price: float
    fraction: float


@dataclass(frozen=True)
class TrailingRule:
    method: str
    activation_r: float
    atr_multiple: float
    current_stop: float | None = None


@dataclass(frozen=True)
class TimeStop:
    progress_r: float
    sessions: int
    action: str


@dataclass(frozen=True)
class RiskSizing:
    stop_distance_pct: float
    uncapped_size_pct: float
    allocation_cap_pct: float
    suggested_size_pct: float
    planned_risk_pct: float
    capped: bool


@dataclass(frozen=True)
class ExitPlan:
    strategy_id: str
    side: str
    entry_price: float
    structural_invalidation: float
    initial_stop: float
    risk_per_share: float
    atr: float
    risk_budget_pct: float
    targets: tuple[ExitTarget, ...]
    runner_fraction: float
    trailing_rule: TrailingRule
    time_stop: TimeStop
    maximum_holding_days: int
    gap_handling: str
    event_handling: str
    risk_sizing: RiskSizing


@dataclass(frozen=True)
class PositionStateSnapshot:
    state: str
    remaining_fraction: float
    trade_id: str | None = None
    filled_targets: tuple[str, ...] = ()
    previous_trailing_stop: float | None = None
    last_event: str | None = None
    exit_reason: str | None = None

    def __post_init__(self) -> None:
        allowed = {"flat", "entered", "profit-protected", "trend-runner", "exited"}
        if self.state not in allowed:
            raise ValueError(f"Unknown position state: {self.state}")
        if isinstance(self.remaining_fraction, bool) or not isinstance(self.remaining_fraction, (int, float)):
            raise ValueError("remaining_fraction must be numeric")
        if not 0.0 <= float(self.remaining_fraction) <= 1.0:
            raise ValueError("remaining_fraction must be between 0 and 1")
        if self.state in {"flat", "exited"} and self.remaining_fraction != 0.0:
            raise ValueError(f"{self.state} positions must have zero remaining fraction")


@dataclass(frozen=True)
class StrategyAssessment:
    strategy_id: str
    horizon: str
    setup_score: float
    entry_decision: str
    position_decision: str | None
    factor_scores: dict[str, float]
    factor_clusters: dict[str, float]
    gates_passed: tuple[str, ...]
    gates_failed: tuple[str, ...]
    gates_missing: tuple[str, ...]
    leveraged_overlay: bool
    decision_policy: str = "opportunity-layered-v2"
    suggested_allocation_pct: float | None = None
    allocation_rationale: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataQuality:
    confidence: float
    available_components: tuple[str, ...]
    missing_components: tuple[str, ...]
    stale_components: tuple[str, ...]
    session_phase: str
    entry_eligible: bool
    probe_eligible: bool = False


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
    entry_price: float = 0.0
    user_context: dict[str, Any] = field(default_factory=dict)
    data_quality: DataQuality | None = None
    schema_version: str = SCHEMA_VERSION
    position_state: PositionStateSnapshot | None = None
    exit_plan: ExitPlan | None = None
    strategy_assessment: StrategyAssessment | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None
    horizon: str | None = None
    trade_id: str | None = None
    leveraged: bool = False

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["component_scores"] = self.component_scores.to_record()
        # `label` is the legacy classifier kept for historical comparability; the
        # authoritative execution verdict lives in strategy_assessment. Mirror it at
        # the top level so consumers that only read shallow fields cannot mistake a
        # legacy "hold" for an actionable decision.
        payload["entry_decision"] = (
            self.strategy_assessment.entry_decision if self.strategy_assessment else None
        )
        payload["label_semantics"] = "legacy-compatibility-only"
        return payload
