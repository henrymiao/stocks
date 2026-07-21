# Finance Methodology Evidence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenD-first, market-specific swing structure, thesis, valuation-scenario, and rolling-linkage evidence without letting uncalibrated positive signals increase the current strategy score.

**Architecture:** New methods live in focused sidecar modules and return explicit structured results with provenance, coverage, confidence, and unknown states. A method-policy adapter may only preserve or downgrade the existing `StrategyAssessment`; it never upgrades an entry or changes the legacy component score. Live and historical market data continue to come from Futu OpenD, while optional official/manual assumptions enter through one validated JSON contract.

**Tech Stack:** Python 3 standard library, frozen dataclasses, Futu OpenD through the existing `FutuFetcher`, JSON/JSONL, and `unittest`.

---

## Pre-flight

Run from `/Users/shuren/WorkSpace/codes/stocks`:

```bash
git status --short --branch
python3 -m unittest discover -s tests -v
```

Expected: the worktree is clean apart from this plan if it has not yet been committed, and the existing suite passes before feature work begins. Do not continue from an unexplained red baseline.

## File Map

Create:

- `tools/stock_skills/method_models.py`: result and provenance contracts for the sidecar layer.
- `tools/stock_skills/provenance.py`: evidence validation, precedence, and conflict detection.
- `tools/stock_skills/market_profiles.py`: US/A-share/Hong Kong analytical conventions; no fetching.
- `tools/stock_skills/swing_structure.py`: Stage 1–4, MA template, pivot, contraction, and breakout-volume analysis.
- `tools/stock_skills/linkage.py`: aligned-return rolling correlation, beta, downside correlation, and stability.
- `tools/stock_skills/valuation_scenarios.py`: explicit earnings-multiple, SOTP, and DCF scenarios with refusal on incomplete inputs.
- `tools/stock_skills/thesis.py`: pre-technical drivers, rival case, conditional paths, and evaluated invalidations.
- `tools/stock_skills/method_policy.py`: aggregation and monotonic decision restrictions.
- `tests/test_provenance.py`
- `tests/test_market_profiles.py`
- `tests/test_swing_structure.py`
- `tests/test_linkage.py`
- `tests/test_valuation_scenarios.py`
- `tests/test_thesis.py`
- `tests/test_method_policy.py`

Modify:

- `tools/stock_skills/models.py`: attach `MethodAssessment`, bump recommendation and decision-policy versions at integration.
- `tools/stock_skills/cli.py`: orchestrate method inputs, dynamic bar depth, OpenD reference histories, output, and journal serialization.
- `tools/stock_skills/scan_watchlist.py`: let swing deep analysis use its default long history unless the user explicitly overrides bars.
- `tools/stock_skills/review.py`: retain method state and restrictions in realised outcomes.
- `tests/test_models.py`
- `tests/test_cli.py`
- `tests/test_strategy.py`
- `tests/test_watchlist_cli.py`
- `tests/test_review.py`
- `skills/stock-analysis/SKILL.md`: document the new evidence layer and corrected policy version.

Do not modify `tools/stock_skills/futu_fetcher.py` unless an existing tested quote method is actually insufficient. It already exposes `get_daily_bars`, `get_fundamentals`, `get_financials`, and quote-only behavior.

### Task 1: Add provenance, market profiles, and method contracts

**Files:**

- Create: `tools/stock_skills/method_models.py`
- Create: `tools/stock_skills/provenance.py`
- Create: `tools/stock_skills/market_profiles.py`
- Create: `tests/test_provenance.py`
- Create: `tests/test_market_profiles.py`
- Modify: `tools/stock_skills/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing provenance and market-routing tests**

```python
# tests/test_provenance.py
import unittest

from tools.stock_skills.method_models import EvidenceValue
from tools.stock_skills.provenance import resolve_evidence


class ProvenanceTests(unittest.TestCase):
    def test_opend_wins_and_material_disagreement_is_exposed(self):
        live = EvidenceValue(100.0, "opend", "2026-07-21T10:00:00+08:00", "live", 1.0, "futu:snapshot")
        manual = EvidenceValue(92.0, "official-manual", "2026-07-21", "current", 0.9, "exchange:filing")

        resolved, conflict = resolve_evidence("last_price", live, manual, relative_tolerance=0.05)

        self.assertEqual(resolved, live)
        self.assertEqual(conflict, "last_price:opend!=official-manual")

    def test_unknown_never_becomes_zero_or_neutral(self):
        resolved, conflict = resolve_evidence("eps_growth", None, None)
        self.assertIsNone(resolved)
        self.assertIsNone(conflict)


if __name__ == "__main__":
    unittest.main()
```

```python
# tests/test_market_profiles.py
import unittest

from tools.stock_skills.market_profiles import resolve_market_profile


class MarketProfileTests(unittest.TestCase):
    def test_routes_three_equity_markets_without_reusing_us_assumptions(self):
        us = resolve_market_profile("US.NVDA")
        a_share = resolve_market_profile("SH.600309")
        hk = resolve_market_profile("HK.00700")

        self.assertEqual(us.profile_id, "us-equity-v1")
        self.assertEqual(a_share.profile_id, "a-share-equity-v1")
        self.assertEqual(hk.profile_id, "hk-equity-v1")
        self.assertEqual(a_share.benchmark_codes, ("SH.000001", "SZ.399006"))
        self.assertNotEqual(us.buy_zone_extension_pct, a_share.buy_zone_extension_pct)
        self.assertEqual(a_share.price_limit_policy, "board-aware")
        self.assertEqual(hk.lot_policy, "board-lot")

    def test_unknown_prefix_is_non_actionable_instead_of_us_default(self):
        profile = resolve_market_profile("CC.BTC_USD", asset_type="crypto")
        self.assertEqual(profile.profile_id, "unknown-market-v1")
        self.assertEqual(profile.allowed_valuation_methods, ())


if __name__ == "__main__":
    unittest.main()
```

Extend `tests/test_models.py` with a serialization assertion that an optional `method_assessment=None` remains JSON-ready and does not break old recommendation construction.

- [ ] **Step 2: Run the focused tests and verify the red state**

```bash
python3 -m unittest tests.test_provenance tests.test_market_profiles tests.test_models -v
```

Expected: FAIL because `method_models`, `provenance`, and `market_profiles` do not exist.

- [ ] **Step 3: Implement the contracts and routing**

Create `tools/stock_skills/method_models.py` with frozen dataclasses. Keep every unknown value explicit:

```python
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
```

Create `tools/stock_skills/provenance.py`:

```python
from __future__ import annotations

from .method_models import EvidenceValue


def _materially_different(left: object, right: object, tolerance: float) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left != right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        scale = max(abs(float(left)), abs(float(right)), 1e-12)
        return abs(float(left) - float(right)) / scale > tolerance
    return left != right


def resolve_evidence(
    key: str,
    opend: EvidenceValue | None,
    supplemental: EvidenceValue | None,
    *,
    relative_tolerance: float = 0.05,
) -> tuple[EvidenceValue | None, str | None]:
    if opend is None:
        return supplemental, None
    if supplemental is None:
        return opend, None
    conflict = None
    if _materially_different(opend.value, supplemental.value, relative_tolerance):
        conflict = f"{key}:{opend.source}!={supplemental.source}"
    return opend, conflict
```

Create `tools/stock_skills/market_profiles.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketProfile:
    profile_id: str
    benchmark_codes: tuple[str, ...]
    buy_zone_extension_pct: float
    minimum_stage_bars: int
    allowed_valuation_methods: tuple[str, ...]
    session_timezone: str
    price_limit_policy: str
    lot_policy: str
    liquidity_currency: str


_US = MarketProfile(
    "us-equity-v1", ("US.QQQ", "US.SPY"), 0.05, 220,
    ("earnings-multiple", "sotp", "dcf"), "America/New_York", "none", "single-share", "USD",
)
_A = MarketProfile(
    "a-share-equity-v1", ("SH.000001", "SZ.399006"), 0.03, 220,
    ("earnings-multiple", "sotp", "dcf"), "Asia/Shanghai", "board-aware", "board-lot", "CNY",
)
_HK = MarketProfile(
    "hk-equity-v1", ("HK.800000", "HK.800700"), 0.03, 220,
    ("earnings-multiple", "sotp", "dcf"), "Asia/Shanghai", "none", "board-lot", "HKD",
)
_UNKNOWN = MarketProfile(
    "unknown-market-v1", (), 0.0, 220, (), "UTC", "unknown", "unknown", "unknown",
)


def resolve_market_profile(code: str, asset_type: str = "equity") -> MarketProfile:
    prefix = code.split(".", 1)[0].upper() if "." in code else ""
    if prefix == "US":
        return _US
    if prefix in {"SH", "SZ"}:
        return _A
    if prefix == "HK":
        return _HK
    return _UNKNOWN
```

Import `MethodAssessment` into `tools/stock_skills/models.py` and add this optional field to `Recommendation` without changing the schema constant yet:

```python
method_assessment: MethodAssessment | None = None
```

- [ ] **Step 4: Run focused tests and verify green**

```bash
python3 -m unittest tests.test_provenance tests.test_market_profiles tests.test_models -v
```

Expected: PASS.

- [ ] **Step 5: Commit the foundation**

```bash
git add tools/stock_skills/method_models.py tools/stock_skills/provenance.py tools/stock_skills/market_profiles.py tools/stock_skills/models.py tests/test_provenance.py tests/test_market_profiles.py tests/test_models.py
git commit -m "feat: add method evidence contracts and market profiles"
```

### Task 2: Implement deterministic swing-structure evidence

**Files:**

- Create: `tools/stock_skills/swing_structure.py`
- Create: `tests/test_swing_structure.py`

- [ ] **Step 1: Write failing stage, unknown, and gate-effect tests**

```python
import unittest

from tools.stock_skills.market_profiles import resolve_market_profile
from tools.stock_skills.models import KLineBar
from tools.stock_skills.swing_structure import analyze_swing_structure


def _bars(closes):
    return [
        KLineBar(str(index), close, close * 1.01, close * 0.99, close, 1_000 + index * 10, close * 1_000)
        for index, close in enumerate(closes)
    ]


class SwingStructureTests(unittest.TestCase):
    def test_insufficient_history_is_unknown(self):
        result = analyze_swing_structure(_bars([100.0] * 219), 100.0, resolve_market_profile("HK.00700"))
        self.assertEqual(result.stage, "unknown")
        self.assertEqual(result.gate_effect, "none")
        self.assertEqual(result.coverage, 0.0)

    def test_ordered_rising_average_template_is_stage_two(self):
        closes = [50.0 + index * 0.4 for index in range(240)]
        result = analyze_swing_structure(_bars(closes), closes[-1], resolve_market_profile("US.NVDA"))
        self.assertEqual(result.stage, "stage-2")
        self.assertTrue(result.checklist["ma200-rising"])
        self.assertEqual(result.gate_effect, "none")

    def test_ordered_falling_average_template_rejects_new_swing_risk(self):
        closes = [150.0 - index * 0.4 for index in range(240)]
        result = analyze_swing_structure(_bars(closes), closes[-1], resolve_market_profile("SH.600309"))
        self.assertEqual(result.stage, "stage-4")
        self.assertEqual(result.gate_effect, "reject-new-risk")

    def test_contracting_stage_one_near_pivot_is_probe_only(self):
        bars = _bars([100.0] * 210)
        ranges = ((94.0, 106.0), (96.0, 104.0), (98.0, 102.0))
        for group, (low, high) in enumerate(ranges):
            for offset in range(10):
                close = (low + high) / 2.0
                bars.append(KLineBar(f"base-{group}-{offset}", close, high, low, close, 1_000, close * 1_000))
        result = analyze_swing_structure(bars, 102.0, resolve_market_profile("HK.00700"))
        self.assertEqual(result.stage, "stage-1")
        self.assertEqual(result.contraction_count, 2)
        self.assertIsNotNone(result.buy_zone)
        self.assertEqual(result.gate_effect, "probe-only")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify failure**

```bash
python3 -m unittest tests.test_swing_structure -v
```

Expected: FAIL because `swing_structure` does not exist.

- [ ] **Step 3: Implement the analyzer**

Use completed bars in chronological order. Define:

```python
from __future__ import annotations

from statistics import mean

from .market_profiles import MarketProfile
from .method_models import SwingStructureAnalysis
from .models import KLineBar


def _sma(values: list[float], window: int, end: int | None = None) -> float | None:
    selected = values[:end] if end is not None else values
    if len(selected) < window:
        return None
    return sum(selected[-window:]) / window


def _range_pct(bars: list[KLineBar]) -> float:
    middle = mean(bar.close for bar in bars)
    return 0.0 if middle <= 0 else (max(bar.high for bar in bars) - min(bar.low for bar in bars)) / middle


def analyze_swing_structure(
    bars: list[KLineBar],
    current_price: float,
    profile: MarketProfile,
) -> SwingStructureAnalysis:
    required = profile.minimum_stage_bars
    if len(bars) < required or current_price <= 0:
        return SwingStructureAnalysis(
            "unknown", None, None, None, {}, None, None, None, None,
            "none", 0.0, 0.0, (f"need at least {required} completed daily bars",),
        )

    closes = [bar.close for bar in bars]
    ma50 = _sma(closes, 50)
    ma150 = _sma(closes, 150)
    ma200 = _sma(closes, 200)
    ma50_prior = _sma(closes, 50, -10)
    ma200_prior = _sma(closes, 200, -20)
    assert None not in {ma50, ma150, ma200, ma50_prior, ma200_prior}
    high_52w = max(bar.high for bar in bars[-220:])
    low_52w = min(bar.low for bar in bars[-220:])
    checklist = {
        "price-above-ma50": current_price > ma50,
        "ma50-above-ma150": ma50 > ma150,
        "ma150-above-ma200": ma150 > ma200,
        "ma200-rising": ma200 > ma200_prior,
        "price-30pct-above-low": current_price >= low_52w * 1.30,
        "price-within-25pct-high": current_price >= high_52w * 0.75,
    }
    if current_price > ma50 > ma150 > ma200 and ma200 > ma200_prior:
        stage = "stage-2"
    elif current_price < ma50 < ma150 < ma200 and ma200 < ma200_prior:
        stage = "stage-4"
    elif current_price < ma50 and ma50 < ma50_prior:
        stage = "stage-3"
    else:
        stage = "stage-1"

    pivot = max(bar.high for bar in bars[-21:-1])
    windows = (bars[-30:-20], bars[-20:-10], bars[-10:])
    ranges = [_range_pct(window) for window in windows]
    contraction_count = sum(right < left for left, right in zip(ranges, ranges[1:]))
    previous_volume = mean(bar.volume for bar in bars[-21:-1])
    volume_ratio = None if previous_volume <= 0 else bars[-1].volume / previous_volume
    near_pivot = pivot > 0 and pivot * 0.97 <= current_price <= pivot * (1.0 + profile.buy_zone_extension_pct)
    late_stage_one = stage == "stage-1" and contraction_count == 2 and near_pivot
    gate_effect = "reject-new-risk" if stage in {"stage-3", "stage-4"} else ("probe-only" if late_stage_one else "none")
    buy_zone = (round(pivot, 4), round(pivot * (1.0 + profile.buy_zone_extension_pct), 4))
    return SwingStructureAnalysis(
        stage=stage,
        ma50=round(ma50, 4),
        ma150=round(ma150, 4),
        ma200=round(ma200, 4),
        checklist=checklist,
        pivot=round(pivot, 4),
        buy_zone=buy_zone,
        contraction_count=contraction_count,
        breakout_volume_ratio=None if volume_ratio is None else round(volume_ratio, 4),
        gate_effect=gate_effect,
        coverage=1.0,
        confidence=1.0,
        notes=(),
    )
```

Keep the classifications mutually exclusive and preserve `unknown` when history is short. Do not use the current partial daily bar; Task 7 supplies only completed bars.

- [ ] **Step 4: Run focused tests**

```bash
python3 -m unittest tests.test_swing_structure -v
```

Expected: PASS for Stage 1–4 fixtures, unknown history, pivot, contraction, and market-specific buy zones.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/swing_structure.py tests/test_swing_structure.py
git commit -m "feat: add swing stage and contraction evidence"
```

### Task 3: Implement rolling linkage on aligned returns

**Files:**

- Create: `tools/stock_skills/linkage.py`
- Create: `tests/test_linkage.py`

- [ ] **Step 1: Write failing correlation, beta, downside, and instability tests**

```python
import unittest

from tools.stock_skills.linkage import analyze_linkage
from tools.stock_skills.models import KLineBar


def _series(returns, scale=1.0):
    close = 100.0
    bars = [KLineBar("000", close, close, close, close, 1_000, 100_000.0)]
    for index, value in enumerate(returns, start=1):
        close *= 1.0 + value * scale
        bars.append(KLineBar(f"{index:03d}", close, close, close, close, 1_000, close * 1_000))
    return bars


class LinkageTests(unittest.TestCase):
    def test_aligned_scaled_returns_produce_expected_correlation_and_beta(self):
        returns = [0.01 if index % 3 else -0.007 for index in range(65)]
        result = analyze_linkage(_series(returns, 1.5), {"US.QQQ": _series(returns)})
        row = result.references[0]
        self.assertAlmostEqual(row.correlation_60d, 1.0, places=6)
        self.assertAlmostEqual(row.beta_60d, 1.5, places=1)
        self.assertAlmostEqual(row.downside_correlation, 1.0, places=6)

    def test_misaligned_or_short_history_is_unknown(self):
        result = analyze_linkage(_series([0.01] * 10), {"HK.800000": _series([0.01] * 10)})
        self.assertEqual(result.references[0].stance, "unknown")
        self.assertEqual(result.coverage, 0.0)

    def test_correlation_regime_change_is_unstable(self):
        reference = [0.01 if index % 2 else -0.01 for index in range(70)]
        target = reference[:35] + [-value for value in reference[35:]]
        result = analyze_linkage(_series(target), {"SH.000001": _series(reference)})
        self.assertEqual(result.references[0].stability, "unstable")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify failure**

```bash
python3 -m unittest tests.test_linkage -v
```

Expected: FAIL because `linkage` does not exist.

- [ ] **Step 3: Implement aligned-return statistics**

Implement `tools/stock_skills/linkage.py` with the complete aligned-return calculation:

```python
from __future__ import annotations

import math
from statistics import mean

from .method_models import LinkageAnalysis, LinkageReferenceAnalysis
from .models import KLineBar


def _returns_by_time(bars: list[KLineBar]) -> dict[str, float]:
    ordered = sorted(bars, key=lambda bar: bar.time)
    result = {}
    for previous, current in zip(ordered, ordered[1:]):
        if previous.close > 0:
            result[current.time] = current.close / previous.close - 1.0
    return result


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = mean(left), mean(right)
    left_sum = sum((value - left_mean) ** 2 for value in left)
    right_sum = sum((value - right_mean) ** 2 for value in right)
    if left_sum <= 0 or right_sum <= 0:
        return None
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    return numerator / math.sqrt(left_sum * right_sum)


def _beta(target: list[float], reference: list[float]) -> float | None:
    if len(target) != len(reference) or len(target) < 2:
        return None
    target_mean, reference_mean = mean(target), mean(reference)
    variance = sum((value - reference_mean) ** 2 for value in reference)
    if variance <= 0:
        return None
    covariance = sum(
        (target_value - target_mean) * (reference_value - reference_mean)
        for target_value, reference_value in zip(target, reference)
    )
    return covariance / variance


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def analyze_linkage(
    target_bars: list[KLineBar],
    reference_bars: dict[str, list[KLineBar]],
) -> LinkageAnalysis:
    target_returns = _returns_by_time(target_bars)
    rows = []
    confidence_parts = []
    usable = 0
    for code in sorted(reference_bars):
        reference_returns = _returns_by_time(reference_bars[code])
        times = sorted(set(target_returns) & set(reference_returns))[-60:]
        target = [target_returns[time] for time in times]
        reference = [reference_returns[time] for time in times]
        corr20 = _correlation(target[-20:], reference[-20:]) if len(times) >= 20 else None
        corr60 = _correlation(target, reference) if len(times) >= 60 else None
        beta60 = _beta(target, reference) if len(times) >= 60 else None
        downside_pairs = [(a, b) for a, b in zip(target, reference) if b < 0]
        downside = (
            _correlation([pair[0] for pair in downside_pairs], [pair[1] for pair in downside_pairs])
            if len(downside_pairs) >= 5 else None
        )
        first = _correlation(target[:30], reference[:30]) if len(times) >= 60 else None
        second = _correlation(target[-30:], reference[-30:]) if len(times) >= 60 else None
        stability = (
            "unstable"
            if first is not None and second is not None and abs(second - first) >= 0.35
            else ("stable" if corr60 is not None else "unknown")
        )
        if stability == "unstable":
            stance = "unstable"
        elif corr60 is not None and corr60 >= 0.40 and target and reference:
            stance = "confirming" if target[-1] * reference[-1] >= 0 else "diverging"
        else:
            stance = "unknown"
        if corr60 is not None:
            usable += 1
        confidence_parts.append(min(len(times) / 60.0, 1.0))
        rows.append(LinkageReferenceAnalysis(
            code, _rounded(corr20), _rounded(corr60), _rounded(beta60), _rounded(downside),
            stability, stance, len(times),
        ))
    requested = len(reference_bars)
    return LinkageAnalysis(
        references=tuple(rows),
        coverage=0.0 if requested == 0 else round(usable / requested, 4),
        confidence=0.0 if not confidence_parts else round(mean(confidence_parts), 4),
        notes=() if requested else ("no reference histories",),
    )
```

The complete algorithm is:

1. Sort each series by `bar.time`.
2. Convert consecutive closes into simple returns keyed by the later bar's time.
3. Intersect timestamps and retain the most recent 60 aligned observations.
4. Require 20 observations for 20-day correlation and 60 for 60-day correlation/beta.
5. Compute beta as covariance(target, reference) divided by reference variance; return `None` when variance is zero.
6. Compute downside correlation from aligned observations where the reference return is negative; require at least five.
7. Compare correlation in the first and second 30-observation halves. Mark `unstable` when both exist and differ by at least 0.35.
8. When stable 60-day correlation is at least 0.40, compare the latest signs: same sign is `confirming`, opposite sign is `diverging`; otherwise use `unknown`.
9. Aggregate coverage as usable 60-day references divided by requested references. Confidence is the mean of `min(observations / 60, 1)`.

Use `statistics.mean` and `math.sqrt`; round stored outputs to four decimals. Do not calculate correlation from price levels and do not infer causality.

- [ ] **Step 4: Run focused tests**

```bash
python3 -m unittest tests.test_linkage -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/linkage.py tests/test_linkage.py
git commit -m "feat: add rolling cross-market linkage evidence"
```

### Task 4: Implement explicit valuation scenarios

**Files:**

- Create: `tools/stock_skills/valuation_scenarios.py`
- Create: `tests/test_valuation_scenarios.py`

- [ ] **Step 1: Write failing earnings-multiple, DCF refusal, DCF, and ordering tests**

```python
import unittest

from tools.stock_skills.market_profiles import resolve_market_profile
from tools.stock_skills.valuation_scenarios import analyze_valuation_scenarios


class ValuationScenarioTests(unittest.TestCase):
    def test_earnings_multiple_cases_are_explicit_and_ordered(self):
        assumptions = {
            "method": "earnings-multiple",
            "cases": {
                "bear": {"eps": 2.0, "multiple": 15.0},
                "base": {"eps": 2.4, "multiple": 20.0},
                "bull": {"eps": 2.8, "multiple": 25.0},
            },
        }
        result = analyze_valuation_scenarios(assumptions, resolve_market_profile("HK.00700"))
        self.assertEqual([case.fair_value for case in result.cases], [30.0, 48.0, 70.0])
        self.assertTrue(all(case.method == "earnings-multiple" for case in result.cases))
        self.assertEqual(result.status, "available")
        self.assertIn("earnings-multiple", result.sensitivity)

    def test_incomplete_dcf_is_refused_without_defaults(self):
        result = analyze_valuation_scenarios(
            {"method": "dcf", "cases": {"base": {"fcff": 100.0}}},
            resolve_market_profile("US.NVDA"),
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.cases, ())
        self.assertIn("missing", result.notes[0])

    def test_complete_dcf_requires_discount_rate_above_terminal_growth(self):
        invalid = {
            "method": "dcf",
            "cases": {
                name: {"fcff": 100.0, "growth_rate": 0.08, "years": 5, "discount_rate": 0.03,
                       "terminal_growth": 0.03, "net_debt": 20.0, "shares": 10.0}
                for name in ("bear", "base", "bull")
            },
        }
        result = analyze_valuation_scenarios(invalid, resolve_market_profile("SH.600309"))
        self.assertEqual(result.status, "unavailable")

    def test_two_valid_methods_report_base_case_disagreement(self):
        earnings = {
            "method": "earnings-multiple",
            "cases": {
                "bear": {"eps": 2.0, "multiple": 15.0},
                "base": {"eps": 2.4, "multiple": 20.0},
                "bull": {"eps": 2.8, "multiple": 25.0},
            },
        }
        sotp = {
            "method": "sotp",
            "cases": {
                "bear": {"parts": [{"value": 350.0}], "net_debt": 50.0, "shares": 10.0},
                "base": {"parts": [{"value": 550.0}], "net_debt": 50.0, "shares": 10.0},
                "bull": {"parts": [{"value": 750.0}], "net_debt": 50.0, "shares": 10.0},
            },
        }
        result = analyze_valuation_scenarios({"methods": [earnings, sotp]}, resolve_market_profile("HK.00700"))
        self.assertEqual(result.methods_used, ("earnings-multiple", "sotp"))
        self.assertIsNotNone(result.method_disagreement_pct)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify failure**

```bash
python3 -m unittest tests.test_valuation_scenarios -v
```

Expected: FAIL because `valuation_scenarios` does not exist.

- [ ] **Step 3: Implement scenario validation and calculations**

Implement three allowed methods only when selected by the resolved market profile:

```python
_CASE_ORDER = ("bear", "base", "bull")


def _earnings_value(case: dict[str, object]) -> float:
    eps = _positive(case, "eps")
    multiple = _positive(case, "multiple")
    return eps * multiple


def _sotp_value(case: dict[str, object]) -> float:
    parts = case.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("missing non-empty parts")
    gross_value = sum(_positive(item, "value") for item in parts if isinstance(item, dict))
    net_debt = _number(case, "net_debt")
    shares = _positive(case, "shares")
    return (gross_value - net_debt) / shares


def _dcf_value(case: dict[str, object]) -> float:
    fcff = _positive(case, "fcff")
    growth = _number(case, "growth_rate")
    years = int(_positive(case, "years"))
    discount = _positive(case, "discount_rate")
    terminal_growth = _number(case, "terminal_growth")
    net_debt = _number(case, "net_debt")
    shares = _positive(case, "shares")
    if not 1 <= years <= 10:
        raise ValueError("years must be between 1 and 10")
    if discount <= terminal_growth:
        raise ValueError("discount_rate must exceed terminal_growth")
    present = 0.0
    terminal_fcff = fcff
    for year in range(1, years + 1):
        terminal_fcff *= 1.0 + growth
        present += terminal_fcff / ((1.0 + discount) ** year)
    terminal = terminal_fcff * (1.0 + terminal_growth) / (discount - terminal_growth)
    present += terminal / ((1.0 + discount) ** years)
    return (present - net_debt) / shares
```

`analyze_valuation_scenarios` must:

- accept either the single-method shorthand shown above or an object whose `methods` value is a non-empty list of the same method records;
- evaluate every method independently, retain valid methods, and add an explanatory note for each rejected method;
- return `unavailable` with zero coverage when assumptions are absent, every method is disallowed/invalid, or all required inputs are missing;
- require all three named cases for each retained method;
- require `bear <= base <= bull` fair values;
- create earnings sensitivity at base EPS ±10% and base multiple ±10%, stored under `sensitivity["earnings-multiple"]`;
- create DCF sensitivity at base discount rate ±1 percentage point and terminal growth ±0.5 percentage point, skipping combinations where discount is not greater than terminal growth and storing it under `sensitivity["dcf"]`;
- set method disagreement to `(max(base_values) - min(base_values)) / mean(base_values) * 100` when at least two methods are valid, otherwise `None`;
- expose the method name and exact input dictionary in every `ValuationCase`.

Catch `TypeError`, `ValueError`, and `KeyError` at the public boundary and return an explanatory unavailable result. Never insert a risk-free rate, terminal growth, target multiple, or peer assumption.

- [ ] **Step 4: Run focused tests**

```bash
python3 -m unittest tests.test_valuation_scenarios -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/valuation_scenarios.py tests/test_valuation_scenarios.py
git commit -m "feat: add explicit valuation scenario analysis"
```

### Task 5: Implement pre-technical structured thesis

**Files:**

- Create: `tools/stock_skills/thesis.py`
- Create: `tests/test_thesis.py`

- [ ] **Step 1: Write failing logic-first and invalidation tests**

```python
import unittest

from tools.stock_skills.method_models import ValuationScenarioAnalysis
from tools.stock_skills.models import FundamentalAnalysis
from tools.stock_skills.thesis import analyze_thesis


UNKNOWN_VALUATION = ValuationScenarioAnalysis("unavailable", (), (), {}, None, 0.0, 0.0, ("no assumptions",))


class ThesisTests(unittest.TestCase):
    def test_no_observed_driver_stays_unknown(self):
        result = analyze_thesis(None, "unknown", "neutral", UNKNOWN_VALUATION, {}, {})
        self.assertEqual(result.state, "unknown")
        self.assertTrue(result.unresolved)

    def test_growth_and_sector_leadership_create_observed_upside_drivers(self):
        fundamental = FundamentalAnalysis(75.0, "fair", "growth", 1.1, ["EPS growth 30%"], quality=80.0)
        result = analyze_thesis(fundamental, "leading", "risk-on", UNKNOWN_VALUATION, {}, {})
        self.assertEqual(result.state, "supported")
        self.assertTrue(any("business quality" in item for item in result.upside_drivers))
        self.assertTrue(any("sector" in item for item in result.upside_drivers))
        self.assertNotIn("breakout", " ".join(result.upside_drivers).lower())

    def test_only_evaluated_manual_condition_can_invalidate(self):
        manual = {
            "invalidations": [
                {"field": "revenue_growth", "operator": "<", "value": 0.0, "reason": "growth thesis failed"}
            ]
        }
        result = analyze_thesis(None, "unknown", "neutral", UNKNOWN_VALUATION, manual, {"revenue_growth": -5.0})
        self.assertEqual(result.state, "invalidated")
        self.assertEqual(result.invalidations, ("growth thesis failed",))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify failure**

```bash
python3 -m unittest tests.test_thesis -v
```

Expected: FAIL because `thesis` does not exist.

- [ ] **Step 3: Implement the thesis builder without technical inputs**

The public signature is:

```python
def analyze_thesis(
    fundamental: FundamentalAnalysis | None,
    sector_stance: str,
    market_regime: str,
    valuation: ValuationScenarioAnalysis,
    manual: dict[str, object],
    observed_metrics: dict[str, float],
) -> ThesisAnalysis:
```

Implementation rules:

- Add an upside observation for `fundamental.quality >= 65`, `fundamental.stance in {"cheap", "fair"}`, sector `leading`, or an available valuation whose base case exceeds current price supplied in `manual.current_price`.
- Add a downside observation for `fundamental.quality < 40`, `fundamental.stance == "expensive"`, sector `lagging`/`sector-weak`, or market `risk-off`.
- Keep observations separate from conditional inference. Bull/Base/Bear paths must use wording such as “If observed growth and sector leadership persist...” rather than claiming an unsourced catalyst.
- Set the rival hypothesis to the strongest downside driver when upside drivers exist, otherwise the strongest upside driver when downside drivers exist.
- Evaluate manual invalidations with operators `<`, `<=`, `>`, `>=`, `==`, and `!=`. A missing observed metric leaves the condition unresolved and cannot invalidate.
- Use `invalidated` only when at least one condition evaluates true; otherwise use `supported` for at least two upside and no downside drivers, `mixed` for any observed but conflicting/partial evidence, and `unknown` for no drivers.
- Set `technical_confirmation="not-evaluated"`. Task 7 may annotate confirmation after structure/linkage results, but those signals must not create the primary causal driver.
- Coverage is evaluated manual conditions plus available business/sector/market/valuation slots divided by all applicable slots. Confidence is coverage capped at 1.

- [ ] **Step 4: Run focused tests**

```bash
python3 -m unittest tests.test_thesis -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/thesis.py tests/test_thesis.py
git commit -m "feat: add structured pre-technical thesis evidence"
```

### Task 6: Aggregate method evidence and apply monotonic restrictions

**Files:**

- Create: `tools/stock_skills/method_policy.py`
- Create: `tests/test_method_policy.py`
- Modify: `tools/stock_skills/models.py`
- Modify: `tests/test_strategy.py`

- [ ] **Step 1: Write failing policy tests**

Create `tests/test_method_policy.py` with complete helpers and downgrade invariants:

```python
import unittest

from tools.stock_skills.method_models import (
    LinkageAnalysis,
    SwingStructureAnalysis,
    ThesisAnalysis,
    ValuationScenarioAnalysis,
)
from tools.stock_skills.method_policy import build_method_assessment, apply_method_restrictions
from tools.stock_skills.models import StrategyAssessment
from tools.stock_skills.strategy import get_strategy_profile


def _assessment(entry="enter", setup=75.0, horizon="swing", position=None, allocation=20.0):
    return StrategyAssessment(
        strategy_id=f"{horizon}-balanced-v1",
        horizon=horizon,
        setup_score=setup,
        entry_decision=entry,
        position_decision=position,
        factor_scores={},
        factor_clusters={},
        gates_passed=(),
        gates_failed=(),
        gates_missing=(),
        leveraged_overlay=False,
        suggested_allocation_pct=allocation,
        allocation_rationale="fixture",
        decision_inputs={"planned_allocation_pct": allocation},
    )


def _methods(
    stage="stage-2", gate=None, thesis_state="supported", conflicts=(),
    valuation_disagreement=None, valuation_critical=False,
):
    if gate is None:
        gate = "reject-new-risk" if stage in {"stage-3", "stage-4"} else "none"
    structure = SwingStructureAnalysis(
        stage, 100.0, 95.0, 90.0, {}, 110.0, (110.0, 113.3), 2, 1.2,
        gate, 1.0, 1.0,
    )
    thesis = ThesisAnalysis(
        thesis_state, ("growth",), (), "bull", "base", "bear", "rival", (), (),
        "not-evaluated", 1.0, 1.0,
    )
    valuation = ValuationScenarioAnalysis(
        "available" if valuation_disagreement is not None else "unavailable",
        ("earnings-multiple", "sotp") if valuation_disagreement is not None else (),
        (), {}, valuation_disagreement, 1.0 if valuation_disagreement is not None else 0.0,
        1.0 if valuation_disagreement is not None else 0.0,
    )
    linkage = LinkageAnalysis((), 0.0, 0.0)
    return build_method_assessment(
        "hk-equity-v1", structure, thesis, valuation, linkage,
        valuation_critical=valuation_critical, source_conflicts=conflicts,
    )


class MethodPolicyTests(unittest.TestCase):
    def test_positive_evidence_does_not_change_score_or_upgrade_watch(self):
        original = _assessment(entry="watch", setup=64.0)
        final = apply_method_restrictions(original, _methods(stage="stage-2"), get_strategy_profile("swing"), False)
        self.assertEqual(final.setup_score, 64.0)
        self.assertEqual(final.entry_decision, "watch")

    def test_stage_four_rejects_new_swing_risk_but_not_short_setup(self):
        swing = apply_method_restrictions(_assessment(entry="enter"), _methods(stage="stage-4"), get_strategy_profile("swing"), False)
        short = apply_method_restrictions(_assessment(entry="enter", horizon="short"), _methods(stage="stage-4"), get_strategy_profile("short"), False)
        self.assertEqual(swing.entry_decision, "reject")
        self.assertEqual(short.entry_decision, "enter")

    def test_stage_one_caps_full_swing_entry_to_probe(self):
        original = _assessment(entry="enter", allocation=20.0)
        final = apply_method_restrictions(original, _methods(stage="stage-1", gate="probe-only"), get_strategy_profile("swing"), False)
        self.assertEqual(final.entry_decision, "probe")
        self.assertEqual(final.suggested_allocation_pct, 4.0)

    def test_existing_add_is_downgraded_to_hold_not_forced_exit(self):
        original = _assessment(entry="enter", position="add", allocation=20.0)
        final = apply_method_restrictions(original, _methods(stage="stage-4"), get_strategy_profile("swing"), True)
        self.assertEqual(final.position_decision, "hold")
        self.assertNotEqual(final.position_decision, "full-exit")

    def test_source_conflict_rejects_short_and_swing(self):
        methods = _methods(conflicts=("last_price:opend!=official-manual",))
        short = apply_method_restrictions(_assessment(horizon="short"), methods, get_strategy_profile("short"), False)
        swing = apply_method_restrictions(_assessment(), methods, get_strategy_profile("swing"), False)
        self.assertEqual(short.entry_decision, "reject")
        self.assertEqual(swing.entry_decision, "reject")

    def test_evaluated_thesis_invalidation_rejects_only_new_swing_risk(self):
        methods = _methods(thesis_state="invalidated")
        short = apply_method_restrictions(_assessment(horizon="short"), methods, get_strategy_profile("short"), False)
        swing = apply_method_restrictions(_assessment(), methods, get_strategy_profile("swing"), False)
        self.assertEqual(short.entry_decision, "enter")
        self.assertEqual(swing.entry_decision, "reject")

    def test_valuation_disagreement_restricts_only_when_declared_critical(self):
        ordinary = apply_method_restrictions(
            _assessment(), _methods(valuation_disagreement=35.0), get_strategy_profile("swing"), False,
        )
        critical = apply_method_restrictions(
            _assessment(), _methods(valuation_disagreement=35.0, valuation_critical=True),
            get_strategy_profile("swing"), False,
        )
        self.assertEqual(ordinary.entry_decision, "enter")
        self.assertEqual(critical.entry_decision, "reject")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify failure**

```bash
python3 -m unittest tests.test_method_policy tests.test_strategy -v
```

Expected: FAIL because `method_policy` does not exist.

- [ ] **Step 3: Implement aggregation and downgrade-only policy**

Create `tools/stock_skills/method_policy.py` with:

```python
from dataclasses import replace

from .method_models import MethodAssessment, MethodRestriction
from .models import StrategyAssessment
from .strategy import StrategyProfile

METHOD_POLICY = "finance-method-evidence-v1"
VALUATION_DISAGREEMENT_REJECT_PCT = 30.0


def build_method_assessment(
    profile_id, structure, thesis, valuation, linkage, *,
    valuation_critical=False, source_conflicts=(), errors=None,
):
    restrictions = []
    if source_conflicts:
        restrictions.append(MethodRestriction("source-conflict", "reject-new-risk", ("short", "swing"), "material source conflict"))
    if structure.gate_effect == "reject-new-risk":
        restrictions.append(MethodRestriction(f"swing-{structure.stage}", "reject-new-risk", ("swing",), f"{structure.stage} blocks new swing risk"))
    elif structure.gate_effect == "probe-only":
        restrictions.append(MethodRestriction("swing-stage-1-probe", "probe-only", ("swing",), "late Stage 1 permits only a capped probe"))
    if thesis.state == "invalidated":
        restrictions.append(MethodRestriction("thesis-invalidated", "reject-new-risk", ("swing",), "evaluated thesis invalidation"))
    if (
        valuation_critical
        and valuation.method_disagreement_pct is not None
        and valuation.method_disagreement_pct >= VALUATION_DISAGREEMENT_REJECT_PCT
    ):
        restrictions.append(MethodRestriction(
            "valuation-method-disagreement", "reject-new-risk", ("swing",),
            f"critical valuation methods disagree by {valuation.method_disagreement_pct}%",
        ))
    coverages = [structure.coverage, thesis.coverage, valuation.coverage, linkage.coverage]
    confidences = [structure.confidence, thesis.confidence, valuation.confidence, linkage.confidence]
    return MethodAssessment(
        profile_id, structure, thesis, valuation, linkage,
        round(sum(coverages) / 4.0, 4),
        round(sum(confidences) / 4.0, 4),
        tuple(restrictions), tuple(source_conflicts), METHOD_POLICY, errors or {},
    )


def apply_method_restrictions(assessment, methods, profile, has_position):
    applicable = [item for item in methods.restrictions if assessment.horizon in item.horizons]
    reject = any(item.effect == "reject-new-risk" for item in applicable)
    probe_only = any(item.effect == "probe-only" for item in applicable)
    entry = assessment.entry_decision
    position = assessment.position_decision
    allocation = assessment.suggested_allocation_pct
    if reject and entry in {"enter", "probe", "watch"}:
        entry = "reject"
        allocation = None
    elif probe_only and entry == "enter":
        entry = "probe"
        planned = assessment.decision_inputs.get("planned_allocation_pct")
        if isinstance(planned, (int, float)) and not isinstance(planned, bool):
            allocation = round(min(float(planned) * profile.probe_allocation_fraction, profile.probe_allocation_cap_pct), 2)
    if has_position and position == "add" and (reject or probe_only):
        position = "hold"
    notes = assessment.notes + tuple(f"method restriction: {item.code} — {item.reason}" for item in applicable)
    inputs = dict(assessment.decision_inputs)
    inputs.update(method_policy=methods.method_policy, base_entry_decision=assessment.entry_decision)
    return replace(
        assessment,
        entry_decision=entry,
        position_decision=position,
        suggested_allocation_pct=allocation,
        decision_inputs=inputs,
        notes=notes,
    )
```

Preserve an already stricter `reject`, `partial-exit`, or `full-exit`. The adapter must never convert `reject`/`watch` to `probe`/`enter`, never increase allocation, and never alter `setup_score`, `factor_scores`, or `factor_clusters`.

Do not bump `DECISION_POLICY` in this task; that happens atomically with CLI integration so no record advertises the new policy before restrictions are actually wired.

- [ ] **Step 4: Run focused policy and strategy tests**

```bash
python3 -m unittest tests.test_method_policy tests.test_strategy -v
```

Expected: PASS with existing strategy results unchanged when no applicable method restriction is present.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/method_policy.py tests/test_method_policy.py tools/stock_skills/models.py tests/test_strategy.py
git commit -m "feat: add downgrade-only method decision policy"
```

### Task 7: Integrate the sidecar layer with OpenD-backed CLI analysis

**Files:**

- Modify: `tools/stock_skills/cli.py`
- Modify: `tools/stock_skills/models.py`
- Modify: `tools/stock_skills/scan_watchlist.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_watchlist_cli.py`

- [ ] **Step 1: Write failing integration tests**

Import `_bars_for_horizon` and `_completed_daily_bars` from `cli`, then add these tests to `tests/test_cli.py`:

```python
def _method_bars(count):
    return [
        KLineBar(f"{index:03d}", 100.0 + index, 101.0 + index, 99.0 + index, 100.0 + index, 1_000, 100_000.0)
        for index in range(count)
    ]


def test_default_bar_depth_is_horizon_specific(self):
    self.assertEqual(_bars_for_horizon("short", None), 30)
    self.assertEqual(_bars_for_horizon("swing", None), 260)
    self.assertEqual(_bars_for_horizon("swing", 80), 80)

def test_completed_daily_bars_excludes_live_partial_bar(self):
    bars = _method_bars(220)
    completed = _completed_daily_bars(bars, session_phase="intraday")
    self.assertEqual(completed, bars[:-1])

def test_dry_run_serializes_method_evidence_and_new_policy(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "recommendation.json"
        exit_code = main([
            "dry-run", "--code", FIXTURE_CODE, "--horizon", "swing",
            "--event-days", "10", "--output", str(output),
        ])
        payload = json.loads(output.read_text(encoding="utf-8"))
    self.assertEqual(exit_code, 0)
    self.assertEqual(payload["schema_version"], "recommendation-v6")
    self.assertEqual(payload["strategy_assessment"]["decision_policy"], "logic-first-method-evidence-v6")
    self.assertIn("method_assessment", payload)
    self.assertEqual(payload["entry_decision"], payload["strategy_assessment"]["entry_decision"])

def test_no_yfinance_or_trade_module_is_imported(self):
    import sys
    self.assertNotIn("yfinance", sys.modules)
    self.assertFalse(any(name.startswith("futu.trade") for name in sys.modules))
```

Add a recording fake and a live-command test:

```python
class RecordingMethodFetcher(FakeFetcher):
    target_bar_requests = []
    reference_bar_requests = []

    def build_state(self, code, num_bars=30, user_context=None):
        self.__class__.target_bar_requests.append((code, num_bars))
        return super().build_state(code, num_bars=num_bars, user_context=user_context)

    def get_daily_bars(self, code, num=30):
        self.__class__.reference_bar_requests.append((code, num))
        if code == "US.BAD":
            raise RuntimeError("fixture reference failure")
        return _method_bars(num)


def test_live_swing_uses_long_target_history_and_bounded_reference_history(self):
    RecordingMethodFetcher.target_bar_requests.clear()
    RecordingMethodFetcher.reference_bar_requests.clear()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "recommendation.json"
        with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", RecordingMethodFetcher):
            exit_code = main([
                "analyze", "--code", "US.NVDA", "--horizon", "swing",
                "--cross", "US.QQQ", "US.BAD", "--no-sector", "--no-market", "--no-macro",
                "--no-fundamental", "--event-days", "10", "--no-journal", "--output", str(output),
            ])
        payload = json.loads(output.read_text(encoding="utf-8"))
    self.assertEqual(exit_code, 0)
    self.assertEqual(RecordingMethodFetcher.target_bar_requests, [("US.NVDA", 260)])
    self.assertLessEqual(len(RecordingMethodFetcher.reference_bar_requests), 4)
    self.assertTrue(all(num == 80 for _, num in RecordingMethodFetcher.reference_bar_requests))
    self.assertNotIn("US.BAD", [row["code"] for row in payload["method_assessment"]["linkage"]["references"]])
```

In `tests/test_watchlist_cli.py`, extract child-command construction into the pure `_analysis_command` helper in `scan_watchlist.py` and test it directly:

```python
def test_swing_child_command_uses_dynamic_default_unless_bars_are_explicit(self):
    entry = {"code": "HK.00700", "valuation_profile": "growth"}
    base = _analysis_command(entry, "swing", "/tmp/out.json", "/tmp/shared.json", "data/watchlists/core.json", None)
    short = _analysis_command(entry, "short", "/tmp/out.json", "/tmp/shared.json", "data/watchlists/core.json", None)
    explicit = _analysis_command(entry, "swing", "/tmp/out.json", "/tmp/shared.json", "data/watchlists/core.json", 90)
    self.assertNotIn("--bars", base)
    self.assertEqual(short[short.index("--bars") + 1], "60")
    self.assertEqual(explicit[explicit.index("--bars") + 1], "90")
```

- [ ] **Step 2: Run integration tests and verify failure**

```bash
python3 -m unittest tests.test_cli tests.test_models tests.test_watchlist_cli -v
```

Expected: FAIL because the helper functions, schema/policy values, and method orchestration are absent.

- [ ] **Step 3: Add CLI helpers and validated manual input loading**

Add:

```python
def _bars_for_horizon(horizon: str, requested: int | None) -> int:
    if requested is not None:
        if requested <= 0:
            raise ValueError("bars must be positive")
        return requested
    return 260 if horizon == "swing" else 30


def _completed_daily_bars(bars: list[KLineBar], session_phase: str) -> list[KLineBar]:
    return bars[:-1] if session_phase == "intraday" and bars else list(bars)


def _load_method_inputs(raw: str | None) -> dict[str, object]:
    if raw is None:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("method inputs must be a JSON object")
    allowed = {"thesis", "valuation", "evidence"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown method input sections: {sorted(unknown)}")
    return payload


def _manual_evidence(payload: dict[str, object]) -> dict[str, EvidenceValue]:
    section = payload.get("evidence", {})
    if not isinstance(section, dict):
        raise ValueError("method evidence must be an object")
    result = {}
    for key, record in section.items():
        if not isinstance(record, dict):
            raise ValueError(f"method evidence {key} must be an object")
        if record.get("source") != "official-manual":
            raise ValueError(f"method evidence {key} must use official-manual")
        if not record.get("as_of") or not record.get("source_ref"):
            raise ValueError(f"method evidence {key} requires as_of and source_ref")
        result[str(key)] = EvidenceValue(
            value=record.get("value"),
            source="official-manual",
            as_of=str(record["as_of"]),
            freshness=str(record.get("freshness", "current")),
            confidence=float(record.get("confidence", 0.8)),
            source_ref=str(record["source_ref"]),
        )
    return result


def _method_reference_codes(code: str, index_codes: list[str], cross_codes: list[str]) -> list[str]:
    selected = []
    for candidate in [*index_codes, *cross_codes]:
        if candidate != code and candidate not in selected:
            selected.append(candidate)
    return selected[:4]


def _reference_history(fetcher, codes: list[str]) -> dict[str, list[KLineBar]]:
    result = {}
    for code in codes:
        try:
            bars = fetcher.get_daily_bars(code, num=80)
        except (AttributeError, OSError, RuntimeError, ValueError):
            continue
        if bars:
            result[code] = bars
    return result
```

Wrap OpenD `last_price`, `volume`, `turnover`, PE, PB, EPS growth, revenue growth, margins, and ROE in `EvidenceValue` records. Resolve matching manual evidence with `resolve_evidence`. OpenD values win. Manual values may fill missing company/valuation metrics, but the live-only keys `{last_price, volume, turnover, capital_flow}` may never be filled manually. Collect every conflict string and pass it to the method assessment.

Add these tests:

```python
def test_manual_method_evidence_requires_official_source_and_reference(self):
    valid = _manual_evidence({"evidence": {"revenue_growth": {
        "value": 20.0, "source": "official-manual", "as_of": "2026-06-30",
        "source_ref": "exchange:report", "confidence": 0.9,
    }}})
    self.assertEqual(valid["revenue_growth"].value, 20.0)
    with self.assertRaises(ValueError):
        _manual_evidence({"evidence": {"revenue_growth": {
            "value": 20.0, "source": "yahoo", "as_of": "2026-06-30", "source_ref": "x",
        }}})
    with self.assertRaises(ValueError):
        _manual_evidence({"evidence": {"revenue_growth": {
            "value": 20.0, "source": "official-manual", "as_of": "2026-06-30",
        }}})

def test_conflicting_manual_live_price_is_reported_but_never_replaces_opend(self):
    manual = json.dumps({"evidence": {"last_price": {
        "value": 0.01, "source": "official-manual", "as_of": "2026-07-21",
        "source_ref": "exchange:notice", "confidence": 0.9,
    }}})
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "recommendation.json"
        with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
            exit_code = main([
                "analyze", "--code", "SZ.002463", "--horizon", "swing",
                "--method-inputs-json", manual, "--no-sector", "--no-market", "--no-macro",
                "--no-fundamental", "--event-days", "10", "--no-journal", "--output", str(output),
            ])
        payload = json.loads(output.read_text(encoding="utf-8"))
    self.assertEqual(exit_code, 0)
    self.assertNotEqual(payload["entry_price"], 0.01)
    self.assertIn("last_price:opend!=official-manual", payload["method_assessment"]["source_conflicts"])
    self.assertIn("source-conflict", [item["code"] for item in payload["method_assessment"]["restrictions"]])
```

Change `analyze --bars` default from `30` to `None`; call `_bars_for_horizon` before `build_state`. Add optional `--method-inputs-json`. It accepts explicit assumptions only and must not trigger any network request.

In `scan_watchlist.py`, change `--bars` default to `None` and extract the base command:

```python
def _analysis_command(entry, horizon, output, shared_context, watchlist, bars):
    command = [
        sys.executable,
        "-m",
        "tools.stock_skills.cli",
        "analyze",
        "--code",
        entry["code"],
        "--horizon",
        horizon,
        "--profile",
        entry["valuation_profile"],
        "--watchlist",
        str(watchlist),
        "--shared-context",
        str(shared_context),
        "--no-journal",
        "--output",
        str(output),
    ]
    effective_bars = bars if bars is not None else (60 if horizon == "short" else None)
    if effective_bars is not None:
        command.extend(["--bars", str(effective_bars)])
    return command
```

Use this helper inside the nested deep analyzer, then append event, portfolio heat, theme heat, and underlying-confirmation flags exactly as today. This lets the child `analyze` command select 260 bars for swing, preserves the scanner's current 60-bar short depth, and retains the current 30-bar direct short default unless the user explicitly overrides bars.

- [ ] **Step 4: Orchestrate method analysis and apply policy**

Extend `_recommend` with optional keyword-only inputs:

```python
reference_bars: dict[str, list[KLineBar]] | None = None,
asset_type: str = "equity",
method_inputs: dict[str, object] | None = None,
```

Use one failure boundary per method so a defect cannot abort the unrelated recommendation:

```python
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def _safe_method(name: str, calculate: Callable[[], T], fallback: T, errors: dict[str, str]) -> T:
    try:
        return calculate()
    except Exception as exc:  # module isolation boundary; exact error is journaled
        errors[name] = f"{type(exc).__name__}: {exc}"
        return fallback
```

Construct explicit zero-coverage fallbacks with `stage/state/status/stance="unknown"` (valuation uses `status="unavailable"`) and a note naming the failed module. Pass the resulting `errors` mapping to `build_method_assessment`. Add this test:

```python
def test_one_method_failure_is_journaled_without_aborting_recommendation(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "recommendation.json"
        with mock.patch("tools.stock_skills.cli.analyze_linkage", side_effect=RuntimeError("fixture")):
            exit_code = main([
                "dry-run", "--code", FIXTURE_CODE, "--horizon", "swing",
                "--event-days", "10", "--output", str(output),
            ])
        payload = json.loads(output.read_text(encoding="utf-8"))
    self.assertEqual(exit_code, 0)
    self.assertIn("RuntimeError: fixture", payload["method_assessment"]["errors"]["linkage"])
    self.assertEqual(payload["method_assessment"]["linkage"]["coverage"], 0.0)
```

After existing fundamental, sector, and market analyses are available:

1. Resolve `MarketProfile` from code and asset type.
2. Analyze valuation from `method_inputs.get("valuation")`; absent assumptions return unavailable.
3. Build the pre-technical thesis from fundamentals, sector, market, valuation, and `method_inputs.get("thesis")`.
4. Analyze swing structure from completed daily bars.
5. Analyze linkage from completed target/reference bars.
6. Add `technical_confirmation` to the thesis with `dataclasses.replace`: `confirming` for Stage 2 plus confirming linkage, `contradicting` for Stage 3/4 or stable divergence, otherwise `unknown`. Do not alter primary drivers or thesis state except an already evaluated manual invalidation.
7. Build `MethodAssessment`, passing `valuation_critical=True` only when the validated thesis input explicitly declares it. A method disagreement of at least 30% then restricts new swing risk; without that declaration it is an uncertainty note only.
8. Run the existing `evaluate_strategy` exactly as before.
9. Run `apply_method_restrictions` on that result.
10. Attach both final strategy and method assessments to the recommendation.

Update text output with a compact explanation:

```python
method_text = (
    f" Method evidence ({methods.method_policy}): profile={methods.market_profile_id}, "
    f"stage={methods.swing_structure.stage}, thesis={methods.thesis.state}, "
    f"valuation={methods.valuation.status}, linkage_coverage={methods.linkage.coverage}, "
    f"restrictions={','.join(item.code for item in methods.restrictions) or 'none'}."
)
```

Replace the generic `analyst_hypothesis` with a formatter based on the structured thesis: observed upside, strongest rival, Base path, and invalidations/unresolved evidence. Keep `trader_plan` technical and append `method_text` plus the authoritative final strategy decision.

Atomically update in `models.py`:

```python
SCHEMA_VERSION = "recommendation-v6"
DECISION_POLICY = "logic-first-method-evidence-v6"
```

The changed policy is required because method restrictions now affect entry/add decisions. Historical readers remain permissive.

- [ ] **Step 5: Fetch only OpenD reference histories in live analysis**

In `_cmd_analyze`, derive asset type from watchlist tags (`etf` if tagged ETF/leveraged, otherwise `equity`), build at most four reference codes from selected indices and cross-market codes, and call `_reference_history`. Pass its result and the validated method JSON to `_recommend`.

Offline and dry-run paths pass `{}` reference histories. Their method outputs may be unknown, but they must remain usable and deterministic.

No import, dependency, subprocess command, or fallback may mention `yfinance`, Yahoo, or a trading script.

- [ ] **Step 6: Run integration and affected regression tests**

```bash
python3 -m unittest tests.test_cli tests.test_models tests.test_strategy tests.test_watchlist_cli tests.test_futu_fetcher -v
```

Expected: PASS. Existing component totals and unrestricted strategy decisions remain unchanged; Stage 3/4, thesis invalidation, conflicts, and Stage-1 probe-only evidence can only downgrade.

- [ ] **Step 7: Commit integration**

```bash
git add tools/stock_skills/cli.py tools/stock_skills/models.py tools/stock_skills/scan_watchlist.py tests/test_cli.py tests/test_models.py tests/test_strategy.py tests/test_watchlist_cli.py
git commit -m "feat: integrate OpenD method evidence into recommendations"
```

### Task 8: Journal method outcomes and update the stock-analysis skill

**Files:**

- Modify: `tools/stock_skills/cli.py`
- Modify: `tools/stock_skills/review.py`
- Modify: `tests/test_review.py`
- Modify: `skills/stock-analysis/SKILL.md`

- [ ] **Step 1: Write failing outcome-retention tests**

Add to `tests/test_review.py`:

```python
def test_review_retains_shadow_method_state_for_calibration(self):
    recommendation = {
        "code": "HK.00700",
        "timestamp": "2026-07-21T16:00:00+08:00",
        "label": "hold",
        "method_assessment": {
            "method_policy": "finance-method-evidence-v1",
            "market_profile_id": "hk-equity-v1",
            "swing_structure": {"stage": "stage-2"},
            "thesis": {"state": "supported"},
            "valuation": {"status": "unavailable"},
            "linkage": {"coverage": 0.5},
            "restrictions": [],
        },
    }
    bars = [KLineBar("2026-07-22", 500.0, 510.0, 495.0, 508.0, 1_000, 500_000.0)]
    outcome = evaluate_recommendation(recommendation, 500.0, bars, "1d")
    self.assertEqual(outcome["method_policy"], "finance-method-evidence-v1")
    self.assertEqual(outcome["method_stage"], "stage-2")
    self.assertEqual(outcome["method_restrictions"], [])
```

Add to `tests/test_cli.py`:

```python
def test_review_accepts_twenty_day_shadow_window(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        recommendations = Path(tmpdir) / "recommendations.jsonl"
        reviews = Path(tmpdir) / "reviews.jsonl"
        recommendations.write_text("", encoding="utf-8")
        exit_code = main([
            "review", "--window", "20d",
            "--recommendations", str(recommendations),
            "--reviews", str(reviews),
        ])
    self.assertEqual(exit_code, 0)
```

- [ ] **Step 2: Run tests and verify failure**

```bash
python3 -m unittest tests.test_review tests.test_cli -v
```

Expected: FAIL because method fields and the 20-day review window are absent.

- [ ] **Step 3: Retain method fields without changing weight optimization**

In `review.evaluate_recommendation`, safely extract nested dictionaries and add:

```python
"method_policy": methods.get("method_policy"),
"method_profile": methods.get("market_profile_id"),
"method_stage": structure.get("stage"),
"thesis_state": thesis.get("state"),
"valuation_status": valuation.get("status"),
"linkage_coverage": linkage.get("coverage"),
"method_restrictions": [item.get("code") for item in restrictions if isinstance(item, dict)],
```

Do not add these fields to legacy component weights or strategy cluster weights. They are shadow outcome dimensions only.

Add `"20d": 20` to `REVIEW_WINDOW_DAYS`; parser choices should derive from that map.

- [ ] **Step 4: Update `skills/stock-analysis/SKILL.md`**

Document:

- `method_models.py`, `market_profiles.py`, `swing_structure.py`, `linkage.py`, `valuation_scenarios.py`, `thesis.py`, and `method_policy.py`;
- OpenD as the only live/historical market-data source;
- `--method-inputs-json` for optional explicit official/manual assumptions;
- current 30-bar direct-short and 60-bar scanner-short defaults / new 260-bar swing default, with explicit override behavior;
- Stage 3/4 and evaluated thesis invalidation as new-swing-risk restrictions, not automatic sells;
- late Stage 1 as probe-only when existing swing probe gates pass;
- positive method evidence receiving zero Phase-1 score weight;
- schema `recommendation-v6` and decision policy `logic-first-method-evidence-v6`.

Correct any stale policy identifier already present in the skill. Preserve the no-trade rule.

- [ ] **Step 5: Run review, CLI, and documentation-adjacent tests**

```bash
python3 -m unittest tests.test_review tests.test_cli tests.test_models tests.test_watchlist_docs -v
```

Expected: PASS.

- [ ] **Step 6: Commit review and documentation changes**

```bash
git add tools/stock_skills/cli.py tools/stock_skills/review.py tests/test_review.py tests/test_cli.py skills/stock-analysis/SKILL.md
git commit -m "docs: expose method evidence and calibration fields"
```

### Task 9: Run complete regression and inspect serialization

**Files:**

- Verify only; modify the smallest responsible file if a failure exposes a real defect, then rerun the focused test before the full suite.

- [ ] **Step 1: Run the full unit suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: PASS with zero failures and zero errors.

- [ ] **Step 2: Run the offline fixture and inspect invariants**

```bash
python3 -m tools.stock_skills.cli dry-run --code SZ.002463 --horizon swing --event-days 10 --output /tmp/method-evidence-dry-run.json
python3 -c "import json; p=json.load(open('/tmp/method-evidence-dry-run.json')); assert p['schema_version']=='recommendation-v6'; assert p['strategy_assessment']['decision_policy']=='logic-first-method-evidence-v6'; assert 'method_assessment' in p; assert p['entry_decision']==p['strategy_assessment']['entry_decision']; print(p['method_assessment']['market_profile_id'], p['method_assessment']['swing_structure']['stage'], p['entry_decision'])"
```

Expected: command exits 0; the short fixture history may make stage `unknown`, but serialization, policy, and authoritative decision mirroring are correct.

- [ ] **Step 3: Prove no forbidden dependency was introduced**

```bash
! rg -n "import yfinance|from yfinance|query[0-9]?\.finance\.yahoo|trade/order|place_order" tools/stock_skills skills/stock-analysis
git diff a0e3a92..HEAD -- requirements.txt pyproject.toml setup.py setup.cfg 2>/dev/null
```

Expected: the search returns no match and dependency manifests show no new package compared with the approved design commit `a0e3a92`.

- [ ] **Step 4: Inspect final repository state and commit any verification-only correction**

```bash
git status --short --branch
git log --oneline -8
git diff --check
```

Expected: clean worktree, the planned focused commits are visible, and `git diff --check` reports no whitespace errors. If verification required a correction, commit only that correction with a specific message after its focused and full tests pass.

## Execution Notes

- Follow strict red-green-refactor for every behavior change.
- Do not run live OpenD integration tests as a substitute for deterministic unit tests; a final optional live smoke test may be run only when OpenD is available.
- Preserve unrelated user changes and do not rewrite watchlist records.
- Keep the recommendation's legacy `total_score` byte-for-byte stable for identical existing inputs.
- Treat `strategy_assessment` after method restrictions as the single authoritative action; `label` remains legacy compatibility only.
- A method exception must serialize as an unknown method result plus `errors[module]`; it must not abort unrelated analysis.
- Never use method evidence to force an existing-position sell. Existing structured exits and position state remain authoritative.
