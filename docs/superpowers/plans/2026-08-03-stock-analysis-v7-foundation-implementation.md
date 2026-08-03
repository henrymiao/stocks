# Stock Analysis v7 Point-in-Time Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the common security-identity, point-in-time universe, immutable input-package, and model-version contracts required for v6 champion/v7 shadow analysis across CN, HK, and US markets without changing any current v6 decision.

**Architecture:** Normalize listings through a versioned identity registry, upgrade the existing discovery universe to a backward-compatible point-in-time v2 schema, freeze each analysis event into canonical JSON with a deterministic digest, and bind both model releases to that same digest. A read-only foundation validator proves that configured universes and identities are internally consistent; it does not fetch live data, score securities, or authorize risk.

**Tech Stack:** Python 3 standard library, frozen dataclasses, `zoneinfo`, SHA-256 canonical JSON digests, JSON files, `argparse`, and `unittest`.

**Design reference:** `docs/superpowers/specs/2026-08-03-stock-analysis-v7-shadow-framework-design.md`

---

## Scope Boundary

This plan implements delivery phase 1 only:

- common CN/HK/US security identity and cross-listing ownership keys;
- versioned point-in-time universe membership;
- immutable evidence packages with publication/observation cutoffs;
- explicit model and policy release bindings;
- deterministic offline validation and migration tooling.

It deliberately does **not** implement the broad-market funnel, core-quality models, valuation scenarios, opportunity engines, sleeve management, portfolio construction, champion/challenger scoring, or promotion policy. Those are the seven subsequent projects in the approved design. Existing `recommendation-v6` output and `logic-first-method-evidence-v6` policy remain authoritative and unchanged.

Do not touch the unrelated user-owned untracked file `data/watchlists/active-sector-pool.json`.

## Invariants

1. A listing code identifies a security; `company_id` aggregates economic exposure across A/H/ADR listings.
2. Only `ordinary-stock` and `unleveraged-etf` are investable. `benchmark-index` may supply context but can never become a candidate.
3. Universe membership, security identity, observations, and publications must be effective no later than the requested `as_of` time.
4. Missing, stale, and conflicting evidence are explicit states. None is serialized as a neutral numeric value.
5. Canonical input-package bytes are immutable after construction and independent of dictionary insertion order.
6. v6 and v7 run bindings for one event must contain the same `input_package_id` and `input_digest`.
7. This phase may add metadata and validation commands, but it may not alter current v6 scores, gates, entry decisions, or position decisions.

## File Map

Create:

- `tools/stock_skills/markets.py`: single CN/HK/US prefix, timezone, and currency contract.
- `tools/stock_skills/identity.py`: listing identity, company exposure grouping, registry parsing, activity windows, and content versioning.
- `tools/stock_skills/point_in_time.py`: evidence stamps, canonical immutable input packages, model releases, and champion/challenger run bindings.
- `tools/stock_skills/foundation_migrate.py`: deterministic v1-universe to v2/identity-registry migration.
- `tools/stock_skills/foundation_validation.py`: cross-file point-in-time consistency validation.
- `data/identities/company-overrides.json`: explicit A/H/ADR economic-identity mappings; never infer these from names.
- `data/identities/securities-v1.json`: generated identity registry for every configured member and benchmark.
- `tests/test_identity.py`
- `tests/test_markets.py`
- `tests/test_point_in_time.py`
- `tests/test_foundation_migrate.py`
- `tests/test_foundation_validation.py`

Modify:

- `tools/stock_skills/session.py`: consume the common timezone/prefix contract without changing session semantics.
- `tools/stock_skills/market_profiles.py`: consume the common currency/timezone contract without changing analytical thresholds.
- `tools/stock_skills/universe.py`: backward-compatible universe v2 fields, membership windows, publication cutoffs, and deterministic version IDs.
- `tools/stock_skills/cli.py`: add the read-only `foundation-check` command.
- `data/universes/cn.json`
- `data/universes/hk.json`
- `data/universes/us.json`
- `tests/test_opportunity_discovery.py`: preserve v1 compatibility and exercise v2 point-in-time filtering.
- `tests/test_cli.py`: validate the new command's JSON and exit codes.
- `docs/self-evolving-stock-skills-usage.md`: document foundation validation and the shadow-only boundary.

## Pre-flight

- [ ] From `/Users/shuren/WorkSpace/codes/stocks`, record the baseline without changing it:

```bash
git status --short --branch
python3 -m unittest discover -s tests -v
```

Expected: the test suite passes. The only unrelated path currently expected is `?? data/watchlists/active-sector-pool.json`; leave it unstaged and unchanged. If any other test is red, stop and explain the baseline before implementing.

- [ ] Create a dedicated branch if the implementation is not already isolated:

```bash
git switch -c codex/stock-analysis-v7-foundation
```

Expected: `Switched to a new branch 'codex/stock-analysis-v7-foundation'`.

### Task 1: Add Common Market, Security Identity, and Cross-Listing Contracts

**Files:**

- Create: `tools/stock_skills/markets.py`
- Create: `tools/stock_skills/identity.py`
- Create: `tests/test_markets.py`
- Create: `tests/test_identity.py`
- Modify: `tools/stock_skills/session.py`
- Modify: `tools/stock_skills/market_profiles.py`
- Modify: `tests/test_session.py`
- Modify: `tests/test_market_profiles.py`

- [ ] **Step 1: Write failing common-market tests**

Create `tests/test_markets.py`:

```python
import unittest

from tools.stock_skills.markets import (
    market_currency,
    market_from_code,
    market_timezone,
    normalize_market,
)


class MarketContractTests(unittest.TestCase):
    def test_routes_cn_hk_us_prefixes_to_one_contract(self):
        self.assertEqual(market_from_code("SH.600309"), "CN")
        self.assertEqual(market_from_code("SZ.300750"), "CN")
        self.assertEqual(market_from_code("HK.00700"), "HK")
        self.assertEqual(market_from_code("US.NVDA"), "US")
        self.assertEqual(market_currency("CN"), "CNY")
        self.assertEqual(market_currency("HK"), "HKD")
        self.assertEqual(market_currency("US"), "USD")

    def test_uses_exchange_local_timezones_and_rejects_unknowns(self):
        self.assertEqual(str(market_timezone("CN")), "Asia/Shanghai")
        self.assertEqual(str(market_timezone("HK")), "Asia/Hong_Kong")
        self.assertEqual(str(market_timezone("US")), "America/New_York")
        with self.assertRaisesRegex(ValueError, "Unsupported market"):
            normalize_market("CC")
        with self.assertRaisesRegex(ValueError, "Malformed market code"):
            market_from_code("NVDA")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Write failing identity tests**

Create `tests/test_identity.py`:

```python
import unittest

from tools.stock_skills.identity import (
    IdentityRegistry,
    SecurityIdentity,
    identity_registry_from_record,
)


class IdentityTests(unittest.TestCase):
    def test_cross_listings_share_company_but_not_security_identity(self):
        registry = identity_registry_from_record(
            {
                "schema_version": "security-identity-registry-v1",
                "published_at": "2026-08-01T18:00:00+08:00",
                "identities": [
                    {
                        "security_id": "listing:SH.688981",
                        "company_id": "company:smic",
                        "code": "SH.688981",
                        "name": "中芯国际",
                        "market": "CN",
                        "instrument_type": "ordinary-stock",
                        "currency": "CNY",
                        "active_from": "2020-07-16T09:30:00+08:00",
                    },
                    {
                        "security_id": "listing:HK.00981",
                        "company_id": "company:smic",
                        "code": "HK.00981",
                        "name": "中芯国际",
                        "market": "HK",
                        "instrument_type": "ordinary-stock",
                        "currency": "HKD",
                        "active_from": "2004-03-18T09:30:00+08:00",
                    },
                ],
            }
        )

        a_share = registry.resolve("SH.688981", "2026-08-03T10:00:00+08:00")
        h_share = registry.resolve("HK.00981", "2026-08-03T10:00:00+08:00")

        self.assertNotEqual(a_share.security_id, h_share.security_id)
        self.assertEqual(a_share.company_id, h_share.company_id)
        self.assertEqual(registry.company_codes("company:smic"), ("HK.00981", "SH.688981"))

    def test_only_ordinary_stocks_and_unleveraged_etfs_are_investable(self):
        stock = SecurityIdentity(
            "listing:HK.00700", "company:tencent", "HK.00700", "腾讯控股",
            "HK", "ordinary-stock", "HKD", "2004-06-16T09:30:00+08:00",
        )
        etf = SecurityIdentity(
            "listing:US.SPY", "fund:spy", "US.SPY", "SPDR S&P 500 ETF",
            "US", "unleveraged-etf", "USD", "1993-01-29T09:30:00-05:00",
        )
        index = SecurityIdentity(
            "benchmark:SH.000300", "benchmark:csi300", "SH.000300", "沪深300",
            "CN", "benchmark-index", "CNY", "2005-04-08T09:30:00+08:00",
        )

        self.assertTrue(stock.investable)
        self.assertTrue(etf.investable)
        self.assertFalse(index.investable)

    def test_future_and_ended_identity_cannot_resolve_at_as_of(self):
        registry = IdentityRegistry(
            published_at="2026-08-01T18:00:00+08:00",
            identities=(
                SecurityIdentity(
                    "listing:HK.TEST", "company:test", "HK.TEST", "Test",
                    "HK", "ordinary-stock", "HKD",
                    "2026-08-05T09:30:00+08:00", None,
                ),
            ),
        )

        with self.assertRaisesRegex(KeyError, "not active"):
            registry.resolve("HK.TEST", "2026-08-03T10:00:00+08:00")

    def test_registry_version_is_content_addressed_and_order_stable(self):
        first = identity_registry_from_record(
            {
                "schema_version": "security-identity-registry-v1",
                "published_at": "2026-08-01T18:00:00+08:00",
                "identities": [
                    {
                        "security_id": "listing:US.SPY",
                        "company_id": "fund:spy",
                        "code": "US.SPY",
                        "name": "SPY",
                        "market": "US",
                        "instrument_type": "unleveraged-etf",
                        "currency": "USD",
                        "active_from": "1993-01-29T09:30:00-05:00",
                    }
                ],
            }
        )
        second = identity_registry_from_record(
            {
                "published_at": "2026-08-01T18:00:00+08:00",
                "identities": [
                    {
                        "currency": "USD",
                        "instrument_type": "unleveraged-etf",
                        "market": "US",
                        "name": "SPY",
                        "code": "US.SPY",
                        "company_id": "fund:spy",
                        "security_id": "listing:US.SPY",
                        "active_from": "1993-01-29T09:30:00-05:00",
                    }
                ],
                "schema_version": "security-identity-registry-v1",
            }
        )

        self.assertEqual(first.version_id, second.version_id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the focused tests and verify the red state**

```bash
python3 -m unittest tests.test_markets tests.test_identity -v
```

Expected: import failures for `tools.stock_skills.markets` and `tools.stock_skills.identity`.

- [ ] **Step 4: Implement the single market contract**

Create `tools/stock_skills/markets.py`:

```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


MARKET_TIMEZONES = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}
MARKET_PREFIXES = {"CN": frozenset({"SH", "SZ"}), "HK": frozenset({"HK"}), "US": frozenset({"US"})}
MARKET_CURRENCIES = {"CN": "CNY", "HK": "HKD", "US": "USD"}


def normalize_market(value: str) -> str:
    market = str(value).upper()
    if market not in MARKET_TIMEZONES:
        raise ValueError(f"Unsupported market: {value!r}")
    return market


def market_from_code(code: str) -> str:
    if "." not in code or not code.split(".", 1)[1]:
        raise ValueError(f"Malformed market code: {code!r}")
    prefix = code.split(".", 1)[0].upper()
    for market, prefixes in MARKET_PREFIXES.items():
        if prefix in prefixes:
            return market
    raise ValueError(f"Unsupported market prefix: {prefix!r}")


def market_timezone(market: str) -> ZoneInfo:
    return ZoneInfo(MARKET_TIMEZONES[normalize_market(market)])


def market_currency(market: str) -> str:
    return MARKET_CURRENCIES[normalize_market(market)]


def market_moment(value: str, market: str) -> datetime:
    moment = datetime.fromisoformat(value)
    timezone = market_timezone(market)
    return moment.replace(tzinfo=timezone) if moment.tzinfo is None else moment.astimezone(timezone)
```

Update `session.py`, `market_profiles.py`, and later `universe.py` to import these values instead of adding another map. Preserve public imports from `universe.py` if existing callers use them. In `session.py`, keep `CC` as the existing explicit continuous-market branch and route only equity prefixes through `market_from_code()`; this avoids adding crypto to the v7 equity contract. Build each market profile's `session_timezone` and `liquidity_currency` from `market_timezone()` and `market_currency()`. Change the HK profile's timezone label to `Asia/Hong_Kong`; this has the same 2026 UTC offset but removes contract drift. Existing session phase outcomes must remain unchanged.

- [ ] **Step 5: Implement the frozen identity contracts**

Create `tools/stock_skills/identity.py` with these public contracts:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .markets import MARKET_CURRENCIES, MARKET_PREFIXES, market_moment, normalize_market


IDENTITY_SCHEMA_VERSION = "security-identity-registry-v1"
INVESTABLE_INSTRUMENT_TYPES = frozenset({"ordinary-stock", "unleveraged-etf"})
INSTRUMENT_TYPES = INVESTABLE_INSTRUMENT_TYPES | {"benchmark-index"}
def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SecurityIdentity:
    security_id: str
    company_id: str
    code: str
    name: str
    market: str
    instrument_type: str
    currency: str
    active_from: str
    active_to: str | None = None

    def __post_init__(self) -> None:
        market = normalize_market(self.market)
        object.__setattr__(self, "market", market)
        prefix = self.code.split(".", 1)[0].upper() if "." in self.code else ""
        if prefix not in MARKET_PREFIXES[market]:
            raise ValueError(f"{self.code!r} does not belong to {market}")
        if self.instrument_type not in INSTRUMENT_TYPES:
            raise ValueError(f"Unsupported instrument type: {self.instrument_type!r}")
        if self.currency != MARKET_CURRENCIES[market]:
            raise ValueError(f"{self.code!r} must use {MARKET_CURRENCIES[market]}")
        if self.active_to is not None and market_moment(self.active_to, market) <= market_moment(self.active_from, market):
            raise ValueError("active_to must be later than active_from")

    @property
    def investable(self) -> bool:
        return self.instrument_type in INVESTABLE_INSTRUMENT_TYPES

    def active_at(self, at: str) -> bool:
        market = normalize_market(self.market)
        moment = market_moment(at, market)
        start = market_moment(self.active_from, market)
        end = None if self.active_to is None else market_moment(self.active_to, market)
        return start <= moment and (end is None or moment < end)


@dataclass(frozen=True)
class IdentityRegistry:
    published_at: str
    identities: tuple[SecurityIdentity, ...]
    schema_version: str = IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != IDENTITY_SCHEMA_VERSION:
            raise ValueError(f"Unsupported identity schema: {self.schema_version!r}")
        codes = [identity.code for identity in self.identities]
        security_ids = [identity.security_id for identity in self.identities]
        if len(codes) != len(set(codes)):
            raise ValueError("Identity registry contains duplicate codes")
        if len(security_ids) != len(set(security_ids)):
            raise ValueError("Identity registry contains duplicate security IDs")

    @property
    def version_id(self) -> str:
        material = {
            "schema_version": self.schema_version,
            "published_at": self.published_at,
            "identities": sorted((asdict(identity) for identity in self.identities), key=lambda row: row["security_id"]),
        }
        return f"identity:{hashlib.sha256(_canonical_json(material).encode('utf-8')).hexdigest()}"

    def resolve(self, code: str, at: str) -> SecurityIdentity:
        match = next((identity for identity in self.identities if identity.code == code), None)
        if match is None:
            raise KeyError(f"Unknown identity code: {code}")
        if not match.active_at(at):
            raise KeyError(f"Identity {code} is not active at {at}")
        return match

    def company_codes(self, company_id: str) -> tuple[str, ...]:
        return tuple(sorted(identity.code for identity in self.identities if identity.company_id == company_id))

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "published_at": self.published_at,
            "version_id": self.version_id,
            "identities": [
                asdict(identity)
                for identity in sorted(self.identities, key=lambda item: item.security_id)
            ],
        }


def identity_registry_from_record(payload: dict[str, Any]) -> IdentityRegistry:
    return IdentityRegistry(
        published_at=str(payload["published_at"]),
        identities=tuple(SecurityIdentity(**row) for row in payload.get("identities", [])),
        schema_version=str(payload.get("schema_version", IDENTITY_SCHEMA_VERSION)),
    )
```

Also add `load_identity_registry(path)` and `save_identity_registry(path, registry)` using UTF-8 JSON. The loader must ignore a persisted `version_id` and recompute it from material fields; a mismatched persisted value raises `ValueError` instead of being trusted.

- [ ] **Step 6: Run focused and routing regression tests**

```bash
python3 -m unittest tests.test_markets tests.test_identity tests.test_session tests.test_market_profiles -v
```

Expected: all common-market, identity, session, and market-profile tests pass.

- [ ] **Step 7: Commit the market and identity contracts**

```bash
git add tools/stock_skills/markets.py tools/stock_skills/identity.py tools/stock_skills/session.py tools/stock_skills/market_profiles.py tests/test_markets.py tests/test_identity.py tests/test_session.py tests/test_market_profiles.py
git commit -m "feat: add point-in-time security identities"
```

### Task 2: Upgrade the Universe to a Backward-Compatible Point-in-Time v2 Contract

**Files:**

- Modify: `tools/stock_skills/universe.py`
- Modify: `tests/test_opportunity_discovery.py`

- [ ] **Step 1: Add failing v1 compatibility and v2 cutoff tests**

First replace the existing configured-universe routing test so the expected timezone also comes from the new common contract:

```python
    def test_configured_universes_are_valid_and_market_routed(self):
        expected_timezones = {
            "cn": "Asia/Shanghai",
            "hk": "Asia/Hong_Kong",
            "us": "America/New_York",
        }
        for market in ("cn", "hk", "us"):
            universe = load_universe(Path("data/universes") / f"{market}.json")
            self.assertEqual(universe.market, market.upper())
            self.assertTrue(universe.unique_codes())
            self.assertEqual(universe.timezone, expected_timezones[market])
```

Then append the remaining tests to `OpportunityDiscoveryTests` in `tests/test_opportunity_discovery.py`:

```python
    def test_v1_universe_remains_loadable_during_migration(self):
        payload = _star_universe().to_record()
        payload["schema_version"] = "opportunity-universe-v1"
        payload.pop("published_at", None)
        payload.pop("identity_registry_version", None)
        for sector in payload["sectors"]:
            for member in sector["members"]:
                member.pop("security_id", None)
                member.pop("member_from", None)
                member.pop("member_to", None)

        loaded = universe_from_record(payload, source="legacy-fixture")

        self.assertEqual(loaded.schema_version, "opportunity-universe-v1")
        self.assertEqual(loaded.published_at, loaded.as_of)
        self.assertEqual(loaded.unique_codes(), _star_universe().unique_codes())

    def test_v2_membership_filters_future_and_ended_members(self):
        payload = _star_universe().to_record()
        payload.update(
            {
                "schema_version": "opportunity-universe-v2",
                "published_at": "2026-07-20T08:00:00+08:00",
                "identity_registry_version": "identity:test",
            }
        )
        members = payload["sectors"][0]["members"]
        for member in members:
            member["security_id"] = f"listing:{member['code']}"
            member["member_from"] = "2026-01-01T00:00:00+08:00"
        members[1]["member_to"] = "2026-07-19T23:59:59+08:00"
        members[2]["member_from"] = "2026-07-21T00:00:00+08:00"

        loaded = universe_from_record(payload)
        active = loaded.active_member_codes("2026-07-20T15:15:00+08:00")

        self.assertNotIn(members[1]["code"], active)
        self.assertNotIn(members[2]["code"], active)
        self.assertIn(members[3]["code"], active)

    def test_future_published_membership_is_rejected(self):
        payload = _star_universe().to_record()
        payload.update(
            {
                "schema_version": "opportunity-universe-v2",
                "published_at": "2026-07-21T08:00:00+08:00",
                "identity_registry_version": "identity:test",
            }
        )
        for member in payload["sectors"][0]["members"]:
            member["security_id"] = f"listing:{member['code']}"
            member["member_from"] = "2026-01-01T00:00:00+08:00"

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cn.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "published after"):
                resolve_universe("CN", configured_path=path, at="2026-07-20T15:15:00+08:00")

    def test_universe_version_ignores_runtime_source_but_not_membership(self):
        payload = _star_universe().to_record()
        configured = universe_from_record(payload, source="configured")
        cached = universe_from_record(payload, source="cache")
        changed = payload.copy()
        changed["sectors"] = json.loads(json.dumps(payload["sectors"]))
        changed["sectors"][0]["members"][0]["weight"] = 2.0
        changed.pop("version_id", None)

        self.assertEqual(configured.version_id, cached.version_id)
        self.assertNotEqual(configured.version_id, universe_from_record(changed).version_id)
```

Add `universe_from_record` to the existing imports at the top of the test file.

- [ ] **Step 2: Run the focused tests and verify the red state**

```bash
python3 -m unittest tests.test_opportunity_discovery.OpportunityDiscoveryTests.test_v1_universe_remains_loadable_during_migration tests.test_opportunity_discovery.OpportunityDiscoveryTests.test_v2_membership_filters_future_and_ended_members tests.test_opportunity_discovery.OpportunityDiscoveryTests.test_future_published_membership_is_rejected tests.test_opportunity_discovery.OpportunityDiscoveryTests.test_universe_version_ignores_runtime_source_but_not_membership -v
```

Expected: failures for missing publication, membership-window, and version APIs.

- [ ] **Step 3: Extend `UniverseMember` without breaking positional callers**

Append new fields after the existing five fields so `_star_universe()` and current tests remain valid:

```python
@dataclass(frozen=True)
class UniverseMember:
    code: str
    name: str
    role: str = "constituent"
    weight: float = 1.0
    shared_identity: str | None = None
    security_id: str | None = None
    member_from: str | None = None
    member_to: str | None = None

    def active_at(self, at: str, market: str) -> bool:
        moment = _parse_moment(at, market)
        start = None if self.member_from is None else _parse_moment(self.member_from, market)
        end = None if self.member_to is None else _parse_moment(self.member_to, market)
        return (start is None or start <= moment) and (end is None or moment < end)
```

Use half-open membership intervals `[member_from, member_to)` and validate that `member_to > member_from` when both exist. Import `MARKET_TIMEZONES`, `MARKET_PREFIXES`, `normalize_market`, `market_timezone`, and `market_moment` from `markets.py`; keep compatibility aliases in `universe.py` for current importers. Do not infer `company_id` from `shared_identity`; the identity registry becomes the single economic-exposure authority.

- [ ] **Step 4: Add v2 fields and a material-only universe digest**

Extend `MarketUniverse` after existing fields:

```python
    published_at: str | None = None
    identity_registry_version: str | None = None
```

Keep `schema_version="opportunity-universe-v1"` as the dataclass default for existing constructors. Add:

```python
    @property
    def effective_published_at(self) -> str:
        return self.published_at or self.as_of

    @property
    def version_id(self) -> str:
        material = self._material_record()
        encoded = json.dumps(
            material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"universe:{hashlib.sha256(encoded).hexdigest()}"

    def _material_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "market": self.market,
            "as_of": self.as_of,
            "expires_at": self.expires_at,
            "published_at": self.effective_published_at,
            "identity_registry_version": self.identity_registry_version,
            "sectors": [asdict(sector) for sector in self.sectors],
        }

    def to_record(self) -> dict[str, Any]:
        record = self._material_record()
        record["source"] = self.source
        record["version_id"] = self.version_id
        return record

    def active_member_codes(self, at: str) -> tuple[str, ...]:
        active: list[str] = []
        for sector in self.sectors:
            for member in sector.members:
                if member.active_at(at, self.market) and member.code not in active:
                    active.append(member.code)
        return tuple(active)

    def unique_codes(self, at: str | None = None) -> tuple[str, ...]:
        codes: list[str] = []
        for sector in self.sectors:
            members = sector.members if at is None else tuple(
                member for member in sector.members if member.active_at(at, self.market)
            )
            for code in (sector.benchmark, *(member.code for member in members)):
                if code not in codes:
                    codes.append(code)
        return tuple(codes)
```

Import `hashlib`. The explicit `_material_record()` boundary keeps runtime `source` changes out of the digest and avoids recursive `to_record()` calls.

- [ ] **Step 5: Parse both schemas and enforce publication time in `resolve_universe`**

For v1 input:

- default `published_at` to `as_of`;
- leave `identity_registry_version=None`;
- default each `security_id` to `listing:{code}`;
- default each `member_from` to the universe `as_of` only for serialized migration output, not for legacy runtime filtering.

For v2 input require `published_at`, `identity_registry_version`, `security_id`, and `member_from`. Reject unsupported schema versions. When a persisted v2 `version_id` exists, recompute it and reject a mismatch. Before returning refreshed, cached, or configured membership, require:

```python
if _parse_moment(universe.effective_published_at, market) > _parse_moment(moment, market):
    raise RuntimeError(
        f"{market} membership was published after requested as_of: "
        f"{universe.effective_published_at} > {moment}"
    )
```

When reconstructing a cached `MarketUniverse`, preserve `published_at` and `identity_registry_version` as well as the existing fields.

- [ ] **Step 6: Run the complete discovery regression suite**

```bash
python3 -m unittest tests.test_opportunity_discovery -v
```

Expected: all current discovery behavior and the four new contract tests pass.

- [ ] **Step 7: Commit the universe contract**

```bash
git add tools/stock_skills/universe.py tests/test_opportunity_discovery.py
git commit -m "feat: version point-in-time universe membership"
```

### Task 3: Add Deterministic Foundation Data Migration

**Files:**

- Create: `tools/stock_skills/foundation_migrate.py`
- Create: `data/identities/company-overrides.json`
- Create: `data/identities/securities-v1.json`
- Create: `tests/test_foundation_migrate.py`
- Modify: `data/universes/cn.json`
- Modify: `data/universes/hk.json`
- Modify: `data/universes/us.json`

- [ ] **Step 1: Write a failing migration test**

Create `tests/test_foundation_migrate.py`:

```python
import unittest

from tools.stock_skills.foundation_migrate import migrate_universes


class FoundationMigrationTests(unittest.TestCase):
    def test_migration_is_deterministic_and_uses_only_explicit_company_overrides(self):
        universes = {
            "CN": {
                "schema_version": "opportunity-universe-v1",
                "market": "CN",
                "as_of": "2026-07-21T16:00:00+08:00",
                "source": "fixture",
                "sectors": [
                    {
                        "key": "chips",
                        "name": "芯片",
                        "representative": "SH.688981",
                        "benchmark": "SH.000300",
                        "members": [
                            {"code": "SH.688981", "name": "中芯国际", "role": "leader"}
                        ],
                    }
                ],
            },
            "HK": {
                "schema_version": "opportunity-universe-v1",
                "market": "HK",
                "as_of": "2026-07-21T16:00:00+08:00",
                "source": "fixture",
                "sectors": [
                    {
                        "key": "chips",
                        "name": "芯片",
                        "representative": "HK.00981",
                        "benchmark": "HK.800700",
                        "members": [
                            {"code": "HK.00981", "name": "中芯国际", "role": "leader"}
                        ],
                    }
                ],
            },
        }
        overrides = {"company:smic": ["SH.688981", "HK.00981"]}

        first_universes, first_registry = migrate_universes(
            universes, overrides, published_at="2026-08-03T18:00:00+08:00"
        )
        second_universes, second_registry = migrate_universes(
            universes, overrides, published_at="2026-08-03T18:00:00+08:00"
        )

        self.assertEqual(first_universes, second_universes)
        self.assertEqual(first_registry.to_record(), second_registry.to_record())
        self.assertEqual(
            first_registry.resolve("SH.688981", "2026-08-04T10:00:00+08:00").company_id,
            "company:smic",
        )
        self.assertEqual(
            first_registry.resolve("HK.00981", "2026-08-04T10:00:00+08:00").company_id,
            "company:smic",
        )
        self.assertEqual(first_universes["CN"]["schema_version"], "opportunity-universe-v2")
        self.assertEqual(
            first_universes["CN"]["identity_registry_version"], first_registry.version_id
        )

    def test_duplicate_override_assignment_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "assigned to multiple company IDs"):
            migrate_universes(
                {},
                {"company:first": ["HK.00700"], "company:second": ["HK.00700"]},
                published_at="2026-08-03T18:00:00+08:00",
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the red state**

```bash
python3 -m unittest tests.test_foundation_migrate -v
```

Expected: import failure for `tools.stock_skills.foundation_migrate`.

- [ ] **Step 3: Implement the migration rules**

`migrate_universes(universes, company_overrides, published_at)` must:

1. reject a code assigned to more than one explicit company ID;
2. collect every member code and every benchmark code across the input universes;
3. classify a member as `unleveraged-etf` only when `role == "etf"`; classify other members as `ordinary-stock`; classify benchmark-only codes as `benchmark-index`;
4. assign `security_id="listing:{code}"` for investable listings and `security_id="benchmark:{code}"` for benchmark-only codes;
5. assign `company_id` from the explicit override map, otherwise `company_id="security:{code}"` for a stock, `fund:{code}` for an ETF, or `benchmark:{code}` for an index;
6. assign currency and market from the code prefix using `identity.py` constants;
7. set `active_from` and each member's `member_from` to its source universe `as_of` because no earlier point-in-time claim is available;
8. retain existing `shared_identity` only as legacy metadata; never use it to join exposure;
9. sort registry identities by `security_id` and preserve sector/member order in universes;
10. set `schema_version="opportunity-universe-v2"`, `published_at`, `identity_registry_version`, and a source label ending in `-migrated-v2`.

Expose a CLI:

```bash
python3 -m tools.stock_skills.foundation_migrate \
  --universe data/universes/cn.json \
  --universe data/universes/hk.json \
  --universe data/universes/us.json \
  --company-overrides data/identities/company-overrides.json \
  --published-at 2026-08-03T18:00:00+08:00 \
  --identity-output data/identities/securities-v1.json \
  --write-universes
```

The command must write through temporary sibling files followed by `Path.replace()` so an interrupted migration cannot leave partial JSON. It must refuse `--write-universes` if any input is already v2 unless `--verify-only` is supplied.

- [ ] **Step 4: Add explicit economic-identity overrides**

Create `data/identities/company-overrides.json`:

```json
{
  "schema_version": "company-identity-overrides-v1",
  "source": "manual-explicit-cross-listing-map",
  "company_codes": {
    "company:byd": ["HK.01211", "SZ.002594"],
    "company:smic": ["HK.00981", "SH.688981"],
    "company:zijin": ["HK.02899", "SH.601899"]
  }
}
```

Do not add Alibaba or XPeng cross-market pairs unless both listings exist in the configured input set. A later broad-universe project can add them from an approved security master.

- [ ] **Step 5: Run migration tests, then migrate the three current files**

```bash
python3 -m unittest tests.test_foundation_migrate -v
python3 -m tools.stock_skills.foundation_migrate --universe data/universes/cn.json --universe data/universes/hk.json --universe data/universes/us.json --company-overrides data/identities/company-overrides.json --published-at 2026-08-03T18:00:00+08:00 --identity-output data/identities/securities-v1.json --write-universes
```

Expected: tests pass; the command reports three migrated universes and one generated registry. No other data file changes.

- [ ] **Step 6: Verify deterministic data and existing discovery behavior**

```bash
python3 -m tools.stock_skills.foundation_migrate --universe data/universes/cn.json --universe data/universes/hk.json --universe data/universes/us.json --company-overrides data/identities/company-overrides.json --published-at 2026-08-03T18:00:00+08:00 --identity-output data/identities/securities-v1.json --verify-only
python3 -m unittest tests.test_identity tests.test_foundation_migrate tests.test_opportunity_discovery -v
git diff --check
```

Expected: verify-only reports no drift, tests pass, and `git diff --check` is silent.

- [ ] **Step 7: Commit migration code and versioned data**

```bash
git add tools/stock_skills/foundation_migrate.py tests/test_foundation_migrate.py data/identities/company-overrides.json data/identities/securities-v1.json data/universes/cn.json data/universes/hk.json data/universes/us.json
git commit -m "data: migrate configured universes to identity v2"
```

### Task 4: Freeze Immutable Point-in-Time Evidence Packages

**Files:**

- Create: `tools/stock_skills/point_in_time.py`
- Create: `tests/test_point_in_time.py`

- [ ] **Step 1: Write failing package and run-binding tests**

Create `tests/test_point_in_time.py`:

```python
import unittest

from tools.stock_skills.point_in_time import (
    EvidenceStamp,
    ModelRelease,
    PointInTimeInput,
    bind_shadow_pair,
)


class PointInTimeTests(unittest.TestCase):
    def _stamp(self, component="snapshot", status="available", observed_at=None):
        missing = status == "missing"
        conflicting = status == "conflicting"
        return EvidenceStamp(
            component=component,
            status=status,
            source=None if missing else "futu-opend",
            observed_at=None if missing else (observed_at or "2026-08-03T10:00:00+08:00"),
            published_at=None,
            captured_at="2026-08-03T10:00:02+08:00",
            source_ref=None if missing else "futu:snapshot",
            adjustment_basis=None if missing else "none",
            conflict_refs=("futu:snapshot", "exchange:filing") if conflicting else (),
        )

    def test_package_digest_is_order_stable_and_source_payload_is_copied(self):
        source = {"snapshot": {"last_price": 445.0, "code": "HK.00700"}}
        first = PointInTimeInput.build(
            code="HK.00700",
            security_id="listing:HK.00700",
            company_id="company:tencent",
            market="HK",
            as_of="2026-08-03T10:00:00+08:00",
            captured_at="2026-08-03T10:00:02+08:00",
            session_phase="intraday",
            universe_version="universe:test",
            identity_version="identity:test",
            payload=source,
            evidence=(self._stamp(),),
        )
        second = PointInTimeInput.build(
            code="HK.00700",
            security_id="listing:HK.00700",
            company_id="company:tencent",
            market="HK",
            as_of="2026-08-03T10:00:00+08:00",
            captured_at="2026-08-03T10:00:02+08:00",
            session_phase="intraday",
            universe_version="universe:test",
            identity_version="identity:test",
            payload={"snapshot": {"code": "HK.00700", "last_price": 445.0}},
            evidence=(self._stamp(),),
        )
        source["snapshot"]["last_price"] = 999.0

        self.assertEqual(first.input_digest, second.input_digest)
        self.assertEqual(first.package_id, second.package_id)
        self.assertEqual(first.payload()["snapshot"]["last_price"], 445.0)

    def test_future_observation_and_future_publication_are_rejected(self):
        future_observation = self._stamp(observed_at="2026-08-03T10:00:01+08:00")
        future_publication = EvidenceStamp(
            component="financials",
            status="available",
            source="official-filing",
            observed_at="2026-06-30T00:00:00+08:00",
            published_at="2026-08-03T10:00:01+08:00",
            captured_at="2026-08-03T10:00:02+08:00",
            source_ref="exchange:filing",
            adjustment_basis="reported",
            conflict_refs=(),
        )

        for stamp in (future_observation, future_publication):
            with self.subTest(component=stamp.component):
                with self.assertRaisesRegex(ValueError, "after package as_of"):
                    PointInTimeInput.build(
                        code="HK.00700",
                        security_id="listing:HK.00700",
                        company_id="company:tencent",
                        market="HK",
                        as_of="2026-08-03T10:00:00+08:00",
                        captured_at="2026-08-03T10:00:02+08:00",
                        session_phase="intraday",
                        universe_version="universe:test",
                        identity_version="identity:test",
                        payload={},
                        evidence=(stamp,),
                    )

    def test_missing_stale_and_conflicting_are_preserved_as_states(self):
        package = PointInTimeInput.build(
            code="HK.00700",
            security_id="listing:HK.00700",
            company_id="company:tencent",
            market="HK",
            as_of="2026-08-03T10:00:00+08:00",
            captured_at="2026-08-03T10:00:02+08:00",
            session_phase="intraday",
            universe_version="universe:test",
            identity_version="identity:test",
            payload={},
            evidence=(
                self._stamp("capital", "stale"),
                self._stamp("financials", "missing"),
                self._stamp("identity", "conflicting"),
            ),
        )

        self.assertEqual(package.missing_components, ("financials",))
        self.assertEqual(package.stale_components, ("capital",))
        self.assertEqual(package.conflicting_components, ("identity",))

    def test_champion_and_challenger_bind_to_identical_input(self):
        package = PointInTimeInput.build(
            code="HK.00700",
            security_id="listing:HK.00700",
            company_id="company:tencent",
            market="HK",
            as_of="2026-08-03T10:00:00+08:00",
            captured_at="2026-08-03T10:00:02+08:00",
            session_phase="intraday",
            universe_version="universe:test",
            identity_version="identity:test",
            payload={},
            evidence=(self._stamp(),),
        )
        champion, challenger = bind_shadow_pair(
            package,
            ModelRelease("stock-analysis-v6", "logic-first-method-evidence-v6", "recommendation-v6"),
            ModelRelease("stock-analysis-v7-shadow", "stock-analysis-v7-shadow-v1", "recommendation-v7-shadow-v1"),
        )

        self.assertEqual(champion.input_package_id, challenger.input_package_id)
        self.assertEqual(champion.input_digest, challenger.input_digest)
        self.assertNotEqual(champion.model_release, challenger.model_release)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the red state**

```bash
python3 -m unittest tests.test_point_in_time -v
```

Expected: import failure for `tools.stock_skills.point_in_time`.

- [ ] **Step 3: Implement explicit evidence states and cutoff validation**

Create `tools/stock_skills/point_in_time.py` with:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .markets import market_moment, normalize_market


INPUT_SCHEMA_VERSION = "analysis-input-v1"
EVIDENCE_STATUSES = frozenset({"available", "missing", "stale", "conflicting"})


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class EvidenceStamp:
    component: str
    status: str
    source: str | None
    observed_at: str | None
    published_at: str | None
    captured_at: str
    source_ref: str | None
    adjustment_basis: str | None
    conflict_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError(f"Unsupported evidence status: {self.status!r}")
        if self.status == "missing" and any(
            value is not None for value in (
                self.observed_at, self.source, self.source_ref, self.adjustment_basis
            )
        ):
            raise ValueError("Missing evidence cannot claim an observation, source, or basis")
        if self.status != "missing" and (self.observed_at is None or self.source is None):
            raise ValueError(f"{self.status} evidence requires source and observed_at")
        if self.status == "conflicting" and len(self.conflict_refs) < 2:
            raise ValueError("Conflicting evidence requires at least two source references")
        if self.status != "conflicting" and self.conflict_refs:
            raise ValueError("Only conflicting evidence may carry conflict_refs")


@dataclass(frozen=True)
class PointInTimeInput:
    package_id: str
    input_digest: str
    code: str
    security_id: str
    company_id: str
    market: str
    as_of: str
    captured_at: str
    session_phase: str
    universe_version: str
    identity_version: str
    payload_json: str
    evidence: tuple[EvidenceStamp, ...]
    schema_version: str = INPUT_SCHEMA_VERSION

    @classmethod
    def build(
        cls,
        *,
        code: str,
        security_id: str,
        company_id: str,
        market: str,
        as_of: str,
        captured_at: str,
        session_phase: str,
        universe_version: str,
        identity_version: str,
        payload: Mapping[str, Any],
        evidence: tuple[EvidenceStamp, ...],
    ) -> "PointInTimeInput":
        market = normalize_market(market)
        cutoff = market_moment(as_of, market)
        package_capture = market_moment(captured_at, market)
        for stamp in evidence:
            stamp_capture = market_moment(stamp.captured_at, market)
            if stamp_capture > package_capture:
                raise ValueError(f"Evidence capture is after package captured_at: {stamp.component}")
            for label, value in (("observation", stamp.observed_at), ("publication", stamp.published_at)):
                if value is None:
                    continue
                evidence_moment = market_moment(value, market)
                if evidence_moment > cutoff:
                    raise ValueError(f"Evidence {label} is after package as_of: {stamp.component}")
                if evidence_moment > stamp_capture:
                    raise ValueError(f"Evidence {label} is after its captured_at: {stamp.component}")
        payload_json = _canonical(payload)
        material = {
            "schema_version": INPUT_SCHEMA_VERSION,
            "code": code,
            "security_id": security_id,
            "company_id": company_id,
            "market": market,
            "as_of": as_of,
            "captured_at": captured_at,
            "session_phase": session_phase,
            "universe_version": universe_version,
            "identity_version": identity_version,
            "payload": json.loads(payload_json),
            "evidence": [asdict(stamp) for stamp in sorted(evidence, key=lambda item: item.component)],
        }
        digest = hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()
        return cls(
            package_id=f"input:{digest}",
            input_digest=digest,
            code=code,
            security_id=security_id,
            company_id=company_id,
            market=market,
            as_of=as_of,
            captured_at=captured_at,
            session_phase=session_phase,
            universe_version=universe_version,
            identity_version=identity_version,
            payload_json=payload_json,
            evidence=tuple(sorted(evidence, key=lambda item: item.component)),
        )

    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    def components_with_status(self, status: str) -> tuple[str, ...]:
        return tuple(stamp.component for stamp in self.evidence if stamp.status == status)

    @property
    def missing_components(self) -> tuple[str, ...]:
        return self.components_with_status("missing")

    @property
    def stale_components(self) -> tuple[str, ...]:
        return self.components_with_status("stale")

    @property
    def conflicting_components(self) -> tuple[str, ...]:
        return self.components_with_status("conflicting")
```

Reject duplicate `component` names, unsupported markets, a `captured_at` earlier than any observation/publication it claims to have captured, and a malformed package ID during deserialization. `captured_at` may legitimately be later than `as_of` for a historical replay, so it is audit metadata rather than an evidence cutoff. Add `to_record()` and `point_in_time_input_from_record()`; the reader must recompute the digest and reject any mismatch.

- [ ] **Step 4: Implement model release and shared-input bindings**

In the same module:

```python
@dataclass(frozen=True)
class ModelRelease:
    model_id: str
    decision_policy: str
    output_schema: str


@dataclass(frozen=True)
class AnalysisRunBinding:
    model_release: ModelRelease
    input_package_id: str
    input_digest: str


def bind_shadow_pair(
    package: PointInTimeInput,
    champion: ModelRelease,
    challenger: ModelRelease,
) -> tuple[AnalysisRunBinding, AnalysisRunBinding]:
    if champion.model_id == challenger.model_id:
        raise ValueError("Champion and challenger must use distinct model IDs")
    return (
        AnalysisRunBinding(champion, package.package_id, package.input_digest),
        AnalysisRunBinding(challenger, package.package_id, package.input_digest),
    )
```

This binding is metadata only. Do not call the v7 scorer here and do not bump constants in `models.py`.

- [ ] **Step 5: Run focused tests and serialization round-trip**

```bash
python3 -m unittest tests.test_point_in_time -v
```

Expected: four tests pass, including future-evidence rejection and identical shadow bindings.

- [ ] **Step 6: Commit the immutable input contract**

```bash
git add tools/stock_skills/point_in_time.py tests/test_point_in_time.py
git commit -m "feat: freeze point-in-time analysis inputs"
```

### Task 5: Validate Identities and Universes as One Read-Only Foundation

**Files:**

- Create: `tools/stock_skills/foundation_validation.py`
- Create: `tests/test_foundation_validation.py`
- Modify: `tools/stock_skills/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing cross-file validation tests**

Create `tests/test_foundation_validation.py`:

```python
import unittest

from tools.stock_skills.foundation_validation import validate_foundation
from tools.stock_skills.identity import IdentityRegistry, SecurityIdentity
from tools.stock_skills.universe import MarketUniverse, SectorUniverse, UniverseMember


class FoundationValidationTests(unittest.TestCase):
    def _registry(self):
        return IdentityRegistry(
            published_at="2026-08-03T08:00:00+08:00",
            identities=(
                SecurityIdentity(
                    "listing:HK.00700", "company:tencent", "HK.00700", "腾讯控股",
                    "HK", "ordinary-stock", "HKD", "2004-06-16T09:30:00+08:00",
                ),
                SecurityIdentity(
                    "benchmark:HK.800000", "benchmark:hsi", "HK.800000", "恒生指数",
                    "HK", "benchmark-index", "HKD", "1969-11-24T09:30:00+08:00",
                ),
            ),
        )

    def _universe(self, identity_version):
        return MarketUniverse(
            market="HK",
            as_of="2026-08-03T08:00:00+08:00",
            source="fixture",
            sectors=(
                SectorUniverse(
                    "internet", "互联网", "HK.00700", "HK.800000",
                    (
                        UniverseMember(
                            "HK.00700", "腾讯控股", "leader", 1.0, None,
                            "listing:HK.00700", "2026-08-03T08:00:00+08:00", None,
                        ),
                    ),
                ),
            ),
            schema_version="opportunity-universe-v2",
            published_at="2026-08-03T08:00:00+08:00",
            identity_registry_version=identity_version,
        )

    def test_valid_foundation_reports_active_investable_and_reference_counts(self):
        registry = self._registry()
        report = validate_foundation(
            registry,
            (self._universe(registry.version_id),),
            as_of="2026-08-03T10:00:00+08:00",
        )

        self.assertTrue(report["ready"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["markets"][0]["investable_members"], 1)
        self.assertEqual(report["markets"][0]["reference_codes"], 1)

    def test_missing_identity_and_version_mismatch_are_errors(self):
        registry = self._registry()
        universe = self._universe("identity:wrong")
        sector = universe.sectors[0]
        broken = MarketUniverse(
            market=universe.market,
            as_of=universe.as_of,
            source=universe.source,
            sectors=(
                SectorUniverse(
                    sector.key, sector.name, "HK.MISSING", sector.benchmark,
                    sector.members + (
                        UniverseMember(
                            "HK.MISSING", "Missing", "constituent", 1.0, None,
                            "listing:HK.MISSING", universe.as_of, None,
                        ),
                    ),
                ),
            ),
            schema_version=universe.schema_version,
            published_at=universe.published_at,
            identity_registry_version=universe.identity_registry_version,
        )

        report = validate_foundation(
            registry, (broken,), as_of="2026-08-03T10:00:00+08:00"
        )

        self.assertFalse(report["ready"])
        self.assertTrue(any("identity registry version" in error for error in report["errors"]))
        self.assertTrue(any("HK.MISSING" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify the red state**

```bash
python3 -m unittest tests.test_foundation_validation -v
```

Expected: import failure for `tools.stock_skills.foundation_validation`.

- [ ] **Step 3: Implement deterministic validation**

`validate_foundation(registry, universes, as_of)` returns:

```python
{
    "schema_version": "stock-analysis-foundation-validation-v1",
    "as_of": as_of,
    "identity_version": registry.version_id,
    "ready": not errors,
    "markets": market_rows,
    "errors": sorted(errors),
    "warnings": sorted(warnings),
}
```

For every universe it must:

- reject a universe publication or registry publication after `as_of`;
- require `identity_registry_version == registry.version_id` for v2;
- resolve every active member and benchmark in the registry at `as_of`;
- require member `security_id` to match the registry identity;
- reject non-investable active members;
- require benchmarks to be `benchmark-index` or `unleveraged-etf` references;
- report zero-active-member sectors as errors because expired membership disables that slice;
- report duplicate markets and duplicate sector keys as errors;
- return counts for active investable members, reference codes, sectors, and shared-company groups;
- sort markets by `CN`, `HK`, `US` and sort all diagnostics for reproducibility.

Validation does not fetch or score anything and never mutates its inputs.

- [ ] **Step 4: Add the `foundation-check` CLI and its tests**

Add `_cmd_foundation_check(args)` to `tools/stock_skills/cli.py`. It loads the registry and each repeated `--universe` path, calls `validate_foundation`, writes the same JSON to stdout and optional `--output`, and returns `0` when `ready` is true or `1` otherwise.

Register:

```python
foundation = subparsers.add_parser(
    "foundation-check",
    help="Validate point-in-time identity and universe contracts without fetching or scoring",
)
foundation.add_argument("--identity-registry", required=True)
foundation.add_argument("--universe", action="append", required=True)
foundation.add_argument("--as-of", required=True)
foundation.add_argument("--output", default=None)
```

Add dispatch before the final `return 2`:

```python
if args.command == "foundation-check":
    return _cmd_foundation_check(args)
```

In `tests/test_cli.py`, use `tempfile.TemporaryDirectory()` and the data produced by `migrate_universes` to assert:

- valid files return `0` and emit `ready: true`;
- a universe with a wrong registry version returns `1` and emits `ready: false`;
- `foundation-check` does not construct or patch `FutuFetcher`.

- [ ] **Step 5: Run focused validation and CLI tests**

```bash
python3 -m unittest tests.test_foundation_validation tests.test_cli -v
```

Expected: all validation tests and all existing CLI tests pass.

- [ ] **Step 6: Run the real configured-data check**

```bash
python3 -m tools.stock_skills.cli foundation-check --identity-registry data/identities/securities-v1.json --universe data/universes/cn.json --universe data/universes/hk.json --universe data/universes/us.json --as-of 2026-08-03T18:00:00+08:00 --output /tmp/stock-analysis-v7-foundation.json
```

Expected: exit code `0`; JSON contains `"ready": true`, three market rows, no errors, and the same identity version referenced by all three universes.

- [ ] **Step 7: Commit validation and CLI wiring**

```bash
git add tools/stock_skills/foundation_validation.py tools/stock_skills/cli.py tests/test_foundation_validation.py tests/test_cli.py
git commit -m "feat: validate stock analysis foundation contracts"
```

### Task 6: Prove the Input Factory Rejects Lookahead Without Changing v6

**Files:**

- Modify: `tools/stock_skills/point_in_time.py`
- Modify: `tools/stock_skills/discovery_runtime.py`
- Modify: `tests/test_point_in_time.py`
- Modify: `tests/test_opportunity_discovery.py`

- [ ] **Step 1: Add failing tests for completed bars and one-time package creation**

Add to `tests/test_point_in_time.py`:

```python
    def test_bar_payload_rejects_any_bar_after_as_of(self):
        with self.assertRaisesRegex(ValueError, "bar is after package as_of"):
            PointInTimeInput.build_market_payload(
                code="US.NVDA",
                security_id="listing:US.NVDA",
                company_id="security:US.NVDA",
                market="US",
                as_of="2026-08-03T16:00:00-04:00",
                captured_at="2026-08-03T16:00:02-04:00",
                session_phase="after-close",
                universe_version="universe:test",
                identity_version="identity:test",
                snapshot={"timestamp": "2026-08-03T16:00:00-04:00", "last_price": 100.0},
                daily_bars=[
                    {"time": "2026-08-03T00:00:00-04:00", "close": 100.0},
                    {"time": "2026-08-04T00:00:00-04:00", "close": 101.0},
                ],
                intraday_bars=[],
                evidence=(
                    EvidenceStamp(
                        component="snapshot",
                        status="available",
                        source="futu-opend",
                        observed_at="2026-08-03T16:00:00-04:00",
                        published_at=None,
                        captured_at="2026-08-03T16:00:02-04:00",
                        source_ref="futu:snapshot",
                        adjustment_basis="none",
                        conflict_refs=(),
                    ),
                ),
            )
```

Add an offline discovery-runtime test that patches `PointInTimeInput.build_market_payload`, invokes a new `freeze_discovery_inputs(...)` once, then binds champion and challenger from the returned package. Assert one builder call and equal package IDs. Do not route `discover` through this function yet.

- [ ] **Step 2: Run the two focused tests and verify the red state**

```bash
python3 -m unittest tests.test_point_in_time.PointInTimeTests.test_bar_payload_rejects_any_bar_after_as_of tests.test_opportunity_discovery.OpportunityDiscoveryTests.test_shadow_bindings_share_one_frozen_discovery_input -v
```

Expected: failures for missing `build_market_payload` and `freeze_discovery_inputs`.

- [ ] **Step 3: Implement a market-payload factory with explicit adjustment basis**

`PointInTimeInput.build_market_payload(...)` must:

- accept already-fetched snapshot, completed daily bars, completed intraday bars, capital, financial, sector, macro, and cross-market records;
- accept no fetcher or callback;
- validate every snapshot timestamp and every bar `time` against `as_of`;
- require one explicit `adjustment_basis` value per K-line collection;
- preserve empty collections and record their evidence component as `missing`;
- sort bars chronologically before canonicalization;
- delegate to `PointInTimeInput.build()` exactly once.

Add `freeze_discovery_inputs(...)` in `discovery_runtime.py` as a thin offline adapter from existing `MarketUniverse`, identity, snapshot/bar records, and evidence stamps to the package factory. It must not fetch, refresh, score, write a store, or mutate bars.

- [ ] **Step 4: Re-run focused and existing no-lookahead tests**

```bash
python3 -m unittest tests.test_point_in_time tests.test_opportunity_discovery -v
```

Expected: all tests pass. Existing `test_golden_star50_replay_is_armed_without_lookahead` continues to produce the same v6 candidate result.

- [ ] **Step 5: Prove v6 policy constants and golden output did not change**

```bash
python3 -c "from tools.stock_skills.models import SCHEMA_VERSION, DECISION_POLICY; assert SCHEMA_VERSION == 'recommendation-v6'; assert DECISION_POLICY == 'logic-first-method-evidence-v6'; print(SCHEMA_VERSION, DECISION_POLICY)"
python3 -m unittest tests.test_models tests.test_strategy tests.test_engine tests.test_opportunity_discovery -v
```

Expected: prints `recommendation-v6 logic-first-method-evidence-v6`; all tests pass.

- [ ] **Step 6: Commit the offline input factory**

```bash
git add tools/stock_skills/point_in_time.py tools/stock_skills/discovery_runtime.py tests/test_point_in_time.py tests/test_opportunity_discovery.py
git commit -m "feat: freeze shared shadow analysis inputs"
```

### Task 7: Document, Audit, and Verify the Phase-1 Boundary

**Files:**

- Modify: `docs/self-evolving-stock-skills-usage.md`

- [ ] **Step 1: Document the read-only foundation command**

Add a section named `v7 shadow foundation` explaining:

- v6 remains production champion;
- identity `company_id` prevents false A/H diversification;
- universe v2 and the registry are point-in-time and content-addressed;
- `foundation-check` is offline and read-only;
- an input package is immutable, auditable, and shared by model bindings;
- no v7 score or recommendation exists yet;
- later phases must not bypass the foundation validator.

Include the exact real-data command from Task 5.

- [ ] **Step 2: Run the foundation test slice**

```bash
python3 -m unittest tests.test_identity tests.test_foundation_migrate tests.test_point_in_time tests.test_foundation_validation tests.test_opportunity_discovery tests.test_cli -v
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the complete regression suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass with no v6 recommendation or policy snapshot changes.

- [ ] **Step 4: Audit schema, policy, lookahead, and placeholder invariants**

```bash
python3 -c "from tools.stock_skills.models import SCHEMA_VERSION, DECISION_POLICY; assert (SCHEMA_VERSION, DECISION_POLICY) == ('recommendation-v6', 'logic-first-method-evidence-v6')"
python3 -m tools.stock_skills.cli foundation-check --identity-registry data/identities/securities-v1.json --universe data/universes/cn.json --universe data/universes/hk.json --universe data/universes/us.json --as-of 2026-08-03T18:00:00+08:00
rg -n "TODO|FIXME|pass$|NotImplemented" tools/stock_skills/identity.py tools/stock_skills/point_in_time.py tools/stock_skills/foundation_migrate.py tools/stock_skills/foundation_validation.py
git diff --check
git status --short
```

Expected:

- schema and decision-policy assertion succeeds;
- foundation JSON reports `ready: true`;
- placeholder scan returns no matches;
- `git diff --check` is silent;
- `data/watchlists/active-sector-pool.json` remains unrelated and unstaged.

- [ ] **Step 5: Inspect the final diff for scope creep**

```bash
git diff --stat main...HEAD
git diff main...HEAD -- tools/stock_skills/models.py tools/stock_skills/strategy.py data/models/signal_weights.json
```

Expected: the first command contains only the phase-1 file map; the second command is empty. If it is not empty, revert that phase-1 scope violation before completion.

- [ ] **Step 6: Commit documentation**

```bash
git add docs/self-evolving-stock-skills-usage.md
git commit -m "docs: explain v7 point-in-time foundation"
```

## Phase-1 Acceptance Checklist

- [ ] Every configured CN/HK/US member and benchmark resolves through one versioned identity registry.
- [ ] A/H economic duplicates use a common `company_id` and distinct `security_id` values.
- [ ] Only ordinary stocks and unleveraged ETFs are investable; benchmark indexes remain context-only.
- [ ] Legacy universe v1 fixtures still load, while migrated production universes use v2.
- [ ] Future membership, future observations, and future financial publication dates are rejected.
- [ ] Missing, stale, and conflicting evidence remain explicit non-neutral states.
- [ ] Input payload mutation after construction cannot change stored bytes or digest.
- [ ] Champion and challenger run bindings use one package ID and one digest.
- [ ] The real `foundation-check` succeeds offline for all three configured markets.
- [ ] `recommendation-v6` and `logic-first-method-evidence-v6` remain unchanged.
- [ ] Full tests pass and the unrelated watchlist file remains untouched.

## Handoff to Phase 2

Phase 2 may build the broad three-market investability funnel only through these contracts. Its plan must add listing-master ingestion, exchange calendars, liquidity and suspension rules, ST/delisting/OTC/shell/dilution gates, corporate-action normalization, and partial-market failure isolation. It must consume `SecurityIdentity`, `MarketUniverse`, and `PointInTimeInput`; it must not duplicate their parsing, time-cutoff, or version logic.
