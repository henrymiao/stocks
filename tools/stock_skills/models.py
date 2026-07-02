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

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["component_scores"] = self.component_scores.to_record()
        return payload
