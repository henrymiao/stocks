# Self-Evolving Stock Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a testable first version of the self-evolving stock analysis skill suite for the user's technology, semiconductor, AI hardware, and crypto-focused watchlist.

**Architecture:** Implement a small Python package under `tools/stock_skills/` with pure scoring modules first, then add journal/review and Futu data collection adapters. Keep all live-data calls behind one collector module so trend, capital-flow, macro, and position logic can be tested with fixtures.

**Tech Stack:** Python 3 standard library, existing Futu OpenAPI scripts from `/Users/shuren/.agents/skills/futuapi/scripts`, JSON/JSONL files for watchlists, recommendation logs, reviews, and signal weights, `python -m unittest` for tests.

---

## Scope

This plan implements the Version 1 MVP from the approved spec:

- Active watchlist analysis.
- Analyst-style investment hypothesis.
- Trader-style price plan and invalidation levels.
- Trend, capital flow, sector, cross-market, macro, and position-fit scores.
- Recommendation labels.
- JSONL recommendation journal.
- Review evaluator for 1/3/5/10 trading-day outcomes.
- Futu data adapter with unit tests that do not require OpenD.

The first implementation does not install Codex skills under `$CODEX_HOME/skills`. It creates the working package and documented command paths first; skill installation can happen after this package behaves reliably.

## File Structure

Create these files:

- `tools/stock_skills/__init__.py`  
  Package marker and version.
- `tools/stock_skills/models.py`  
  Dataclasses used by every module.
- `tools/stock_skills/config.py`  
  Watchlist and weight loading with validation.
- `tools/stock_skills/trend.py`  
  Price/volume analysis.
- `tools/stock_skills/capital.py`  
  Capital-flow and order-size interpretation.
- `tools/stock_skills/macro.py`  
  Macro and cross-market risk overlays.
- `tools/stock_skills/engine.py`  
  Score composition, recommendation labels, analyst/trader output.
- `tools/stock_skills/journal.py`  
  Recommendation and review JSONL persistence.
- `tools/stock_skills/review.py`  
  Outcome evaluation and signal-weight adjustment suggestions.
- `tools/stock_skills/futu_fetcher.py`  
  Subprocess wrapper around existing `futuapi` scripts.
- `tools/stock_skills/cli.py`  
  Command-line entry points for dry-run analysis and review.
- `data/watchlists/core.json`  
  User's editable seed watchlist.
- `data/models/signal_weights.json`  
  Initial component weights.
- `tests/test_models.py`
- `tests/test_config.py`
- `tests/test_trend.py`
- `tests/test_capital.py`
- `tests/test_macro.py`
- `tests/test_engine.py`
- `tests/test_journal.py`
- `tests/test_review.py`
- `tests/test_futu_fetcher.py`
- `tests/test_cli.py`

Modify these files:

- `.gitignore`  
  Ignore generated live snapshots and journal outputs while keeping seed configs tracked.

---

### Task 1: Package Skeleton and Core Models

**Files:**
- Create: `tools/stock_skills/__init__.py`
- Create: `tools/stock_skills/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing model tests**

Create `tests/test_models.py`:

```python
import unittest

from tools.stock_skills.models import (
    CapitalSnapshot,
    ComponentScores,
    InstrumentState,
    KLineBar,
    MarketSnapshot,
    Recommendation,
)


class ModelTests(unittest.TestCase):
    def test_recommendation_serializes_to_json_ready_dict(self):
        recommendation = Recommendation(
            code="SZ.002463",
            name="沪电股份",
            timestamp="2026-06-18T15:00:00+08:00",
            label="hold",
            total_score=67.4,
            component_scores=ComponentScores(
                trend=70,
                capital_flow=58,
                sector=65,
                cross_market=60,
                macro_risk=55,
                position_fit=75,
            ),
            analyst_hypothesis="AI PCB demand remains the core thesis.",
            trader_plan="Hold above 145; trim failed pushes near 150.",
            support_levels=[145.0, 142.8],
            resistance_levels=[149.9, 150.0],
            invalidation_level=142.8,
            confidence=0.62,
            source_refs=["data/snapshots/SZ.002463.json"],
            user_context={"last_trim_price": 149.5},
        )

        payload = recommendation.to_record()

        self.assertEqual(payload["code"], "SZ.002463")
        self.assertEqual(payload["component_scores"]["trend"], 70)
        self.assertEqual(payload["support_levels"], [145.0, 142.8])
        self.assertEqual(payload["user_context"]["last_trim_price"], 149.5)

    def test_instrument_state_accepts_snapshot_bars_and_capital(self):
        state = InstrumentState(
            snapshot=MarketSnapshot(
                code="SZ.002463",
                name="沪电股份",
                last_price=147.9,
                open=146.0,
                high=149.36,
                low=142.81,
                prev_close=146.55,
                volume=83679015,
                turnover=12271729868.41,
                timestamp="2026-06-18T15:00:00+08:00",
            ),
            daily_bars=[
                KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99154170, 14460550533.78),
                KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83679015, 12271729868.41),
            ],
            intraday_bars=[],
            capital=CapitalSnapshot(
                net_inflow=24492584.5,
                super_inflow=744236606.14,
                big_inflow=-411741404.48,
                mid_inflow=-210842830.36,
                small_inflow=-97159786.8,
                timestamp="2026-06-18T15:00:00+08:00",
            ),
        )

        self.assertEqual(state.snapshot.code, "SZ.002463")
        self.assertEqual(len(state.daily_bars), 2)
        self.assertGreater(state.capital.super_inflow, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
python -m unittest tests.test_models -v
```

Expected: fail with `ModuleNotFoundError: No module named 'tools.stock_skills'`.

- [ ] **Step 3: Create package marker**

Create `tools/stock_skills/__init__.py`:

```python
"""Self-evolving stock analysis helpers."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Implement the dataclasses**

Create `tools/stock_skills/models.py`:

```python
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
```

- [ ] **Step 5: Run the model tests**

Run:

```bash
python -m unittest tests.test_models -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/stock_skills/__init__.py tools/stock_skills/models.py tests/test_models.py
git commit -m "feat: add stock skill core models"
```

---

### Task 2: Watchlist and Weight Configuration

**Files:**
- Create: `data/watchlists/core.json`
- Create: `data/models/signal_weights.json`
- Create: `tools/stock_skills/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_config.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.config import load_watchlist, load_weights


class ConfigTests(unittest.TestCase):
    def test_load_watchlist_returns_enabled_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "core.json"
            path.write_text(
                json.dumps(
                    {
                        "watchlist": [
                            {"code": "SZ.002463", "name": "沪电股份", "enabled": True, "tags": ["pcb"]},
                            {"code": "US.SOXS", "name": "Direxion Daily Semiconductor Bear 3X", "enabled": False, "tags": ["hedge"]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            entries = load_watchlist(path)

        self.assertEqual([entry["code"] for entry in entries], ["SZ.002463"])
        self.assertEqual(entries[0]["tags"], ["pcb"])

    def test_load_weights_requires_all_components_and_sum_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weights.json"
            path.write_text(
                json.dumps(
                    {
                        "trend": 0.25,
                        "capital_flow": 0.20,
                        "sector": 0.15,
                        "cross_market": 0.15,
                        "macro_risk": 0.15,
                        "position_fit": 0.10,
                    }
                ),
                encoding="utf-8",
            )

            weights = load_weights(path)

        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertEqual(weights["trend"], 0.25)

    def test_load_weights_rejects_missing_component(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weights.json"
            path.write_text(json.dumps({"trend": 1.0}), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_weights(path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
python -m unittest tests.test_config -v
```

Expected: fail with `ModuleNotFoundError` or missing `tools.stock_skills.config`.

- [ ] **Step 3: Add the seed watchlist**

Create `data/watchlists/core.json`:

```json
{
  "watchlist": [
    {"code": "SZ.002463", "name": "沪电股份", "enabled": true, "tags": ["a-share", "pcb", "ai-hardware"]},
    {"code": "SZ.002938", "name": "鹏鼎控股", "enabled": true, "tags": ["a-share", "pcb", "consumer-electronics"]},
    {"code": "SH.600584", "name": "长电科技", "enabled": true, "tags": ["a-share", "semiconductor", "packaging"]},
    {"code": "US.MRVL", "name": "Marvell", "enabled": true, "tags": ["us", "ai-infrastructure", "semiconductor"]},
    {"code": "US.GOOGL", "name": "Alphabet", "enabled": true, "tags": ["us", "mega-cap", "ai"]},
    {"code": "US.CRCL", "name": "Circle", "enabled": true, "tags": ["us", "crypto-equity", "stablecoin"]},
    {"code": "US.SOXL", "name": "Direxion Daily Semiconductor Bull 3X", "enabled": true, "tags": ["us", "semiconductor", "leveraged"]},
    {"code": "US.SOXS", "name": "Direxion Daily Semiconductor Bear 3X", "enabled": true, "tags": ["us", "semiconductor", "hedge"]},
    {"code": "US.NVDA", "name": "NVIDIA", "enabled": true, "tags": ["us", "ai-hardware", "semiconductor"]},
    {"code": "US.QQQ", "name": "Invesco QQQ Trust", "enabled": true, "tags": ["us", "growth-proxy", "macro"]},
    {"code": "US.SPY", "name": "SPDR S&P 500 ETF", "enabled": true, "tags": ["us", "market-proxy", "macro"]},
    {"code": "CC.BTC", "name": "Bitcoin", "enabled": true, "tags": ["crypto", "risk-appetite"]},
    {"code": "CC.ETH", "name": "Ethereum", "enabled": true, "tags": ["crypto", "risk-appetite"]}
  ]
}
```

- [ ] **Step 4: Add initial signal weights**

Create `data/models/signal_weights.json`:

```json
{
  "trend": 0.25,
  "capital_flow": 0.2,
  "sector": 0.15,
  "cross_market": 0.15,
  "macro_risk": 0.15,
  "position_fit": 0.1
}
```

- [ ] **Step 5: Implement config loading**

Create `tools/stock_skills/config.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_WEIGHT_KEYS = {
    "trend",
    "capital_flow",
    "sector",
    "cross_market",
    "macro_risk",
    "position_fit",
}


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def load_watchlist(path: str | Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    entries = payload.get("watchlist")
    if not isinstance(entries, list):
        raise ValueError("watchlist must be a list")

    enabled_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("watchlist entries must be objects")
        if entry.get("enabled", True):
            code = entry.get("code")
            name = entry.get("name")
            tags = entry.get("tags", [])
            if not isinstance(code, str) or "." not in code:
                raise ValueError(f"Invalid watchlist code: {code!r}")
            if not isinstance(name, str) or not name:
                raise ValueError(f"Invalid watchlist name for {code}")
            if not isinstance(tags, list):
                raise ValueError(f"Invalid tags for {code}")
            enabled_entries.append(entry)
    return enabled_entries


def load_weights(path: str | Path) -> dict[str, float]:
    payload = load_json(path)
    keys = set(payload)
    if keys != REQUIRED_WEIGHT_KEYS:
        missing = sorted(REQUIRED_WEIGHT_KEYS - keys)
        extra = sorted(keys - REQUIRED_WEIGHT_KEYS)
        raise ValueError(f"Invalid weight keys. Missing={missing}, extra={extra}")

    weights = {key: float(value) for key, value in payload.items()}
    total = sum(weights.values())
    if abs(total - 1.0) > 0.000001:
        raise ValueError(f"Signal weights must sum to 1.0, got {total}")
    if any(value < 0 for value in weights.values()):
        raise ValueError("Signal weights must be non-negative")
    return weights
```

- [ ] **Step 6: Run config tests**

Run:

```bash
python -m unittest tests.test_config -v
```

Expected: 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add data/watchlists/core.json data/models/signal_weights.json tools/stock_skills/config.py tests/test_config.py
git commit -m "feat: add stock watchlist and signal weights"
```

---

### Task 3: Technical Trend Analyzer

**Files:**
- Create: `tools/stock_skills/trend.py`
- Create: `tests/test_trend.py`

- [ ] **Step 1: Write failing trend tests**

Create `tests/test_trend.py`:

```python
import unittest

from tools.stock_skills.models import KLineBar, MarketSnapshot
from tools.stock_skills.trend import analyze_trend


class TrendTests(unittest.TestCase):
    def test_clean_breakout_scores_high(self):
        bars = [
            KLineBar("2026-06-15", 128.5, 134.0, 122.22, 133.76, 99_418_986, 12_861_198_025.68),
            KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 152.0, 145.4, 151.4, 135_000_000, 20_000_000_000.0),
        ]
        snapshot = MarketSnapshot("SZ.002463", "沪电股份", 151.4, 146.0, 152.0, 145.4, 146.55, 135_000_000, 20_000_000_000.0, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertGreaterEqual(result.score, 80)
        self.assertEqual(result.status, "breakout-confirmed")
        self.assertIn(149.9, result.resistance_levels)

    def test_failed_breakout_near_resistance_scores_mid(self):
        bars = [
            KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83_679_015, 12_271_729_868.41),
        ]
        snapshot = MarketSnapshot("SZ.002463", "沪电股份", 147.9, 146.0, 149.36, 142.81, 146.55, 83_679_015, 12_271_729_868.41, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertGreaterEqual(result.score, 55)
        self.assertLess(result.score, 75)
        self.assertEqual(result.status, "high-level-consolidation")
        self.assertEqual(result.invalidation_level, 142.81)

    def test_breakdown_scores_low(self):
        bars = [
            KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 148.0, 141.0, 141.5, 120_000_000, 17_000_000_000.0),
        ]
        snapshot = MarketSnapshot("SZ.002463", "沪电股份", 141.5, 146.0, 148.0, 141.0, 146.55, 120_000_000, 17_000_000_000.0, "2026-06-18T15:00:00+08:00")

        result = analyze_trend(snapshot, bars)

        self.assertLessEqual(result.score, 45)
        self.assertEqual(result.status, "breakdown-risk")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run trend tests and verify they fail**

Run:

```bash
python -m unittest tests.test_trend -v
```

Expected: fail because `tools.stock_skills.trend` does not exist.

- [ ] **Step 3: Implement trend analyzer**

Create `tools/stock_skills/trend.py`:

```python
from __future__ import annotations

from statistics import mean

from .models import KLineBar, MarketSnapshot, TrendAnalysis


def _round_level(value: float) -> float:
    return round(float(value), 2)


def analyze_trend(snapshot: MarketSnapshot, bars: list[KLineBar]) -> TrendAnalysis:
    if len(bars) < 2:
        return TrendAnalysis(
            score=50,
            status="insufficient-data",
            support_levels=[],
            resistance_levels=[],
            invalidation_level=None,
            notes=["Need at least two bars for trend analysis."],
        )

    recent = bars[-1]
    prior = bars[-2]
    lookback = bars[-6:-1] if len(bars) >= 6 else bars[:-1]
    prior_high = max(bar.high for bar in lookback)
    prior_low = min(bar.low for bar in lookback)
    avg_volume = mean(bar.volume for bar in lookback)
    volume_ratio = recent.volume / avg_volume if avg_volume else 1.0
    close_change = (snapshot.last_price - snapshot.prev_close) / snapshot.prev_close if snapshot.prev_close else 0.0

    score = 50.0
    notes: list[str] = []
    status = "neutral"

    if snapshot.last_price > prior_high and volume_ratio >= 1.15:
        score += 32
        status = "breakout-confirmed"
        notes.append("Price closed above recent resistance with volume expansion.")
    elif recent.high >= prior_high and snapshot.last_price <= prior_high:
        score += 12
        status = "high-level-consolidation"
        notes.append("Price tested resistance but did not close above it.")
    elif snapshot.last_price < prior.low or snapshot.last_price < prior_low:
        score -= 18
        status = "breakdown-risk"
        notes.append("Price closed below recent support area.")
    elif snapshot.last_price > prior.close:
        score += 10
        status = "constructive"
        notes.append("Close improved versus the previous bar.")

    if close_change > 0.03:
        score += 8
        notes.append("Daily gain shows strong demand.")
    elif close_change < -0.03:
        score -= 8
        notes.append("Daily loss shows distribution pressure.")

    if volume_ratio >= 1.3:
        score += 6
        notes.append("Volume is meaningfully above recent average.")
    elif volume_ratio < 0.75 and snapshot.last_price > prior.close:
        score -= 5
        notes.append("Price rise lacks volume confirmation.")

    support_levels = sorted({_round_level(prior.low), _round_level(prior_low), _round_level(recent.low)}, reverse=True)
    resistance_levels = sorted({_round_level(prior.high), _round_level(prior_high), _round_level(recent.high)})
    invalidation_level = _round_level(min(prior.low, recent.low))
    score = max(0.0, min(100.0, round(score, 2)))

    return TrendAnalysis(
        score=score,
        status=status,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        invalidation_level=invalidation_level,
        notes=notes,
    )
```

- [ ] **Step 4: Run trend tests**

Run:

```bash
python -m unittest tests.test_trend -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/trend.py tests/test_trend.py
git commit -m "feat: add technical trend analyzer"
```

---

### Task 4: Capital Flow Interpreter

**Files:**
- Create: `tools/stock_skills/capital.py`
- Create: `tests/test_capital.py`

- [ ] **Step 1: Write failing capital-flow tests**

Create `tests/test_capital.py`:

```python
import unittest

from tools.stock_skills.capital import analyze_capital
from tools.stock_skills.models import CapitalSnapshot


class CapitalTests(unittest.TestCase):
    def test_broad_inflow_confirms_trend(self):
        capital = CapitalSnapshot(900_000_000, 400_000_000, 250_000_000, 150_000_000, 100_000_000, "2026-06-18T15:00:00+08:00")

        result = analyze_capital(capital)

        self.assertGreaterEqual(result.score, 80)
        self.assertEqual(result.stance, "confirms")

    def test_super_inflow_but_large_mid_outflow_is_divergent(self):
        capital = CapitalSnapshot(24_492_584.5, 744_236_606.14, -411_741_404.48, -210_842_830.36, -97_159_786.8, "2026-06-18T15:00:00+08:00")

        result = analyze_capital(capital)

        self.assertGreaterEqual(result.score, 50)
        self.assertLess(result.score, 70)
        self.assertEqual(result.stance, "stabilizes")
        self.assertTrue(any("super-large" in note for note in result.notes))

    def test_broad_outflow_contradicts_trend(self):
        capital = CapitalSnapshot(-600_000_000, -100_000_000, -200_000_000, -200_000_000, -100_000_000, "2026-06-18T15:00:00+08:00")

        result = analyze_capital(capital)

        self.assertLessEqual(result.score, 35)
        self.assertEqual(result.stance, "contradicts")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run capital-flow tests and verify they fail**

Run:

```bash
python -m unittest tests.test_capital -v
```

Expected: fail because `tools.stock_skills.capital` does not exist.

- [ ] **Step 3: Implement capital-flow interpreter**

Create `tools/stock_skills/capital.py`:

```python
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
```

- [ ] **Step 4: Run capital-flow tests**

Run:

```bash
python -m unittest tests.test_capital -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/capital.py tests/test_capital.py
git commit -m "feat: add capital flow interpreter"
```

---

### Task 5: Macro and Cross-Market Overlays

**Files:**
- Create: `tools/stock_skills/macro.py`
- Create: `tests/test_macro.py`

- [ ] **Step 1: Write failing macro tests**

Create `tests/test_macro.py`:

```python
import unittest

from tools.stock_skills.macro import analyze_cross_market, analyze_macro_risk
from tools.stock_skills.models import MarketSnapshot


def snapshot(code, last, prev):
    return MarketSnapshot(code, code, last, last, last, last, prev, 1, 1.0, "2026-06-18T15:00:00+08:00")


class MacroTests(unittest.TestCase):
    def test_rate_hike_bias_creates_risk_off_macro(self):
        result = analyze_macro_risk(
            {
                "fed_bias": "hike",
                "geopolitical_risk": "elevated",
                "oil_shock": True,
                "dollar_pressure": "high",
            }
        )

        self.assertLessEqual(result.score, 35)
        self.assertEqual(result.regime, "risk-off")

    def test_neutral_macro_when_inputs_are_missing(self):
        result = analyze_macro_risk({})

        self.assertEqual(result.score, 50)
        self.assertEqual(result.regime, "neutral")

    def test_cross_market_penalizes_weak_us_ai_tape(self):
        result = analyze_cross_market(
            {
                "US.QQQ": snapshot("US.QQQ", 722.51, 729.86),
                "US.SPY": snapshot("US.SPY", 740.96, 750.33),
                "US.NVDA": snapshot("US.NVDA", 204.65, 207.41),
            }
        )

        self.assertLess(result.score, 50)
        self.assertEqual(result.regime, "risk-off")

    def test_cross_market_rewards_strong_ai_tape(self):
        result = analyze_cross_market(
            {
                "US.QQQ": snapshot("US.QQQ", 750.0, 729.86),
                "US.SPY": snapshot("US.SPY", 760.0, 750.33),
                "US.NVDA": snapshot("US.NVDA", 216.0, 207.41),
            }
        )

        self.assertGreater(result.score, 60)
        self.assertEqual(result.regime, "risk-on")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run macro tests and verify they fail**

Run:

```bash
python -m unittest tests.test_macro -v
```

Expected: fail because `tools.stock_skills.macro` does not exist.

- [ ] **Step 3: Implement macro overlays**

Create `tools/stock_skills/macro.py`:

```python
from __future__ import annotations

from .models import CrossMarketAnalysis, MacroAnalysis, MarketSnapshot


def analyze_macro_risk(inputs: dict[str, object]) -> MacroAnalysis:
    score = 50.0
    notes: list[str] = []

    fed_bias = inputs.get("fed_bias")
    if fed_bias == "hike":
        score -= 18
        notes.append("Fed bias points toward higher rates.")
    elif fed_bias == "cut":
        score += 12
        notes.append("Fed bias points toward easier liquidity.")

    if inputs.get("geopolitical_risk") == "elevated":
        score -= 8
        notes.append("Geopolitical risk is elevated.")
    if inputs.get("oil_shock") is True:
        score -= 8
        notes.append("Oil or energy shock may pressure inflation.")
    if inputs.get("dollar_pressure") == "high":
        score -= 6
        notes.append("Dollar or yield pressure is high.")

    score = round(max(0.0, min(100.0, score)), 2)
    if score >= 60:
        regime = "risk-on"
    elif score <= 40:
        regime = "risk-off"
    else:
        regime = "neutral"
    if not notes:
        notes.append("Macro inputs are neutral or missing.")

    return MacroAnalysis(score=score, regime=regime, notes=notes)


def _pct_change(snapshot: MarketSnapshot) -> float:
    if snapshot.prev_close == 0:
        return 0.0
    return (snapshot.last_price - snapshot.prev_close) / snapshot.prev_close


def analyze_cross_market(snapshots: dict[str, MarketSnapshot]) -> CrossMarketAnalysis:
    score = 50.0
    notes: list[str] = []
    weights = {
        "US.QQQ": 18,
        "US.SPY": 10,
        "US.NVDA": 18,
        "US.SOXL": 12,
        "CC.BTC": 8,
        "CC.ETH": 6,
    }

    for code, weight in weights.items():
        snapshot = snapshots.get(code)
        if snapshot is None:
            continue
        change = _pct_change(snapshot)
        if change >= 0.02:
            score += weight * 0.6
            notes.append(f"{code} is strongly positive.")
        elif change > 0:
            score += weight * 0.25
            notes.append(f"{code} is positive.")
        elif change <= -0.02:
            score -= weight * 0.7
            notes.append(f"{code} is sharply negative.")
        else:
            score -= weight * 0.3
            notes.append(f"{code} is negative.")

    score = round(max(0.0, min(100.0, score)), 2)
    if score >= 60:
        regime = "risk-on"
    elif score <= 45:
        regime = "risk-off"
    else:
        regime = "neutral"
    if not notes:
        notes.append("No cross-market snapshots were supplied.")

    return CrossMarketAnalysis(score=score, regime=regime, notes=notes)
```

- [ ] **Step 4: Run macro tests**

Run:

```bash
python -m unittest tests.test_macro -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/macro.py tests/test_macro.py
git commit -m "feat: add macro and cross market overlays"
```

---

### Task 6: Recommendation Engine with Analyst and Trader Frames

**Files:**
- Create: `tools/stock_skills/engine.py`
- Create: `tests/test_engine.py`

- [ ] **Step 1: Write failing engine tests**

Create `tests/test_engine.py`:

```python
import unittest

from tools.stock_skills.engine import build_recommendation, classify_total_score
from tools.stock_skills.models import (
    CapitalAnalysis,
    ComponentScores,
    CrossMarketAnalysis,
    InstrumentState,
    KLineBar,
    MacroAnalysis,
    MarketSnapshot,
    TrendAnalysis,
)


class EngineTests(unittest.TestCase):
    def test_classify_total_score_respects_extended_resistance(self):
        self.assertEqual(classify_total_score(84, price_location="near_resistance"), "trim-on-strength")
        self.assertEqual(classify_total_score(84, price_location="healthy_pullback"), "strong-watch")
        self.assertEqual(classify_total_score(38, price_location="anywhere"), "risk-reduce")

    def test_build_recommendation_combines_frames(self):
        state = InstrumentState(
            snapshot=MarketSnapshot("SZ.002463", "沪电股份", 147.9, 146.0, 149.36, 142.81, 146.55, 83_679_015, 12_271_729_868.41, "2026-06-18T15:00:00+08:00"),
            daily_bars=[
                KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
                KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83_679_015, 12_271_729_868.41),
            ],
            intraday_bars=[],
            user_context={"last_trim_price": 149.5},
        )
        trend = TrendAnalysis(66, "high-level-consolidation", [145.0, 142.81], [149.9, 150.0], 142.81, ["Price is consolidating high."])
        capital = CapitalAnalysis(58, "stabilizes", ["super-large inflow is offset."])
        macro = MacroAnalysis(35, "risk-off", ["Fed bias points toward higher rates."])
        cross = CrossMarketAnalysis(42, "risk-off", ["US.QQQ is sharply negative."])
        weights = {
            "trend": 0.25,
            "capital_flow": 0.20,
            "sector": 0.15,
            "cross_market": 0.15,
            "macro_risk": 0.15,
            "position_fit": 0.10,
        }

        recommendation = build_recommendation(
            state=state,
            trend=trend,
            capital=capital,
            macro=macro,
            cross_market=cross,
            sector_score=60,
            position_fit_score=70,
            weights=weights,
            source_refs=["data/snapshots/SZ.002463.json"],
        )

        self.assertEqual(recommendation.code, "SZ.002463")
        self.assertIn(recommendation.label, {"hold", "trim-on-strength"})
        self.assertIn("investment hypothesis", recommendation.analyst_hypothesis)
        self.assertIn("invalidation", recommendation.trader_plan)
        self.assertEqual(recommendation.invalidation_level, 142.81)
        self.assertIsInstance(recommendation.component_scores, ComponentScores)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run engine tests and verify they fail**

Run:

```bash
python -m unittest tests.test_engine -v
```

Expected: fail because `tools.stock_skills.engine` does not exist.

- [ ] **Step 3: Implement recommendation engine**

Create `tools/stock_skills/engine.py`:

```python
from __future__ import annotations

from .models import (
    CapitalAnalysis,
    ComponentScores,
    CrossMarketAnalysis,
    InstrumentState,
    MacroAnalysis,
    Recommendation,
    TrendAnalysis,
)


def classify_total_score(total_score: float, price_location: str) -> str:
    if total_score >= 80:
        return "trim-on-strength" if price_location == "near_resistance" else "strong-watch"
    if total_score >= 70:
        return "low-buy-zone" if price_location == "healthy_pullback" else "hold"
    if total_score >= 60:
        return "hold"
    if total_score >= 45:
        return "trim-on-strength"
    if total_score >= 30:
        return "risk-reduce"
    return "avoid"


def detect_price_location(state: InstrumentState, trend: TrendAnalysis) -> str:
    price = state.snapshot.last_price
    if trend.resistance_levels:
        nearest_resistance = min(trend.resistance_levels, key=lambda level: abs(level - price))
        if nearest_resistance > 0 and abs(price - nearest_resistance) / nearest_resistance <= 0.015:
            return "near_resistance"
    if trend.support_levels:
        nearest_support = min(trend.support_levels, key=lambda level: abs(level - price))
        if nearest_support > 0 and abs(price - nearest_support) / nearest_support <= 0.02:
            return "healthy_pullback"
    return "middle"


def _weighted_total(scores: ComponentScores, weights: dict[str, float]) -> float:
    return round(
        scores.trend * weights["trend"]
        + scores.capital_flow * weights["capital_flow"]
        + scores.sector * weights["sector"]
        + scores.cross_market * weights["cross_market"]
        + scores.macro_risk * weights["macro_risk"]
        + scores.position_fit * weights["position_fit"],
        2,
    )


def build_recommendation(
    state: InstrumentState,
    trend: TrendAnalysis,
    capital: CapitalAnalysis,
    macro: MacroAnalysis,
    cross_market: CrossMarketAnalysis,
    sector_score: float,
    position_fit_score: float,
    weights: dict[str, float],
    source_refs: list[str],
) -> Recommendation:
    component_scores = ComponentScores(
        trend=trend.score,
        capital_flow=capital.score,
        sector=sector_score,
        cross_market=cross_market.score,
        macro_risk=macro.score,
        position_fit=position_fit_score,
    )
    total_score = _weighted_total(component_scores, weights)
    price_location = detect_price_location(state, trend)
    label = classify_total_score(total_score, price_location)
    confidence = round(max(0.1, min(0.95, total_score / 100)), 2)

    support_text = ", ".join(str(level) for level in trend.support_levels) or "unavailable"
    resistance_text = ", ".join(str(level) for level in trend.resistance_levels) or "unavailable"
    invalidation = trend.invalidation_level
    last_trim = state.user_context.get("last_trim_price")
    trim_text = f" Prior partial trim near {last_trim} should reduce chase pressure." if last_trim else ""

    analyst_hypothesis = (
        f"investment hypothesis: {state.snapshot.name} remains worth tracking if sector demand and earnings logic "
        f"continue to support the trade. Trend status is {trend.status}, capital stance is {capital.stance}, "
        f"macro regime is {macro.regime}, and cross-market regime is {cross_market.regime}."
    )
    trader_plan = (
        f"trader plan: current price {state.snapshot.last_price}. Support levels: {support_text}. "
        f"Resistance levels: {resistance_text}. Use invalidation near {invalidation}. "
        f"Action label is {label}; avoid chasing near resistance unless a new volume-confirmed breakout appears."
        f"{trim_text}"
    )

    return Recommendation(
        code=state.snapshot.code,
        name=state.snapshot.name,
        timestamp=state.snapshot.timestamp,
        label=label,
        total_score=total_score,
        component_scores=component_scores,
        analyst_hypothesis=analyst_hypothesis,
        trader_plan=trader_plan,
        support_levels=trend.support_levels,
        resistance_levels=trend.resistance_levels,
        invalidation_level=invalidation,
        confidence=confidence,
        source_refs=source_refs,
        user_context=state.user_context,
    )
```

- [ ] **Step 4: Run engine tests**

Run:

```bash
python -m unittest tests.test_engine -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/engine.py tests/test_engine.py
git commit -m "feat: add recommendation engine"
```

---

### Task 7: Recommendation Journal

**Files:**
- Create: `tools/stock_skills/journal.py`
- Create: `tests/test_journal.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing journal tests**

Create `tests/test_journal.py`:

```python
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.journal import append_record, read_records


class JournalTests(unittest.TestCase):
    def test_append_and_read_jsonl_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "recommendations.jsonl"

            append_record(path, {"code": "SZ.002463", "label": "hold"})
            append_record(path, {"code": "US.NVDA", "label": "strong-watch"})
            records = read_records(path)

        self.assertEqual([record["code"] for record in records], ["SZ.002463", "US.NVDA"])

    def test_read_missing_journal_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            records = read_records(Path(tmpdir) / "missing.jsonl")

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run journal tests and verify they fail**

Run:

```bash
python -m unittest tests.test_journal -v
```

Expected: fail because `tools.stock_skills.journal` does not exist.

- [ ] **Step 3: Implement journal helpers**

Create `tools/stock_skills/journal.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_record(path: str | Path, record: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def read_records(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL record on line {line_number} is not an object")
            records.append(payload)
    return records
```

- [ ] **Step 4: Update `.gitignore` for generated state**

Append these lines to `.gitignore` while preserving existing entries:

```gitignore
data/journal/*.jsonl
data/snapshots/*.json
```

- [ ] **Step 5: Run journal tests**

Run:

```bash
python -m unittest tests.test_journal -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add .gitignore tools/stock_skills/journal.py tests/test_journal.py
git commit -m "feat: add recommendation journal"
```

---

### Task 8: Review Evaluator and Weight Suggestions

**Files:**
- Create: `tools/stock_skills/review.py`
- Create: `tests/test_review.py`

- [ ] **Step 1: Write failing review tests**

Create `tests/test_review.py`:

```python
import unittest

from tools.stock_skills.models import KLineBar
from tools.stock_skills.review import evaluate_recommendation, suggest_weight_adjustments


class ReviewTests(unittest.TestCase):
    def test_evaluate_recommendation_records_successful_hold(self):
        recommendation = {
            "code": "SZ.002463",
            "label": "hold",
            "timestamp": "2026-06-18T15:00:00+08:00",
            "invalidation_level": 142.8,
            "support_levels": [145.0, 142.8],
            "resistance_levels": [149.9, 150.0],
        }
        future_bars = [
            KLineBar("2026-06-19", 148.0, 151.0, 146.2, 150.8, 90_000_000, 13_000_000_000.0),
            KLineBar("2026-06-22", 150.8, 153.0, 149.5, 152.2, 100_000_000, 15_000_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=147.9, future_bars=future_bars, review_window="3d")

        self.assertEqual(outcome["code"], "SZ.002463")
        self.assertTrue(outcome["directional_success"])
        self.assertFalse(outcome["invalidated"])
        self.assertGreater(outcome["maximum_favorable_pct"], 0)

    def test_evaluate_recommendation_detects_invalidation(self):
        recommendation = {
            "code": "SZ.002463",
            "label": "hold",
            "timestamp": "2026-06-18T15:00:00+08:00",
            "invalidation_level": 142.8,
            "support_levels": [145.0, 142.8],
            "resistance_levels": [149.9, 150.0],
        }
        future_bars = [
            KLineBar("2026-06-19", 147.0, 148.0, 141.9, 142.1, 120_000_000, 16_000_000_000.0),
        ]

        outcome = evaluate_recommendation(recommendation, entry_price=147.9, future_bars=future_bars, review_window="1d")

        self.assertFalse(outcome["directional_success"])
        self.assertTrue(outcome["invalidated"])

    def test_suggest_weight_adjustments_returns_small_explainable_changes(self):
        current = {"trend": 0.25, "capital_flow": 0.2, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.1}
        reviews = [
            {"directional_success": False, "dominant_failure": "macro_risk"},
            {"directional_success": False, "dominant_failure": "macro_risk"},
            {"directional_success": True, "dominant_failure": "none"},
        ]

        suggestion = suggest_weight_adjustments(current, reviews)

        self.assertGreater(suggestion["weights"]["macro_risk"], current["macro_risk"])
        self.assertAlmostEqual(sum(suggestion["weights"].values()), 1.0)
        self.assertTrue(suggestion["notes"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run review tests and verify they fail**

Run:

```bash
python -m unittest tests.test_review -v
```

Expected: fail because `tools.stock_skills.review` does not exist.

- [ ] **Step 3: Implement review evaluator**

Create `tools/stock_skills/review.py`:

```python
from __future__ import annotations

from collections import Counter
from typing import Any

from .models import KLineBar


POSITIVE_LABELS = {"strong-watch", "low-buy-zone", "hold"}
NEGATIVE_LABELS = {"trim-on-strength", "risk-reduce", "avoid"}


def evaluate_recommendation(
    recommendation: dict[str, Any],
    entry_price: float,
    future_bars: list[KLineBar],
    review_window: str,
) -> dict[str, Any]:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if not future_bars:
        raise ValueError("future_bars must not be empty")

    highest = max(bar.high for bar in future_bars)
    lowest = min(bar.low for bar in future_bars)
    final_close = future_bars[-1].close
    maximum_favorable_pct = round((highest - entry_price) / entry_price * 100, 4)
    maximum_adverse_pct = round((lowest - entry_price) / entry_price * 100, 4)
    final_return_pct = round((final_close - entry_price) / entry_price * 100, 4)
    invalidation_level = recommendation.get("invalidation_level")
    invalidated = bool(invalidation_level is not None and lowest <= float(invalidation_level))
    label = str(recommendation.get("label", ""))

    if label in POSITIVE_LABELS:
        directional_success = final_return_pct >= 0 and not invalidated
    elif label in NEGATIVE_LABELS:
        directional_success = final_return_pct <= 0 or invalidated
    else:
        directional_success = not invalidated

    if invalidated:
        dominant_failure = "trend"
    elif final_return_pct < 0 and label in POSITIVE_LABELS:
        dominant_failure = "macro_risk"
    else:
        dominant_failure = "none"

    return {
        "code": recommendation.get("code"),
        "source_timestamp": recommendation.get("timestamp"),
        "review_window": review_window,
        "label": label,
        "entry_price": entry_price,
        "final_close": final_close,
        "maximum_favorable_pct": maximum_favorable_pct,
        "maximum_adverse_pct": maximum_adverse_pct,
        "final_return_pct": final_return_pct,
        "invalidated": invalidated,
        "directional_success": directional_success,
        "dominant_failure": dominant_failure,
    }


def suggest_weight_adjustments(current_weights: dict[str, float], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    if not reviews:
        return {"weights": dict(current_weights), "notes": ["No reviews supplied; weights unchanged."]}

    failures = [review.get("dominant_failure") for review in reviews if review.get("directional_success") is False]
    counter = Counter(str(failure) for failure in failures if failure and failure != "none")
    weights = dict(current_weights)
    notes: list[str] = []

    if counter:
        top_failure, count = counter.most_common(1)[0]
        if top_failure in weights:
            weights[top_failure] += 0.02
            notes.append(f"Increased {top_failure} by 0.02 after {count} failed review(s).")
            reducible = [key for key in weights if key != top_failure and weights[key] > 0.05]
            if reducible:
                reduction = 0.02 / len(reducible)
                for key in reducible:
                    weights[key] -= reduction
    else:
        notes.append("No recurring failure factor found; weights unchanged.")

    total = sum(weights.values())
    normalized = {key: round(value / total, 6) for key, value in weights.items()}
    drift = round(1.0 - sum(normalized.values()), 6)
    first_key = next(iter(normalized))
    normalized[first_key] = round(normalized[first_key] + drift, 6)

    return {"weights": normalized, "notes": notes}
```

- [ ] **Step 4: Run review tests**

Run:

```bash
python -m unittest tests.test_review -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/review.py tests/test_review.py
git commit -m "feat: add recommendation review evaluator"
```

---

### Task 9: Futu Data Fetcher Adapter

**Files:**
- Create: `tools/stock_skills/futu_fetcher.py`
- Create: `tests/test_futu_fetcher.py`

- [ ] **Step 1: Write failing fetcher tests**

Create `tests/test_futu_fetcher.py`:

```python
import json
import unittest

from tools.stock_skills.futu_fetcher import FutuFetcher


class FakeRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        return json.dumps(
            {
                "data": [
                    {
                        "code": "SZ.002463",
                        "name": "沪电股份",
                        "last_price": 147.9,
                        "open": 146.0,
                        "high": 149.36,
                        "low": 142.81,
                        "prev_close": 146.55,
                        "volume": 83679015,
                        "turnover": 12271729868.41,
                    }
                ]
            },
            ensure_ascii=False,
        )


class FutuFetcherTests(unittest.TestCase):
    def test_snapshot_uses_existing_futu_script(self):
        runner = FakeRunner()
        fetcher = FutuFetcher(
            python_bin="/Users/shuren/.futu-venv/bin/python",
            skill_dir="/Users/shuren/.agents/skills/futuapi",
            runner=runner,
        )

        snapshot = fetcher.get_snapshot("SZ.002463")

        self.assertEqual(snapshot.code, "SZ.002463")
        self.assertEqual(snapshot.last_price, 147.9)
        self.assertIn("get_snapshot.py", runner.commands[0][1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run fetcher tests and verify they fail**

Run:

```bash
python -m unittest tests.test_futu_fetcher -v
```

Expected: fail because `tools.stock_skills.futu_fetcher` does not exist.

- [ ] **Step 3: Implement Futu fetcher**

Create `tools/stock_skills/futu_fetcher.py`:

```python
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import MarketSnapshot

Runner = Callable[[list[str]], str]


def _default_runner(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if lines:
        return lines[-1]
    return completed.stdout


class FutuFetcher:
    def __init__(
        self,
        python_bin: str = "/Users/shuren/.futu-venv/bin/python",
        skill_dir: str = "/Users/shuren/.agents/skills/futuapi",
        runner: Runner = _default_runner,
    ) -> None:
        self.python_bin = python_bin
        self.skill_dir = Path(skill_dir)
        self.runner = runner

    def _script(self, category: str, name: str) -> str:
        path = self.skill_dir / "scripts" / category / name
        if not path.exists():
            raise FileNotFoundError(f"Futu script not found: {path}")
        return str(path)

    def get_snapshot(self, code: str) -> MarketSnapshot:
        command = [self.python_bin, self._script("quote", "get_snapshot.py"), code, "--json"]
        payload = json.loads(self.runner(command))
        rows = payload.get("data", [])
        if not rows:
            raise ValueError(f"No snapshot returned for {code}")
        row = rows[0]
        return MarketSnapshot(
            code=row["code"],
            name=row.get("name", code),
            last_price=float(row["last_price"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            prev_close=float(row["prev_close"]),
            volume=int(row["volume"]),
            turnover=float(row["turnover"]),
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
```

- [ ] **Step 4: Run fetcher tests**

Run:

```bash
python -m unittest tests.test_futu_fetcher -v
```

Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add tools/stock_skills/futu_fetcher.py tests/test_futu_fetcher.py
git commit -m "feat: add futu data fetcher adapter"
```

---

### Task 10: CLI Dry Run

**Files:**
- Create: `tools/stock_skills/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.cli import main


class CliTests(unittest.TestCase):
    def test_dry_run_analyze_prints_recommendation_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recommendation.json"
            exit_code = main(["dry-run", "--code", "SZ.002463", "--output", str(output)])

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["code"], "SZ.002463")
        self.assertIn(payload["label"], {"hold", "trim-on-strength", "risk-reduce", "strong-watch", "low-buy-zone", "avoid"})
        self.assertIn("investment hypothesis", payload["analyst_hypothesis"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
python -m unittest tests.test_cli -v
```

Expected: fail because `tools.stock_skills.cli` does not exist.

- [ ] **Step 3: Implement dry-run CLI**

Create `tools/stock_skills/cli.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .capital import analyze_capital
from .engine import build_recommendation
from .macro import analyze_cross_market, analyze_macro_risk
from .models import CapitalSnapshot, InstrumentState, KLineBar, MarketSnapshot
from .trend import analyze_trend


def _sample_state(code: str) -> InstrumentState:
    name = "沪电股份" if code == "SZ.002463" else code
    snapshot = MarketSnapshot(code, name, 147.9, 146.0, 149.36, 142.81, 146.55, 83_679_015, 12_271_729_868.41, "2026-06-18T15:00:00+08:00")
    bars = [
        KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
        KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
        KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83_679_015, 12_271_729_868.41),
    ]
    capital = CapitalSnapshot(24_492_584.5, 744_236_606.14, -411_741_404.48, -210_842_830.36, -97_159_786.8, "2026-06-18T15:00:00+08:00")
    return InstrumentState(snapshot=snapshot, daily_bars=bars, intraday_bars=[], capital=capital, user_context={"last_trim_price": 149.5})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-evolving stock skill tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run", help="Run fixture-based analysis without Futu OpenD")
    dry_run.add_argument("--code", required=True)
    dry_run.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    if args.command == "dry-run":
        state = _sample_state(args.code)
        trend = analyze_trend(state.snapshot, state.daily_bars)
        capital = analyze_capital(state.capital)
        macro = analyze_macro_risk({"fed_bias": "hike", "geopolitical_risk": "elevated"})
        cross = analyze_cross_market({})
        weights = {"trend": 0.25, "capital_flow": 0.20, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.10}
        recommendation = build_recommendation(
            state=state,
            trend=trend,
            capital=capital,
            macro=macro,
            cross_market=cross,
            sector_score=60,
            position_fit_score=70,
            weights=weights,
            source_refs=["fixture"],
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(recommendation.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
python -m unittest tests.test_cli -v
```

Expected: 1 test passes.

- [ ] **Step 5: Run the full unit suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/stock_skills/cli.py tests/test_cli.py
git commit -m "feat: add stock analysis dry run cli"
```

---

### Task 11: Final Verification and Usage Notes

**Files:**
- Create: `docs/self-evolving-stock-skills-usage.md`

- [ ] **Step 1: Create concise usage notes**

Create `docs/self-evolving-stock-skills-usage.md`:

```markdown
# Self-Evolving Stock Skills Usage

## Dry Run

Run fixture-based analysis without Futu OpenD:

```bash
python -m tools.stock_skills.cli dry-run --code SZ.002463 --output /tmp/hudian-recommendation.json
```

The output JSON contains:

- `label`
- `total_score`
- `component_scores`
- `analyst_hypothesis`
- `trader_plan`
- `support_levels`
- `resistance_levels`
- `invalidation_level`

## Live Data Path

Live data collection is routed through `tools.stock_skills.futu_fetcher.FutuFetcher`, which wraps the existing `futuapi` scripts under:

```text
/Users/shuren/.agents/skills/futuapi/scripts
```

OpenD must be running for live calls. The analysis engine can still run on stored or fixture data when OpenD is unavailable.

## Safety

This package produces analysis and review records only. It does not place real trades. Any real order must follow the existing `futuapi` explicit-confirmation flow.
```

- [ ] **Step 2: Run all tests**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Run dry-run command manually**

Run:

```bash
python -m tools.stock_skills.cli dry-run --code SZ.002463 --output /tmp/hudian-recommendation.json
python -c "import json; print(json.load(open('/tmp/hudian-recommendation.json'))['label'])"
```

Expected: prints one of `hold`, `trim-on-strength`, `risk-reduce`, `strong-watch`, `low-buy-zone`, or `avoid`.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected: only intended files for this task are unstaged.

- [ ] **Step 5: Commit**

```bash
git add docs/self-evolving-stock-skills-usage.md
git commit -m "docs: add stock skills usage notes"
```

---

## Self-Review Checklist

- Spec coverage:
  - Active watchlist: Task 2.
  - Trend scoring: Task 3.
  - Capital-flow interpretation: Task 4.
  - Macro and cross-market overlay: Task 5.
  - Analyst and trader analysis modes: Task 6.
  - Recommendation journal: Task 7.
  - Review evaluator and weight suggestions: Task 8.
  - Futu integration: Task 9.
  - Dry-run CLI and verification: Tasks 10 and 11.
- Type consistency:
  - All modules use dataclasses from `tools.stock_skills.models`.
  - Score keys match `data/models/signal_weights.json`.
  - CLI uses the same engine and analyzers that tests cover.
- Safety:
  - No real trade execution exists in this package.
  - Live data collection is isolated in `futu_fetcher.py`.
  - OpenD unavailability does not affect pure unit tests.
