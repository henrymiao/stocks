---
name: stock-analysis
description: Use when analyzing stocks, watchlists, technology/semiconductor/AI hardware/crypto-linked names, current holdings, trend quality, capital flow, macro risk, cross-market signals, recommendation journals, or post-trade reviews in this repository.
---

# Stock Analysis

## Overview

Use this skill for repository-local stock analysis workflows built around `tools/stock_skills`. It provides a disciplined analyst/trader framework with separate `short-balanced-v1` and `swing-balanced-v1` setup decisions:

- analyst frame: investment hypothesis, sector strength, market regime, valuation, macro risk, cross-market linkage.
- trader frame: trend status, support/resistance, structural invalidation, action label, structured R-based exits, and capped risk-sized position.
- review frame: recommendation journaling, outcome review, and explainable signal-weight suggestions.

Analysis is **logic first, data verification second**. Before interpreting a move, state a causal up/down hypothesis and its strongest rival: catalyst or expectation change → earnings/cash-flow or risk-premium transmission → sector/stock impact. Mark each link as observed fact, supported inference, or unknown. Price action is evidence for or against that hypothesis; it is not itself the cause. If no reliable catalyst is available, say that the direction is observed but the cause is unconfirmed instead of back-fitting a story.

Analysis is multi-layer: the same-day move is judged against the instrument's **multi-timeframe trend** (MA10/20/50 alignment — a breakout that fires against a falling MA20<MA50 is demoted as a likely false breakout, one aligned with an uptrend is rewarded), its **sector** (peer breadth and relative strength) and the broad **market regime** (index trend), not in isolation — a breakout without trend/sector resonance or against a falling market earns less confidence. **Valuation** is profile-aware: a growth name (AI/semiconductor/PCB) tolerates a far higher PE than a value name, and a high PE is only "expensive" if growth (PEG) does not justify it; when growth/margin/ROE inputs are supplied, a **business-quality** sub-score lifts or lowers the read beyond the raw multiple. **Position sizing** is risk-based: the initial stop sits beyond structural invalidation by a configurable ATR buffer; a wider stop reduces size rather than being tightened artificially. Ordinary allocations are capped at 25% and leveraged ETFs at 15%. Every valid new plan records TP1, TP2, a runner/trailing rule, and a time stop in `exit_plan`. The total score weighs eight components: trend, capital_flow, sector, cross_market, macro_risk, market_regime, fundamental, position_fit. The three backdrop components (cross_market, macro_risk, market_regime) read the same risk-on/off tape, so the engine **de-duplicates** them: it blends them into one backdrop score and shrinks its deviation from neutral (`backdrop_blend`), so an agreeing broad tape counts roughly once, not three times. Whether each component actually earns its weight is measurable with `backtest` (win rate, expectancy, per-component edge).

The legacy total score remains for historical comparison. The authoritative setup score uses **correlation-aware evidence clusters**: `thesis`, `market_behavior`, `environment`, and `risk_fit`. Price/volume, relative strength, and capital flow are normalized inside `market_behavior` and count once, not as three independent confirmations. Require support from at least two independent clusters for `enter` or `add`; one strong cluster can justify only `watch` or a capped `probe`.

Recommendations also carry a shadow `method_assessment` under schema `recommendation-v6` and decision policy `logic-first-method-evidence-v6`. This market-specific sidecar records swing stage, a structured pre-technical thesis, explicit valuation scenarios, rolling linkage, provenance conflicts, coverage, and restrictions. In Phase 1, positive method evidence adds zero points to `setup_score`: it explains and calibrates only. Negative evidence may preserve or downgrade the existing decision, never upgrade it.

A **v7 shadow foundation** exists alongside this, and it is foundation only: point-in-time security identity, versioned universe membership, and immutable input packages. It defines no v7 score, recommendation, or routing — `recommendation-v6` under `logic-first-method-evidence-v6` remains the only authoritative decision path. Its purpose is that a champion and a challenger consume one frozen input package (same `package_id`, same `input_digest`), so a comparison between them can never be contaminated by two different fetches. Run `foundation-check` after editing any universe or identity file.

This skill supports analysis and decision support only. It must not place real trades.

## Repository Paths

Treat the current workspace root as the repository root. Do not assume a user-specific absolute path.

Core files:

- `tools/stock_skills/`: Python analysis package.
- `data/watchlists/core.json`: canonical editable watchlist; the other JSON files in that directory are compatibility views filtered from this source.
- `data/models/signal_weights.json`: initial signal weights.
- `docs/self-evolving-stock-skills-usage.md`: usage notes.
- `tests/`: unit tests.

## Quick Commands

Run all offline tests:

```bash
python3 -m unittest discover -s tests -v
```

Analyze a real instrument via Futu OpenD (snapshot + daily K-line + capital flow + sector strength + market regime + macro proxies + valuation):

```bash
python3 -m tools.stock_skills.cli analyze --code SZ.002463 --output /tmp/hudian-recommendation.json
```

By default `analyze` also fetches the instrument's core sector (peer constituents, for relative strength), a market-aware index backdrop (`US.*` → `US.QQQ`/`US.SPY`, `SH.*`/`SZ.*` → `SH.000001`/`SZ.399006`, `HK.*` → `HK.800000`/`HK.800700`), live macro proxy ETFs (VIXY/TLT/UUP/USO/GLD plus FXY yen and HYG/LQD credit stress), and valuation (PE-TTM/PB/EPS/dividend). US watchlist names tagged as AI, semiconductor, growth, crypto, or stablecoin also get default cross-market references such as QQQ/SPY/NVDA/SMH or BTC/ETH. Direct short analysis defaults to 30 daily bars; watchlist short deep analysis preserves its 60-bar default; swing analysis defaults to 260 bars so the 200-day structure is valid. An explicit `--bars N` overrides any of these defaults. Optional flags include `--horizon short|swing`, `--event-days N` (known major-event distance; required to clear the swing event gate), `--method-inputs-json` (validated explicit official/manual thesis, valuation, and evidence assumptions), `--underlying-confirmed/--no-underlying-confirmed` (mandatory leveraged-ETF underlying confirmation), `--portfolio-open-risk-pct N` and `--theme-open-risk-pct N` (6% portfolio / 3% theme heat gates), `--cross ...`, `--indices ...`, `--sector-limit N`, `--macro-codes ...`, `--macro-json ...`, growth/quality flags, `--profile ...`, `--risk-budget-pct N`, `--stop-buffer-atr N`, `--cost-basis`, `--trade-id`, skip flags, and `--weights`. Existing-position analysis with `--cost-basis` requires the original `--trade-id`, which is copied into `position_state`. The trader plan includes the horizon-specific structured exit and a separate `strategy_assessment` with setup score and hard gates.

A **defensive overlay** (`defensive-overlay-v1`) routes low-volatility value names off the momentum gates. `relative-strength` asks a staple to outrun a benchmark a semiconductor sets and `volume-confirmation` asks for a volume spike from a name that trades an even book every day — both are failures by construction, not evidence, and on the US watchlist they meant banks, staples and energy were never scored at all. The overlay drops those two gates (and the same two conditions on the probe path) and moves 0.15 of cluster weight from `market_behavior` to `thesis`; everything about whether the trade works is kept, so a cheap stock in a confirmed downtrend is still refused. Routing comes from the watchlist's own `valuation_profile: value` or a `defensive`/`staple`/`dividend` tag; `--defensive`/`--no-defensive` overrides it.

Pass `--portfolio data/portfolio/positions.json` to fill the two heat gates from the positions book instead of by hand. Both gates were hand-passed parameters with no data source, so nobody passed them and `portfolio-heat` was missing on every recommendation ever journaled — which made `enter` **structurally unreachable**, since it requires zero missing gates. The book stores shares, cost, currency, theme, and the current stop per position plus cash, and heat is recomputed from live prices on every call: open risk is weight-times-loss-to-stop against **NAV including cash**, never against equity value alone. An explicit `--portfolio-open-risk-pct`/`--theme-open-risk-pct` still wins; an incomplete book (any missing price or stop) leaves the gates unset rather than reporting an understated number. `--theme NAME` maps a candidate that is not yet in the book onto an existing theme bucket.

`--method-inputs-json` also accepts a `decline` section that classifies **why** a security fell before its price is read as evidence of a bottom: `cause` is one of `liquidity`, `bounded-event`, `valuation-reset`, `structural-impairment`, `unconfirmed`, plus `bear_case_loss_pct` (null when the downside cannot be bounded), `selling_exhaustion`, and mandatory `as_of`/`source_ref`. A drawdown is not a discount — the same −30% is a recoverable flush, a bounded one-off, a permanent repricing, or a broken business, and only the first two have a "low" at all. `structural-impairment` rejects new risk at every horizon regardless of price; an `unconfirmed` cause, an unbounded bear case, or selling that has not exhausted each cap the result at a probe. Like the rest of the method sidecar it can only preserve or downgrade, never upgrade, and it is opt-in: an absent classification means unassessed, never safe.

`--method-inputs-json` supplements company, event, or valuation assumptions only. Each evidence record must use `source: "official-manual"` with `as_of` and `source_ref`. It cannot replace OpenD `last_price`, volume, turnover, or capital flow; a material conflict is journaled and rejects new risk until resolved.

Back-test past calls into win rate, expectancy, and per-component edge (offline; reads the journals, run `review` first to populate outcomes):

```bash
python3 -m tools.stock_skills.cli backtest --recommendations data/journal/recommendations.jsonl --reviews data/journal/reviews.jsonl --output /tmp/backtest.json
```

`backtest` reports overall win rate / expectancy / payoff / average MFE/MAE, the same split by label and by code, and a `component_edge` section: for each factor it compares the win rate when that factor was bullish (score ≥55) versus bearish (≤45). A positive `edge` means a high score for that factor genuinely preceded better outcomes — evidence the weight is earned; a negative edge flags a factor that is not pulling its weight. Expectancy and win/loss P&L are direction-aware (a `risk-reduce`/`avoid` call profits when price falls).

Replay structured exits through chronological OHLC paths:

```bash
python3 -m tools.stock_skills.cli path-backtest --scenario /tmp/path-scenarios.json --output /tmp/path-report.json
```

`path-backtest` is distinct from the frozen fixed-window baseline: it applies partial fills, conservative same-bar ordering, gap-through-stop fills, monotonic trailing stops, time exits, optional completed-close add-ons, and configurable execution costs, then reports R-based expectancy, profit factor, drawdown, capture/giveback, and holding metrics. Each serialized add-on supplies `trigger_r`, `fraction`, and `stop_after_add`; the simulator rejects it unless the raised stop keeps total open risk at or below the original 1R budget.

Scan the canonical tiered watchlist with one shared batch snapshot. Always-scan holdings, top-ranked thematic leaders, and bounded thematic decliners receive deep analysis:

```bash
python3 tools/stock_skills/scan_watchlist.py \
  --watchlist data/watchlists/core.json \
  --horizon both --deep-top 10 --deep-bottom 5 \
  --output /tmp/watchlist-scan.json
```

`--deep-per-theme N` guarantees each theme reaches the gates on its own best-ranked names. Momentum ranking is not a neutral filter: a bank or a staple moving 0.2% a day can never place in a Top-N or Bottom-N by daily change, so whole sectors are never scored — and that silence reads as "nothing there qualifies" when nothing there was tested. Themes come from an explicit `theme` field or the first tag that names a business rather than a market or a position state.

The four tiers are `core`, `thematic`, `proxy`, and `discovery`. `position_status` distinguishes active, reduced, exited, and watch-only names; `scan_policy` controls always/ranked/snapshot-only treatment. The loader validates the canonical source and resolves one-level compatibility views without copying instrument records. The scanner ranks thematic candidates separately for short and swing profiles using cheap liquidity, daily momentum, and benchmark-relative-strength evidence, while `--deep-bottom` prevents the largest declines from disappearing behind a momentum-only Top N. Selection reasons are recorded as `always`, `top`, or `bottom`. These scores are promotion scores only, never trade recommendations. Proxy/discovery and rejected rows remain snapshot-only. `--snapshot-only` performs no deep analysis, shared macro/index snapshots are reused, and deep analysis uses `--no-journal`.

Discover forming opportunities across a whole market universe, before any name reaches the watchlist:

```bash
python3 -m tools.stock_skills.cli discover --market CN --horizon swing --output /tmp/discovery.json
python3 -m tools.stock_skills.cli confirm-discoveries --market CN --output /tmp/confirm.json
python3 -m tools.stock_skills.cli review-discoveries --market CN --output /tmp/discovery-review.json
```

`discover` scans the market universe (`data/universes/{cn,hk,us}.json`, versioned membership built from exchange industry plates by `universe_expand.py` and ranked by turnover — 210 CN / 210 HK / 280 US members) for sector-led setups and records each candidate in the SQLite store `data/discovery.db` under schema `opportunity-discovery-v1`. Candidates move through an explicit state machine — `forming` → `armed` → `triggered`, or `invalidated` / `expired` — and every transition is appended to an audit table. **A discovery is an alert, never an entry recommendation**: promotion requires at least two supporting evidence groups plus sector coverage, and an armed candidate still has to clear the ordinary `analyze` gates before any risk is taken. Features are computed from **completed bars only**, so a forming score never reads a partial session. Short candidates stay valid 3 sessions and swing candidates 10 before expiring. Notifications fire only on material transitions (a new arming, or a fall to invalidated/expired) and are de-duplicated in the store; `--no-notify` suppresses them.

`confirm-discoveries` re-checks armed candidates intraday against the latest **completed five-minute bar**, rejecting evidence older than 10 minutes so a frozen feed cannot confirm a trigger, and optionally runs deep analysis on the confirmed names (`--no-deep-analysis` skips it).

`review-discoveries` measures **alert quality, deliberately separate from trade P&L**: for each triggered candidate it reports MFE/MAE/return over fixed 1/3/5/10-session windows measured from `trigger_level`, and returns `null` for any window that has not fully elapsed. These reviews live in the discovery store, not in `reviews.jsonl`, and are not inputs to legacy component or cluster weight optimisation.

Shared flags: `--market CN|HK|US` (required), `--horizon short|swing` (discover; default short), `--backfill 60|260`, `--universe`, `--membership-cache`, `--db` (default `data/discovery.db`), `--market-db`, `--as-of`, `--output`. `--fixture` runs the whole pipeline deterministically offline with no OpenD, which is how the discovery tests exercise it.

Validate the v7 point-in-time foundation (offline, read-only, no fetch/score/store write):

```bash
python3 -m tools.stock_skills.cli foundation-check \
  --identity-registry data/identities/securities-v1.json \
  --universe data/universes/cn.json --universe data/universes/hk.json --universe data/universes/us.json \
  --as-of 2026-08-03T18:00:00+08:00
```

It checks active membership, investability, reference-only benchmarks, publication cutoffs, cross-file version agreement, and identity links, and exits non-zero when any market is not `ready`. Every universe/identity edit changes a content-addressed digest, so the three universe files and the registry must be re-migrated together via `foundation_migrate.py` — never hand-edit one side.

Turn a rejection into a waiting price with `entry_zone.py`:

```python
from tools.stock_skills.entry_zone import entry_zone_from_recommendation
zone = entry_zone_from_recommendation(recommendation_payload)   # any analyze/scan output
zone.entry_ceiling   # highest price at which resistance-room passes
zone.distance_pct    # how far that sits below the current price
zone.actionable      # True only when price is the ONLY thing blocking it
```

`resistance-room` is the one gate that is a function of price, so it is the one gate that can be
solved: `P <= (resistance + m*stop) / (1 + m)` where `m` is the horizon's `minimum_resistance_r`
(1.8 short / 2.5 swing). The result answers "at what price would this be buyable" instead of only
"not now" — a rejection at 1% away and one at 30% away otherwise look identical. Gates that price
cannot fix (trend regime, volume, market regime, weekly alignment) are returned separately in
`non_price_gates`, and `actionable` is False whenever any remain: **a price alert is never a licence
to skip the other gates**. A name with no overhead resistance yields no zone — it needs a confirmed
breakout, not a pullback.

To populate the journals immediately from the repo's existing 复盘 notes (so `backtest` has data without waiting for live calls), run the backfill importer:

```bash
python3 -m tools.stock_skills.import_reviews   # parse notes → recommendations.jsonl + offline-synthesised reviews.jsonl
```

It self-synthesises review outcomes by using each code's later-dated note prices as the realised future price; entry/label parses are best-effort (flagged in `source_refs`), and the live `review` can refine them with true OHLC later.

Replay the frozen `SZ.002463` fixture offline (pipeline check only, no OpenD):

```bash
python3 -m tools.stock_skills.cli dry-run --code SZ.002463 --output /tmp/fixture-check.json
```

`dry-run` rejects any code other than `SZ.002463`: it is a fixed sample for verifying the scoring pipeline, not analysis of the given code. Use `analyze` for real instruments.

Review past recommendations to accumulate realised evidence:

```bash
# Suggest only — writes reviews, prints proposed weights, does NOT change weights:
python3 -m tools.stock_skills.cli review --window 3d

# Legacy --apply is retained for compatibility but is deliberately ineligible:
python3 -m tools.stock_skills.cli review --window 5d --apply
```

`review` reads `data/journal/recommendations.jsonl` (written by `analyze`), fetches each call's later daily bars via OpenD, and scores 1/3/5/10/20-day outcomes into `data/journal/reviews.jsonl`. Method stage, thesis state, valuation status, linkage coverage, and restrictions are retained as shadow calibration dimensions; they do not enter legacy component or cluster weight optimisation. The old failure-count weight bump is frozen; `--apply` cannot write weights through this legacy path.

Build the advisory evidence-optimisation report offline:

```bash
python3 -m tools.stock_skills.cli evidence-optimize --output /tmp/evidence-optimization.json
```

The report excludes synthetic/incomplete outcomes, deduplicates by `trade_id`, separates strategy versions and ordinary/leveraged instruments, and requires 60 unique realised closed trades per exact bucket. Candidate weights are selected only on chronological training windows and compared with the frozen baseline only on later test windows using expectancy and drawdown. The command has no apply mode and never changes weights.

Read any analysis in plain Chinese instead of raw JSON:

```bash
python3 -m tools.stock_skills.cli analyze --code US.GOOGL --horizon core --portfolio data/portfolio/positions.json --explain --output /tmp/googl.json
python3 -m tools.stock_skills.cli explain --input /tmp/googl.json --portfolio data/portfolio/positions.json
```

`explain` re-presents a record, it never re-analyses one, so it cannot disagree with the JSON it renders. It separates the three fields that are easiest to confuse — `label` and `position_decision` answer what to do with a position already held, `entry_decision` answers only whether new risk may be opened — splits failed gates into the one a lower price can fix (`resistance-room`) and the ones it cannot, and closes with the three-to-five levels actually worth watching. `docs/术语.md` defines every term once.

Inspect a label:

```bash
python3 -c "import json; p=json.load(open('/tmp/hudian-recommendation.json')); print(p['label'], p['total_score'])"
```

## Workflow

1. Load the user's intent, holdings, horizon, leverage, and relevant stock codes.
2. Before examining confirming price data, write the primary bullish/bearish causal chain, its strongest alternative explanation, and a falsifier. Prefer catalysts that precede the move; never infer a cause solely because price rose or fell.
3. Confirm the user's **holding horizon and leverage** before framing risk. Use `--horizon short` for intraday to 1–3 days, `--horizon swing` for 1–4 weeks, and **`--horizon core` for multi-quarter thesis holdings** (`core-thesis-v1`). Running a core holding as `swing` is a category error that vetoes every add while the thesis is intact: on 2026-07-31 GOOGL scored a base `watch`, then `swing-stage-3` downgraded it to `reject` — a one-to-four-week distribution rule applied to a position held for the business. The core track weights `thesis` at 0.50, **skips the tactical timing gates** (trend-regime, relative-strength, volume-confirmation, entry-trigger, resistance-room) in both the gate list and the probe path, and keeps every structural guard (exit plan, liquidity, portfolio heat, position cap, event window, source conflicts). Its time stop is a 120-session thesis review, not a 2-day tactical stop. When a position mixes horizons, split it explicitly rather than applying one tactical plan to everything.
4. For a real-instrument analysis with current data, run `analyze` (it calls `futuapi` through `futu_fetcher.py`; OpenD must be running). Use the result to validate, weaken, or reject the prior hypothesis.
5. For code review, pipeline verification, or framework work, use `dry-run` or the unit tests — these do not require OpenD.
6. Use `tools.stock_skills` modules to keep reasoning structured:
   - `trend.py`: breakout, failed breakout, support/resistance, invalidation, plus an MA10/20/50 multi-timeframe overlay (`trend_regime`) that demotes counter-trend breakouts and rewards trend-aligned ones.
   - `capital.py`: order-size flow confirmation/divergence (denoised — uses the full-day cumulative flow plus the intraday direction, not a single mid-session reading).
   - `sector.py`: sector strength from peer constituents (median move, breadth) and the instrument's relative strength (leading / in-line / lagging / sector-weak).
   - `market.py`: market regime from market-aware broad indices (A-share: 上证 SH.000001 / 创业板 SZ.399006; US: QQQ/SPY; HK: 恒指 HK.800000 / 恒生科技 HK.800700) → risk-on / neutral / risk-off. `analyze_market(..., profile=...)` re-mixes each market's broad vs growth index by the instrument's valuation profile while **preserving that market's total weight**, so a rotation (growth index down hard, broad index flat) no longer vetoes the value names that are winning it. The tilt changes the mix only — a genuine broad selloff still reads risk-off for every profile.
   - `portfolio.py`: the book-level layer the per-instrument gates cannot see. `theme_exposure` aggregates holdings by theme; `worst_correlation` finds the holding a candidate most duplicates; `rank_candidates` discounts each candidate's evidence by that correlation (capped at 60% — duplication demotes, never vetoes) and reports the binding constraint; `allocate_budget` then walks the ranked list top-down spending the **shared** open-risk budget, funding the tail partially rather than dropping it. A position of weight W% whose stop sits R% below entry consumes W*R/100 percentage points of heat — weight and heat are different units and must never be compared directly.
   - `entry_zone.py`: solves the resistance-room gate for the entry price that would clear it, so a blocked candidate produces a waiting price instead of a bare "no". Non-price gates are reported separately and keep `actionable` False.
   - `macro.py`: macro risk from live proxy ETFs (VIXY fear, TLT yields, UUP dollar, USO oil, GLD gold, FXY yen, and HYG/LQD credit transmission) via `analyze_macro_from_proxies`; simultaneous yen appreciation plus fear or credit deterioration receives a carry-unwind penalty. `analyze_macro_risk` accepts `jgb_stress`, `yen_carry_stress`, and `credit_stress` manual overrides in addition to the original macro inputs. Raw JP10Y/JP30Y/JP40Y, USDJPY, MOVE, MOF overseas-security flows, and Treasury TIC are confirmation evidence when available externally; do not silently treat a missing raw feed as a neutral observation, and never use `US.MOVE` because Futu resolves it to an unrelated listed equity. Plus `analyze_cross_market` for the US/global tape.
   - `fundamental.py`: profile-aware valuation (growth/value/neutral) from PE-TTM/PB/EPS/dividend, with PEG when EPS growth is supplied, plus a business-quality sub-score from revenue growth / gross margin / net margin / ROE (strong quality can lift an otherwise "expensive" multiple to "fair"). Profile is inferred from watchlist tags. The quality inputs are auto-fetched: `analyze` calls `futu_fetcher.get_financials` (latest income statement → revenue/EPS YoY, gross/net margin) and derives ROE from PB/PE; the `--revenue-growth/--gross-margin/--net-margin/--eps-growth/--roe` flags override per-field, and `--no-financials` skips the statement fetch (valuation multiples only). The latest revenue breakdown (主营构成) is added to `source_refs`.
   - `method_models.py`: immutable method-evidence contracts, coverage/confidence, source conflicts, and restrictions serialized in every v6 recommendation.
   - `market_profiles.py`: A-share, HK, and US market structure/valuation routing without hidden live assumptions.
   - `swing_structure.py`: completed-bar Stage 1–4 template, pivot/contraction evidence, and buy-zone geometry. Stage 3/4 reject new swing risk; they are not automatic sell signals for an existing position. A late, contracting Stage 1 near its pivot is probe-only when all existing swing probe gates also pass.
   - `linkage.py`: rolling 20/60-day correlation, beta, downside correlation, stability, and confirming/diverging reference behavior.
   - `valuation_scenarios.py`: explicit bear/base/bull earnings-multiple, SOTP, and DCF cases with sensitivity and no fabricated defaults.
   - `thesis.py`: observed drivers first, bull/base/bear conditional paths, rival hypothesis, unresolved fields, and evaluated invalidations. Only an invalidation evaluated against observed evidence can reject new swing risk; it is not an automatic existing-position sell.
   - `method_policy.py`: Phase-1 monotonic adapter. Positive method evidence cannot add score or upgrade an action; conflicts, Stage 3/4, evaluated thesis invalidation, or critical valuation disagreement can only restrict new entries/additions.
   - `exit_engine.py`: structured exit-plan builder and position-state transitions. Initial stop = structural invalidation minus the ATR buffer; TP1/TP2 are defined in R; the runner uses a monotonic trailing rule; ordinary/leveraged allocations are capped at 25%/15%. Invalid stop inputs produce no executable `exit_plan` and make `position_fit` unavailable.
   - `strategy.py`: versioned short/swing correlation clusters, horizon-specific hard gates, exit-policy selection, and `leveraged-overlay-v1`. The current `logic-first-method-evidence-v6` policy aggregates correlated factors once before weighting independent evidence clusters, then permits the method sidecar to preserve or downgrade the result. Missing critical evidence cannot be converted into an entry.
   - `path_backtest.py`: chronological OHLC execution simulator, costs, R metrics, aggregation, and portfolio/theme heat checks. It is offline-only and never calls trade APIs.
   - `evidence_optimization.py`: versioned evidence joins, synthetic/incomplete exclusion, trade-id deduplication, ordinary/leveraged buckets, and advisory chronological walk-forward evaluation.
   - `watchlist_scan.py`: tier-aware snapshot filters, separate short/swing promotion rankings, and bounded always/Top-N/Bottom-N deep-analysis selection. The command wrapper is `scan_watchlist.py`.
   - `universe.py`: market universes and sector membership (manually versioned), market timezones, and code normalization — the input to discovery. Schema v2 adds `security_id`, membership windows, publication cutoffs, and a content-addressed `version_id`.
   - `markets.py`: the single CN/HK/US prefix, timezone, currency, and session-close contract. `bar_close_moment` encodes that an OpenD bar is stamped with its interval **start**, so a bar counts as observed only once its interval has elapsed.
   - `identity.py`: point-in-time `SecurityIdentity` (listing) versus `company_id` (economic issuer, so A/H listings never read as independent diversification), activity windows, and the content-addressed registry. A reissued listing code is legal only as non-overlapping closed windows.
   - `point_in_time.py`: `EvidenceStamp` four-state evidence (available/missing/stale/conflicting), the immutable `PointInTimeInput` package with explicit adjustment basis and no-lookahead cutoffs, and `bind_shadow_pair` champion/challenger bindings.
   - `foundation_validation.py` / `foundation_migrate.py`: read-only cross-file validation behind `foundation-check`, and the deterministic v1→v2 + registry migration.
   - `discovery_features.py`: completed-bar feature tracks and sector context used to score a candidate; it never reads a partial session.
   - `discovery_engine.py`: candidate construction, the `forming`/`armed`/`triggered`/`invalidated`/`expired` state machine with session-based expiry, intraday confirmation against completed five-minute bars, and `review_discovery` fixed-window alert scoring. Discovery output is an alert queue, not a recommendation.
   - `discovery_runtime.py`: live wiring (universe → OpenD bars → engine) plus deterministic offline fixture loading.
   - `discovery_store.py`: SQLite persistence for candidates, transitions, notification de-duplication, and discovery reviews.
   - `position.py`: ATR (`compute_atr`) plus structured-plan position description (`analyze_structured_position`). The old `analyze_position` remains only to preserve the frozen `position_fit` component score for baseline comparisons; its stop and sizing are not used as execution guidance by new live/offline recommendations.
   - `engine.py`: total score, action label, analyst hypothesis, trader plan. `backdrop_blend` de-duplicates the three correlated backdrop factors so an agreeing tape is not triple-counted.
   - `backtest.py`: offline aggregation of `reviews.jsonl` into win rate, expectancy, MFE/MAE, label/code breakdowns, and per-component predictive edge. Driven by the `backtest` command.
   - `journal.py`: JSONL recommendation records. `analyze` appends to `data/journal/recommendations.jsonl` by default (`--no-journal` to skip).
   - `review.py`: outcome generation and failure attribution. Its legacy failure-count weight mutation is frozen; optimisation is handled by the advisory walk-forward report.
   - `futu_fetcher.py`: wrapper around `futuapi` scripts. Fetches snapshot, daily K-line, capital flow, and historical K-line for review (quote-only — it must never call trade scripts).
7. Present output in this order: directional logic and rival hypothesis; data verdict by independent cluster; decision/trigger/invalidation/allocation. State which components fell back to the neutral default (see `source_refs`).
8. **Always state the data timestamp and session phase** (pre-open / intraday / after-close) with the conclusion. Neutral-50 fallbacks are not merely cosmetic — during pre-open or a holiday the capital/sector feeds go blank and the label can flip (an instrument scored `hold` on full closing data has re-scored `trim-on-strength` pre-open on the same fundamentals). For a 复盘 of a finished day, prefer completed-session data; treat any intraday or pre-open label as provisional and re-confirm after the close.

## Action Labels

Use the package's labels consistently:

- `strong-watch`
- `low-buy-zone`
- `hold`
- `trim-on-strength`
- `risk-reduce`
- `avoid`

Do not translate these labels inside JSON outputs. Chinese prose may explain them.

## Live Data Boundary

OpenD through quote-only `futu_fetcher.py` is the only live and historical market-data source used by this analysis framework. Explicit official/manual method inputs are assumptions, never substitutes for live trigger data. OpenD is not needed for:

- unit tests.
- fixture dry-runs.
- code review.
- journal/review logic checks.
- editing watchlists or weights.

When live data is needed, prefer using the existing `futuapi` skill and scripts. Avoid claiming current prices are known unless fresh data was fetched successfully.

`FutuFetcher` resolves `futuapi` in this order when `FUTUAPI_SKILL_DIR` is not set: `~/.codex/skills/futuapi`, `~/.agents/skills/futuapi`, then `~/.claude/skills/futuapi`. If none contains `scripts/quote/get_snapshot.py`, live analysis stops with an error listing every attempted location.

Every new recommendation includes `data_quality`: available, missing, and stale components; session phase; evidence confidence; and whether the evidence is sufficient for a new entry. Live and offline snapshots preserve both Futu's market `update_time` and the local capture time; stale intraday/partial-close price evidence marks `trend` stale and blocks entry. Missing data still leaves the directional component neutral for backward-compatible scoring, but it lowers evidence confidence and is never presented as observed neutrality.

## Safety

- Do not place real orders from this skill.
- Real trading must follow the `futuapi` explicit confirmation flow.
- Do not call `unlock_trade`.
- Treat recommendations as decision support, not investment guarantees.
- Record invalidation levels and review windows when giving actionable analysis.
