# Evidence-Based Optimisation Implementation Plan

**Goal:** Deliver Phase 6 without premature automation: preserve historical strategy versions, evaluate non-overlapping chronological windows, and refuse weight changes when any exact strategy/instrument bucket lacks sufficient realised evidence.

**Design source:** `docs/superpowers/specs/2026-07-10-stock-strategy-watchlist-upgrade-design.md`

## Task 1: Stable evidence identity

- Add top-level `strategy_id`, `strategy_version`, `horizon`, `trade_id`, and `leveraged` fields to new recommendations.
- Carry the same fields into realised reviews.
- Accept an existing `trade_id` for position-management records; otherwise generate a deterministic id.
- Preserve compatibility with legacy recommendation records.

## Task 2: Evidence eligibility

- Join recommendation/review records by code and source timestamp.
- Require complete realised-OHLC reviews.
- Exclude markdown-derived, imported, and synthetic outcomes from optimisation.
- Deduplicate repeated observations by `trade_id`.
- Keep legacy baseline, structured-exit, dual-horizon, and leveraged-overlay phases identifiable.

## Task 3: Strategy buckets and walk-forward evaluation

- Separate every exact strategy id into ordinary and leveraged buckets.
- Require at least 60 unique closed trades per bucket before directional interpretation.
- Use expanding chronological training windows with strictly later, non-overlapping test windows.
- Select small regularised candidate perturbations on training data only.
- Report candidate and frozen-baseline out-of-sample expectancy and maximum drawdown.
- Treat a candidate as eligible only when out-of-sample expectancy improves without unacceptable drawdown deterioration.

## Task 4: Freeze unsafe legacy mutation

- Disable the former failure-count `+0.02` weight bump.
- Keep `review` useful for generating realised outcomes, but make its legacy suggestion non-applicable.
- Provide a separate `evidence-optimize` command that only writes an advisory report.
- Do not provide an apply flag or mutate the weights file.

## Task 5: Verification

- Test insufficient samples, strategy/leveraged separation, synthetic exclusion, trade deduplication, and chronological folds.
- Run the report against the repository journals and record the actual eligibility result.
- Run the full offline suite, syntax checks, and whitespace validation.

## Acceptance checks

- No training row appears in its fold's out-of-sample window.
- No synthetic or incomplete review can count toward the 60-trade threshold.
- Ordinary and leveraged instruments never share an optimisation bucket.
- Legacy records remain reportable but cannot silently inherit a newer strategy version.
- Neither `review --apply` nor `evidence-optimize` changes weights under the new flow.
