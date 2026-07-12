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

Analysis is multi-layer: the same-day move is judged against the instrument's **multi-timeframe trend** (MA10/20/50 alignment — a breakout that fires against a falling MA20<MA50 is demoted as a likely false breakout, one aligned with an uptrend is rewarded), its **sector** (peer breadth and relative strength) and the broad **market regime** (index trend), not in isolation — a breakout without trend/sector resonance or against a falling market earns less confidence. **Valuation** is profile-aware: a growth name (AI/semiconductor/PCB) tolerates a far higher PE than a value name, and a high PE is only "expensive" if growth (PEG) does not justify it; when growth/margin/ROE inputs are supplied, a **business-quality** sub-score lifts or lowers the read beyond the raw multiple. **Position sizing** is risk-based: the initial stop sits beyond structural invalidation by a configurable ATR buffer; a wider stop reduces size rather than being tightened artificially. Ordinary allocations are capped at 25% and leveraged ETFs at 15%. Every valid new plan records TP1, TP2, a runner/trailing rule, and a time stop in `exit_plan`. The total score weighs eight components: trend, capital_flow, sector, cross_market, macro_risk, market_regime, fundamental, position_fit. The three backdrop components (cross_market, macro_risk, market_regime) read the same risk-on/off tape, so the engine **de-duplicates** them: it blends them into one backdrop score and shrinks its deviation from neutral (`backdrop_blend`), so an agreeing broad tape counts roughly once, not three times. Whether each component actually earns its weight is measurable with `backtest` (win rate, expectancy, per-component edge).

This skill supports analysis and decision support only. It must not place real trades.

## Repository Paths

Treat the current workspace root as the repository root. Do not assume a user-specific absolute path.

Core files:

- `tools/stock_skills/`: Python analysis package.
- `data/watchlists/core.json`: editable core watchlist.
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

By default `analyze` also fetches the instrument's core sector (peer constituents, for relative strength), a market-aware index backdrop (`US.*` → `US.QQQ`/`US.SPY`, `SH.*`/`SZ.*` → `SH.000001`/`SZ.399006`, `HK.*` → `HK.800000`/`HK.800700`), live macro proxy ETFs (VIXY/TLT/UUP/USO/GLD plus FXY yen and HYG/LQD credit stress), and valuation (PE-TTM/PB/EPS/dividend). US watchlist names tagged as AI, semiconductor, growth, crypto, or stablecoin also get default cross-market references such as QQQ/SPY/NVDA/SMH or BTC/ETH. Optional flags: `--horizon short|swing` (default short), `--event-days N` (known major-event distance; required to clear the swing event gate), `--underlying-confirmed/--no-underlying-confirmed` (mandatory leveraged-ETF underlying confirmation), `--portfolio-open-risk-pct N` and `--theme-open-risk-pct N` (6% portfolio / 3% theme heat gates), `--bars N`, `--cross ...`, `--indices ...`, `--sector-limit N`, `--macro-codes ...`, `--macro-json ...`, growth/quality flags, `--profile ...`, `--risk-budget-pct N`, `--stop-buffer-atr N`, `--cost-basis`, `--trade-id`, skip flags, and `--weights`. Existing-position analysis with `--cost-basis` requires the original `--trade-id`, which is copied into `position_state`. The trader plan includes the horizon-specific structured exit and a separate `strategy_assessment` with setup score and hard gates.

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

Scan the tiered watchlist with one shared batch snapshot, then deeply analyze only core and promoted thematic names:

```bash
python3 tools/stock_skills/scan_watchlist.py --horizon short --deep-top 10 --output /tmp/watchlist-scan.json
```

The four tiers are `core`, `thematic`, `proxy`, and `discovery`. The loader fills compatible defaults for older entries but rejects duplicate enabled codes and invalid metadata. The scanner ranks thematic candidates separately for short and swing profiles using cheap liquidity, daily momentum, and benchmark-relative-strength evidence. These scores are promotion scores only, never trade recommendations. Proxy/discovery and rejected rows remain snapshot-only; core plus Top N thematic rows receive the normal strategy analysis. `--horizon both` runs both deep profiles, while `--snapshot-only` performs no deep analysis. Shared macro/index snapshots are reused across promoted names, temporary outputs are unique to the scan, and deep analysis uses `--no-journal`.

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

`review` reads `data/journal/recommendations.jsonl` (written by `analyze`), fetches each call's later daily bars via OpenD, and scores 1/3/5/10-day outcomes into `data/journal/reviews.jsonl`. The old failure-count weight bump is frozen; `--apply` cannot write weights through this legacy path.

Build the advisory evidence-optimisation report offline:

```bash
python3 -m tools.stock_skills.cli evidence-optimize --output /tmp/evidence-optimization.json
```

The report excludes synthetic/incomplete outcomes, deduplicates by `trade_id`, separates strategy versions and ordinary/leveraged instruments, and requires 60 unique realised closed trades per exact bucket. Candidate weights are selected only on chronological training windows and compared with the frozen baseline only on later test windows using expectancy and drawdown. The command has no apply mode and never changes weights.

Inspect a label:

```bash
python3 -c "import json; p=json.load(open('/tmp/hudian-recommendation.json')); print(p['label'], p['total_score'])"
```

## Workflow

1. Load the user's intent and relevant stock codes.
2. Confirm the user's **holding horizon and leverage** before framing risk. Use `--horizon short` for intraday to 1–3 days and `--horizon swing` for 1–4 weeks. Thesis-based multi-quarter core holdings remain outside both tactical profiles and need a separate fundamental exit framework. When a position mixes horizons, split it explicitly rather than applying one tactical plan to everything.
3. For a real-instrument analysis with current data, run `analyze` (it calls `futuapi` through `futu_fetcher.py`; OpenD must be running).
4. For code review, pipeline verification, or framework work, use `dry-run` or the unit tests — these do not require OpenD.
5. Use `tools.stock_skills` modules to keep reasoning structured:
   - `trend.py`: breakout, failed breakout, support/resistance, invalidation, plus an MA10/20/50 multi-timeframe overlay (`trend_regime`) that demotes counter-trend breakouts and rewards trend-aligned ones.
   - `capital.py`: order-size flow confirmation/divergence (denoised — uses the full-day cumulative flow plus the intraday direction, not a single mid-session reading).
   - `sector.py`: sector strength from peer constituents (median move, breadth) and the instrument's relative strength (leading / in-line / lagging / sector-weak).
   - `market.py`: market regime from market-aware broad indices (A-share: 上证 SH.000001 / 创业板 SZ.399006; US: QQQ/SPY; HK: 恒指 HK.800000 / 恒生科技 HK.800700) → risk-on / neutral / risk-off.
   - `macro.py`: macro risk from live proxy ETFs (VIXY fear, TLT yields, UUP dollar, USO oil, GLD gold, FXY yen, and HYG/LQD credit transmission) via `analyze_macro_from_proxies`; simultaneous yen appreciation plus fear or credit deterioration receives a carry-unwind penalty. `analyze_macro_risk` accepts `jgb_stress`, `yen_carry_stress`, and `credit_stress` manual overrides in addition to the original macro inputs. Raw JP10Y/JP30Y/JP40Y, USDJPY, MOVE, MOF overseas-security flows, and Treasury TIC are confirmation evidence when available externally; do not silently treat a missing raw feed as a neutral observation, and never use `US.MOVE` because Futu resolves it to an unrelated listed equity. Plus `analyze_cross_market` for the US/global tape.
   - `fundamental.py`: profile-aware valuation (growth/value/neutral) from PE-TTM/PB/EPS/dividend, with PEG when EPS growth is supplied, plus a business-quality sub-score from revenue growth / gross margin / net margin / ROE (strong quality can lift an otherwise "expensive" multiple to "fair"). Profile is inferred from watchlist tags. The quality inputs are auto-fetched: `analyze` calls `futu_fetcher.get_financials` (latest income statement → revenue/EPS YoY, gross/net margin) and derives ROE from PB/PE; the `--revenue-growth/--gross-margin/--net-margin/--eps-growth/--roe` flags override per-field, and `--no-financials` skips the statement fetch (valuation multiples only). The latest revenue breakdown (主营构成) is added to `source_refs`.
   - `exit_engine.py`: structured exit-plan builder and position-state transitions. Initial stop = structural invalidation minus the ATR buffer; TP1/TP2 are defined in R; the runner uses a monotonic trailing rule; ordinary/leveraged allocations are capped at 25%/15%. Invalid stop inputs produce no executable `exit_plan` and make `position_fit` unavailable.
   - `strategy.py`: versioned short/swing factor weights, horizon-specific hard gates, exit-policy selection, and `leveraged-overlay-v1`. Missing critical evidence cannot be converted into an entry.
   - `path_backtest.py`: chronological OHLC execution simulator, costs, R metrics, aggregation, and portfolio/theme heat checks. It is offline-only and never calls trade APIs.
   - `evidence_optimization.py`: versioned evidence joins, synthetic/incomplete exclusion, trade-id deduplication, ordinary/leveraged buckets, and advisory chronological walk-forward evaluation.
   - `watchlist_scan.py`: tier-aware snapshot filters, separate short/swing promotion rankings, and bounded core/Top-N deep-analysis selection. The command wrapper is `scan_watchlist.py`.
   - `position.py`: ATR (`compute_atr`) plus structured-plan position description (`analyze_structured_position`). The old `analyze_position` remains only to preserve the frozen `position_fit` component score for baseline comparisons; its stop and sizing are not used as execution guidance by new live/offline recommendations.
   - `engine.py`: total score, action label, analyst hypothesis, trader plan. `backdrop_blend` de-duplicates the three correlated backdrop factors so an agreeing tape is not triple-counted.
   - `backtest.py`: offline aggregation of `reviews.jsonl` into win rate, expectancy, MFE/MAE, label/code breakdowns, and per-component predictive edge. Driven by the `backtest` command.
   - `journal.py`: JSONL recommendation records. `analyze` appends to `data/journal/recommendations.jsonl` by default (`--no-journal` to skip).
   - `review.py`: outcome generation and failure attribution. Its legacy failure-count weight mutation is frozen; optimisation is handled by the advisory walk-forward report.
   - `futu_fetcher.py`: wrapper around `futuapi` scripts. Fetches snapshot, daily K-line, capital flow, and historical K-line for review (quote-only — it must never call trade scripts).
6. Present output as analysis with clear uncertainty and invalidation conditions. State which components fell back to the neutral default (see `source_refs`).
7. **Always state the data timestamp and session phase** (pre-open / intraday / after-close) with the conclusion. Neutral-50 fallbacks are not merely cosmetic — during pre-open or a holiday the capital/sector feeds go blank and the label can flip (an instrument scored `hold` on full closing data has re-scored `trim-on-strength` pre-open on the same fundamentals). For a 复盘 of a finished day, prefer completed-session data; treat any intraday or pre-open label as provisional and re-confirm after the close.

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

OpenD is only needed for live Futu data collection through `futu_fetcher.py` or direct `futuapi` scripts. It is not needed for:

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
