# Tiered Watchlist Scanner Implementation Plan

**Goal:** Deliver Phase 5 of the stock strategy upgrade: a validated tiered watchlist, one shared batch snapshot, strategy-specific promotion rankings, and bounded deep analysis.

**Design source:** `docs/superpowers/specs/2026-07-10-stock-strategy-watchlist-upgrade-design.md`

## Task 1: Watchlist schema and validation

- Add normalized defaults for `tier`, `priority`, `strategy_profiles`, `asset_type`, `valuation_profile`, `benchmark`, `underlying_proxy`, and `event_policy`.
- Preserve compatibility with existing entries that only contain code, name, tags, and enabled.
- Reject invalid codes, duplicate enabled codes, unsupported tiers/profiles, and invalid priorities.
- Add focused configuration tests before changing the production loader.

## Task 2: Batch filter and promotion engine

- Fetch candidates, benchmarks, underlying proxies, and macro proxies in one batch operation (chunking remains the fetcher's responsibility).
- Compute cheap liquidity, daily momentum, and benchmark-relative-strength promotion scores.
- Rank thematic candidates separately for short and swing profiles.
- Keep proxy and discovery entries snapshot-only.
- Promote all eligible core entries plus only the configured top N thematic entries.
- Never attach a trade recommendation to rejected or snapshot-only rows.

## Task 3: Shared context and safe deep analysis

- Serialize the batch snapshot as an ephemeral per-scan context.
- Let deep analysis reuse shared cross-market, market-index, and macro snapshots, fetching only genuinely missing codes.
- Use a unique temporary directory and checked subprocess results; never reuse deterministic `/tmp/scan_CODE.json` files.
- Surface per-name deep-analysis failures as deferred/error records without aborting the whole scan.

## Task 4: Core watchlist migration

- Remove duplicate enabled codes while merging useful tags into the retained entry.
- Add a watchlist schema version and explicit tier metadata where operator intent matters, especially holdings, active setups, proxies, and discovery entries.
- Preserve every unique instrument.

## Task 5: Documentation and verification

- Document the tier model, scanner flags, ranking semantics, and the distinction between promotion and trade decisions.
- Add unit and integration tests for one shared batch, ranking separation, deep-analysis bounds, rejection handling, and shared-context reuse.
- Run the full test suite and whitespace validation.

## Acceptance checks

- Duplicate enabled codes fail validation.
- A scan calls the batch snapshot interface once for the complete scan context.
- Core names and only Top N thematic names receive deep analysis.
- Short and swing rankings are separate.
- Missing/illiquid candidates are rejected without a recommendation.
- Deep analysis reuses cached macro/index context and does not consume stale temp output.
- No real trading call, journal append, staging, or commit is introduced.
