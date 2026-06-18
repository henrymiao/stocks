---
name: stock-analysis
description: Use when analyzing stocks, watchlists, technology/semiconductor/AI hardware/crypto-linked names, current holdings, trend quality, capital flow, macro risk, cross-market signals, recommendation journals, or post-trade reviews in this repository.
---

# Stock Analysis

## Overview

Use this skill for repository-local stock analysis workflows built around `tools/stock_skills`. It provides a disciplined analyst/trader framework:

- analyst frame: investment hypothesis, sector logic, macro risk, cross-market linkage.
- trader frame: trend status, support/resistance, invalidation level, action label, and position context.
- review frame: recommendation journaling, outcome review, and explainable signal-weight suggestions.

This skill supports analysis and decision support only. It must not place real trades.

## Repository Paths

Assume the workspace root is:

```text
/Users/shuren/WorkSpace/codes/stocks
```

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

Run a fixture-based dry run without Futu OpenD:

```bash
python3 -m tools.stock_skills.cli dry-run --code SZ.002463 --output /tmp/hudian-recommendation.json
```

Inspect the dry-run label:

```bash
python3 -c "import json; p=json.load(open('/tmp/hudian-recommendation.json')); print(p['label'], p['total_score'])"
```

## Workflow

1. Load the user's intent and relevant stock codes.
2. If the request needs current market data, use `futuapi` and ensure OpenD is running.
3. If the request is code review, dry-run verification, or framework work, do not require OpenD.
4. Use `tools.stock_skills` modules to keep reasoning structured:
   - `trend.py`: breakout, failed breakout, support/resistance, invalidation.
   - `capital.py`: order-size flow confirmation/divergence.
   - `macro.py`: macro and cross-market risk regimes.
   - `engine.py`: total score, action label, analyst hypothesis, trader plan.
   - `journal.py`: JSONL recommendation records.
   - `review.py`: outcome review and weight suggestions.
   - `futu_fetcher.py`: wrapper around existing `futuapi` quote scripts.
5. Present output as analysis with clear uncertainty and invalidation conditions.

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

## Safety

- Do not place real orders from this skill.
- Real trading must follow the `futuapi` explicit confirmation flow.
- Do not call `unlock_trade`.
- Treat recommendations as decision support, not investment guarantees.
- Record invalidation levels and review windows when giving actionable analysis.
