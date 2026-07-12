# Stock OHLC Path Backtest and Portfolio Heat Implementation Plan

**Goal:** Replay structured exit plans through chronological OHLC bars with conservative fill ordering, partial exits, trailing/time exits, execution costs, R metrics, and portfolio/theme risk limits.

**Design reference:** `docs/superpowers/specs/2026-07-10-stock-strategy-watchlist-upgrade-design.md`

## Scope

This is delivery phase 4. It adds deterministic long-instrument path simulation for ordinary and inverse/leveraged ETFs (the traded ETF itself remains a long execution). It does not tune strategy thresholds or weights; optimisation remains a later phase.

## Tasks

- [x] Simulate initial stops, TP1/TP2 partial fills, runner trailing stops, time stops, and maximum holding periods.
- [x] Use conservative stop-first ordering when a stop and target occur inside the same OHLC bar.
- [x] Fill gaps through an active stop at the opening price rather than the theoretical stop.
- [x] Keep trailing stops monotonic and update them only from information available after a completed bar.
- [x] Support completed-close profitable add-ons only when the raised stop keeps total open risk at or below the original 1R budget.
- [x] Deduplicate repeated scenarios by stable `trade_id` so daily observations are not counted as independent trades.
- [x] Apply configurable commission, spread, and slippage basis points to entry and exit fills.
- [x] Report expectancy R, profit factor, drawdown R, average win/loss R, MFE/MAE, capture/giveback, holding time, and consecutive losses.
- [x] Add 6% portfolio and 3% correlated-theme heat gates; scale risk to remaining headroom or reject when exhausted.
- [x] Add the offline `path-backtest --scenario ... --output ...` command and serialized scenario validation.
- [x] Preserve the legacy fixed-window `backtest` for frozen-baseline comparison.
- [x] Add path, cost, heat, aggregation, and CLI regression tests.

## Acceptance State

- Same-bar ambiguity is handled conservatively and reproducibly.
- Partial exits contribute position-weighted realised R.
- Gap losses use the observed open.
- Costs always reduce net R relative to gross R.
- Add-ons cannot increase open risk beyond the original plan, and repeated trade ids count once.
- No accepted plan exceeds configured portfolio or theme heat.
- Existing legacy scores, labels, and fixed-window backtests remain unchanged.
- No real trading capability is introduced.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m tools.stock_skills.cli path-backtest --scenario /tmp/path-scenarios.json --output /tmp/path-report.json
```
