# Stock Dual-Horizon Strategies and Leveraged Overlay Implementation Plan

**Goal:** Produce separate short and swing setup scores, hard-gated entry decisions, and a versioned leveraged-ETF overlay while preserving the legacy total score and action label.

**Design reference:** `docs/superpowers/specs/2026-07-10-stock-strategy-watchlist-upgrade-design.md`

## Scope

This is delivery phase 3. It adds `short-balanced-v1`, `swing-balanced-v1`, and `leveraged-overlay-v1`. It does not simulate OHLC fill order, gaps, costs, partial-fill P&L, or portfolio/theme heat; those remain phase 4.

## Tasks

- [x] Define versioned short and swing factor weights and exit-policy parameters.
- [x] Add horizon-specific `setup_score`, `entry_decision`, `position_decision`, and explicit passed/failed/missing gates.
- [x] Reject entries with insufficient evidence or no structured exit plan; treat missing triggers, weekly alignment, and event data as missing rather than neutral.
- [x] Add the 1–3 day short gates for trend, relative strength, volume, trigger, resistance room, market regime, and liquidity.
- [x] Add the 1–4 week swing gates for daily/weekly alignment, relative strength, trigger, resistance room, event window, market regime, and liquidity.
- [x] Add `leveraged-overlay-v1` with 15% allocation cap, earlier partial targets, tighter trailing stop, and mandatory underlying confirmation.
- [x] Add `--horizon`, `--event-days`, and `--underlying-confirmed` to live/offline analysis; allow short/swing fixture verification.
- [x] Version the additive output as `recommendation-v3` with nested `strategy_assessment`.
- [x] Preserve the legacy `total_score`, component scores, and label thresholds as a frozen baseline.
- [x] Add profile, gate, CLI, and serialization tests.

## Acceptance State

- Short and swing analyses produce different strategy IDs, factor weights, stops, targets, trailing rules, time stops, and maximum holding periods.
- A high legacy score cannot override a failed hard gate.
- Missing critical evidence is visible in `gates_missing` or `gates_failed` and cannot produce `enter`.
- Leveraged ETFs cannot produce `enter` without explicit underlying confirmation.
- Existing-position decisions are separated from entry decisions.
- No real trading capability is introduced.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m tools.stock_skills.cli dry-run --code SZ.002463 --horizon short --output /tmp/short.json
python3 -m tools.stock_skills.cli dry-run --code SZ.002463 --horizon swing --event-days 10 --output /tmp/swing.json
```
