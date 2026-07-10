# Stock Strategy and Watchlist Upgrade Design

Date: 2026-07-10
Status: Approved direction; implementation not started

## 1. Purpose

Upgrade the repository-local stock analysis system so it can support a larger watchlist while producing more executable, testable decisions for two holding horizons:

- intraday to 1–3 trading days;
- 1–4 week swing trades.

The preferred exit style is balanced: realise a minority of gains at predefined R-multiples, then let the remaining position run under a trailing stop. The primary optimisation target is risk-adjusted expectancy and profit retention, not headline win rate.

The system remains decision support only. It must not place real orders.

## 2. User Constraints and Risk Policy

- Support ordinary stocks, ETFs, and 3x leveraged ETFs such as SOXL/SOXS.
- Ordinary-instrument risk budget in a risk-on market: 1.5%–2.0% of account equity per trade.
- Leveraged-ETF risk budget: 0.75%–1.25% per trade.
- Maximum total open portfolio risk: 5%–6% of account equity.
- Maximum open risk in one correlated theme or sector: 3%.
- Never average down. Additional entries are allowed only after the position is profitable and a new support structure has formed.
- A wider, structurally correct stop must reduce position size or reject the trade; it must not be replaced by an artificially tight stop merely to preserve position size.

These percentages are initial policy defaults. They are not claims of safety and must remain user-configurable.

Initial maximum allocation caps are 25% of account equity for an ordinary instrument and 15% for a leveraged ETF, even when the calculated stop distance would imply a larger position. Position sizing is:

```text
position_fraction = risk_budget_fraction / stop_distance_fraction
```

followed by the applicable allocation cap and portfolio/theme heat checks.

## 3. Current-State Findings

The current framework has useful foundations: multi-timeframe trend, capital flow, sector breadth, market and macro context, profile-aware fundamentals, ATR sizing, recommendation journaling, and outcome aggregation.

The following issues prevent reliable optimisation of profit-taking:

1. One total score is used to drive entry, hold, trim, and risk-reduction decisions. These are different decisions with different evidence requirements.
2. Recommendations contain a stop and prose guidance but no structured first target, second target, trailing rule, time stop, or position-state transition.
3. The current position logic chooses the tighter of technical invalidation and an ATR stop. This can place the stop inside normal volatility before the thesis is invalidated.
4. Missing inputs often contribute a neutral score of 50 instead of reducing confidence. A recommendation can therefore appear better supported than it is.
5. Confidence is derived directly from total score instead of calibrated against realised outcomes.
6. Review evaluates a fixed future close and MFE/MAE, not the actual path through partial targets, stops, trailing stops, gaps, costs, and time exits.
7. Position-management labels such as `trim-on-strength` are treated as bearish directional calls during backtesting. A partial trim is not equivalent to opening a short position.
8. The journal currently contains recommendation records but no completed `reviews.jsonl`, so automatic weight evolution has no reliable realised sample.
9. The live Futu skill path defaults to a missing Claude installation directory in the current environment, while valid Codex/agents installations exist elsewhere. Live-path discovery must be fixed before expanding automation.
10. The watchlist is editable and snapshot fetching is batch-capable, but the CLI performs deep analysis one code at a time and repeatedly fetches shared index, macro, sector, and financial context.

## 4. Decision Architecture

Replace the single recommendation decision with four explicit outputs.

### 4.1 `setup_score`

Measures whether the instrument has a potentially tradable setup for a specified horizon. Short and swing strategies use separate factor weights.

### 4.2 `entry_decision`

Applies hard gates after scoring. A high setup score cannot override an unacceptable reward-to-risk ratio, missing critical data, poor liquidity, imminent event risk, or a prohibited market regime.

Possible values:

- `enter`
- `watch`
- `reject`
- `existing-position-only`

### 4.3 `position_decision`

Uses cost basis, current open risk, realised partial exits, market regime, correlated portfolio exposure, and current position state.

Possible values:

- `hold`
- `add-on-profit`
- `protect-profit`
- `partial-exit`
- `full-exit`

### 4.4 `exit_plan`

Provides machine-readable prices and rules:

- initial stop;
- risk per share and R definition;
- first and second partial-profit targets and fractions;
- trailing-stop method and activation point;
- time-stop condition;
- maximum holding period;
- gap and event handling.

## 5. Position State Machine

Every recommendation with an open position moves through an explicit state machine:

```text
flat
  -> entered
  -> profit-protected
  -> trend-runner
  -> exited
```

Transitions are event-driven:

- `flat -> entered`: entry trigger fills and all hard gates pass.
- `entered -> profit-protected`: first target fills or the strategy-specific protection threshold is reached.
- `profit-protected -> trend-runner`: second target fills and the remaining position is governed only by the trailing/time exit.
- any open state -> exited: initial stop, trailing stop, time stop, thesis invalidation, or mandatory event exit fires.

An add-on does not create a separate unbounded risk budget. Stops must be raised or size reduced so total trade and portfolio heat remain within policy.

## 6. Strategy Profiles

All numeric thresholds below are versioned initial defaults. They must be tested against a frozen baseline and walk-forward samples before being tuned.

Initial strategy identifiers are `short-balanced-v1` and `swing-balanced-v1`. The leveraged overlay is versioned independently as `leveraged-overlay-v1` so its results can be separated from ordinary instruments.

### 6.1 Intraday / 1–3 Day Profile

Entry gates:

- daily price above a non-falling MA20;
- positive relative strength against the relevant index or sector;
- projected or realised volume at least 1.2x the recent comparable average;
- either a 15/30-minute opening-range breakout or the first controlled pullback to VWAP/EMA9 after a valid breakout;
- at least 1.8R of unobstructed space to the next meaningful resistance, unless price is entering price discovery on confirmed volume;
- no ordinary long entry during a risk-off market state;
- enough intraday liquidity to support the configured slippage assumption.

Exit defaults for ordinary instruments:

| Stage | Rule |
| --- | --- |
| Initial stop | Structural invalidation minus a 0.25 ATR buffer for a long position |
| Partial 1 | Sell 25% at +1.0R |
| Partial 2 | Sell 25% at +1.8R |
| Runner | Trail the remaining 50% at the higher of the prior two-bar low and highest close minus 1.5 ATR |
| Time stop | Exit if the position fails to reach +0.5R within one session, or fails to extend on volume within two sessions |
| Overnight | Allowed only if the setup independently passes the swing qualification gates |

Add-ons are allowed only after at least +0.5R and a new support structure. No losing-position add-ons are permitted.

Projected intraday volume compares elapsed-session volume with the average volume reached at the same elapsed time over comparable recent sessions; it is not a simple full-day volume extrapolation.

### 6.2 1–4 Week Swing Profile

Entry gates:

- daily MA20 above MA50 with MA20 rising;
- weekly trend aligned where sufficient data exists;
- 20-day relative strength or sector breadth demonstrates leadership;
- preferred triggers are a contracting-volume pullback to MA10/MA20 followed by renewed demand, or a volume-confirmed base breakout;
- at least 2.5R of expected upside before major resistance;
- no normal-size new position within five trading days of an unmodelled earnings or major event gap.

Exit defaults:

| Stage | Rule |
| --- | --- |
| Initial stop | Structural invalidation minus a 0.5 ATR buffer for a long position; wide stops reduce size or reject the setup |
| Partial 1 | Sell 20% at +1.5R |
| Partial 2 | Sell 20% at +2.5R |
| Runner | Trail the remaining 60% at the higher of EMA20 and highest close minus 2.5 ATR; a 10-day-low variant may be tested separately |
| Time stop | Exit or reduce if the trade fails to reach +0.5R within five sessions |
| Trend exit | Exit after the configured confirmed MA20/structure failure, not on one isolated intraday breach |

An add-on is allowed only after at least +1R or a new base breakout. The add-on is capped at half the initial planned size and cannot increase total open risk beyond policy.

### 6.3 Leveraged-ETF Overlay

The leveraged overlay modifies either horizon profile:

- risk budget is capped at 0.75%–1.25%;
- first partial occurs at +0.8R to +1.0R and second partial at +1.5R;
- the remaining 50% uses a tighter trailing rule;
- the ETF signal must be confirmed by its underlying index or sector proxy;
- an ETF move without underlying confirmation is rejected;
- multi-week holding requires both daily and weekly underlying-trend alignment;
- volatility decay, gap risk, and higher slippage assumptions are included in backtests;
- inverse ETF backdrop scores are reflected, but the ETF's own trend and liquidity remain primary execution inputs.

For the initial leveraged variant, the trailing stop is the higher of the prior two-bar low and highest close minus 1.2 ATR. Every trailing stop is monotonic: it may move in the trade's favour but never widen after entry.

## 7. Horizon-Specific Scoring

### 7.1 Short Profile, Initial Weights

| Factor | Weight |
| --- | ---: |
| Price/volume trend and trigger quality | 30% |
| Relative strength and sector confirmation | 20% |
| Market regime | 15% |
| Intraday capital flow | 15% |
| Liquidity and event quality | 10% |
| Position fit and reward-to-risk | 10% |

Fundamentals are a risk/catalyst filter for this horizon, not a major continuous score.

### 7.2 Swing Profile, Initial Weights

| Factor | Weight |
| --- | ---: |
| Daily/weekly trend quality | 25% |
| Relative strength and sector breadth | 20% |
| Fundamental growth and business quality | 20% |
| Market and macro regime | 15% |
| Volume/accumulation quality | 10% |
| Position fit and reward-to-risk | 10% |

One-day capital flow cannot dominate a four-week decision. It is supporting evidence unless persistence is measured across several sessions.

## 8. Data Confidence and Hard Gates

Each result records coverage by factor and an aggregate `data_confidence` independent of directional score.

Rules:

- Missing non-critical data lowers confidence and records the fallback.
- Missing critical trigger, price, liquidity, or stop data rejects a new entry.
- A neutral factor is allowed only when a valid, genuinely neutral observation exists. Missing does not mean neutral.
- The output identifies the session phase: pre-open, intraday, after-close, holiday/stale.
- Entry decisions require a minimum confidence threshold configured per strategy.
- Confidence is later calibrated to historical outcome buckets; it is not calculated as `total_score / 100`.

The initial minimum data-confidence threshold is 0.80 for a new entry. Existing-position risk management continues below that threshold, but the output must state which data is missing and may only hold or reduce risk, not add.

## 9. Watchlist Design and Scan Flow

Use four tiers instead of one undifferentiated list:

| Tier | Suggested scale | Default treatment |
| --- | ---: | --- |
| Core holdings / active setups | 25–40 | Full analysis |
| Thematic peers | 40–80 | Batch snapshot, then rank |
| Macro/index/sector proxies | 10–20 | Fetch once and cache per scan |
| Dynamic discovery | 100–300 | Snapshot/filter only until promoted |

Watchlist entries add explicit metadata:

- `tier`
- `priority`
- `strategy_profiles`
- `asset_type`
- `valuation_profile`
- `benchmark`
- `underlying_proxy`
- `event_policy`
- `enabled`
- `tags`

Scan flow:

1. Validate and deduplicate entries.
2. Batch-fetch snapshots in chunks supported by Futu.
3. Compute cheap liquidity, market, and relative-strength filters.
4. Rank candidates separately by strategy profile.
5. Deep-analyse only the configured top N or active holdings.
6. Reuse cached macro, index, sector, and financial context.
7. Write a scan result without automatically creating a trade recommendation for rejected candidates.

## 10. Journal Schema

Every actionable recommendation records at least:

```text
strategy_id
strategy_version
horizon
position_state
entry_decision
position_decision
entry_trigger
entry_price
initial_stop
risk_per_share
risk_budget_pct
tp1_price
tp1_fraction
tp2_price
tp2_fraction
trailing_method
trailing_activation
time_stop
maximum_holding_days
market_regime
data_confidence
component_scores
source_refs
```

Position-management records must link to the original trade id. Repeated daily observations of the same trade are not counted as independent trades.

## 11. Path-Based Backtest

The backtest replays each strategy using chronological OHLC bars and the recorded plan.

Required behaviour:

- simulate initial stop, partial targets, trailing activation, add-ons, and time exits;
- calculate realised position-weighted P&L after each partial fill;
- apply conservative ordering when stop and target are both crossed inside one bar;
- model gaps through stops at the available opening price;
- include configurable commissions, spread, and slippage;
- use larger slippage and gap assumptions for leveraged ETFs;
- keep long-entry, inverse-entry, hold, trim, and exit semantics separate;
- group repeated recommendations by trade id rather than treating them as independent samples.

Primary metrics:

- expectancy in R;
- profit factor;
- maximum drawdown;
- average win and loss in R;
- MFE capture ratio;
- profit giveback ratio;
- average holding time;
- consecutive losses;
- portfolio and theme heat;
- win rate as a secondary metric.

A balanced strategy is allowed to have a moderate win rate if the sample demonstrates a materially larger average win than loss and acceptable drawdown.

## 12. Validation and Weight Evolution

- Preserve the current system as a frozen baseline.
- Compare baseline, exit-only upgrade, dual-horizon upgrade, and leveraged overlay separately.
- Split results chronologically with walk-forward validation; never tune and report on the same period.
- Report ordinary and leveraged instruments separately.
- Require approximately 60 closed trades per strategy bucket before treating a result as directionally useful; require more before making broad automatic changes.
- Do not automatically apply weight changes while the realised review sample is absent or insufficient.
- Replace failure-count weight bumps with regularised optimisation against out-of-sample expectancy and drawdown only after sample thresholds are met.
- Store every strategy version so past trades are evaluated under the rules that existed when they were generated.

## 13. Error and Edge-Case Handling

- Auto-discover the installed Futu skill across supported locations, with an environment override and a clear error listing attempted paths.
- Detect stale or partial-session data and lower confidence or defer the decision.
- Do not convert an intraday setup into an overnight position unless swing gates pass.
- If the opening gap exceeds the planned stop, use the observed fill price in review rather than the theoretical stop.
- Reject invalid or duplicate watchlist codes.
- Reject impossible exit plans, such as targets below entry for a long strategy or fractions that do not sum to at most 100%.
- Cap position size explicitly; a tiny stop distance must never create an oversized allocation.
- When price or event data is unavailable, state the missing dependency rather than inventing a current recommendation.

## 14. Testing Strategy

### Unit tests

- R and target calculation;
- structural stop plus volatility buffer;
- risk sizing and portfolio/theme heat;
- state-machine transitions;
- strategy-specific gates and weights;
- leveraged overlay;
- watchlist validation and deduplication;
- confidence degradation for missing data.

### Path simulation tests

- stop before target;
- target before stop;
- stop and target inside the same bar;
- gap through stop;
- both partials followed by a long runner;
- first partial followed by trailing exit;
- time stop without price progress;
- profitable add-on without increasing risk;
- ordinary and inverse leveraged ETF paths.

### Integration tests

- real-path discovery without relying on a Claude-only location;
- one batch snapshot shared across watchlist candidates;
- shared macro/index context fetched once per scan;
- journal-to-review round trip with stable trade and strategy ids.

### Acceptance criteria

- Every actionable entry has a complete, valid structured exit plan.
- Short and swing recommendations are produced by distinct profiles.
- Missing data reduces confidence and can reject entries.
- Backtests reproduce partial fills, trailing exits, gaps, and costs.
- No recommendation violates per-trade, theme, or portfolio heat limits.
- Baseline and upgraded strategies can be compared on out-of-sample expectancy and drawdown.
- No real trading call is introduced.

## 15. Delivery Phases

1. **Runtime and evidence foundation**: fix skill-path discovery, correct repository-path documentation, add data coverage/confidence, and create real review output.
2. **Structured exit engine**: add R, structural stops, partial targets, trailing rules, time stops, state transitions, and risk caps.
3. **Dual-horizon strategies**: add short and swing profiles plus the leveraged overlay.
4. **Path backtest**: simulate fills, gaps, costs, partials, trailing exits, and portfolio heat.
5. **Watchlist scanner**: add tiered schema, batch scan, shared caches, ranking, and deep-analysis promotion.
6. **Evidence-based optimisation**: after sufficient closed samples, evaluate walk-forward results and only then tune weights or thresholds.

This order deliberately prioritises trustworthy exits and measurement before expanding signal complexity or enabling automatic model evolution.
