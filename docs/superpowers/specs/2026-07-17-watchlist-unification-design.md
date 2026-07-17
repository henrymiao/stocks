# Unified Watchlist Audit Design

## Goal

Complete the July 2026 watchlist audit by replacing duplicated instrument records with one canonical watchlist, preserving every unique instrument, adding recently requested instruments, and ensuring holdings and sharp decliners are not omitted from deep analysis.

The change remains analysis-only. It must not place, amend, or cancel trades.

## Current-State Findings

The repository currently contains five JSON watchlists with 154 enabled records but only 125 unique security codes. Twenty-four codes occur in more than one file, often with conflicting priorities or incomplete strategy and valuation metadata. The default scanner reads `data/watchlists/core.json`, so instruments that exist only in a thematic file can be omitted. The promotion score also favors positive momentum, which can exclude important holdings or the largest decliners from deep analysis.

## Canonical Data Model

`data/watchlists/core.json` remains the canonical path because the CLI and documentation already use it by default. It will contain exactly one record per security code.

Every canonical entry is normalized to include:

- `code`, `name`, `enabled`;
- `tier` and `priority`;
- `strategy_profiles`;
- `asset_type` and `valuation_profile`;
- `benchmark` and optional `underlying_proxy`;
- `event_policy`;
- `position_status`;
- `scan_policy`;
- deduplicated `tags`.

Allowed position states are:

- `holding`: an active position;
- `reduced-holding`: an active position after a partial reduction;
- `exited-watch`: no current position, but retained for a re-entry decision;
- `watch`: no current position.

Allowed scan policies are:

- `always`: eligible entries receive deep analysis on every requested horizon;
- `ranked`: thematic entries compete for bounded promotion slots;
- `snapshot-only`: context or discovery entries never receive a trade recommendation.

Position quantity, cost basis, and portfolio weight remain outside the watchlist. They belong to portfolio state and are not inferred from watchlist tags.

## Confirmed Position and Focus States

- `HK.09868` XPeng and `SZ.000021` Shenzhen Kaifa Technology are active holdings and use `scan_policy: always`.
- `HK.00700` Tencent and `HK.09988` Alibaba are reduced holdings, retain the `holding` tag, and use `scan_policy: always`.
- `SZ.002463` WUS Printed Circuit and `HK.03690` Meituan are exited watches and remain eligible for re-entry analysis.
- `HK.02513` Zhipu, `HK.07709` CSOP two-times SK Hynix leveraged product, and `SH.563380` aviation and aerospace ETF are added as thematic watches.
- `HK.07709` is explicitly typed as a leveraged ETF and requires underlying confirmation before an actionable entry.
- `SH.563380` receives aerospace, defence, ETF, high-volatility, and oversold-watch tags. A low price or new historical low does not itself create an entry signal.

## Compatibility Views

The four legacy thematic files become view definitions instead of copied instrument lists. A view contains:

- a relative `source` path pointing to `core.json`;
- optional `include_tags_any`, `include_tags_all`, market, tier, or code filters.

`load_watchlist` resolves one view level relative to the view file, loads and validates the canonical list, then applies the declared filters. Views may not reference another view, which prevents cycles and keeps errors explicit. Existing CLI commands that name a legacy watchlist path continue to work.

The compatibility views are:

- A-share broad short screen;
- A-share national technology;
- Hong Kong national technology;
- Hong Kong core/tomorrow focus.

## Merge Rules

The migration starts from all 125 unique existing codes and adds the three confirmed new codes. Duplicate records are merged deterministically:

1. Preserve the canonical Chinese or established display name.
2. Union and deduplicate tags.
3. Use the highest explicit priority.
4. Prefer `core` over `thematic`, `proxy`, and `discovery` only when operator intent or confirmed position state requires it.
5. Union valid strategy profiles.
6. Preserve explicit valuation and asset metadata; reject irreconcilable conflicts instead of silently choosing.
7. Apply the confirmed position and scan-policy overrides above after the mechanical merge.

The canonical file must reject duplicate codes, invalid position states, invalid scan policies, and leveraged ETFs without an explicit underlying proxy.

## Bidirectional Deep-Analysis Selection

The scanner continues to batch-fetch one shared snapshot set. For each requested horizon it selects:

1. every eligible entry with `scan_policy: always`;
2. the existing top `deep_top` ranked thematic entries;
3. up to `deep_bottom` eligible thematic entries with the weakest daily or benchmark-relative performance.

Selection is deduplicated. `snapshot-only` entries and rejected snapshots are never promoted. The result includes the reason for selection (`always`, `top`, or `bottom`) so the output remains auditable.

`deep_bottom` defaults to a small bounded number and can be set to zero. This prevents a weak market from turning the scan into unbounded deep analysis while ensuring large declines are visible before they become late decisions.

## Error Handling

- Missing or invalid source files produce a path-specific error.
- View cycles or view-to-view references are rejected.
- Unknown filters, position states, and scan policies are rejected.
- Invalid or stale snapshots remain rejected before ranking.
- A missing leveraged underlying keeps the instrument non-actionable.
- Migration does not edit portfolio quantities or submit trading requests.

## Testing

Tests are written before production changes and cover:

- loading a canonical entry with position and scan metadata;
- rejecting invalid states and duplicate codes;
- resolving each compatibility view against the canonical source;
- rejecting nested views and malformed filters;
- preserving all expected unique instruments after migration;
- exact metadata for XPeng, Shenzhen Kaifa, Tencent, Alibaba, WUS Printed Circuit, Meituan, Zhipu, HK.07709, and SH.563380;
- selecting always-scan holdings regardless of rank;
- promoting bounded top and bottom thematic candidates without duplicates;
- keeping proxy and snapshot-only entries out of deep analysis;
- the existing full test suite.

## Acceptance Criteria

- `core.json` is the only file containing instrument records.
- The canonical watchlist contains 128 unique enabled codes unless validation identifies an existing disabled record that must remain disabled.
- Legacy watchlist paths still load as filtered views.
- Alibaba and Tencent are represented as reduced but active holdings.
- WUS Printed Circuit and Meituan are represented as exited watches.
- Zhipu, HK.07709, and SH.563380 are present with correct instrument types and policies.
- Holdings and explicitly always-scanned names receive deep analysis independently of Top-N ranking.
- The largest decliners can be selected through a bounded Bottom-N path.
- No trading side effect is introduced.
