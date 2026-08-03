from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .markets import (
    MARKET_PREFIXES as _MARKET_PREFIXES,
    MARKET_TIMEZONES,
    market_moment,
    market_timezone,
    normalize_market,
)


_ROLES = {"index", "etf", "leader", "constituent"}
_SCHEMA_VERSIONS = {"opportunity-universe-v1", "opportunity-universe-v2"}


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

    def __post_init__(self) -> None:
        if "." not in self.code:
            raise ValueError(f"Malformed universe code: {self.code!r}")
        if self.role not in _ROLES:
            raise ValueError(f"Unsupported universe role: {self.role!r}")
        if self.weight <= 0:
            raise ValueError("Universe member weight must be positive")

    def active_at(self, at: str, market: str) -> bool:
        moment = market_moment(at, market)
        start = None if self.member_from is None else market_moment(self.member_from, market)
        end = None if self.member_to is None else market_moment(self.member_to, market)
        return (start is None or start <= moment) and (end is None or moment < end)


@dataclass(frozen=True)
class SectorUniverse:
    key: str
    name: str
    representative: str
    benchmark: str
    members: tuple[UniverseMember, ...]

    def __post_init__(self) -> None:
        if not self.key or not self.name:
            raise ValueError("Sector key and name are required")
        codes = [member.code for member in self.members]
        if not codes:
            raise ValueError(f"Sector {self.key!r} has no members")
        if len(set(codes)) != len(codes):
            raise ValueError(f"Sector {self.key!r} contains duplicate members")
        if self.representative not in codes:
            raise ValueError(
                f"Sector {self.key!r} representative {self.representative!r} is not a member"
            )


@dataclass(frozen=True)
class MarketUniverse:
    market: str
    as_of: str
    sectors: tuple[SectorUniverse, ...]
    source: str = "configured"
    expires_at: str | None = None
    schema_version: str = "opportunity-universe-v1"
    published_at: str | None = None
    identity_registry_version: str | None = None

    def __post_init__(self) -> None:
        market = normalize_market(self.market)
        object.__setattr__(self, "market", market)
        if self.schema_version not in _SCHEMA_VERSIONS:
            raise ValueError(f"Unsupported universe schema: {self.schema_version!r}")
        if self.schema_version == "opportunity-universe-v2":
            if not self.published_at:
                raise ValueError("Universe v2 requires published_at")
            if not self.identity_registry_version:
                raise ValueError("Universe v2 requires identity_registry_version")
        if not self.sectors:
            raise ValueError(f"{market} universe has no sectors")
        seen: set[str] = set()
        for sector in self.sectors:
            if sector.key in seen:
                raise ValueError(f"Duplicate sector key: {sector.key!r}")
            seen.add(sector.key)
            for member in sector.members:
                prefix = member.code.split(".", 1)[0].upper()
                if prefix not in _MARKET_PREFIXES[market]:
                    raise ValueError(
                        f"{member.code!r} does not belong to discovery market {market}"
                    )
                if self.schema_version == "opportunity-universe-v2":
                    if not member.security_id:
                        raise ValueError(f"Universe v2 member {member.code} requires security_id")
                    if not member.member_from:
                        raise ValueError(f"Universe v2 member {member.code} requires member_from")
                if member.member_from and member.member_to:
                    if market_moment(member.member_to, market) <= market_moment(
                        member.member_from, market
                    ):
                        raise ValueError(
                            f"Universe member {member.code} member_to must be later than member_from"
                        )
            benchmark_prefix = sector.benchmark.split(".", 1)[0].upper()
            if benchmark_prefix not in _MARKET_PREFIXES[market]:
                raise ValueError(
                    f"Benchmark {sector.benchmark!r} does not belong to {market}"
                )

    @property
    def timezone(self) -> str:
        return MARKET_TIMEZONES[normalize_market(self.market)]

    @property
    def effective_published_at(self) -> str:
        return self.published_at or self.as_of

    def _material_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "market": self.market,
            "as_of": self.as_of,
            "expires_at": self.expires_at,
            "published_at": self.effective_published_at,
            "identity_registry_version": self.identity_registry_version,
            "sectors": [
                {
                    "key": sector.key,
                    "name": sector.name,
                    "representative": sector.representative,
                    "benchmark": sector.benchmark,
                    "members": [asdict(member) for member in sector.members],
                }
                for sector in self.sectors
            ],
        }

    @property
    def version_id(self) -> str:
        encoded = json.dumps(
            self._material_record(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"universe:{hashlib.sha256(encoded).hexdigest()}"

    def active_member_codes(self, at: str) -> tuple[str, ...]:
        codes: list[str] = []
        for sector in self.sectors:
            for member in sector.members:
                if member.active_at(at, self.market) and member.code not in codes:
                    codes.append(member.code)
        return tuple(codes)

    def unique_codes(self, at: str | None = None) -> tuple[str, ...]:
        codes: list[str] = []
        for sector in self.sectors:
            members = (
                sector.members
                if at is None
                else tuple(
                    member
                    for member in sector.members
                    if member.active_at(at, self.market)
                )
            )
            for code in (sector.benchmark, *(member.code for member in members)):
                if code not in codes:
                    codes.append(code)
        return tuple(codes)

    def to_record(self) -> dict[str, Any]:
        record = self._material_record()
        record["source"] = self.source
        record["version_id"] = self.version_id
        return record


def universe_from_record(payload: dict[str, Any], *, source: str | None = None) -> MarketUniverse:
    if not isinstance(payload, dict):
        raise ValueError("Universe payload must be an object")
    schema_version = str(payload.get("schema_version", "opportunity-universe-v1"))
    if schema_version not in _SCHEMA_VERSIONS:
        raise ValueError(f"Unsupported universe schema: {schema_version!r}")
    sectors: list[SectorUniverse] = []
    for raw_sector in payload.get("sectors", []):
        if not isinstance(raw_sector, dict):
            raise ValueError("Universe sector must be an object")
        members = tuple(
            UniverseMember(
                code=str(raw_member["code"]),
                name=str(raw_member.get("name") or raw_member["code"]),
                role=str(raw_member.get("role", "constituent")),
                weight=float(raw_member.get("weight", 1.0)),
                shared_identity=(
                    None
                    if raw_member.get("shared_identity") in {None, ""}
                    else str(raw_member["shared_identity"])
                ),
                security_id=(
                    str(raw_member["security_id"])
                    if raw_member.get("security_id") not in {None, ""}
                    else f"listing:{raw_member['code']}"
                ),
                member_from=(
                    None
                    if raw_member.get("member_from") in {None, ""}
                    else str(raw_member["member_from"])
                ),
                member_to=(
                    None
                    if raw_member.get("member_to") in {None, ""}
                    else str(raw_member["member_to"])
                ),
            )
            for raw_member in raw_sector.get("members", [])
        )
        sectors.append(
            SectorUniverse(
                key=str(raw_sector["key"]),
                name=str(raw_sector.get("name") or raw_sector["key"]),
                representative=str(raw_sector["representative"]),
                benchmark=str(raw_sector["benchmark"]),
                members=members,
            )
        )
    universe = MarketUniverse(
        market=normalize_market(str(payload["market"])),
        as_of=str(payload["as_of"]),
        sectors=tuple(sectors),
        source=str(source or payload.get("source", "configured")),
        expires_at=(None if payload.get("expires_at") is None else str(payload["expires_at"])),
        schema_version=schema_version,
        published_at=(
            None if payload.get("published_at") is None else str(payload["published_at"])
        ),
        identity_registry_version=(
            None
            if payload.get("identity_registry_version") is None
            else str(payload["identity_registry_version"])
        ),
    )
    persisted_version = payload.get("version_id")
    if (
        schema_version == "opportunity-universe-v2"
        and persisted_version is not None
        and persisted_version != universe.version_id
    ):
        raise ValueError(
            f"Universe version_id mismatch: {persisted_version} != {universe.version_id}"
        )
    return universe


def load_universe(path: str | Path) -> MarketUniverse:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    return universe_from_record(payload, source=f"file:{source}")


def save_universe(path: str | Path, universe: MarketUniverse) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(universe.to_record(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_moment(value: str, market: str) -> datetime:
    return market_moment(value, market)


def cache_is_valid(universe: MarketUniverse, at: str) -> bool:
    if universe.expires_at is None:
        return True
    return _parse_moment(universe.expires_at, universe.market) >= _parse_moment(
        at, universe.market
    )


MembershipRefresher = Callable[[str], MarketUniverse]


def _ensure_published(universe: MarketUniverse, at: str) -> None:
    if _parse_moment(universe.effective_published_at, universe.market) > _parse_moment(
        at, universe.market
    ):
        raise RuntimeError(
            f"{universe.market} membership was published after requested as_of: "
            f"{universe.effective_published_at} > {at}"
        )


def resolve_universe(
    market: str,
    *,
    configured_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    refresher: MembershipRefresher | None = None,
    at: str | None = None,
) -> MarketUniverse:
    """Resolve current membership without fabricating neutral sector evidence.

    A successful OpenD-backed refresher wins and is cached.  On refresh failure a
    still-valid cache may be used.  An expired cache is ignored; the configured
    universe is then used only when explicitly present.
    """

    market = normalize_market(market)
    moment = at or datetime.now(market_timezone(market)).isoformat(timespec="seconds")
    refresh_error: Exception | None = None
    if refresher is not None:
        try:
            refreshed = refresher(market)
            if normalize_market(refreshed.market) != market:
                raise ValueError("Membership refresher returned the wrong market")
            _ensure_published(refreshed, moment)
            if cache_path is not None:
                save_universe(cache_path, refreshed)
            return refreshed
        except Exception as exc:  # heterogeneous OpenD/cache failures
            refresh_error = exc

    if cache_path is not None and Path(cache_path).is_file():
        try:
            cached = load_universe(cache_path)
            if normalize_market(cached.market) != market:
                raise ValueError("Membership cache contains the wrong market")
            if not cache_is_valid(cached, moment):
                raise RuntimeError(f"cached membership expired at {cached.expires_at}")
            _ensure_published(cached, moment)
        except Exception as exc:  # malformed, expired, or future cache is never authoritative
            refresh_error = exc
        else:
            return MarketUniverse(
                market=cached.market,
                as_of=cached.as_of,
                sectors=cached.sectors,
                source=f"cache:{cache_path}",
                expires_at=cached.expires_at,
                schema_version=cached.schema_version,
                published_at=cached.published_at,
                identity_registry_version=cached.identity_registry_version,
            )

    if configured_path is not None and Path(configured_path).is_file():
        configured = load_universe(configured_path)
        if normalize_market(configured.market) != market:
            raise ValueError(f"Configured universe market is {configured.market}, expected {market}")
        if cache_is_valid(configured, moment):
            try:
                _ensure_published(configured, moment)
            except RuntimeError as exc:
                refresh_error = exc
            else:
                return configured
        else:
            refresh_error = RuntimeError(
                f"configured membership expired at {configured.expires_at}"
            )

    detail = f": {refresh_error}" if refresh_error is not None else ""
    raise RuntimeError(f"No valid {market} discovery membership is available{detail}")
