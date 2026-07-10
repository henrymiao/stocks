---
name: stock-analysis
description: Use when analyzing stocks, watchlists, technology/semiconductor/AI hardware/crypto-linked names, current holdings, trend quality, capital flow, macro risk, cross-market signals, recommendation journals, or post-trade reviews in this repository.
---

# Stock Analysis

## Overview

Use this skill for repository-local stock analysis workflows built around `tools/stock_skills`. It provides a disciplined analyst/trader framework:

- analyst frame: investment hypothesis, sector strength, market regime, valuation, macro risk, cross-market linkage.
- trader frame: trend status, support/resistance, invalidation level, action label, ATR-based stop, and risk-sized position.
- review frame: recommendation journaling, outcome review, and explainable signal-weight suggestions.

Analysis is multi-layer: the same-day move is judged against the instrument's **multi-timeframe trend** (MA10/20/50 alignment — a breakout that fires against a falling MA20<MA50 is demoted as a likely false breakout, one aligned with an uptrend is rewarded), its **sector** (peer breadth and relative strength) and the broad **market regime** (index trend), not in isolation — a breakout without trend/sector resonance or against a falling market earns less confidence. **Valuation** is profile-aware: a growth name (AI/semiconductor/PCB) tolerates a far higher PE than a value name, and a high PE is only "expensive" if growth (PEG) does not justify it; when growth/margin/ROE inputs are supplied, a **business-quality** sub-score lifts or lowers the read beyond the raw multiple. **Position sizing** is risk-based: the stop is the tighter of the technical invalidation and an ATR volatility stop, and the suggested size spends a fixed account-risk budget over that stop distance (wider stop → smaller position). The total score weighs eight components: trend, capital_flow, sector, cross_market, macro_risk, market_regime, fundamental, position_fit. The three backdrop components (cross_market, macro_risk, market_regime) read the same risk-on/off tape, so the engine **de-duplicates** them: it blends them into one backdrop score and shrinks its deviation from neutral (`backdrop_blend`), so an agreeing broad tape counts roughly once, not three times. Whether each component actually earns its weight is measurable with `backtest` (win rate, expectancy, per-component edge).

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

By default `analyze` also fetches the instrument's core sector (peer constituents, for relative strength), a market-aware index backdrop (`US.*` → `US.QQQ`/`US.SPY`, `SH.*`/`SZ.*` → `SH.000001`/`SZ.399006`, `HK.*` → `HK.800000`/`HK.800700`), live macro proxy ETFs (VIXY/TLT/UUP/USO/GLD), and valuation (PE-TTM/PB/EPS/dividend). US watchlist names tagged as AI, semiconductor, growth, crypto, or stablecoin also get default cross-market references such as QQQ/SPY/NVDA/SMH or BTC/ETH. Optional flags: `--bars N` (daily bars, default 30; ≥50 enables the MA20/MA50 trend regime), `--cross US.QQQ US.NVDA` (override cross-market references), `--indices ...` (override index codes), `--sector-limit N` (peer sample size, default 30), `--macro-codes ...` (override macro proxies), `--macro-json '{"fed_bias":"hike"}'` (hand-typed macro override), `--eps-growth 40` (YoY EPS growth %% → enables PEG), `--revenue-growth / --gross-margin / --net-margin / --roe` (business-quality inputs, percent → feed the quality sub-score; **auto-fetched from the latest income statement by default**, these flags override per-field), `--no-financials` (skip the statement fetch → valuation multiples only), `--profile growth|value|neutral` (override valuation profile; default inferred from watchlist tags), `--risk-budget-pct 1.0` (account %% to risk per trade), `--atr-multiple 2.0` (volatility-stop width), `--cost-basis 140` (report open P&L), `--no-sector` / `--no-market` / `--no-macro` / `--no-fundamental` (skip those fetches), `--last-trim-price 149.5` (position context), `--weights data/models/signal_weights.json`. Components without a data feed score a neutral 50 and are flagged in `source_refs`. The trader plan includes a concrete stop price and suggested position size as %% of account.

Back-test past calls into win rate, expectancy, and per-component edge (offline; reads the journals, run `review` first to populate outcomes):

```bash
python3 -m tools.stock_skills.cli backtest --recommendations data/journal/recommendations.jsonl --reviews data/journal/reviews.jsonl --output /tmp/backtest.json
```

`backtest` reports overall win rate / expectancy / payoff / average MFE/MAE, the same split by label and by code, and a `component_edge` section: for each factor it compares the win rate when that factor was bullish (score ≥55) versus bearish (≤45). A positive `edge` means a high score for that factor genuinely preceded better outcomes — evidence the weight is earned; a negative edge flags a factor that is not pulling its weight. Expectancy and win/loss P&L are direction-aware (a `risk-reduce`/`avoid` call profits when price falls).

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

Review past recommendations and (optionally) evolve the weights:

```bash
# Suggest only — writes reviews, prints proposed weights, does NOT change weights:
python3 -m tools.stock_skills.cli review --window 3d

# Apply — writes weights back, creating a .bak backup and a weight_history.jsonl entry:
python3 -m tools.stock_skills.cli review --window 5d --apply
```

`review` reads `data/journal/recommendations.jsonl` (written by `analyze`), fetches each call's later daily bars via OpenD, scores 1/3/5/10-day outcomes into `data/journal/reviews.jsonl`, then suggests signal-weight changes. Weights only change with `--apply`, and every applied change is reversible (`signal_weights.json.bak`) and explainable (`weight_history.jsonl`).

Weight changes require at least 60 realised review rows. `--apply` below that threshold records no weight change and creates no backup; this prevents the system from adapting to a handful of correlated outcomes.

Inspect a label:

```bash
python3 -c "import json; p=json.load(open('/tmp/hudian-recommendation.json')); print(p['label'], p['total_score'])"
```

## Workflow

1. Load the user's intent and relevant stock codes.
2. Confirm the user's **holding horizon and leverage** before framing risk. The trader plan's tight stop (invalidation/ATR) is a short-term / leveraged construct; an unleveraged mid-term holder should be given thesis-based exits (quarterly fundamentals) plus a wide structural backstop instead. When a position mixes both, split it explicitly (mid-term core with wide stop + short-term sleeve with tight stop) rather than applying one stop to everything.
3. For a real-instrument analysis with current data, run `analyze` (it calls `futuapi` through `futu_fetcher.py`; OpenD must be running).
4. For code review, pipeline verification, or framework work, use `dry-run` or the unit tests — these do not require OpenD.
5. Use `tools.stock_skills` modules to keep reasoning structured:
   - `trend.py`: breakout, failed breakout, support/resistance, invalidation, plus an MA10/20/50 multi-timeframe overlay (`trend_regime`) that demotes counter-trend breakouts and rewards trend-aligned ones.
   - `capital.py`: order-size flow confirmation/divergence (denoised — uses the full-day cumulative flow plus the intraday direction, not a single mid-session reading).
   - `sector.py`: sector strength from peer constituents (median move, breadth) and the instrument's relative strength (leading / in-line / lagging / sector-weak).
   - `market.py`: market regime from market-aware broad indices (A-share: 上证 SH.000001 / 创业板 SZ.399006; US: QQQ/SPY; HK: 恒指 HK.800000 / 恒生科技 HK.800700) → risk-on / neutral / risk-off.
   - `macro.py`: macro risk from live proxy ETFs (VIXY fear, TLT yields, UUP dollar, USO oil, GLD gold) via `analyze_macro_from_proxies`; `analyze_macro_risk` still accepts hand-typed overrides. Plus `analyze_cross_market` for the US/global tape.
   - `fundamental.py`: profile-aware valuation (growth/value/neutral) from PE-TTM/PB/EPS/dividend, with PEG when EPS growth is supplied, plus a business-quality sub-score from revenue growth / gross margin / net margin / ROE (strong quality can lift an otherwise "expensive" multiple to "fair"). Profile is inferred from watchlist tags. The quality inputs are auto-fetched: `analyze` calls `futu_fetcher.get_financials` (latest income statement → revenue/EPS YoY, gross/net margin) and derives ROE from PB/PE; the `--revenue-growth/--gross-margin/--net-margin/--eps-growth/--roe` flags override per-field, and `--no-financials` skips the statement fetch (valuation multiples only). The latest revenue breakdown (主营构成) is added to `source_refs`.
   - `position.py`: ATR (`compute_atr`) and risk-based sizing (`analyze_position`) — stop = tighter of invalidation and ATR stop; size = risk budget ÷ stop distance. **Known artifact**: when price sits almost on the stop (tiny stop distance), the formula suggests an absurdly large size (e.g. ~90% of account on a name 1% above its invalidation). Treat any suggested size above ~25% as "price is hugging the stop — no edge, tiny margin for error", not as a real allocation; say so explicitly when presenting.
   - `engine.py`: total score, action label, analyst hypothesis, trader plan. `backdrop_blend` de-duplicates the three correlated backdrop factors so an agreeing tape is not triple-counted.
   - `backtest.py`: offline aggregation of `reviews.jsonl` into win rate, expectancy, MFE/MAE, label/code breakdowns, and per-component predictive edge. Driven by the `backtest` command.
   - `journal.py`: JSONL recommendation records. `analyze` appends to `data/journal/recommendations.jsonl` by default (`--no-journal` to skip).
   - `review.py`: outcome review and weight suggestions, driven by the `review` command. Weight changes are advisory unless `--apply` is passed, and applied changes are backed up and logged to `weight_history.jsonl`.
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

Every new recommendation includes `data_quality`: available, missing, and stale components; session phase; evidence confidence; and whether the evidence is sufficient for a new entry. Missing data still leaves the directional component neutral for backward-compatible scoring, but it lowers evidence confidence and is never presented as observed neutrality.

## Safety

- Do not place real orders from this skill.
- Real trading must follow the `futuapi` explicit confirmation flow.
- Do not call `unlock_trade`.
- Treat recommendations as decision support, not investment guarantees.
- Record invalidation levels and review windows when giving actionable analysis.
