---
name: backtest-evidence-hygiene
description: "Journal evidence rules: 5d realized win_rate ~57% but expectancy slightly negative (right often, wrong big); leveraged-ETF reverse splits create basis-mismatch rows; only trust realized-ohlc evidence"
metadata: 
  node_type: memory
  type: project
  originSessionId: d5010ffd-636f-48ca-b6d4-05178ed91ed8
---

State of the recommendation-journal evidence as of 2026-07-18 (first full catch-up run):

- 81 realized 5d reviews: win_rate ~0.57, direction-aware expectancy ~-1.1%/call, avg win +6.2% vs avg loss -10.8%. Pattern: **right often, wrong big** — the calls' 5-day directional edge is thin and the left tail is fat, which is exactly what the structured exit engine must truncate in execution. Notable miss cluster: SH.600584 risk-reduce calls kept rising (wr 0.17, n=6).
- Component-edge sample sizes are n=7–40 per bucket — treat edges as dashboard, not conclusions. Nothing shows clear positive edge yet; sector bullish calls actually underperformed (edge -0.41 at n=10).
- **Basis-mismatch trap**: leveraged ETFs reverse-split routinely (US.SOXS did ~1:10 between June calls and July fetch), so an old entry_price against later-fetched adjusted bars fabricates +400–900% returns. `review` now flags first-bar/entry ratio outside (0.5, 2.0) as `evidence_kind: basis-mismatch`; backtest excludes those rows plus `synthetic` (md-* backfill) rows from realized stats and reports them separately.
- ~24 of 69 journal recommendations are markdown-imported with heuristic entry prices — their realized reviews carry entry noise; evidence-optimize already excludes them.
- The 60-closed-trades-per-bucket gate for weight optimization is years away at current call volume. Near-term feedback = backtest by_label/by_code tables, not weight tuning. Keep review running per [[daily-review-protocol]].
- **HK fake-neutral bias (fixed 2026-07-18)**: market.py `_MARKET_WEIGHTS` lacked HK.800000/800700 until 2026-07-18, so every HK.* journal recommendation before that date scored market_regime=50 regardless of the actual HK tape. When reading component_edge for market_regime (and backdrop-blended scores) on HK rows, treat pre-fix rows as biased-neutral, not observed.
