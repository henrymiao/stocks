from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


MARKET_TIMEZONES = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Shanghai",
    "US": "America/New_York",
}

_MARKET_PREFIXES = {
    "CN": {"SH", "SZ"},
    "HK": {"HK"},
    "US": {"US"},
}

_ROLES = {"index", "etf", "leader", "constituent"}


def normalize_market(value: str) -> str:
    market = str(value).upper()
    if market not in MARKET_TIMEZONES:
        raise ValueError(f"Unsupported discovery market: {value!r}")
    return market


def market_timezone(market: str) -> ZoneInfo:
    return ZoneInfo(MARKET_TIMEZONES[normalize_market(market)])


@dataclass(frozen=True)
class UniverseMember:
    code: str
    name: str
    role: str = "constituent"
    weight: float = 1.0
    shared_identity: str | None = None

    def __post_init__(self) -> None:
        if "." not in self.code:
            raise ValueError(f"Malformed universe code: {self.code!r}")
        if self.role not in _ROLES:
            raise ValueError(f"Unsupported universe role: {self.role!r}")
        if self.weight <= 0:
            raise ValueError("Universe member weight must be positive")


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

    def __post_init__(self) -> None:
        market = normalize_market(self.market)
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
            benchmark_prefix = sector.benchmark.split(".", 1)[0].upper()
            if benchmark_prefix not in _MARKET_PREFIXES[market]:
                raise ValueError(
                    f"Benchmark {sector.benchmark!r} does not belong to {market}"
                )

    @property
    def timezone(self) -> str:
        return MARKET_TIMEZONES[normalize_market(self.market)]

    def unique_codes(self) -> tuple[str, ...]:
        codes: list[str] = []
        for sector in self.sectors:
            for code in (sector.benchmark, *(member.code for member in sector.members)):
                if code not in codes:
                    codes.append(code)
        return tuple(codes)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def universe_from_record(payload: dict[str, Any], *, source: str | None = None) -> MarketUniverse:
    if not isinstance(payload, dict):
        raise ValueError("Universe payload must be an object")
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
    return MarketUniverse(
        market=normalize_market(str(payload["market"])),
        as_of=str(payload["as_of"]),
        sectors=tuple(sectors),
        source=str(source or payload.get("source", "configured")),
        expires_at=(None if payload.get("expires_at") is None else str(payload["expires_at"])),
        schema_version=str(payload.get("schema_version", "opportunity-universe-v1")),
    )


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
    moment = datetime.fromisoformat(value)
    tz = market_timezone(market)
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)


def cache_is_valid(universe: MarketUniverse, at: str) -> bool:
    if universe.expires_at is None:
        return True
    return _parse_moment(universe.expires_at, universe.market) >= _parse_moment(
        at, universe.market
    )


MembershipRefresher = Callable[[str], MarketUniverse]


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
            if cache_path is not None:
                save_universe(cache_path, refreshed)
            return refreshed
        except Exception as exc:  # heterogeneous OpenD/cache failures
            refresh_error = exc

    if cache_path is not None and Path(cache_path).is_file():
        cached = load_universe(cache_path)
        if normalize_market(cached.market) == market and cache_is_valid(cached, moment):
            return MarketUniverse(
                market=cached.market,
                as_of=cached.as_of,
                sectors=cached.sectors,
                source=f"cache:{cache_path}",
                expires_at=cached.expires_at,
                schema_version=cached.schema_version,
            )

    if configured_path is not None and Path(configured_path).is_file():
        configured = load_universe(configured_path)
        if normalize_market(configured.market) != market:
            raise ValueError(f"Configured universe market is {configured.market}, expected {market}")
        if cache_is_valid(configured, moment):
            return configured
        refresh_error = RuntimeError(f"configured membership expired at {configured.expires_at}")

    detail = f": {refresh_error}" if refresh_error is not None else ""
    raise RuntimeError(f"No valid {market} discovery membership is available{detail}")
