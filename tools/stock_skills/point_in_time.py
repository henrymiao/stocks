from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .markets import (
    DAILY_BAR_INTERVAL,
    INTRADAY_BAR_MINUTES,
    bar_close_moment,
    market_moment,
    normalize_market,
)


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
        if not self.component:
            raise ValueError("Evidence component is required")
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError(f"Unsupported evidence status: {self.status!r}")
        if self.status == "missing" and any(
            value is not None
            for value in (
                self.observed_at,
                self.source,
                self.source_ref,
                self.adjustment_basis,
            )
        ):
            raise ValueError("Missing evidence cannot claim an observation, source, or basis")
        if self.status != "missing" and (self.observed_at is None or self.source is None):
            raise ValueError(f"{self.status} evidence requires source and observed_at")
        if self.status == "conflicting" and len(self.conflict_refs) < 2:
            raise ValueError("Conflicting evidence requires at least two source references")
        if self.status != "conflicting" and self.conflict_refs:
            raise ValueError("Only conflicting evidence may carry conflict_refs")


def _material_record(
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
) -> dict[str, Any]:
    return {
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
        "payload": payload,
        "evidence": [asdict(stamp) for stamp in evidence],
    }


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
        ordered_evidence = tuple(sorted(evidence, key=lambda item: item.component))
        components = [stamp.component for stamp in ordered_evidence]
        if len(components) != len(set(components)):
            raise ValueError("Point-in-time input contains duplicate evidence component names")

        for stamp in ordered_evidence:
            stamp_capture = market_moment(stamp.captured_at, market)
            if stamp_capture > package_capture:
                raise ValueError(
                    f"Evidence capture is after package captured_at: {stamp.component}"
                )
            for label, value in (
                ("observation", stamp.observed_at),
                ("publication", stamp.published_at),
            ):
                if value is None:
                    continue
                evidence_moment = market_moment(value, market)
                if evidence_moment > cutoff:
                    raise ValueError(
                        f"Evidence {label} is after package as_of: {stamp.component}"
                    )
                if evidence_moment > stamp_capture:
                    raise ValueError(
                        f"Evidence {label} is after its captured_at: {stamp.component}"
                    )

        payload_json = _canonical(payload)
        frozen_payload = json.loads(payload_json)
        material = _material_record(
            code=code,
            security_id=security_id,
            company_id=company_id,
            market=market,
            as_of=as_of,
            captured_at=captured_at,
            session_phase=session_phase,
            universe_version=universe_version,
            identity_version=identity_version,
            payload=frozen_payload,
            evidence=ordered_evidence,
        )
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
            evidence=ordered_evidence,
        )

    @classmethod
    def build_market_payload(
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
        snapshot: Mapping[str, Any] | None,
        daily_bars: list[Mapping[str, Any]],
        intraday_bars: list[Mapping[str, Any]],
        daily_adjustment_basis: str | None,
        intraday_adjustment_basis: str | None,
        intraday_bar_interval: str,
        evidence: tuple[EvidenceStamp, ...],
        capital: Mapping[str, Any] | None = None,
        financial: Mapping[str, Any] | None = None,
        sector: Mapping[str, Any] | None = None,
        macro: Mapping[str, Any] | None = None,
        cross_market: Mapping[str, Any] | None = None,
    ) -> "PointInTimeInput":
        market = normalize_market(market)
        cutoff = market_moment(as_of, market)
        for label, basis in (
            ("daily_bars", daily_adjustment_basis),
            ("intraday_bars", intraday_adjustment_basis),
        ):
            if basis is None or not str(basis).strip():
                raise ValueError(f"{label} requires an explicit adjustment basis")
        if intraday_bar_interval not in INTRADAY_BAR_MINUTES:
            raise ValueError(f"Unsupported bar interval: {intraday_bar_interval!r}")

        snapshot_record = None if snapshot is None else dict(snapshot)
        if snapshot_record is not None:
            if "timestamp" not in snapshot_record:
                raise ValueError("Snapshot requires a timestamp")
            if market_moment(str(snapshot_record["timestamp"]), market) > cutoff:
                raise ValueError("Snapshot is after package as_of")

        def freeze_bars(
            component: str, records: list[Mapping[str, Any]], interval: str
        ) -> list[dict[str, Any]]:
            frozen: list[dict[str, Any]] = []
            for row in records:
                record = dict(row)
                if "time" not in record:
                    raise ValueError(f"{component} bar requires time")
                bar_time = str(record["time"])
                if market_moment(bar_time, market) > cutoff:
                    raise ValueError(f"{component} bar is after package as_of")
                if bar_close_moment(bar_time, market, interval) > cutoff:
                    raise ValueError(f"{component} bar is incomplete at package as_of")
                frozen.append(record)
            return sorted(
                frozen,
                key=lambda item: market_moment(str(item["time"]), market),
            )

        daily_records = freeze_bars("daily", daily_bars, DAILY_BAR_INTERVAL)
        intraday_records = freeze_bars("intraday", intraday_bars, intraday_bar_interval)
        component_values: dict[str, object] = {
            "snapshot": snapshot_record,
            "daily_bars": daily_records,
            "intraday_bars": intraday_records,
            "capital": capital,
            "financial": financial,
            "sector": sector,
            "macro": macro,
            "cross_market": cross_market,
        }
        normalized_evidence = list(evidence)
        evidence_by_component = {stamp.component: stamp for stamp in normalized_evidence}
        if len(evidence_by_component) != len(normalized_evidence):
            raise ValueError("Point-in-time input contains duplicate evidence component names")
        for component, value in component_values.items():
            empty = value is None or value == {} or value == [] or value == ()
            stamp = evidence_by_component.get(component)
            if empty and stamp is None:
                normalized_evidence.append(
                    EvidenceStamp(
                        component=component,
                        status="missing",
                        source=None,
                        observed_at=None,
                        published_at=None,
                        captured_at=captured_at,
                        source_ref=None,
                        adjustment_basis=None,
                    )
                )
            elif empty and stamp is not None and stamp.status != "missing":
                raise ValueError(f"Empty {component} payload must be marked missing")
            elif not empty and stamp is not None and stamp.status == "missing":
                raise ValueError(f"Non-empty {component} payload cannot be marked missing")

        payload = {
            "snapshot": snapshot_record,
            "daily_bars": {
                "adjustment_basis": str(daily_adjustment_basis),
                "interval": DAILY_BAR_INTERVAL,
                "bars": daily_records,
            },
            "intraday_bars": {
                "adjustment_basis": str(intraday_adjustment_basis),
                "interval": intraday_bar_interval,
                "bars": intraday_records,
            },
            "capital": capital,
            "financial": financial,
            "sector": sector,
            "macro": macro,
            "cross_market": cross_market,
        }
        return cls.build(
            code=code,
            security_id=security_id,
            company_id=company_id,
            market=market,
            as_of=as_of,
            captured_at=captured_at,
            session_phase=session_phase,
            universe_version=universe_version,
            identity_version=identity_version,
            payload=payload,
            evidence=tuple(normalized_evidence),
        )

    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    def components_with_status(self, status: str) -> tuple[str, ...]:
        if status not in EVIDENCE_STATUSES:
            raise ValueError(f"Unsupported evidence status: {status!r}")
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

    def to_record(self) -> dict[str, Any]:
        record = _material_record(
            code=self.code,
            security_id=self.security_id,
            company_id=self.company_id,
            market=self.market,
            as_of=self.as_of,
            captured_at=self.captured_at,
            session_phase=self.session_phase,
            universe_version=self.universe_version,
            identity_version=self.identity_version,
            payload=self.payload(),
            evidence=self.evidence,
        )
        record["package_id"] = self.package_id
        record["input_digest"] = self.input_digest
        return record


def point_in_time_input_from_record(payload: dict[str, Any]) -> PointInTimeInput:
    if not isinstance(payload, dict):
        raise ValueError("Point-in-time input payload must be an object")
    schema_version = str(payload.get("schema_version", ""))
    if schema_version != INPUT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported point-in-time input schema: {schema_version!r}")
    raw_evidence = payload.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ValueError("Point-in-time input evidence must be a list")
    evidence = tuple(
        EvidenceStamp(
            component=str(row["component"]),
            status=str(row["status"]),
            source=None if row.get("source") is None else str(row["source"]),
            observed_at=(
                None if row.get("observed_at") is None else str(row["observed_at"])
            ),
            published_at=(
                None if row.get("published_at") is None else str(row["published_at"])
            ),
            captured_at=str(row["captured_at"]),
            source_ref=(
                None if row.get("source_ref") is None else str(row["source_ref"])
            ),
            adjustment_basis=(
                None
                if row.get("adjustment_basis") is None
                else str(row["adjustment_basis"])
            ),
            conflict_refs=tuple(str(item) for item in row.get("conflict_refs", [])),
        )
        for row in raw_evidence
    )
    rebuilt = PointInTimeInput.build(
        code=str(payload["code"]),
        security_id=str(payload["security_id"]),
        company_id=str(payload["company_id"]),
        market=str(payload["market"]),
        as_of=str(payload["as_of"]),
        captured_at=str(payload["captured_at"]),
        session_phase=str(payload["session_phase"]),
        universe_version=str(payload["universe_version"]),
        identity_version=str(payload["identity_version"]),
        payload=payload.get("payload", {}),
        evidence=evidence,
    )
    persisted_digest = str(payload.get("input_digest", ""))
    if persisted_digest != rebuilt.input_digest:
        raise ValueError(
            f"Point-in-time input digest mismatch: "
            f"{persisted_digest!r} != {rebuilt.input_digest!r}"
        )
    persisted_package_id = str(payload.get("package_id", ""))
    if persisted_package_id != rebuilt.package_id:
        raise ValueError(
            f"Point-in-time input package_id mismatch: "
            f"{persisted_package_id!r} != {rebuilt.package_id!r}"
        )
    return rebuilt


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
