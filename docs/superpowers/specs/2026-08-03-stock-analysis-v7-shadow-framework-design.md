# Stock Analysis v7 Shadow Framework Design

Date: 2026-08-03  
Status: Approved for implementation planning

## 1. Goal

Evolve the existing stock-analysis framework into a three-market, long-only institutional-style decision system without replacing the current production policy before the new evidence is proven.

The framework covers:

- Mainland China A-shares;
- Hong Kong equities;
- United States equities;
- ordinary stocks and unleveraged ETFs only;
- multi-quarter core holdings and one-to-four-week tactical holdings;
- one-to-three-day and five-minute evidence only as entry, add, trim, and exit timing for the tactical sleeve.

The v7 framework must improve three compatible objectives together:

1. improve net expectancy while controlling drawdown;
2. reduce missed opportunities, especially after large but non-structural declines;
3. expand discovery from the current representative universes to broad, point-in-time market coverage.

The governing principle is scarcity over activity: the framework may produce no recommendation and may hold 30%-50% cash, or more in exceptional conditions, rather than lowering standards.

## 2. Non-goals

- Do not place trades.
- Do not support short selling, options, warrants, leveraged ETFs, or margin in the first v7 release.
- Do not treat a model score as a calibrated probability.
- Do not use intraday bars to invalidate a multi-quarter core thesis.
- Do not force a minimum equity exposure.
- Do not replace the current v6 decision policy as one atomic migration.
- Do not combine materially different alpha sources into one undifferentiated total score.
- Do not fabricate neutral evidence when data is missing, stale, or conflicting.

## 3. Design Principles

### 3.1 Separate questions that require separate models

The system must distinguish:

- whether a company is suitable for a core watch universe;
- whether its current price offers an acceptable expected return;
- whether a tactical opportunity is forming now;
- how much portfolio risk the position consumes;
- whether profits should be realized even while the long-term thesis remains intact.

### 3.2 Optimize the portfolio, not isolated stock accuracy

Position size is determined by expected return, confidence, downside, correlation, liquidity, currency, and portfolio capacity. A high-scoring stock does not automatically receive a large allocation.

### 3.3 Use champion-challenger migration

The current v6 policy remains the production champion. v7 runs as a shadow challenger on identical point-in-time inputs. Each v7 module is promoted independently only after sufficient out-of-sample evidence.

### 3.4 Allow cash and abstention

Cash is an intentional residual allocation when opportunities fail the quality, return, or portfolio gates. Candidate scarcity never lowers a threshold.

## 4. System Architecture

The processing chain is:

```text
CN / HK / US point-in-time data
            |
            v
Investability and data-quality gates
            |
            v
+----------------+----------------+----------------+
| Core Quality   | Trend          | Oversold/Event |
| Engine         | Opportunity    | Opportunity    |
+----------------+----------------+----------------+
            |
            v
Scenario Return and Confidence Engine
            |
            v
Independent Risk and Cost Engine
            |
            v
Portfolio Construction and Sleeve Allocation
            |
            v
observe / probe / build / full / hold / trim / exit
            |
            v
Evidence Lab and Module Promotion
```

### 4.1 Modules

1. **Universe Engine** builds point-in-time market membership and applies investability gates.
2. **Core Engine** determines durable company quality without deciding whether the current price is attractive.
3. **Opportunity Engines** run trend, oversold/reversal, catalyst, and earnings-revision tracks independently.
4. **Return Engine** produces bear/base/bull value and return scenarios with confidence and unresolved assumptions.
5. **Risk Engine** measures price, gap, liquidity, concentration, currency, industry, theme, and permanent-impairment risk.
6. **Portfolio Engine** decides action, total allocation, core/tactical sleeve split, and residual cash.
7. **Evidence Lab** records v6/v7 comparisons, outcomes, missed opportunities, false entries, and promotion eligibility.

### 4.2 Market routing

All markets share contracts, action semantics, provenance rules, and evaluation logic. Each market has separate:

- calendars and session phases;
- liquidity and tradeability rules;
- accounting and valuation routes;
- sector thresholds;
- corporate-action and dilution risks;
- currency and settlement risks.

## 5. Point-in-Time Universe and Funnel

Each market uses the following funnel:

```text
all ordinary stocks and unleveraged ETFs
-> investable universe
-> quality candidates
-> deep-research candidates
-> core-qualified companies
-> currently buildable opportunities
```

Target reporting bounds are:

- 30-50 deep candidates per market per scheduled run;
- no more than 20-30 core-qualified companies per market;
- no more than five currently buildable candidates per market;
- zero to three new actionable opportunities across all markets per day.

These are output bounds, not quotas.

### 5.1 Investability gates

The Universe Engine rejects or restricts:

- suspended, non-updating, or insufficiently liquid securities;
- stale or incomplete market and financial data;
- A-share ST and material delisting-risk securities;
- Hong Kong shell-like, persistently illiquid, frequently dilutive, or structurally abnormal securities;
- US OTC and material going-concern-risk securities;
- newly listed securities without sufficient history for the requested model;
- unresolved adjustment-basis, identifier, or financial-period conflicts.

Missing evidence is reported as missing and cannot promote a candidate.

## 6. Core Company and Core Position

The framework distinguishes:

- **core company**: a company whose durable quality qualifies it for long-term monitoring;
- **core position**: a current holding justified by price, expected return, and portfolio capacity;
- **core weight**: a dynamic allocation that may be trimmed while core-company status remains intact.

### 6.1 Core quality model

The initial common quality structure is:

| Component | Weight |
|---|---:|
| Profitability and reinvestment returns | 25% |
| Competitive advantage and industry runway | 20% |
| Financial resilience | 15% |
| Earnings and cash-flow quality | 15% |
| Management, governance, and capital allocation | 15% |
| Long-term industry durability | 10% |

A company becomes `core-qualified` only when:

- `core_quality_score >= 75`;
- no governance, balance-sheet, competitive-position, or evidence hard veto exists;
- material thesis claims have sufficient official or otherwise approved provenance;
- the bear case does not imply an unbounded or clearly unacceptable permanent-impairment risk.

### 6.2 Current buildability

Core qualification does not authorize a position. A core position is buildable only when:

- base-case expected annualized return is at least 10%, subject to sector-specific interpretation;
- bear-case downside is normally no greater than 25%;
- portfolio industry, theme, currency, correlation, and open-risk capacity remain available;
- data coverage and confidence are sufficient for new risk.

### 6.3 Sector-specific models

The first sector model families are:

1. internet platforms;
2. semiconductors and electronics manufacturing;
3. resources and chemicals;
4. financials;
5. pharmaceuticals and biotechnology;
6. power and electrical equipment;
7. consumer and industrial manufacturing.

The models share contracts but not naive thresholds. Examples include normalized commodity prices and cost curves for resources, pipeline probability and cash runway for biotechnology, and stock-based compensation and buyback quality for internet companies.

### 6.4 Core lifecycle

```text
research
-> core-qualified
-> buildable
-> core-held
-> trim
-> suspended
-> exited
```

Valuation excess may move a holding to `trim` without removing core qualification. Thesis, governance, or durable cash-flow invalidation moves it to `exited`. Core status is reviewed after every material event and at least quarterly.

## 7. Opportunity Engines

Opportunity tracks remain independent. A strong score in one track cannot average away the failure of another track, and multiple transformations of the same price series do not count as independent evidence.

### 7.1 Trend accumulation

Trend evidence includes:

- sector breadth and leader synchronization;
- earnings revisions, orders, or other business confirmation;
- benchmark and peer relative strength;
- volatility and volume contraction;
- breakout or completed-bar retest behavior.

A structurally mature pre-breakout setup may receive a 10%-20% fraction of the planned position. Breakout or retest confirmation may add 20%-30%. Business and sector confirmation may complete the planned position.

### 7.2 Oversold and mispricing reversal

The model classifies the decline before using price as confirmation:

- market or sector liquidity decline;
- bounded one-time event;
- valuation reset after excessive expectations;
- structural earnings impairment;
- unconfirmed cause.

An early probe requires an intact long-term thesis, estimable bear-case loss, valuation margin of safety, marginal selling exhaustion, and portfolio risk capacity. It does not require recovery above every moving average. The initial probe is capped at 10%-20% of the planned position.

Structural impairment rejects the opportunity. An unconfirmed cause cannot authorize a core build and permits only continued observation or an explicitly capped experimental probe when every other hard gate passes.

### 7.3 Catalyst and earnings revision

The model records:

- catalyst probability and expected timing;
- expected revenue, earnings, cash-flow, or multiple transmission;
- how much of the effect appears priced in;
- value if the catalyst does not occur.

A theme without a measurable transmission path remains a thematic observation and cannot create a core position.

## 8. Entry and Position Building

Every actionable candidate has two possible paths:

- **value path**: a small probe is allowed once the price enters a margin-of-safety zone;
- **confirmation path**: a small entry is allowed above the original waiting price if evidence improves and expected value remains acceptable.

The action state is:

```text
observe -> probe -> build -> full
```

Each transition recomputes remaining upside, bear-case loss, costs, correlation, and portfolio capacity. A prior purchase never authorizes an automatic add.

The system outputs an entry interval and state-dependent conditions rather than one exact waiting price. Price can solve a price-only gate, but cannot repair missing evidence, structural deterioration, or insufficient portfolio capacity.

## 9. Core and Tactical Sleeves

Each mixed-horizon holding is recorded as:

- 60%-70% core sleeve;
- 30%-40% tactical sleeve.

The percentages apply to the planned position in that security, not automatically to total portfolio value.

### 9.1 Tactical sleeve exits

- At the first target zone, realize 25%-33% of the tactical sleeve.
- At base-case value with short-term extension, realize another 25%-50%.
- At bull-case value, normally exit the remaining tactical sleeve.
- Exit the tactical sleeve when a breakout fails, an event fails, or the tactical time window expires.
- Intraday and five-minute evidence may affect only the tactical sleeve.

### 9.2 Core sleeve trims and exits

- At bull-case value, trim 10%-25% of the core sleeve.
- Rebalance when security or industry exposure exceeds limits.
- Reduce when valuation expands while earnings revisions stop improving.
- Preserve the base core sleeve through ordinary intraday noise when the thesis remains intact.
- Exit the core sleeve only for durable thesis, governance, competitive, or cash-flow invalidation.

Every profit-taking action also creates explicit re-entry conditions based on renewed valuation margin, upward fair-value revision, post-adjustment support, or restored portfolio capacity.

## 10. Portfolio Construction and Risk

Every position record includes market, sector, theme, currency, cost, quantity, portfolio weight, sleeve, horizon, thesis, invalidation, scenario values, and next review time.

### 10.1 Initial constraints

| Constraint | Initial limit |
|---|---:|
| Probe maximum loss to invalidation | 0.25%-0.50% of portfolio NAV |
| Normal single-name open risk | 1.25% of portfolio NAV |
| Single-theme open risk | 3% of portfolio NAV |
| Total portfolio open risk | 6% of portfolio NAV |
| Single-name market-value hard cap | 25% of portfolio NAV |
| Single-industry market-value cap | 30%-35% of portfolio NAV |

Open risk is position weight multiplied by the loss to the applicable structural or thesis invalidation. Market value and open risk are different units and must never be compared directly.

### 10.2 Position bands

- probe: 1%-3% of portfolio value;
- initial core: 3%-6%;
- standard core: 6%-12%;
- high-confidence core: 12%-20%;
- 20%-25% requires exceptional quality, low duplication, and explicit capacity;
- no new risk may take a security above 25%.

Volatility, gap risk, liquidity, and invalidation distance may lower these bands.

### 10.3 Correlation and concentration

The Portfolio Engine aggregates:

- sector and theme exposure;
- factor exposure;
- realized and downside correlation;
- A/H dual listings and shared company identity;
- ETF and constituent overlap;
- common commodity, macro, and currency drivers.

Different codes do not imply diversification.

### 10.4 Cash and market regime

There is no minimum equity exposure. Cash may remain at 30%-50% or higher when the opportunity set is weak. Market regime may slow new risk or reduce tactical exposure, but it cannot mechanically liquidate an intact, reasonably valued core holding.

### 10.5 Stress testing

The portfolio report includes:

- a 15%-20% simultaneous industry decline;
- a 10%-15% single-name overnight gap;
- synchronized three-market risk-off behavior;
- adverse currency moves;
- reduced liquidity and delayed exits.

A 15% portfolio drawdown is a design target, not a guarantee. The enforceable controls are exposure, open risk, concentration, and scenario loss.

## 11. Shadow Outputs and Data Flow

Every analysis event captures one immutable point-in-time input package and produces both:

- the v6 champion recommendation;
- the v7 shadow recommendation.

The v7 record uses a versioned schema and stores:

- market, code, company identity, sector, and theme;
- model and data timestamps;
- available, missing, stale, and conflicting evidence;
- core qualification and buildability;
- independent opportunity-track results;
- bear/base/bull scenarios and unresolved assumptions;
- risk and cost estimates;
- proposed core and tactical allocations;
- action, trigger, trim, exit, and re-entry conditions;
- binding gates and differences from v6.

One input package must not be silently refreshed between the v6 and v7 runs.

## 12. Evaluation

### 12.1 Tactical evaluation

Evaluate one-, five-, twenty-, and sixty-session outcomes using:

- raw and benchmark-relative return;
- MFE and MAE;
- payoff ratio and net expectancy;
- realized path through stops and profit-taking;
- transaction costs, slippage, and holding time.

### 12.2 Core evaluation

Evaluate sixty-, one-hundred-twenty-, and two-hundred-fifty-session outcomes using:

- market- and sector-relative return;
- earnings and cash-flow thesis realization;
- scenario accuracy;
- drawdown and recovery time;
- value added by trims and re-entry;
- false exits caused by tactical noise.

### 12.3 Four-way decision audit

Every eligible observation is classified as:

1. correct entry;
2. false entry;
3. correct rejection;
4. missed opportunity.

The framework may not claim improvement by reducing false entries while ignoring missed opportunities, or vice versa.

### 12.4 Sample thresholds

- fewer than 30 unique observations: diagnostic only;
- 30-59: directionally informative, no promotion;
- at least 60: eligible for limited promotion;
- at least 100 across at least two market regimes: eligible for broad replacement.

Samples are bucketed by market, horizon, instrument class, opportunity track, strategy ID, and decision policy. Repeated scans of the same trade or opportunity are deduplicated.

### 12.5 Promotion criteria

A v7 module may replace its v6 counterpart only when:

- out-of-sample net expectancy improves;
- maximum drawdown does not materially worsen;
- the result survives costs and reasonable parameter perturbations;
- performance is not dominated by one security, sector, or regime;
- missed opportunities decline without disproportionate false entries;
- data-failure behavior remains safe and deterministic.

Promotion is module-specific and reversible. The Evidence Lab never writes production weights automatically.

## 13. Point-in-Time and Overfitting Controls

The evidence store preserves:

- historical universe membership, including later delistings;
- actual publication dates for financial and analyst data;
- corporate actions and adjustment basis;
- all model versions and parameter experiments;
- original market session and source timestamps;
- missing, stale, and conflicting evidence.

Evaluation uses chronological, non-overlapping training and test windows. Overlapping labels are purged or embargoed as required. Synthetic or adjustment-basis-mismatched outcomes are excluded from promotion evidence.

## 14. Failure Handling

- A non-updating quote preserves the prior state and produces no new signal.
- Missing financial evidence lowers coverage and blocks core promotion.
- Material source conflicts block new core risk until resolved.
- Failure in one market does not stop the other markets.
- Expired membership data disables the affected sector or universe slice.
- A v7 module exception falls back to the v6 output and records the error.
- No error path may relax a threshold, fabricate neutrality, or increase risk.

## 15. Test Strategy

The implementation plan must include:

- unit tests for every module contract and hard gate;
- point-in-time tests that reject future bars, future membership, and future publications;
- sector-model tests demonstrating that incompatible metrics are not mixed;
- market-calendar and session tests for CN, HK, and US;
- corporate-action and adjustment-basis tests;
- portfolio aggregation tests for themes, A/H identity, ETFs, currency, and correlation;
- path tests for staged entries, tactical profit-taking, core trims, gaps, and re-entry;
- failure-injection tests for stale, missing, conflicting, and partial data;
- champion-challenger comparison fixtures;
- golden missed-opportunity and false-entry replays;
- end-to-end offline fixtures before any live shadow run.

## 16. Delivery Sequence

The program is decomposed into independent projects:

1. common point-in-time data, identity, universe, and version contracts;
2. broad three-market investability funnel;
3. core quality, sector models, scenarios, and buildability;
4. trend, oversold/event, catalyst, and earnings-revision opportunity tracks;
5. core/tactical sleeves, profit-taking, re-entry, and lifecycle state;
6. portfolio risk, concentration, currency, cash, and allocation;
7. champion-challenger evidence joins and shadow reporting;
8. module-specific promotion and reversible migration.

Each project receives its own implementation plan and acceptance tests. Existing v6 production behavior remains unchanged until a v7 module passes its promotion gate.

## 17. Acceptance Criteria

The design is successfully implemented when:

1. CN, HK, and US ordinary stocks and unleveraged ETFs can enter point-in-time investability funnels without fabricated neutral evidence.
2. Core quality and current buildability are separate, explainable outputs.
3. Trend and oversold/event opportunities can independently produce capped probes without bypassing hard risk gates.
4. Every mixed-horizon holding has separately managed core and tactical sleeves.
5. Profit-taking generates explicit re-entry conditions.
6. Portfolio actions respect open-risk, concentration, overlap, currency, and cash constraints.
7. v6 and v7 consume the same immutable input package and produce auditable differences.
8. Missing or stale data cannot create or upgrade a recommendation.
9. v7 modules remain shadow-only until their exact evidence bucket meets the approved promotion criteria.
10. The framework may validly return no actionable opportunity across all three markets.
