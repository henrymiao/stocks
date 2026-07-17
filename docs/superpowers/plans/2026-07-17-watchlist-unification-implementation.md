# Unified Watchlist Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace five duplicated instrument lists with one validated canonical watchlist, compatibility views, explicit position/scan policies, and bounded top-plus-bottom deep-analysis selection.

**Architecture:** Keep `data/watchlists/core.json` as the canonical record store and teach `load_watchlist` to resolve one-level filtered view files. Normalize operator state in `config.py`, then extend `watchlist_scan.py` so always-scan names and bounded largest decliners join the existing top-ranked promotion set. Preserve all unrelated working-tree changes and use path-restricted commits only.

**Tech Stack:** Python 3 standard library, JSON, `unittest`, existing stock-analysis CLI and Futu snapshot abstractions.

---

## File Map

- `tools/stock_skills/config.py`: validate canonical metadata and resolve compatibility views.
- `tools/stock_skills/watchlist_scan.py`: select always, top-ranked, and bottom-decliner deep-analysis candidates with auditable reasons.
- `tools/stock_skills/scan_watchlist.py`: expose `--deep-bottom` and print selection reasons.
- `data/watchlists/core.json`: canonical 128-code instrument catalog.
- Four other files in `data/watchlists/`: compatibility views referencing `core.json`.
- `tests/test_config.py`: schema and view-loader behavior.
- `tests/test_watchlist_scan.py`: bidirectional promotion behavior.
- `tests/test_watchlist_data.py`: repository-data acceptance checks.
- `skills/stock-analysis/SKILL.md` and `docs/self-evolving-stock-skills-usage.md`: operator documentation.

### Task 1: Canonical metadata and compatibility-view loader

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tools/stock_skills/config.py`

- [ ] **Step 1: Write failing schema tests**

```python
def test_load_watchlist_normalizes_position_and_scan_policy(self):
    entry = {
        "code": "HK.00700", "name": "腾讯控股", "tags": ["hk", "holding", "growth"],
        "position_status": "reduced-holding", "scan_policy": "always",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "core.json"
        path.write_text(json.dumps({"watchlist": [entry]}), encoding="utf-8")
        loaded = load_watchlist(path)[0]
    self.assertEqual(loaded["position_status"], "reduced-holding")
    self.assertEqual(loaded["scan_policy"], "always")

def test_load_watchlist_rejects_leveraged_etf_without_underlying(self):
    entry = {
        "code": "HK.07709", "name": "XL二南方海力士", "tags": ["hk", "leveraged"],
        "asset_type": "leveraged-etf", "underlying_proxy": None,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "core.json"
        path.write_text(json.dumps({"watchlist": [entry]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "underlying_proxy"):
            load_watchlist(path)
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_config.ConfigTests.test_load_watchlist_normalizes_position_and_scan_policy tests.test_config.ConfigTests.test_load_watchlist_rejects_leveraged_etf_without_underlying -v
```

Expected: the state test fails because normalized fields are absent and the leveraged test fails because `None` is currently accepted.

- [ ] **Step 3: Implement state normalization**

```python
POSITION_STATUSES = {"holding", "reduced-holding", "exited-watch", "watch"}
SCAN_POLICIES = {"always", "ranked", "snapshot-only"}

def _default_position_status(tags: list[str]) -> str:
    return "holding" if "holding" in set(tags) else "watch"

def _default_scan_policy(tier: str, position_status: str) -> str:
    if position_status in {"holding", "reduced-holding"} or tier == "core":
        return "always"
    if tier in {"proxy", "discovery"}:
        return "snapshot-only"
    return "ranked"
```

Validate both fields in `normalize_watchlist_entry`, add them to the normalized mapping, and raise `ValueError("Leveraged ETF <code> requires underlying_proxy")` when a leveraged ETF has no underlying.

- [ ] **Step 4: Run all config tests**

Run `python3 -m unittest tests.test_config -v`. Expected: PASS.

- [ ] **Step 5: Write failing one-level view tests**

```python
def test_load_watchlist_resolves_one_level_tag_view(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "core.json").write_text(json.dumps({"watchlist": [
            {"code": "SZ.002463", "name": "沪电股份", "tags": ["a-share", "national-tech"]},
            {"code": "HK.00700", "name": "腾讯控股", "tags": ["hk", "national-tech"]},
        ]}), encoding="utf-8")
        (root / "view.json").write_text(json.dumps({
            "source": "core.json",
            "filters": {"market": ["HK"], "include_tags_all": ["national-tech"]},
        }), encoding="utf-8")
        entries = load_watchlist(root / "view.json")
    self.assertEqual([entry["code"] for entry in entries], ["HK.00700"])

def test_load_watchlist_rejects_nested_view(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "base.json").write_text(json.dumps({"source": "core.json", "filters": {}}), encoding="utf-8")
        (root / "view.json").write_text(json.dumps({"source": "base.json", "filters": {}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "nested watchlist view"):
            load_watchlist(root / "view.json")
```

- [ ] **Step 6: Run view tests and verify RED**

Expected: FAIL because `load_watchlist` currently requires a `watchlist` array.

- [ ] **Step 7: Implement deterministic view resolution**

Add a private `_load_watchlist(path, allow_view)` helper. Permit only:

```python
WATCHLIST_VIEW_FILTERS = {
    "include_tags_any", "include_tags_all", "codes", "market", "tier",
}
```

Resolve `source` relative to the view file, reject nested views, load canonical entries once, and apply list-valued filters while preserving canonical order. Reject unknown keys and non-list filter values.

- [ ] **Step 8: Run all config tests again**

Run `python3 -m unittest tests.test_config -v`. Expected: PASS.

### Task 2: Canonical data migration and acceptance checks

**Files:**
- Create: `tests/test_watchlist_data.py`
- Modify: all five files in `data/watchlists/`

- [ ] **Step 1: Write the failing repository-data test**

```python
import unittest
from pathlib import Path

from tools.stock_skills.config import load_json, load_watchlist

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "data" / "watchlists" / "core.json"

class WatchlistDataTests(unittest.TestCase):
    def test_core_is_the_only_instrument_store_and_has_expected_focus_states(self):
        entries = load_watchlist(CORE)
        by_code = {entry["code"]: entry for entry in entries}
        self.assertEqual(len(entries), 128)
        self.assertEqual(len(by_code), 128)
        self.assertEqual(by_code["HK.00700"]["position_status"], "reduced-holding")
        self.assertEqual(by_code["HK.09988"]["position_status"], "reduced-holding")
        self.assertEqual(by_code["SZ.000021"]["position_status"], "holding")
        self.assertEqual(by_code["HK.09868"]["scan_policy"], "always")
        self.assertEqual(by_code["SZ.002463"]["position_status"], "exited-watch")
        self.assertEqual(by_code["HK.03690"]["position_status"], "exited-watch")
        self.assertEqual(by_code["HK.02513"]["name"], "智谱")
        self.assertEqual(by_code["HK.07709"]["asset_type"], "leveraged-etf")
        self.assertEqual(by_code["HK.07709"]["underlying_proxy"], "US.SKHY")
        self.assertIn("oversold-watch", by_code["SH.563380"]["tags"])
        for name in ("a-share-broad-short.json", "national-tech.json", "hk-national-tech.json", "hk-tomorrow-five.json"):
            payload = load_json(CORE.parent / name)
            self.assertIn("source", payload)
            self.assertNotIn("watchlist", payload)

    def test_legacy_views_resolve_nonempty_unique_subsets(self):
        for path in CORE.parent.glob("*.json"):
            entries = load_watchlist(path)
            codes = [entry["code"] for entry in entries]
            self.assertTrue(codes, path.name)
            self.assertEqual(len(codes), len(set(codes)), path.name)
```

- [ ] **Step 2: Run the repository-data test and verify RED**

Run `python3 -m unittest tests.test_watchlist_data -v`. Expected: FAIL with 75 canonical entries and missing focus codes.

- [ ] **Step 3: Merge the canonical catalog**

Preserve the 125 unique existing codes, union duplicate tags, use the maximum priority, fill the complete normalized field set, and add:

```json
{"code":"HK.02513","name":"智谱","enabled":true,"tier":"thematic","priority":90,"strategy_profiles":["short","swing"],"asset_type":"equity","valuation_profile":"growth","benchmark":"HK.800700","underlying_proxy":null,"event_policy":"standard","position_status":"watch","scan_policy":"ranked","tags":["hk","artificial-intelligence","foundation-model","high-volatility","growth"]}
{"code":"HK.07709","name":"XL二南方海力士","enabled":true,"tier":"thematic","priority":80,"strategy_profiles":["short"],"asset_type":"leveraged-etf","valuation_profile":"neutral","benchmark":"HK.800700","underlying_proxy":"US.SKHY","event_policy":"standard","position_status":"watch","scan_policy":"ranked","tags":["hk","etf","leveraged","semiconductor","memory","hbm","high-volatility"]}
{"code":"SH.563380","name":"航空航天ETF华泰柏瑞","enabled":true,"tier":"thematic","priority":70,"strategy_profiles":["short","swing"],"asset_type":"etf","valuation_profile":"neutral","benchmark":"SH.000001","underlying_proxy":null,"event_policy":"standard","position_status":"watch","scan_policy":"ranked","tags":["a-share","etf","aerospace","defense","high-volatility","oversold-watch"]}
```

Apply the approved position overrides after the mechanical merge.

- [ ] **Step 4: Convert legacy lists to exact views**

- A-share broad: `include_tags_all=["a-share","broad-screen"]`.
- A-share national tech: `include_tags_all=["a-share","national-tech"]`.
- HK national tech: `include_tags_all=["hk","national-tech"]`.
- HK focus: `codes=["HK.00700","HK.09988","HK.09868","HK.03690","HK.09961"]`.

Each payload uses `schema_version: 3` and `source: "core.json"`.

- [ ] **Step 5: Run data and config tests**

Run `python3 -m unittest tests.test_watchlist_data tests.test_config -v`. Expected: PASS with 128 unique canonical records.

### Task 3: Always plus Top-N plus Bottom-N selection

**Files:**
- Modify: `tests/test_watchlist_scan.py`
- Modify: `tools/stock_skills/watchlist_scan.py`

- [ ] **Step 1: Write the failing selection test**

```python
def test_always_top_and_bottom_candidates_receive_deep_analysis(self):
    entries = self.entries + [{
        "code": "US.REDUCED", "name": "Reduced", "tier": "thematic", "priority": 90,
        "strategy_profiles": ["short"], "benchmark": "US.SPY", "underlying_proxy": None,
        "tags": ["holding"], "scan_policy": "always", "position_status": "reduced-holding",
    }]
    fetcher = FakeFetcher({
        "US.CORE": _snapshot("US.CORE", 0.5), "US.FAST": _snapshot("US.FAST", 4.0),
        "US.SLOW": _snapshot("US.SLOW", -6.0), "US.SPY": _snapshot("US.SPY", 1.0),
        "US.NEW": _snapshot("US.NEW", 8.0), "US.REDUCED": _snapshot("US.REDUCED", -0.5),
    })
    calls = []
    result = run_watchlist_scan(
        entries, fetcher,
        analyzer=lambda entry, horizon, shared: calls.append(entry["code"]) or {},
        deep_top=1, deep_bottom=1, deep_horizons=("short",),
    )
    self.assertEqual(set(calls), {"US.CORE", "US.REDUCED", "US.FAST", "US.SLOW"})
    reasons = {item["code"]: item["selection_reasons"] for item in result["selections"]["short"]}
    self.assertIn("always", reasons["US.REDUCED"])
    self.assertIn("top", reasons["US.FAST"])
    self.assertIn("bottom", reasons["US.SLOW"])
```

- [ ] **Step 2: Run the test and verify RED**

Expected: `TypeError` because `deep_bottom` is not accepted.

- [ ] **Step 3: Implement bounded bottom selection**

Add `deep_bottom: int = 5`, reject negative values, and build each horizon's selection from:

1. eligible core or `scan_policy == "always"` entries;
2. the first `deep_top` ranked thematic entries;
3. up to `deep_bottom` eligible ranked thematic entries sorted by `(change_pct, relative_strength_pct, code)`.

Deduplicate and emit:

```python
"selections": {
    horizon: [
        {"code": code, "selection_reasons": sorted(reasons_by_code[code])}
        for code in ordered_codes
    ]
}
```

- [ ] **Step 4: Run scanner tests**

Run `python3 -m unittest tests.test_watchlist_scan -v`. Expected: PASS.

### Task 4: CLI and documentation

**Files:**
- Modify: `tools/stock_skills/scan_watchlist.py`
- Modify: `skills/stock-analysis/SKILL.md`
- Modify: `docs/self-evolving-stock-skills-usage.md`

- [ ] **Step 1: Expose Bottom-N**

```python
parser.add_argument(
    "--deep-bottom", type=int, default=5,
    help="Largest eligible thematic decliners per requested horizon",
)
```

Pass `deep_bottom=args.deep_bottom` to `run_watchlist_scan` and surface selection reasons in output.

- [ ] **Step 2: Document canonical and bidirectional scans**

```bash
python3 tools/stock_skills/scan_watchlist.py \
  --watchlist data/watchlists/core.json \
  --horizon both \
  --deep-top 10 \
  --deep-bottom 5 \
  --output /tmp/watchlist-scan.json
```

State that holdings are always scanned, legacy paths are views, promotion is not a buy signal, and no trade is executed.

- [ ] **Step 3: Verify CLI help**

Run `python3 tools/stock_skills/scan_watchlist.py --help`. Expected: exit 0 and output contains `--deep-bottom`.

### Task 5: Full verification and scoped handoff

**Files:** all paths listed above.

- [ ] **Step 1: Run focused tests**

```bash
python3 -m unittest tests.test_config tests.test_watchlist_data tests.test_watchlist_scan -v
```

Expected: PASS.

- [ ] **Step 2: Run full tests**

```bash
python3 -m unittest discover -s tests -v
```

Expected: PASS with no new errors or warnings.

- [ ] **Step 3: Validate data and whitespace**

```bash
for file in data/watchlists/*.json; do python3 -m json.tool "$file" >/dev/null; done
jq '[.watchlist[].code] | length == (unique | length)' data/watchlists/core.json
git diff --check
```

Expected: JSON validation exits 0, `jq` prints `true`, and whitespace validation prints nothing.

- [ ] **Step 4: Inspect scope**

```bash
git status --short
git diff --stat -- tools/stock_skills/config.py tools/stock_skills/watchlist_scan.py tools/stock_skills/scan_watchlist.py data/watchlists tests skills/stock-analysis/SKILL.md docs/self-evolving-stock-skills-usage.md
```

Expected: unrelated pre-existing changes remain untouched.

- [ ] **Step 5: Commit only implementation paths if requested**

Use `git commit --only` with the exact watchlist implementation paths so the pre-existing staged `data/market.db` deletion and unrelated edits cannot be included accidentally.
