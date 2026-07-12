# Stock Structured Exit Engine Implementation Plan

**Goal:** Add a machine-readable exit plan and position-state foundation without changing the existing directional score, label thresholds, or legacy outcome backtest.

**Design reference:** `docs/superpowers/specs/2026-07-10-stock-strategy-watchlist-upgrade-design.md`

## Scope

This is delivery phase 2. It implements structural stops, R-based partial targets, a runner/trailing rule, time-stop metadata, position-state transitions, and per-instrument allocation caps. Dual-horizon entry gates and leveraged confirmation belong to phase 3; OHLC path fills, costs, gaps, and portfolio/theme heat simulation belong to phase 4.

## Tasks

- [x] Add additive, JSON-safe models for exit targets, trailing/time rules, risk sizing, exit plans, and position state while preserving `Recommendation` positional compatibility.
- [x] Build the long execution plan from `structural_invalidation - ATR buffer`; never tighten a structurally valid stop merely to preserve position size.
- [x] Calculate TP1/TP2 from R, preserve a runner fraction, and reject invalid prices, fractions, risk budgets, or missing stop inputs.
- [x] Cap ordinary allocations at 25% and leveraged-ETF allocations at 15%; record uncapped and capped sizes explicitly.
- [x] Make the trailing-stop update monotonic and add the `flat -> entered -> profit-protected -> trend-runner -> exited` state machine.
- [x] Thread `exit_plan`, `position_state`, and `schema_version` through live, offline, fixture, journal, and prose recommendation output.
- [x] Keep the old `analyze_position` and fixed-window backtest as frozen baselines; route new recommendations through structured sizing.
- [x] Add unit and integration coverage and run the complete offline suite.

## Acceptance State

- A valid new recommendation contains a complete `exit_plan` with initial stop, R, TP1, TP2, runner, trailing rule, time stop, maximum holding period, and capped size.
- Missing ATR or structural invalidation makes `position_fit` unavailable and blocks `data_quality.entry_eligible`.
- Inverse ETFs keep long execution geometry; leveraged instruments receive the 15% cap.
- Position states reject illegal jumps and repeated target/exit events are idempotent.
- Existing total-score and action-label thresholds are unchanged.
- No trade or trade-unlock capability is introduced.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m tools.stock_skills.cli dry-run --code SZ.002463 --output /tmp/structured-exit-dry-run.json
python3 -c "import json; p=json.load(open('/tmp/structured-exit-dry-run.json')); print(p['exit_plan'])"
```

