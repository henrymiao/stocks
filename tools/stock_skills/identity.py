from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
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
        if not self.security_id or not self.company_id:
            raise ValueError("security_id and company_id are required")
        prefix = self.code.split(".", 1)[0].upper() if "." in self.code else ""
        if prefix not in MARKET_PREFIXES[market]:
            raise ValueError(f"{self.code!r} does not belong to {market}")
        if self.instrument_type not in INSTRUMENT_TYPES:
            raise ValueError(f"Unsupported instrument type: {self.instrument_type!r}")
        if self.currency != MARKET_CURRENCIES[market]:
            raise ValueError(f"{self.code!r} must use {MARKET_CURRENCIES[market]}")
        start = market_moment(self.active_from, market)
        if self.active_to is not None and market_moment(self.active_to, market) <= start:
            raise ValueError("active_to must be later than active_from")

    @property
    def investable(self) -> bool:
        return self.instrument_type in INVESTABLE_INSTRUMENT_TYPES

    def active_at(self, at: str) -> bool:
        moment = market_moment(at, self.market)
        start = market_moment(self.active_from, self.market)
        end = None if self.active_to is None else market_moment(self.active_to, self.market)
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

    def _material_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "published_at": self.published_at,
            "identities": [
                asdict(identity)
                for identity in sorted(self.identities, key=lambda item: item.security_id)
            ],
        }

    @property
    def version_id(self) -> str:
        digest = hashlib.sha256(
            _canonical_json(self._material_record()).encode("utf-8")
        ).hexdigest()
        return f"identity:{digest}"

    def resolve(self, code: str, at: str) -> SecurityIdentity:
        match = next((identity for identity in self.identities if identity.code == code), None)
        if match is None:
            raise KeyError(f"Unknown identity code: {code}")
        if not match.active_at(at):
            raise KeyError(f"Identity {code} is not active at {at}")
        return match

    def company_codes(self, company_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                identity.code
                for identity in self.identities
                if identity.company_id == company_id
            )
        )

    def to_record(self) -> dict[str, Any]:
        record = self._material_record()
        record["version_id"] = self.version_id
        return record


def identity_registry_from_record(payload: dict[str, Any]) -> IdentityRegistry:
    if not isinstance(payload, dict):
        raise ValueError("Identity registry payload must be an object")
    rows = payload.get("identities", [])
    if not isinstance(rows, list):
        raise ValueError("Identity registry identities must be a list")
    return IdentityRegistry(
        published_at=str(payload["published_at"]),
        identities=tuple(SecurityIdentity(**row) for row in rows),
        schema_version=str(payload.get("schema_version", IDENTITY_SCHEMA_VERSION)),
    )


def load_identity_registry(path: str | Path) -> IdentityRegistry:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    registry = identity_registry_from_record(payload)
    persisted_version = payload.get("version_id")
    if persisted_version is not None and persisted_version != registry.version_id:
        raise ValueError(
            f"Identity registry version_id mismatch: {persisted_version} != {registry.version_id}"
        )
    return registry


def save_identity_registry(path: str | Path, registry: IdentityRegistry) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(registry.to_record(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
