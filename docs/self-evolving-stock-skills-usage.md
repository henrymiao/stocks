# Self-Evolving Stock Skills Usage

## Dry Run

Run fixture-based analysis without Futu OpenD:

```bash
python3 -m tools.stock_skills.cli dry-run --code SZ.002463 --output /tmp/hudian-recommendation.json
```

The output JSON contains:

- `label`
- `total_score`
- `component_scores`
- `analyst_hypothesis`
- `trader_plan`
- `support_levels`
- `resistance_levels`
- `invalidation_level`

## Live Data Path

Live data collection is routed through `tools.stock_skills.futu_fetcher.FutuFetcher`, which wraps the existing `futuapi` scripts under:

```text
/Users/shuren/.agents/skills/futuapi/scripts
```

OpenD must be running for live calls. The analysis engine can still run on stored or fixture data when OpenD is unavailable.

## Safety

This package produces analysis and review records only. It does not place real trades. Any real order must follow the existing `futuapi` explicit-confirmation flow.
