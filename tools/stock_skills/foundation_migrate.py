from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Iterable

from .identity import IdentityRegistry, SecurityIdentity
from .markets import market_currency, market_from_code
from .universe import universe_from_record


UNIVERSE_V1 = "opportunity-universe-v1"
UNIVERSE_V2 = "opportunity-universe-v2"


def _override_index(company_overrides: dict[str, list[str]]) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for company_id, codes in sorted(company_overrides.items()):
        for raw_code in codes:
            code = str(raw_code)
            previous = assignments.get(code)
            if previous is not None and previous != company_id:
                raise ValueError(
                    f"{code} is assigned to multiple company IDs: "
                    f"{previous!r} and {company_id!r}"
                )
            assignments[code] = str(company_id)
    return assignments


def _migrated_source(source: object) -> str:
    label = str(source or "configured")
    return label if label.endswith("-migrated-v2") else f"{label}-migrated-v2"


def _member_type(role: object) -> str:
    return "unleveraged-etf" if str(role) == "etf" else "ordinary-stock"


def migrate_universes(
    universes: dict[str, dict[str, Any]],
    company_overrides: dict[str, list[str]],
    *,
    published_at: str,
) -> tuple[dict[str, dict[str, Any]], IdentityRegistry]:
    """Migrate configured universes without inferring cross-listing identity.

    A listing is linked to an economic company only through ``company_overrides``.
    Legacy ``shared_identity`` values remain universe metadata and never influence
    registry joins.
    """

    override_by_code = _override_index(company_overrides)
    code_facts: dict[str, dict[str, Any]] = {}

    for map_key, payload in universes.items():
        if not isinstance(payload, dict):
            raise ValueError(f"Universe {map_key!r} must be an object")
        schema_version = str(payload.get("schema_version", UNIVERSE_V1))
        if schema_version not in {UNIVERSE_V1, UNIVERSE_V2}:
            raise ValueError(f"Unsupported universe schema: {schema_version!r}")
        as_of = str(payload["as_of"])
        for sector in payload.get("sectors", []):
            for member in sector.get("members", []):
                code = str(member["code"])
                instrument_type = _member_type(member.get("role", "constituent"))
                existing = code_facts.get(code)
                if existing is not None and existing["instrument_type"] != instrument_type:
                    raise ValueError(
                        f"{code} has conflicting instrument types: "
                        f"{existing['instrument_type']} and {instrument_type}"
                    )
                code_facts.setdefault(
                    code,
                    {
                        "name": str(member.get("name") or code),
                        "instrument_type": instrument_type,
                        "active_from": str(member.get("member_from") or as_of),
                    },
                )
            benchmark = str(sector["benchmark"])
            code_facts.setdefault(
                benchmark,
                {
                    "name": benchmark,
                    "instrument_type": "benchmark-index",
                    "active_from": as_of,
                },
            )

    identities: list[SecurityIdentity] = []
    for code, facts in code_facts.items():
        instrument_type = str(facts["instrument_type"])
        security_id = (
            f"benchmark:{code}"
            if instrument_type == "benchmark-index"
            else f"listing:{code}"
        )
        default_company_prefix = {
            "ordinary-stock": "security",
            "unleveraged-etf": "fund",
            "benchmark-index": "benchmark",
        }[instrument_type]
        market = market_from_code(code)
        identities.append(
            SecurityIdentity(
                security_id=security_id,
                company_id=override_by_code.get(code, f"{default_company_prefix}:{code}"),
                code=code,
                name=str(facts["name"]),
                market=market,
                instrument_type=instrument_type,
                currency=market_currency(market),
                active_from=str(facts["active_from"]),
            )
        )

    registry = IdentityRegistry(
        published_at=published_at,
        identities=tuple(sorted(identities, key=lambda item: item.security_id)),
    )

    migrated: dict[str, dict[str, Any]] = {}
    for map_key, payload in universes.items():
        record = copy.deepcopy(payload)
        as_of = str(record["as_of"])
        for sector in record.get("sectors", []):
            for member in sector.get("members", []):
                member["security_id"] = f"listing:{member['code']}"
                member["member_from"] = str(member.get("member_from") or as_of)
        record["schema_version"] = UNIVERSE_V2
        record["published_at"] = published_at
        record["identity_registry_version"] = registry.version_id
        record["source"] = _migrated_source(record.get("source"))
        record.pop("version_id", None)
        migrated[str(map_key)] = universe_from_record(record).to_record()

    return migrated, registry


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_overrides(path: Path) -> dict[str, list[str]]:
    payload = _load_json(path)
    raw = payload.get("company_codes", payload)
    if not isinstance(raw, dict):
        raise ValueError("Company overrides must contain a company_codes object")
    return {str(company_id): [str(code) for code in codes] for company_id, codes in raw.items()}


def _universe_map(paths: Iterable[Path]) -> tuple[dict[str, dict[str, Any]], dict[str, Path]]:
    universes: dict[str, dict[str, Any]] = {}
    market_paths: dict[str, Path] = {}
    for path in paths:
        payload = _load_json(path)
        market = str(payload["market"]).upper()
        if market in universes:
            raise ValueError(f"Duplicate universe market: {market}")
        universes[market] = payload
        market_paths[market] = path
    return universes, market_paths


def _verify_no_drift(
    original_universes: dict[str, dict[str, Any]],
    migrated_universes: dict[str, dict[str, Any]],
    identity_path: Path,
    registry: IdentityRegistry,
) -> None:
    drift = [
        market
        for market in sorted(original_universes)
        if original_universes[market] != migrated_universes[market]
    ]
    expected_registry = registry.to_record()
    if not identity_path.is_file() or _load_json(identity_path) != expected_registry:
        drift.append(str(identity_path))
    if drift:
        raise RuntimeError(f"Foundation data drift detected: {', '.join(drift)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate configured universes to v2")
    parser.add_argument("--universe", action="append", required=True, type=Path)
    parser.add_argument("--company-overrides", required=True, type=Path)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--identity-output", required=True, type=Path)
    parser.add_argument("--write-universes", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    universes, market_paths = _universe_map(args.universe)
    if args.write_universes and not args.verify_only:
        already_v2 = [
            market
            for market, payload in universes.items()
            if payload.get("schema_version") == UNIVERSE_V2
        ]
        if already_v2:
            raise RuntimeError(
                "Refusing to rewrite already-v2 universes without --verify-only: "
                + ", ".join(sorted(already_v2))
            )

    migrated, registry = migrate_universes(
        universes,
        _load_overrides(args.company_overrides),
        published_at=args.published_at,
    )
    if args.verify_only:
        _verify_no_drift(universes, migrated, args.identity_output, registry)
        print(f"Foundation data has no drift ({len(migrated)} universes)")
        return 0
    if args.write_universes:
        _atomic_json_write(args.identity_output, registry.to_record())
        for market in sorted(migrated):
            _atomic_json_write(market_paths[market], migrated[market])
        print(
            f"Migrated {len(migrated)} universes and generated "
            f"{args.identity_output}"
        )
        return 0

    print(json.dumps({"universes": migrated, "registry": registry.to_record()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
