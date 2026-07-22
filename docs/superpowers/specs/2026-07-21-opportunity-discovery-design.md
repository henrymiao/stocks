# Opportunity Discovery Layer Design

Date: 2026-07-21
Status: Approved for implementation planning

## 1. Goal

Add an opportunity-discovery layer ahead of the existing stock analysis and execution-decision pipeline. The new layer must identify sector and instrument setups before a confirmed breakout or rebound, while preserving the existing setup-score, hard-gate, risk sizing, position-management, and exit logic.

The layer covers three separately scheduled markets:

- CN: Shanghai and Shenzhen markets, scheduled in Asia/Shanghai time.
- HK: Hong Kong market, scheduled in Asia/Shanghai time.
- US: United States market, scheduled in America/New_York time, including daylight-saving transitions.

The discovery layer produces candidates and state transitions. It never places trades and never treats a discovery score as an entry recommendation.

## 2. Non-goals

- Do not lower or replace the existing executable setup-score threshold or hard gates.
- Do not change existing position or exit decisions.
- Do not infer a buy signal solely from a US-to-CN/HK cross-market move.
- Do not scan every listed security in the first release.
- Do not promise a fixed hit rate or profit rate before live evidence is accumulated.
- Do not introduce a market-data source that replaces OpenD for prices, K-lines, volume, turnover, or capital flow.

## 3. Architecture

The processing pipeline is:

1. Build a market-specific universe from core indices, sector ETFs, and major constituents.
2. Fetch batch snapshots and update the local completed-daily-bar cache.
3. Compute two independent discovery tracks: trend buildup and oversold reversal.
4. Aggregate ETF, index, constituent breadth, and leader evidence at sector level.
5. Persist `forming` and `armed` candidates after the close.
6. During the next trading session, refresh only `armed` candidates every five minutes.
7. Promote a candidate to `triggered` only when local price, breadth, and leader evidence confirm.
8. Pass `triggered` candidates to the existing deep-analysis pipeline.
9. Let the existing strategy assessment produce `probe`, `enter`, `watch`, or `reject`.

New modules:

- `tools/stock_skills/universe.py`: market universe, ETF/index/constituent mappings, membership refresh, and cache fallback.
- `tools/stock_skills/discovery_features.py`: completed-bar cross-sectional and time-series features.
- `tools/stock_skills/discovery_engine.py`: independent scores, evidence clusters, state transitions, expiry, and invalidation.
- `tools/stock_skills/discovery_store.py`: durable state, notification deduplication, and discovery-review records.

Existing modules remain authoritative for executable decisions:

- `watchlist_scan.py` and `scan_watchlist.py` retain their current watchlist-promotion role.
- `cli.py`, `strategy.py`, `exit_engine.py`, and position management retain their current execution and risk roles.
- `futu_fetcher.py` remains quote-only and must never call trade scripts.

## 4. Market Universe

### 4.1 CN

Core indices:

- SSE 50
- CSI 300
- CSI 500
- CSI 1000
- STAR 50
- ChiNext

Initial sector families:

- Semiconductors, compute/communications, AI, and robotics
- Electric vehicles and batteries
- Innovative drugs and medical devices
- Brokers, banks, and insurance
- Gold, non-ferrous metals, chemicals, and aerospace/defence
- Power, grid equipment, and high-dividend equities

### 4.2 HK

Core indices and sector families:

- Hang Seng Index
- Hang Seng TECH Index
- Hang Seng China Enterprises Index
- Internet, semiconductors, automobiles, innovative drugs, financials, resources, and high-dividend equities

A/H dual listings retain separate local securities and triggers, while shared company identity is recorded for reporting and concentration checks.

### 4.3 US

The US job runs independently in America/New_York time and covers:

- S&P 500
- Nasdaq-100
- Russell 2000
- Semiconductor, software/cloud, AI infrastructure, financial, energy, industrial, healthcare, and consumer ETFs
- Major index and sector constituents

### 4.4 Membership Policy

Each index or sector family contains its representative ETF plus major constituents selected by weight, liquidity, and relative-strength relevance. Duplicate securities are fetched once and may contribute to multiple sector aggregates. Membership is timestamped and cached. OpenD-supported membership is refreshed on a scheduled basis; unsupported or failed refreshes use a still-valid cache. An expired or missing cache disables the affected sector instead of fabricating neutral evidence.

## 5. Discovery Models

The two discovery tracks remain separate. A high score on one track cannot be averaged with a weak score on the other.

### 5.1 Trend Buildup Score

Weights:

- 3/5/10-day relative strength and relative-strength slope: 25%
- Improving constituent breadth: 20%
- Volume accumulation and improving capital evidence: 20%
- Volatility and volume contraction: 15%
- Distance to a valid pivot or breakout level: 10%
- ETF/leader synchronization: 10%

### 5.2 Oversold Reversal Score

Weights:

- Drawdown and oversold location: 15%
- Abnormal volume or turnover climax: 20%
- Failed new low, close-location recovery, or high-volume non-decline: 20%
- Breadth stabilization or breadth/price divergence: 20%
- Major constituents stabilizing before the index or ETF: 15%
- Marginal capital-flow improvement: 10%

### 5.3 Correlation Control

Price, volume, breadth, leaders, and capital evidence are grouped by provenance. A candidate may become `armed` only when at least two independent evidence groups support the setup. Multiple transformations of the same price series do not count as independent confirmation.

## 6. State Machine

States:

- `forming`: either discovery score is at least 55. The candidate appears in the after-close report but is not executable.
- `armed`: either discovery score is at least 65, at least two independent evidence groups support it, data coverage is sufficient, and no hard discovery veto is present.
- `triggered`: during the next session, local five-minute price behavior, sector breadth, and leader behavior confirm the candidate.
- `invalidated`: structural low breaks, breadth deteriorates again, capital divergence becomes material, or the setup expires.
- `expired`: the candidate exceeds its validity window without triggering or improving.

The discovery score is not an entry score. `triggered` is only permission to run the existing deep analysis. The existing strategy assessment remains the sole source of an executable `probe` or `enter` decision.

Validity windows:

- Short, 1-3 day candidates expire after three trading sessions without a trigger.
- Swing, 1-4 week candidates are downgraded or expire after ten trading sessions without improvement.
- A newly qualifying setup after expiry receives a new discovery identifier and evidence window.

## 7. Scheduling and Cross-market Evidence

Each market has its own process, calendar, state, and clock:

- Run a full market-universe discovery scan approximately 15 minutes after the local close.
- Begin next-session confirmation 15 minutes after the local open.
- Refresh only `armed` candidates every five minutes.
- Update state during the middle of the session without rescanning the full universe.
- Recheck invalidation, capital divergence, and overnight risk near the close.

Cross-market evidence is bounded contextual calibration:

- It is considered only after the local discovery score is at least 55.
- It may modestly raise or lower confidence, subject to a configured cap.
- It cannot independently promote a local candidate to `armed` or `triggered`.
- Examples include US semiconductor/AI leadership for the next CN/HK session and yen, Treasury, volatility, or credit stress for high-duration growth assets.

## 8. Data Flow and Caching

OpenD is the primary source for snapshots, completed K-lines, volume, turnover, and capital flow.

To control quota and latency:

1. Backfill 60 or 260 completed daily bars when a security first enters a universe.
2. Store bars in a local rolling cache.
3. Append only the completed local-session bar after each close.
4. Backfill only newly added constituents after membership changes.
5. Fetch all universe snapshots in batches.
6. Fetch capital flow and intraday bars only for promoted candidates.

All local commands must prefer `/Users/shuren/.futu-venv/bin/python`, using the repository's existing interpreter-resolution rules and tests.

## 9. Reporting and Notifications

After-close report limits per market:

- Top five sector opportunities
- At most ten `armed` instruments
- At most five near-upgrade `forming` instruments

When a sector qualifies, report its representative ETF and one to three leaders rather than filling the report with correlated constituents.

Every candidate report includes:

- Market, sector, code, and name
- Discovery track and score
- First-seen and most-recent timestamps
- Independent supporting evidence
- Next-session trigger
- Structural invalidation
- Current state and expiry

Intraday notifications occur only on material transitions:

- `forming -> armed`
- `armed -> triggered`
- `armed/triggered -> invalidated`
- Material score collapse or capital divergence
- First executable `probe` or `enter` result from the existing pipeline

The same state is not notified twice unless it is first cleared and later re-established.

## 10. Data-quality and Failure Rules

- Stale snapshots, incomplete bars, zero-volume future placeholders, or non-updating timestamps cannot upgrade a state.
- Missing capital data is recorded as missing and cannot be converted to a neutral score.
- Sector constituent coverage below 70% caps the sector and its instruments at `forming`.
- A failed membership refresh may use an unexpired cache; an expired cache disables the sector.
- OpenD rate limiting or child-process failure preserves the last known state but emits no market-change notification.
- ETF discovery uses an explicit ETF-to-index-to-constituent mapping. An unsupported ETF owner-plate call must not silently reduce sector evidence to neutral.
- All evidence records carry source timestamps, capture timestamps, session phase, coverage, and confidence.

## 11. Commands

New command surface:

```text
discover --market CN
discover --market HK
discover --market US
confirm-discoveries --market CN
confirm-discoveries --market HK
confirm-discoveries --market US
review-discoveries --market CN|HK|US
```

The commands support JSON output, explicit output paths, offline fixture replay, and a no-notify test mode. Market inference and calendar routing are explicit; a US command always evaluates time in America/New_York.

## 12. Persistence

Each discovery record stores:

- `discovery_id`
- market, code, sector, and representative ETF/index
- track, score, evidence clusters, and feature snapshot
- state and transition history
- first seen, armed, triggered, invalidated, and expired timestamps
- trigger and structural invalidation
- data coverage and provenance
- later 1/3/5/10-day MFE, MAE, and return when reviewed

Discovery reviews are separate from recommendation and trade reviews. They measure alert quality, not trading P&L.

## 13. Tests and Acceptance

### 13.1 Golden STAR 50 Replay

Using only data available through the 2026-07-20 close:

- The STAR 50 setup must be classified as oversold exhaustion and reach at least `armed`.
- Stabilization in major constituents such as SMIC and Cambricon must contribute sector/leader evidence.
- No 2026-07-21 data may be read during the 2026-07-20 calculation.
- The 2026-07-20 result must not be `enter`; it must produce a next-session confirmation plan.
- Only qualifying 2026-07-21 intraday evidence may promote the setup to `triggered` and invoke existing deep analysis.

### 13.2 Negative Fixtures

- High-volume decline closing near the low does not upgrade.
- ETF stabilization with worsening constituent breadth remains at most `forming`.
- One leader rising without breadth does not create a sector opportunity.
- Stale, incomplete, placeholder, or low-coverage data does not upgrade.

### 13.3 Determinism and Regression

- Only completed bars available at the evaluation timestamp are used.
- Identical inputs produce identical candidates, scores, and transitions.
- CN, HK, and US calendars are tested independently, including US daylight-saving transitions.
- Existing watchlist, analysis, strategy, position, and exit tests remain unchanged and pass.
- Missing evidence never improves a result through a default-neutral substitution.

### 13.4 Live Evaluation Metrics

Track by market, sector, track, and horizon:

- Lead time from first `armed` state to trigger
- Trigger rate within the validity window
- False-alert and invalidation rate
- Post-trigger 1/3/5/10-day MFE, MAE, and return
- Sector-level versus instrument-level discovery performance

The first release is accepted when it detects the approved golden setup without look-ahead, rejects the negative fixtures, preserves all existing tests, stays within the report limits, and produces deterministic auditable state transitions. A fixed profitability target is deferred until sufficient real discovery records exist.

## 14. Rollout

Implementation should be incremental:

1. Data contracts, state machine, and offline fixtures
2. CN universe and STAR 50 golden replay
3. CN live after-close discovery and next-session confirmation
4. HK universe and calendar routing
5. US universe, America/New_York scheduling, and daylight-saving tests
6. Cross-market bounded calibration
7. Discovery review metrics and operating documentation

Each phase must keep the existing executable-decision pipeline unchanged until a `triggered` discovery is explicitly handed to it.
