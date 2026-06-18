# Self-Evolving Stock Analysis Skills Design

Date: 2026-06-18
Workspace: `/Users/shuren/WorkSpace/codes/stocks`

## Goal

Build a self-improving skill suite on top of the existing `futuapi` skill to help analyze and rank stocks, current positions, sector opportunities, cross-market signals, macro/geopolitical risk, and future trade review outcomes.

The first version should focus on the user's active watchlist, especially technology, semiconductors, AI hardware, PCB, brokerages, and crypto-related assets. Broader A-share screening, US-China technology-chain mapping, and whole-market discovery should be layered in gradually rather than built as one large system at the start.

The system should improve trend accuracy by making every recommendation auditable:

1. Collect market and position data.
2. Generate structured scores and a recommendation.
3. Record assumptions, key levels, invalidation conditions, and confidence.
4. Revisit the recommendation after fixed review windows.
5. Measure whether the call was useful.
6. Adjust signal weights and rules based on accumulated evidence.

This is an analysis and decision-support system. It must not place real trades automatically.

## Scope

### Version 1

Version 1 should cover:

- Current watchlist analysis for names already tracked in this repository.
- Futu API market data collection: snapshot, K-line, capital flow, capital distribution, sector data, and market state.
- Technical trend scoring: breakout, pullback, volume confirmation, support/resistance, and false-breakout risk.
- Capital-flow interpretation: super-large, large, medium, and small order divergence.
- Macro and geopolitical overlay: Fed rate path, higher-for-longer risk, US tech risk appetite, oil/geopolitical shocks, dollar/yield pressure, and broad risk-on/risk-off state.
- Cross-market linkage: QQQ, SPY, NVDA, SOXX/SOXL/SOXS, MRVL, crypto risk appetite, and their effect on A-share technology and semiconductor names.
- Position-aware advice: adjust output based on current holding status and recent user actions, such as partial trimming at a known price.
- Prediction journal and review: store each recommendation and evaluate it after 1, 3, 5, and 10 trading days.

### Later Versions

Later versions can add:

- Full A-share semiconductor, PCB, AI, brokerage, and crypto-related stock screening.
- More sophisticated factor weights trained from accumulated journal outcomes.
- Portfolio-level risk budgeting and correlation analysis.
- Optional browser or dashboard views.
- Alerts and recurring automations for review windows.

## Non-Goals

- No guaranteed stock recommendation or guaranteed trend accuracy.
- No automatic real-money trading.
- No black-box signal that cannot explain its reasoning.
- No broad market screener in Version 1 unless it directly supports the active watchlist.
- No machine-learning model before enough recommendation history exists.

## Proposed Skill Suite

### `market-data-collector`

Purpose: collect normalized market data from `futuapi`.

Inputs:

- Stock codes, ETF codes, crypto codes, and index proxies.
- Requested timeframes and data types.

Outputs:

- Snapshot data.
- Daily and intraday K-lines.
- Capital flow and capital distribution.
- Market state.
- Sector and constituent data where available.

Notes:

- This skill should reuse the existing `futuapi` scripts instead of reimplementing API calls.
- It should normalize output into JSON files under the workspace so downstream skills do not need to parse terminal text.

### `stock-trend-analyzer`

Purpose: analyze price and volume structure.

Signals:

- Trend direction and slope.
- Breakout and failed breakout detection.
- Support and resistance levels.
- Volume expansion or contraction.
- Intraday recovery or deterioration.
- Gap behavior and high-level consolidation.

Output labels:

- `strong-watch`
- `low-buy-zone`
- `hold`
- `trim-on-strength`
- `risk-reduce`
- `avoid`

### `capital-flow-interpreter`

Purpose: interpret order-size flow patterns.

Examples:

- Super-large inflow with large and medium outflow: possible institutional support, forced churn, or distribution camouflage.
- Broad-based inflow across super-large, large, and medium orders: cleaner trend confirmation.
- Price rise with net outflow: potential chase risk or passive mark-up.
- Price weakness with super-large inflow: possible support test, not automatic buy signal.

This skill should always state whether the capital signal confirms, contradicts, or merely stabilizes the price trend.

### `sector-screener`

Purpose: extend beyond the current watchlist into related sectors.

First-pass sectors:

- A-share PCB and AI hardware.
- A-share semiconductor equipment, materials, and packaging.
- US AI hardware and semiconductor chain.
- Crypto-related equities and assets.
- Brokerages when market volume/risk appetite changes materially.

Version 1 should only use this skill to produce candidates and comparables, not final high-conviction recommendations.

### `cross-market-mapper`

Purpose: map US and global risk signals to the user's watchlist.

Core signals:

- QQQ and SPY trend.
- NVDA and SOXX/SOXL/SOXS trend.
- MRVL and other AI infrastructure peers.
- BTC/ETH and crypto risk appetite.
- USD, US yields, oil, and Fed policy when available.

Example mapping:

- NVDA and SOXX weakening after higher-rate repricing should reduce confidence in A-share AI PCB breakouts.
- BTC/ETH risk-off plus higher yields should reduce confidence in crypto-equity momentum.
- Strong US AI hardware tape can improve confidence in A-share AI hardware leaders, but only if local price and capital-flow signals agree.

### `macro-risk-overlay`

Purpose: convert macro and geopolitical conditions into a compact risk regime.

Regimes:

- `risk-on`: growth-friendly, liquidity supportive, or yields easing.
- `neutral`: no decisive macro signal.
- `risk-off`: rate pressure, geopolitical shock, oil/inflation shock, dollar/yield pressure, or sharp US tech selloff.

This skill should not make standalone buy/sell calls. It adjusts position sizing and confidence.

### `position-advisor`

Purpose: combine signal quality with the user's actual trading context.

Inputs:

- Current holding status, if available.
- User-stated actions, such as partial sell, add, trim, or cost basis.
- Score outputs from other skills.

Outputs:

- Suggested action band, not a forced command.
- Add zone, trim zone, invalidation level, and observation trigger.
- Position sizing language: core hold, trading position, partial trim, wait, or risk-reduce.

Safety:

- Never place real trades automatically.
- Require explicit user confirmation for any real order, following the existing `futuapi` trading rules.

### `prediction-journal`

Purpose: record every recommendation so the system can learn.

Each entry should include:

- Timestamp.
- Instrument code and name.
- Current price.
- Recommendation label.
- Scores by component.
- Key support and resistance.
- Expected path.
- Invalidation condition.
- Suggested review windows.
- Source data snapshot references.
- User context, such as prior partial trim price.

Suggested storage:

- `data/journal/recommendations.jsonl`
- `data/journal/reviews.jsonl`

### `self-review-evaluator`

Purpose: review old recommendations and improve future calls.

Review windows:

- 1 trading day.
- 3 trading days.
- 5 trading days.
- 10 trading days.

Metrics:

- Directional hit rate.
- Maximum favorable excursion.
- Maximum adverse excursion.
- Whether support/resistance levels worked.
- Whether the invalidation condition triggered.
- Whether the recommendation was useful for position management.
- Common failure pattern classification.

The evaluator should update a lightweight weights file, such as:

- `data/models/signal_weights.json`

Any weight adjustment must be explainable and reversible.

## Scoring Model

Initial score:

```text
total_score = trend_score * 0.25
            + capital_flow_score * 0.20
            + sector_score * 0.15
            + cross_market_score * 0.15
            + macro_risk_score * 0.15
            + position_fit_score * 0.10
```

Initial output mapping:

```text
>= 80: strong-watch
70-79: low-buy-zone or hold, depending on price location
60-69: hold or wait
45-59: trim-on-strength or neutral-watch
30-44: risk-reduce
< 30: avoid
```

The mapping should consider price location. A high-quality stock near extended resistance should not be labeled as a simple buy.

## Data Flow

1. User asks for analysis, recommendation, or review.
2. `market-data-collector` fetches fresh data through `futuapi`.
3. `stock-trend-analyzer`, `capital-flow-interpreter`, `cross-market-mapper`, and `macro-risk-overlay` produce component scores.
4. `position-advisor` combines scores with user context.
5. The assistant presents a concise action-oriented analysis.
6. `prediction-journal` records the recommendation.
7. `self-review-evaluator` reviews outcomes after the scheduled windows.
8. Signal weights and pattern notes are updated with clear evidence.

## File Layout

Suggested future layout:

```text
skills/
  market-data-collector/
  stock-trend-analyzer/
  capital-flow-interpreter/
  sector-screener/
  cross-market-mapper/
  macro-risk-overlay/
  position-advisor/
  prediction-journal/
  self-review-evaluator/

data/
  watchlists/
    core.json
  snapshots/
  journal/
    recommendations.jsonl
    reviews.jsonl
  models/
    signal_weights.json
```

If implemented inside this repository, the initial scripts should live under:

```text
tools/stock_skills/
```

The actual Codex skill folders should live under `$CODEX_HOME/skills` or another user-approved skill directory when ready to install.

## Watchlist Seed

Seed the first watchlist from existing repository folders and recent conversation context:

- `SZ.002463` 沪电股份
- `SZ.002938` 鹏鼎控股
- `SH.600584` 长电科技
- `US.MRVL` Marvell
- `US.GOOGL` or `US.GOOG` Alphabet
- `US.CRCL` Circle
- `US.SOXL`
- `US.SOXS`
- `US.NVDA`
- `US.QQQ`
- `US.SPY`
- `CC.BTC`
- `CC.ETH`

This list should be editable by the user.

## Error Handling

- If Futu OpenD is unavailable, report that fresh data cannot be fetched and avoid pretending current prices are known.
- If capital flow data is unavailable, continue with price/volume analysis and mark the capital score as missing.
- If macro data is stale or unavailable, use a neutral macro score and state the limitation.
- If a stock code is ambiguous, ask for clarification before analysis.
- If review data is insufficient, do not adjust weights.

## Testing and Validation

Version 1 should be validated with:

- Script-level tests for score calculation and output mapping.
- Fixture-based tests for common scenarios:
  - clean breakout with volume confirmation.
  - false breakout near resistance.
  - super-large inflow but broad order outflow.
  - macro risk-off overlay lowering confidence.
  - position-aware advice after partial trim.
- Dry-run journal entries that do not require live trading.
- Manual comparison against existing markdown reports in this repository.

## Safety and Compliance

- Always present outputs as analysis, not guaranteed investment advice.
- Real-money trading requires explicit user confirmation.
- Do not call `unlock_trade`.
- Do not automatically submit real orders from recommendations.
- Maintain clear separation between analysis, simulated orders, and real orders.
- Keep every recommendation explainable and reviewable.

## Open Questions

Resolved:

- First version focuses on current watchlist, biased toward technology, semiconductors, and crypto.
- A-share sector screening, US-China technology-chain mapping, and whole-market discovery are secondary layers.
- Macro and geopolitical factors should adjust confidence and sizing, not replace price/volume evidence.

Remaining for implementation planning:

- Exact watchlist file format.
- Whether to install these as separate Codex skills or keep scripts first and wrap them as skills later.
- Whether review should be manual on demand or automated with recurring jobs.
- Which macro data sources should be considered authoritative for rates, yields, oil, dollar, and geopolitical risk.
