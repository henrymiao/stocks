from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from .identity import IdentityRegistry, SecurityIdentity
from .markets import market_moment
from .universe import MarketUniverse


VALIDATION_SCHEMA_VERSION = "stock-analysis-foundation-validation-v1"
_MARKET_ORDER = {"CN": 0, "HK": 1, "US": 2}
_REFERENCE_TYPES = frozenset({"benchmark-index", "unleveraged-etf"})


def _published_after(value: str, as_of: str, market: str) -> bool:
    return market_moment(value, market) > market_moment(as_of, market)


def _resolve(
    registry: IdentityRegistry,
    code: str,
    as_of: str,
    errors: set[str],
    *,
    context: str,
) -> SecurityIdentity | None:
    try:
        return registry.resolve(code, as_of)
    except KeyError as exc:
        errors.add(f"{context} {code} has no active identity at {as_of}: {exc}")
        return None


def validate_foundation(
    registry: IdentityRegistry,
    universes: Iterable[MarketUniverse],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Validate point-in-time identity and universe contracts without side effects."""

    universe_rows = tuple(universes)
    errors: set[str] = set()
    warnings: set[str] = set()
    if not universe_rows:
        errors.add("No market universes were supplied")

    market_counts = Counter(universe.market for universe in universe_rows)
    for market, count in market_counts.items():
        if count > 1:
            errors.add(f"Duplicate market universe: {market} ({count} inputs)")

    active_company_codes: dict[str, set[str]] = defaultdict(set)
    for identity in registry.identities:
        if identity.active_at(as_of):
            active_company_codes[identity.company_id].add(identity.code)
    shared_company_ids = {
        company_id for company_id, codes in active_company_codes.items() if len(codes) > 1
    }

    market_rows: list[dict[str, Any]] = []
    seen_sector_keys: set[tuple[str, str]] = set()
    registry_publication_checked: set[str] = set()
    for universe in universe_rows:
        market = universe.market
        if market not in registry_publication_checked:
            if _published_after(registry.published_at, as_of, market):
                errors.add(
                    f"Identity registry was published after validation as_of: "
                    f"{registry.published_at} > {as_of}"
                )
            registry_publication_checked.add(market)
        if _published_after(universe.effective_published_at, as_of, market):
            errors.add(
                f"{market} universe was published after validation as_of: "
                f"{universe.effective_published_at} > {as_of}"
            )
        if universe.schema_version == "opportunity-universe-v2":
            if universe.identity_registry_version != registry.version_id:
                errors.add(
                    f"{market} universe identity registry version "
                    f"{universe.identity_registry_version!r} does not match "
                    f"{registry.version_id!r}"
                )
        else:
            warnings.add(f"{market} universe uses legacy schema {universe.schema_version}")

        active_member_codes: set[str] = set()
        active_member_companies: set[str] = set()
        reference_codes: set[str] = set()
        for sector in universe.sectors:
            sector_key = (market, sector.key)
            if sector_key in seen_sector_keys:
                errors.add(f"Duplicate sector key for {market}: {sector.key}")
            seen_sector_keys.add(sector_key)

            active_members = tuple(
                member for member in sector.members if member.active_at(as_of, market)
            )
            if not active_members:
                errors.add(f"{market}/{sector.key} has zero active members at {as_of}")
            for member in active_members:
                identity = _resolve(
                    registry,
                    member.code,
                    as_of,
                    errors,
                    context=f"{market}/{sector.key} member",
                )
                if identity is None:
                    continue
                if member.security_id != identity.security_id:
                    errors.add(
                        f"{market}/{sector.key} member {member.code} security_id "
                        f"{member.security_id!r} does not match {identity.security_id!r}"
                    )
                if not identity.investable:
                    errors.add(
                        f"{market}/{sector.key} member {member.code} is not investable "
                        f"({identity.instrument_type})"
                    )
                    continue
                active_member_codes.add(member.code)
                active_member_companies.add(identity.company_id)

            benchmark = _resolve(
                registry,
                sector.benchmark,
                as_of,
                errors,
                context=f"{market}/{sector.key} benchmark",
            )
            if benchmark is not None:
                if benchmark.instrument_type not in _REFERENCE_TYPES:
                    errors.add(
                        f"{market}/{sector.key} benchmark {sector.benchmark} has invalid "
                        f"reference type {benchmark.instrument_type}"
                    )
                else:
                    reference_codes.add(sector.benchmark)

        market_rows.append(
            {
                "market": market,
                "universe_version": universe.version_id,
                "sectors": len(universe.sectors),
                "investable_members": len(active_member_codes),
                "reference_codes": len(reference_codes),
                "shared_company_groups": len(active_member_companies & shared_company_ids),
            }
        )

    market_rows.sort(
        key=lambda row: (_MARKET_ORDER.get(str(row["market"]), 99), str(row["market"]))
    )
    sorted_errors = sorted(errors)
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "as_of": as_of,
        "identity_version": registry.version_id,
        "ready": not sorted_errors,
        "markets": market_rows,
        "errors": sorted_errors,
        "warnings": sorted(warnings),
    }
