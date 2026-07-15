# Stock Opportunity and Probe Mode Implementation Plan

**Goal:** Preserve hard risk controls while allowing small, falsifiable opportunity probes before every confirmation gate has cleared.

## Decision policy

- `reject`: stale/unreliable evidence, no executable stop, inadequate liquidity, exhausted portfolio heat, unmodelled major event, or unconfirmed leveraged underlying.
- `watch`: evidence is incomplete and leadership/capital/price-volume quality is not strong enough for a probe.
- `probe`: no hard veto; setup, relative strength, capital, price-volume, and risk geometry support a small test position.
- `enter`: all confirmation gates pass with a setup score of at least 65.
- `add`: an existing probe receives full confirmation without increasing total planned risk.
- `hold-probe`: an existing probe remains valid but confirmation is still incomplete.

## Risk policy

- Ordinary probe: lesser of 25% of the normal risk-sized position or 5% of account value.
- Leveraged probe: lesser of 20% of the normal risk-sized position or 3% of account value.
- Missing portfolio heat is allowed only for a capped probe, never a full entry.
- Explicitly exhausted portfolio/theme heat remains a hard veto.

## New-listing and event fallback

When live-session daily history is insufficient, use a provisional opening-range structure:

- Structural invalidation: live session low.
- Volatility estimate: maximum of opening range, 35% of the opening gap, or 1% of price.
- Trigger: price above the open and in the upper 40% of the live range.
- Maximum decision: `probe` until normal trend evidence exists.

## Completed changes

- [x] Added `probe_eligible` data-quality state.
- [x] Split hard vetoes from confirmation gates.
- [x] Added `probe` decision and capped allocation output.
- [x] Added opening-range fallback for new listings/event dislocations.
- [x] Added `position_stage=probe` support for `add` and `hold-probe` decisions.
- [x] Updated output schema to `recommendation-v5`.
- [x] Updated the installed `stock-analysis-framework` skill and UI prompt.
- [x] Added SKHY-style new-listing and decision-policy tests.

## Verification

- Skill validation: `Skill is valid!`
- Full suite: 244 tests passed.
- Live SKHY forward check: `probe` under `opportunity-layered-v2`, with allocation reduced to one quarter of the normal risk-sized amount.

