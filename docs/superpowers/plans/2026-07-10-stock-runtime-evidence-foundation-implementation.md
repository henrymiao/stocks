# Stock Runtime and Evidence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make live Futu discovery reliable, record session-aware data confidence independently from directional score, and prevent automatic signal-weight changes until enough realised reviews exist.

**Architecture:** Add three small foundation units: install-path resolution in `futu_fetcher.py`, market-session classification in a new `session.py`, and component coverage assessment in a new `data_quality.py`. Thread the resulting `DataQuality` record through the existing CLI, engine, recommendation JSON, and review workflow without changing current total-score labels; later exit-strategy and watchlist plans will build on these stable interfaces.

**Tech Stack:** Python 3 standard library, dataclasses, `zoneinfo`, JSON/JSONL, `unittest`, existing `tools.stock_skills` package.

**Design reference:** `docs/superpowers/specs/2026-07-10-stock-strategy-watchlist-upgrade-design.md`

---

## Scope Boundary

This plan implements delivery phase 1 only: runtime and evidence foundation. Structured R targets, partial exits, trailing stops, dual-horizon setup scoring, OHLC path simulation, and watchlist ranking remain separate implementation plans because each is independently testable and depends on the interfaces established here.

## File Map

| File | Responsibility |
| --- | --- |
| `tools/stock_skills/futu_fetcher.py` | Discover a usable installed `futuapi` skill directory while preserving explicit overrides and test runners. |
| `tools/stock_skills/session.py` | Classify the observation phase for US, HK, A-share, and crypto instruments. |
| `tools/stock_skills/data_quality.py` | Convert component availability/staleness into a `DataQuality` result and entry-eligibility flag. |
| `tools/stock_skills/models.py` | Define and serialize `DataQuality` on every new recommendation. |
| `tools/stock_skills/cli.py` | Assess actual component coverage, attach session phase, create review output, and gate weight writes. |
| `tools/stock_skills/engine.py` | Use evidence confidence rather than `total_score / 100`. |
| `tools/stock_skills/journal.py` | Create an empty JSONL evidence file even when no row is reviewable. |
| `tools/stock_skills/review.py` | Enforce a 60-review minimum before proposing mutable weights. |
| `skills/stock-analysis/SKILL.md` | Remove the stale user-specific repository path and describe confidence semantics. |
| `docs/self-evolving-stock-skills-usage.md` | Document auto-discovery, data quality, and the sample threshold. |
| `tests/test_futu_fetcher.py` | Path-discovery regression tests. |
| `tests/test_session.py` | Market-session classification tests. |
| `tests/test_data_quality.py` | Coverage, staleness, and eligibility tests. |
| `tests/test_models.py` | Recommendation serialization contract. |
| `tests/test_engine.py` | Confidence source regression test. |
| `tests/test_cli.py` | End-to-end recommendation and review safeguards. |
| `tests/test_journal.py` | Empty JSONL creation test. |
| `tests/test_review.py` | Minimum-sample weight-evolution tests. |

### Task 1: Discover the Installed Futu Skill Reliably

**Files:**
- Modify: `tools/stock_skills/futu_fetcher.py:29-35`
- Modify: `tools/stock_skills/futu_fetcher.py:112-130`
- Test: `tests/test_futu_fetcher.py`

- [ ] **Step 1: Write failing path-discovery tests**

Update the import in `tests/test_futu_fetcher.py` and add these tests:

```python
from tools.stock_skills.futu_fetcher import FutuFetcher, _default_skill_dir


class FutuSkillPathTests(unittest.TestCase):
    def _install_marker(self, home, client):
        marker = home / client / "skills" / "futuapi" / "scripts" / "quote" / "get_snapshot.py"
        marker.parent.mkdir(parents=True)
        marker.touch()
        return marker.parents[2]

    def test_default_skill_dir_prefers_codex_then_agents_then_claude(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            claude = self._install_marker(home, ".claude")
            agents = self._install_marker(home, ".agents")
            codex = self._install_marker(home, ".codex")

            self.assertEqual(_default_skill_dir(home), codex)
            (codex / "scripts" / "quote" / "get_snapshot.py").unlink()
            self.assertEqual(_default_skill_dir(home), agents)
            (agents / "scripts" / "quote" / "get_snapshot.py").unlink()
            self.assertEqual(_default_skill_dir(home), claude)

    def test_default_skill_dir_lists_attempted_paths_when_missing(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError) as ctx:
                _default_skill_dir(Path(tmpdir))

        message = str(ctx.exception)
        self.assertIn(".codex/skills/futuapi", message)
        self.assertIn(".agents/skills/futuapi", message)
        self.assertIn(".claude/skills/futuapi", message)
```

- [ ] **Step 2: Run the new tests and verify the old hard-coded default fails**

Run:

```bash
python3 -m unittest tests.test_futu_fetcher.FutuSkillPathTests -v
```

Expected: both tests fail because `_default_skill_dir` neither accepts `home` nor checks installed candidates.

- [ ] **Step 3: Implement candidate discovery**

Replace `_default_skill_dir` in `tools/stock_skills/futu_fetcher.py` with:

```python
def _skill_dir_candidates(home: Path) -> tuple[Path, ...]:
    return (
        home / ".codex" / "skills" / "futuapi",
        home / ".agents" / "skills" / "futuapi",
        home / ".claude" / "skills" / "futuapi",
    )


def _default_skill_dir(home: Path | None = None) -> Path:
    root = home or Path.home()
    candidates = _skill_dir_candidates(root)
    for candidate in candidates:
        marker = candidate / "scripts" / "quote" / "get_snapshot.py"
        if marker.is_file():
            return candidate
    attempted = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"No installed futuapi skill found. Tried: {attempted}")
```

Keep explicit constructor and environment overrides ahead of discovery:

```python
self.skill_dir = Path(
    skill_dir
    or os.environ.get("FUTUAPI_SKILL_DIR")
    or _default_skill_dir()
)
```

Do not require an explicit `skill_dir` to exist during construction; the custom fake runners intentionally use `/fake/futuapi`, and `_script` already validates real-runner paths.

- [ ] **Step 4: Run focused and existing fetcher tests**

Run:

```bash
python3 -m unittest tests.test_futu_fetcher -v
```

Expected: all `test_futu_fetcher` tests pass, including candidate precedence, missing-path diagnostics, fake runners, batching, capital fallback, financials, and extended-hours parsing.

- [ ] **Step 5: Reproduce the original environment failure path**

Run:

```bash
python3 -c "from tools.stock_skills.futu_fetcher import FutuFetcher; print(FutuFetcher().skill_dir)"
```

Expected in the current environment: prints either `/Users/shuren/.codex/skills/futuapi` or `/Users/shuren/.agents/skills/futuapi`, and does not reference the missing `.claude` directory.

- [ ] **Step 6: Commit the runtime-path fix**

```bash
git add tools/stock_skills/futu_fetcher.py tests/test_futu_fetcher.py
git commit -m "fix: discover installed futu skill paths"
```

### Task 2: Classify Market Session Phase

**Files:**
- Create: `tools/stock_skills/session.py`
- Create: `tests/test_session.py`

- [ ] **Step 1: Write failing session tests**

Create `tests/test_session.py`:

```python
import unittest

from tools.stock_skills.session import classify_session_phase


class SessionPhaseTests(unittest.TestCase):
    def test_us_phases_use_eastern_market_time(self):
        self.assertEqual(classify_session_phase("US.NVDA", "2026-07-10T09:00:00-04:00"), "pre-open")
        self.assertEqual(classify_session_phase("US.NVDA", "2026-07-10T10:00:00-04:00"), "intraday")
        self.assertEqual(classify_session_phase("US.NVDA", "2026-07-10T17:00:00-04:00"), "after-close")

    def test_a_share_lunch_is_not_active_trading(self):
        phase = classify_session_phase("SZ.002463", "2026-07-10T12:00:00+08:00")
        self.assertEqual(phase, "midday-break")

    def test_weekend_is_closed_for_equities(self):
        self.assertEqual(classify_session_phase("HK.00700", "2026-07-11T10:00:00+08:00"), "closed")

    def test_crypto_is_continuous_even_on_weekend(self):
        self.assertEqual(classify_session_phase("CC.BTC", "2026-07-11T10:00:00+08:00"), "continuous")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the missing module failure**

Run:

```bash
python3 -m unittest tests.test_session -v
```

Expected: import failure for `tools.stock_skills.session`.

- [ ] **Step 3: Implement deterministic session classification**

Create `tools/stock_skills/session.py`:

```python
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


def _local_time(code: str, timestamp: str) -> datetime:
    market_tz = ZoneInfo("America/New_York") if code.startswith("US.") else ZoneInfo("Asia/Shanghai")
    observed = datetime.fromisoformat(timestamp)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=market_tz)
    return observed.astimezone(market_tz)


def _inside(value: time, start: time, end: time) -> bool:
    return start <= value < end


def classify_session_phase(code: str, timestamp: str) -> str:
    prefix = code.split(".", 1)[0].upper() if "." in code else ""
    if prefix == "CC":
        return "continuous"

    observed = _local_time(code, timestamp)
    if observed.weekday() >= 5:
        return "closed"
    current = observed.time().replace(tzinfo=None)

    if prefix == "US":
        if _inside(current, time(4, 0), time(9, 30)):
            return "pre-open"
        if _inside(current, time(9, 30), time(16, 0)):
            return "intraday"
        return "after-close"

    if current < time(9, 30):
        return "pre-open"
    morning_end = time(12, 0) if prefix == "HK" else time(11, 30)
    afternoon_start = time(13, 0)
    market_close = time(16, 0) if prefix == "HK" else time(15, 0)
    if _inside(current, time(9, 30), morning_end) or _inside(current, afternoon_start, market_close):
        return "intraday"
    if morning_end <= current < afternoon_start:
        return "midday-break"
    return "after-close"
```

- [ ] **Step 4: Run session tests**

Run:

```bash
python3 -m unittest tests.test_session -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit the session classifier**

```bash
git add tools/stock_skills/session.py tests/test_session.py
git commit -m "feat: classify stock analysis session phases"
```

### Task 3: Add an Independent Data-Quality Model

**Files:**
- Create: `tools/stock_skills/data_quality.py`
- Modify: `tools/stock_skills/models.py:188-220`
- Create: `tests/test_data_quality.py`
- Modify: `tests/test_models.py:3-44`

- [ ] **Step 1: Write failing coverage and serialization tests**

Create `tests/test_data_quality.py`:

```python
import unittest

from tools.stock_skills.data_quality import assess_data_quality


ALL_AVAILABLE = {
    "trend": True,
    "capital_flow": True,
    "sector": True,
    "cross_market": True,
    "macro_risk": True,
    "market_regime": True,
    "fundamental": True,
    "position_fit": True,
}


class DataQualityTests(unittest.TestCase):
    def test_full_coverage_is_entry_eligible(self):
        quality = assess_data_quality(ALL_AVAILABLE, session_phase="after-close")
        self.assertEqual(quality.confidence, 1.0)
        self.assertEqual(quality.missing_components, ())
        self.assertTrue(quality.entry_eligible)

    def test_two_missing_components_fall_below_entry_threshold(self):
        availability = dict(ALL_AVAILABLE, macro_risk=False, cross_market=False)
        quality = assess_data_quality(availability, session_phase="after-close")
        self.assertEqual(quality.confidence, 0.75)
        self.assertEqual(quality.missing_components, ("cross_market", "macro_risk"))
        self.assertFalse(quality.entry_eligible)

    def test_stale_component_receives_half_credit(self):
        quality = assess_data_quality(
            ALL_AVAILABLE,
            session_phase="intraday",
            stale_components={"capital_flow"},
        )
        self.assertEqual(quality.confidence, 0.9375)
        self.assertEqual(quality.stale_components, ("capital_flow",))

    def test_missing_critical_component_rejects_entry(self):
        availability = dict(ALL_AVAILABLE, trend=False)
        quality = assess_data_quality(availability, session_phase="after-close")
        self.assertFalse(quality.entry_eligible)

    def test_unknown_component_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_data_quality(dict(ALL_AVAILABLE, mystery=True), session_phase="after-close")


if __name__ == "__main__":
    unittest.main()
```

Extend `tests/test_models.py` to import `DataQuality`, construct it on `Recommendation`, and assert nested serialization:

```python
data_quality=DataQuality(
    confidence=0.875,
    available_components=("trend", "capital_flow"),
    missing_components=("cross_market",),
    stale_components=(),
    session_phase="after-close",
    entry_eligible=True,
),
```

Add this assertion:

```python
self.assertEqual(payload["data_quality"]["confidence"], 0.875)
self.assertEqual(payload["data_quality"]["missing_components"], ("cross_market",))
```

- [ ] **Step 2: Run the focused tests and verify missing symbols**

Run:

```bash
python3 -m unittest tests.test_data_quality tests.test_models -v
```

Expected: failures because `data_quality.py` and `DataQuality` do not exist.

- [ ] **Step 3: Define `DataQuality`**

Add before `Recommendation` in `tools/stock_skills/models.py`:

```python
@dataclass(frozen=True)
class DataQuality:
    confidence: float
    available_components: tuple[str, ...]
    missing_components: tuple[str, ...]
    stale_components: tuple[str, ...]
    session_phase: str
    entry_eligible: bool
```

Add a required `data_quality: DataQuality` field to `Recommendation` immediately before `confidence`.

- [ ] **Step 4: Implement component coverage assessment**

Create `tools/stock_skills/data_quality.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Set

from .models import DataQuality


COMPONENTS = (
    "trend",
    "capital_flow",
    "sector",
    "cross_market",
    "macro_risk",
    "market_regime",
    "fundamental",
    "position_fit",
)
CRITICAL_COMPONENTS = {"trend", "position_fit"}
ENTRY_CONFIDENCE_THRESHOLD = 0.80


def assess_data_quality(
    availability: Mapping[str, bool],
    session_phase: str,
    stale_components: Set[str] | None = None,
) -> DataQuality:
    unknown = set(availability) - set(COMPONENTS)
    if unknown:
        raise ValueError(f"Unknown data-quality components: {sorted(unknown)}")

    stale = set(stale_components or ())
    unknown_stale = stale - set(COMPONENTS)
    if unknown_stale:
        raise ValueError(f"Unknown stale components: {sorted(unknown_stale)}")

    available = tuple(name for name in COMPONENTS if bool(availability.get(name)))
    missing = tuple(name for name in COMPONENTS if not bool(availability.get(name)))
    stale_ordered = tuple(name for name in COMPONENTS if name in stale and name in available)
    effective_count = len(available) - 0.5 * len(stale_ordered)
    confidence = round(max(0.0, min(1.0, effective_count / len(COMPONENTS))), 4)
    critical_unusable = CRITICAL_COMPONENTS & (set(missing) | stale)

    return DataQuality(
        confidence=confidence,
        available_components=available,
        missing_components=missing,
        stale_components=stale_ordered,
        session_phase=session_phase,
        entry_eligible=confidence >= ENTRY_CONFIDENCE_THRESHOLD and not critical_unusable,
    )
```

- [ ] **Step 5: Run model and data-quality tests**

Run:

```bash
python3 -m unittest tests.test_data_quality tests.test_models -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the data-quality primitives**

```bash
git add tools/stock_skills/data_quality.py tools/stock_skills/models.py tests/test_data_quality.py tests/test_models.py
git commit -m "feat: model stock analysis data confidence"
```

### Task 4: Thread Data Quality Through Recommendations

**Files:**
- Modify: `tools/stock_skills/cli.py:9-21`
- Modify: `tools/stock_skills/cli.py:123-197`
- Modify: `tools/stock_skills/engine.py:98-183`
- Modify: `tests/test_cli.py:69-168`
- Modify: `tests/test_engine.py:73-159`

- [ ] **Step 1: Add failing CLI and engine assertions**

In `tests/test_cli.py`, extend `test_analyze_no_macro_flags_neutral`:

```python
quality = payload["data_quality"]
self.assertIn("macro_risk", quality["missing_components"])
self.assertIn("cross_market", quality["missing_components"])
self.assertEqual(quality["confidence"], 0.75)
self.assertFalse(quality["entry_eligible"])
```

Extend `test_analyze_with_cross_market_does_not_flag_cross_default`:

```python
self.assertNotIn("cross_market", payload["data_quality"]["missing_components"])
```

In `tests/test_engine.py`, import `DataQuality`, construct this value in the `common` arguments used by `build_recommendation`, and add a confidence assertion:

```python
quality = DataQuality(
    confidence=0.875,
    available_components=("trend", "capital_flow"),
    missing_components=("cross_market",),
    stale_components=(),
    session_phase="after-close",
    entry_eligible=True,
)
```

Pass `data_quality=quality`, then assert:

```python
self.assertEqual(rec_long.confidence, 0.875)
self.assertEqual(rec_long.data_quality, quality)
```

- [ ] **Step 2: Run focused tests and verify constructor/call failures**

Run:

```bash
python3 -m unittest tests.test_cli tests.test_engine -v
```

Expected: failures because `_recommend` does not calculate data quality and `build_recommendation` does not accept it.

- [ ] **Step 3: Assess availability in `_recommend`**

Add imports in `tools/stock_skills/cli.py`:

```python
from .data_quality import assess_data_quality
from .session import classify_session_phase
```

After computing `position`, construct evidence availability:

```python
availability = {
    "trend": len(state.daily_bars) >= 2,
    "capital_flow": state.capital is not None,
    "sector": bool(sector_changes),
    "cross_market": bool(cross_snapshots),
    "macro_risk": bool(macro_snapshots) or bool(macro_inputs),
    "market_regime": bool(index_snapshots),
    "fundamental": fundamentals is not None and fundamentals.pe_ttm is not None,
    "position_fit": position.stop_price is not None,
}
data_quality = assess_data_quality(
    availability,
    session_phase=classify_session_phase(state.snapshot.code, state.snapshot.timestamp),
)
```

Pass `data_quality=data_quality` into `build_recommendation`.

- [ ] **Step 4: Make engine confidence evidence-based**

Import `DataQuality` into `tools/stock_skills/engine.py`, add `data_quality: DataQuality` to `build_recommendation`, remove:

```python
confidence = round(max(0.1, min(0.95, total_score / 100)), 2)
```

and construct the recommendation with:

```python
data_quality=data_quality,
confidence=data_quality.confidence,
```

Update every direct `build_recommendation` test call to pass an explicit `DataQuality`; do not introduce a fallback to total score.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_cli tests.test_engine tests.test_models tests.test_data_quality tests.test_session -v
```

Expected: all focused tests pass; existing total scores and action labels remain unchanged while confidence and coverage become evidence-based.

- [ ] **Step 6: Run all offline tests for regression coverage**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass with zero failures and zero errors.

- [ ] **Step 7: Commit recommendation integration**

```bash
git add tools/stock_skills/cli.py tools/stock_skills/engine.py tests/test_cli.py tests/test_engine.py
git commit -m "feat: attach evidence confidence to recommendations"
```

### Task 5: Make Review Evidence Explicit and Guard Weight Evolution

**Files:**
- Modify: `tools/stock_skills/journal.py:8-30`
- Modify: `tools/stock_skills/review.py:8-114`
- Modify: `tools/stock_skills/cli.py:346-386`
- Modify: `tests/test_journal.py`
- Modify: `tests/test_review.py:47-59`
- Modify: `tests/test_cli.py:170-210`

- [ ] **Step 1: Write failing evidence-safety tests**

Add this class to `tests/test_journal.py`:

```python
from tools.stock_skills.journal import append_record, ensure_journal, read_records


class JournalEnsureTests(unittest.TestCase):
    def test_ensure_journal_creates_empty_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "reviews.jsonl"
            ensure_journal(path)
            self.assertTrue(path.exists())
            self.assertEqual(read_records(path), [])
```

Replace the small-sample method inside `ReviewTests` and add the sufficient-sample method beside it:

```python
    def test_suggest_weight_adjustments_refuses_small_sample(self):
        current = {"trend": 0.25, "capital_flow": 0.2, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.1}
        reviews = [
            {"directional_success": False, "dominant_failure": "macro_risk"},
            {"directional_success": False, "dominant_failure": "macro_risk"},
            {"directional_success": True, "dominant_failure": "none"},
        ]

        suggestion = suggest_weight_adjustments(current, reviews)

        self.assertEqual(suggestion["weights"], current)
        self.assertFalse(suggestion["eligible"])
        self.assertEqual(suggestion["sample_size"], 3)
        self.assertIn("60", suggestion["notes"][0])

    def test_suggest_weight_adjustments_allows_sufficient_sample(self):
        current = {"trend": 0.25, "capital_flow": 0.2, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.1}
        reviews = [
            {"directional_success": False, "dominant_failure": "macro_risk"}
            for _ in range(40)
        ] + [
            {"directional_success": True, "dominant_failure": "none"}
            for _ in range(20)
        ]

        suggestion = suggest_weight_adjustments(current, reviews)

        self.assertTrue(suggestion["eligible"])
        self.assertGreater(suggestion["weights"]["macro_risk"], current["macro_risk"])
        self.assertAlmostEqual(sum(suggestion["weights"].values()), 1.0)
```

In `test_review_evaluates_journal_and_only_applies_with_flag`, replace the post-apply expectations with:

```python
self.assertEqual(code1, 0)
self.assertEqual(code2, 0)
self.assertEqual(len(review_rows), 1)
self.assertFalse(review_rows[0]["directional_success"])
self.assertEqual(review_rows[0]["dominant_failure"], "cross_market")
self.assertEqual(weights_after_apply, weights_after_suggest)
self.assertFalse(backup_exists)
```

Add this second method inside `CliTests` to prove an empty evidence file is materialised:

```python
    def test_review_creates_empty_file_when_no_row_is_reviewable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recommendations = Path(tmpdir) / "recommendations.jsonl"
            reviews = Path(tmpdir) / "reviews.jsonl"
            weights = Path(tmpdir) / "signal_weights.json"
            weights.write_text(
                json.dumps({
                    "trend": 0.20,
                    "capital_flow": 0.13,
                    "sector": 0.14,
                    "cross_market": 0.11,
                    "macro_risk": 0.11,
                    "market_regime": 0.12,
                    "fundamental": 0.10,
                    "position_fit": 0.09,
                }),
                encoding="utf-8",
            )
            append_record(
                recommendations,
                {
                    "code": "SZ.002463",
                    "label": "hold",
                    "timestamp": "2026-06-18T15:00:00+08:00",
                    "entry_price": 0.0,
                },
            )

            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main([
                    "review",
                    "--recommendations", str(recommendations),
                    "--reviews", str(reviews),
                    "--weights", str(weights),
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(reviews.exists())
            self.assertEqual(read_records(reviews), [])
```

- [ ] **Step 2: Run focused tests and verify missing guard behaviour**

Run:

```bash
python3 -m unittest tests.test_journal tests.test_review tests.test_cli -v
```

Expected: failures because `ensure_journal`, `eligible`, `sample_size`, and the 60-review guard do not exist.

- [ ] **Step 3: Add empty-journal creation**

Add to `tools/stock_skills/journal.py`:

```python
def ensure_journal(path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(exist_ok=True)
```

Import `ensure_journal` in `cli.py` and call it once before the review loop:

```python
ensure_journal(args.reviews)
```

- [ ] **Step 4: Enforce the minimum review sample**

Add near the label constants in `tools/stock_skills/review.py`:

```python
MIN_WEIGHT_REVIEW_SAMPLE = 60
```

At the start of `suggest_weight_adjustments`, replace the current no-review-only guard with:

```python
usable = [review for review in reviews if isinstance(review.get("directional_success"), bool)]
if len(usable) < MIN_WEIGHT_REVIEW_SAMPLE:
    return {
        "weights": dict(current_weights),
        "eligible": False,
        "sample_size": len(usable),
        "notes": [
            f"Need at least {MIN_WEIGHT_REVIEW_SAMPLE} realised reviews before changing weights; "
            f"received {len(usable)}."
        ],
    }
```

Use `usable` rather than `reviews` for failure counting. Add `eligible=True` and `sample_size=len(usable)` to the normal return value.

- [ ] **Step 5: Prevent ineligible writes in the CLI**

Replace the apply branch in `_cmd_review` with:

```python
if args.apply and suggestion["eligible"]:
    reason = f"Auto-adjust from {len(reviews)} review(s) over {args.window}: " + "; ".join(suggestion["notes"])
    entry = save_weights(args.weights, suggestion["weights"], reason=reason)
    print(f"Applied new weights (backup at {args.weights}.bak). History: {entry['timestamp']}")
elif args.apply:
    print("Weights not applied: realised review sample is below the safety threshold.")
else:
    print("Suggestion only. Re-run with --apply after the sample is eligible to write weights back.")
```

- [ ] **Step 6: Run review and journal tests**

Run:

```bash
python3 -m unittest tests.test_journal tests.test_review tests.test_cli -v
```

Expected: all tests pass; small samples never write weights, a 60-row sample can produce a suggestion, and an empty review run still creates `reviews.jsonl`.

- [ ] **Step 7: Commit evidence safeguards**

```bash
git add tools/stock_skills/journal.py tools/stock_skills/review.py tools/stock_skills/cli.py tests/test_journal.py tests/test_review.py tests/test_cli.py
git commit -m "fix: require realised evidence before weight changes"
```

### Task 6: Align Skill Documentation and Verify the Phase

**Files:**
- Modify: `skills/stock-analysis/SKILL.md:20-38`
- Modify: `skills/stock-analysis/SKILL.md:123-147`
- Modify: `docs/self-evolving-stock-skills-usage.md:3-31`
- Modify: `docs/self-evolving-stock-skills-usage.md:33-52`

- [ ] **Step 1: Replace the stale repository path**

In `skills/stock-analysis/SKILL.md`, replace the user-specific path block with:

```markdown
## Repository Paths

Treat the current workspace root as the repository root. Do not assume a user-specific absolute path.

Core files:
```

Keep the existing core-file list immediately below it.

- [ ] **Step 2: Document Futu discovery and evidence confidence**

In `docs/self-evolving-stock-skills-usage.md`, replace the user-specific path under **Live Data Path** with the discovery statement below. Add the same discovery and confidence statements to the live-analysis sections of both documentation files:

```markdown
`FutuFetcher` resolves `futuapi` in this order when `FUTUAPI_SKILL_DIR` is not set: `~/.codex/skills/futuapi`, `~/.agents/skills/futuapi`, then `~/.claude/skills/futuapi`. If none contains `scripts/quote/get_snapshot.py`, live analysis stops with an error listing every attempted location.

Every new recommendation includes `data_quality`: available, missing, and stale components; session phase; evidence confidence; and whether the evidence is sufficient for a new entry. Missing data still leaves the directional component neutral for backward-compatible scoring, but it lowers evidence confidence and is never presented as observed neutrality.
```

Update the review section:

```markdown
Weight changes require at least 60 realised review rows. `--apply` below that threshold records no weight change and creates no backup; this prevents the system from adapting to a handful of correlated outcomes.
```

- [ ] **Step 3: Check documentation for stale absolute paths and formatting errors**

Run:

```bash
rg -n "/Users/(allglitter|shuren)|\.claude/skills/futuapi/scripts" skills/stock-analysis/SKILL.md docs/self-evolving-stock-skills-usage.md
git diff --check
```

Expected: `rg` returns no matches; `git diff --check` emits no output and exits 0.

- [ ] **Step 4: Run the complete offline test suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: every test passes with zero failures and zero errors.

- [ ] **Step 5: Verify default runtime discovery on the current machine**

Run:

```bash
python3 -c "from tools.stock_skills.futu_fetcher import FutuFetcher; f=FutuFetcher(); print(f.skill_dir); print((f.skill_dir / 'scripts/quote/get_snapshot.py').is_file())"
```

Expected: prints an installed Codex or agents `futuapi` directory followed by `True`.

- [ ] **Step 6: Verify a dry-run recommendation contains evidence quality**

Run:

```bash
python3 -m tools.stock_skills.cli dry-run --code SZ.002463 --output /tmp/stock-foundation-dry-run.json
python3 -c "import json; p=json.load(open('/tmp/stock-foundation-dry-run.json')); print(p['data_quality'])"
```

Expected: prints a dictionary containing `confidence`, `available_components`, `missing_components`, `stale_components`, `session_phase`, and `entry_eligible`.

- [ ] **Step 7: Commit the documentation and phase verification state**

```bash
git add skills/stock-analysis/SKILL.md docs/self-evolving-stock-skills-usage.md
git commit -m "docs: explain stock analysis evidence confidence"
```

## Phase Completion Checklist

- [ ] `FutuFetcher()` resolves a real installed skill without a Claude-only assumption.
- [ ] Missing installations fail with every attempted path in the error.
- [ ] Every new recommendation serializes `data_quality` separately from total score.
- [ ] Session phase is deterministic for US, HK, A-share, and crypto codes.
- [ ] Missing or stale evidence reduces confidence and can make a new entry ineligible.
- [ ] Existing score totals and action-label thresholds remain unchanged in this phase.
- [ ] Review output exists even when no recommendation is yet reviewable.
- [ ] Fewer than 60 realised reviews cannot modify signal weights.
- [ ] All offline tests pass.
- [ ] No real trading capability is introduced.

## Subsequent Plan Order

After this plan passes and is merged, create the remaining plans in this order:

1. structured exit engine and position-state model;
2. short/swing strategy profiles plus leveraged overlay;
3. OHLC path backtest with partial fills, gaps, costs, and portfolio heat;
4. tiered watchlist scanner with batch ranking and shared context caches;
5. walk-forward optimisation after sufficient realised samples.
