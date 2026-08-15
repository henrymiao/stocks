from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .discovery_engine import (
    DiscoveryCandidate,
    candidate_from_record,
    confirm_discoveries,
    discover_universe,
)
from .discovery_store import DiscoveryStore
from .futu_fetcher import FutuFetcher
from .identity import SecurityIdentity
from .models import KLineBar, MarketSnapshot
from .point_in_time import EvidenceStamp, PointInTimeInput
from .store import MarketStore
from .universe import MarketUniverse, market_timezone, universe_from_record


def freeze_discovery_inputs(
    *,
    universe: MarketUniverse,
    identity: SecurityIdentity,
    identity_version: str,
    as_of: str,
    captured_at: str,
    session_phase: str,
    snapshot: MarketSnapshot | dict[str, Any] | None,
    daily_bars: list[KLineBar] | list[dict[str, Any]],
    intraday_bars: list[KLineBar] | list[dict[str, Any]],
    daily_adjustment_basis: str,
    intraday_adjustment_basis: str,
    intraday_bar_interval: str,
    evidence: tuple[EvidenceStamp, ...],
    capital: dict[str, Any] | None = None,
    financial: dict[str, Any] | None = None,
    sector: dict[str, Any] | None = None,
    macro: dict[str, Any] | None = None,
    cross_market: dict[str, Any] | None = None,
) -> PointInTimeInput:
    """Freeze already-fetched discovery records without fetching or scoring."""

    def record(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else asdict(value)

    return PointInTimeInput.build_market_payload(
        code=identity.code,
        security_id=identity.security_id,
        company_id=identity.company_id,
        market=universe.market,
        as_of=as_of,
        captured_at=captured_at,
        session_phase=session_phase,
        universe_version=universe.version_id,
        identity_version=identity_version,
        snapshot=None if snapshot is None else record(snapshot),
        daily_bars=[record(bar) for bar in daily_bars],
        intraday_bars=[record(bar) for bar in intraday_bars],
        daily_adjustment_basis=daily_adjustment_basis,
        intraday_adjustment_basis=intraday_adjustment_basis,
        intraday_bar_interval=intraday_bar_interval,
        evidence=evidence,
        capital=capital,
        financial=financial,
        sector=sector,
        macro=macro,
        cross_market=cross_market,
    )


def bar_from_record(payload: dict[str, Any]) -> KLineBar:
    return KLineBar(
        time=str(payload["time"]),
        open=float(payload["open"]),
        high=float(payload["high"]),
        low=float(payload["low"]),
        close=float(payload["close"]),
        volume=int(payload["volume"]),
        turnover=float(payload.get("turnover", float(payload["close"]) * int(payload["volume"]))),
    )


def snapshot_from_record(payload: dict[str, Any]) -> MarketSnapshot:
    captured = str(payload.get("captured_at") or payload.get("timestamp"))
    return MarketSnapshot(
        code=str(payload["code"]),
        name=str(payload.get("name") or payload["code"]),
        last_price=float(payload["last_price"]),
        open=float(payload["open"]),
        high=float(payload["high"]),
        low=float(payload["low"]),
        prev_close=float(payload["prev_close"]),
        volume=int(payload["volume"]),
        turnover=float(payload["turnover"]),
        timestamp=str(payload.get("timestamp") or captured),
        captured_at=captured,
    )


def load_discovery_fixture(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("universe"), dict):
        raise ValueError("Discovery fixture must contain a universe object")
    return {
        "universe": universe_from_record(payload["universe"], source=f"fixture:{path}"),
        "bars": {
            code: [bar_from_record(row) for row in rows]
            for code, rows in payload.get("bars", {}).items()
        },
        "intraday_bars": {
            code: [bar_from_record(row) for row in rows]
            for code, rows in payload.get("intraday_bars", {}).items()
        },
        "snapshots": {
            code: snapshot_from_record(row)
            for code, row in payload.get("snapshots", {}).items()
        },
        "capital_improvement": {
            code: float(value) for code, value in payload.get("capital_improvement", {}).items()
        },
        "sector_confirmation": {
            sector: {key: float(value) for key, value in evidence.items()}
            for sector, evidence in payload.get("sector_confirmation", {}).items()
        },
        "instrument_confirmation": {
            code: {key: float(value) for key, value in evidence.items()}
            for code, evidence in payload.get("instrument_confirmation", {}).items()
        },
        "future_bars": {
            code: [bar_from_record(row) for row in rows]
            for code, rows in payload.get("future_bars", {}).items()
        },
        "trading_sessions": (
            tuple(str(value) for value in payload["trading_sessions"])
            if isinstance(payload.get("trading_sessions"), list)
            else None
        ),
    }


def _capital_improvement(history: list[dict[str, Any]]) -> float | None:
    if len(history) < 2:
        return None
    previous, current = history[-2], history[-1]
    previous_smart = float(previous["super_net"]) + float(previous["big_net"])
    current_smart = float(current["super_net"]) + float(current["big_net"])
    previous_total = float(previous["net"])
    current_total = float(current["net"])
    scale = max(abs(previous_smart), abs(current_smart), abs(previous_total), abs(current_total), 1.0)
    delta = 0.65 * (current_smart - previous_smart) + 0.35 * (current_total - previous_total)
    score = 50.0 + delta / scale * 45.0
    if current_smart > 0:
        score += 10.0
    if current_total > 0:
        score += 5.0
    return round(max(0.0, min(100.0, score)), 2)


def _sync_daily_cache(
    universe: MarketUniverse,
    fetcher: FutuFetcher,
    store: MarketStore,
    *,
    backfill: int,
) -> tuple[dict[str, list[KLineBar]], dict[str, str]]:
    bars_by_code: dict[str, list[KLineBar]] = {}
    failures: dict[str, str] = {}
    for code in universe.unique_codes():
        cached_count = store.bar_count(code)
        fetch_count = backfill if cached_count < 60 else 5
        try:
            fetched = fetcher.get_daily_bars(code, num=fetch_count)
            store.upsert_bars(code, "1d", fetched)
        except Exception as exc:  # isolate one OpenD entitlement/rate-limit failure
            failures[code] = f"{type(exc).__name__}: {exc}"
        bars_by_code[code] = store.get_bars(code, "1d", limit=backfill)
    return bars_by_code, failures


def _trading_sessions(
    fetcher: FutuFetcher,
    market: str,
    evaluated_at: str,
) -> tuple[tuple[str, ...], str | None]:
    timezone = market_timezone(market)
    moment = datetime.fromisoformat(evaluated_at)
    local = moment.replace(tzinfo=timezone) if moment.tzinfo is None else moment.astimezone(timezone)
    try:
        sessions = tuple(
            fetcher.get_trading_days(
                market,
                start=(local.date() - timedelta(days=10)).isoformat(),
                end=(local.date() + timedelta(days=60)).isoformat(),
            )
        )
    except Exception as exc:
        return (), f"{type(exc).__name__}: {exc}"
    if not sessions:
        return (), "OpenD returned no exchange sessions"
    return sessions, None


def _expected_completed_session(
    market: str,
    evaluated_at: str,
    trading_sessions: tuple[str, ...],
) -> str | None:
    if not trading_sessions:
        return None
    timezone = market_timezone(market)
    moment = datetime.fromisoformat(evaluated_at)
    local = moment.replace(tzinfo=timezone) if moment.tzinfo is None else moment.astimezone(timezone)
    close_hour = 15 if market == "CN" else 16
    # Full discovery is an after-close job.  Running early preserves existing
    # state but cannot create or upgrade a candidate.
    if (
        local.date().isoformat() not in set(trading_sessions)
        or (local.hour, local.minute) < (close_hour, 15)
    ):
        return None
    eligible = [day for day in trading_sessions if day <= local.date().isoformat()]
    return max(eligible) if eligible else None


def _latest_bar_session(bars: list[KLineBar]) -> str | None:
    sessions: list[str] = []
    for bar in bars:
        if bar.volume <= 0:
            continue
        try:
            sessions.append(datetime.fromisoformat(bar.time).date().isoformat())
        except ValueError:
            continue
    return max(sessions) if sessions else None


def run_live_discovery(
    universe: MarketUniverse,
    *,
    evaluated_at: str,
    discovery_store: DiscoveryStore,
    market_store: MarketStore,
    fetcher: FutuFetcher | None = None,
    horizon: str = "short",
    backfill: int = 260,
) -> dict[str, Any]:
    fetcher = fetcher or FutuFetcher()
    snapshot_failure: str | None = None
    try:
        snapshots = fetcher.get_snapshots(list(universe.unique_codes()))
    except Exception as exc:
        snapshots = []
        snapshot_failure = f"{type(exc).__name__}: {exc}"
    for snapshot in snapshots:
        market_store.record_snapshot(snapshot)
    bars, bar_failures = _sync_daily_cache(
        universe, fetcher, market_store, backfill=backfill
    )
    trading_sessions, calendar_failure = _trading_sessions(
        fetcher, universe.market, evaluated_at
    )
    expected_session = _expected_completed_session(
        universe.market, evaluated_at, trading_sessions
    )
    stale_daily_codes = sorted(
        code
        for code, code_bars in bars.items()
        if expected_session is None or _latest_bar_session(code_bars) != expected_session
    )
    scoring_bars = {
        code: ([] if code in stale_daily_codes else code_bars)
        for code, code_bars in bars.items()
    }
    existing = discovery_store.latest_by_key(universe.market)

    preliminary = discover_universe(
        universe,
        scoring_bars,
        evaluated_at=evaluated_at,
        horizon=horizon,
        existing=existing,
        trading_sessions=trading_sessions,
    )
    promoted_codes = {
        row["code"]
        for row in preliminary["candidates"]
        if row["state"] in {"forming", "armed"}
    }
    capital_scores: dict[str, float] = {}
    capital_failures: dict[str, str] = {}
    for code in sorted(promoted_codes):
        try:
            capital = fetcher.get_capital(code)
        except Exception as exc:  # preserve the candidate when optional flow fails
            capital_failures[code] = f"{type(exc).__name__}: {exc}"
            continue
        if capital is None:
            continue
        market_store.record_capital(code, capital)
        score = _capital_improvement(market_store.capital_history(code, limit=3))
        if score is not None:
            capital_scores[code] = score

    report = (
        discover_universe(
            universe,
            scoring_bars,
            evaluated_at=evaluated_at,
            capital_improvement=capital_scores,
            horizon=horizon,
            existing=existing,
            trading_sessions=trading_sessions,
        )
        if capital_scores
        else preliminary
    )
    candidates = [candidate_from_record(row) for row in report["candidates"]]
    discovery_store.upsert_many(candidates)
    report["snapshot_coverage"] = {
        "requested": len(universe.unique_codes()),
        "received": len(snapshots),
    }
    report["capital_candidates_refreshed"] = sorted(capital_scores)
    report["expected_completed_session"] = expected_session
    report["stale_daily_codes"] = stale_daily_codes
    # Say so on the face of the report. Running before the close blanks every code's
    # bars, so each sector reads 0% coverage and the whole universe is disabled -- and
    # what comes back is the previous run's state, preserved verbatim. That is the
    # intended behaviour, but it is indistinguishable from a fresh scan unless you dig
    # `expected_completed_session: null` out of the payload. Three runs were read as
    # today's answer when they carried candidates a week old.
    if expected_session is None:
        report.setdefault("notes", []).append(
            f"Ran before the close for {universe.market}: full discovery is an after-close job "
            f"(from 15 minutes past the local close). Every code was treated as stale, every "
            f"sector disabled at 0% coverage, and the states below are the previous run's, "
            f"preserved unchanged -- not today's. Re-run after the close."
        )
        report["preserved_prior_state"] = True
    report["data_failures"] = {
        "snapshots": snapshot_failure,
        "trading_calendar": calendar_failure,
        "daily_bars": bar_failures,
        "capital": capital_failures,
    }
    return report


def sector_confirmation_from_snapshots(
    universe: MarketUniverse,
    snapshots: dict[str, MarketSnapshot],
    *,
    evaluated_at: str,
    maximum_age: timedelta = timedelta(minutes=20),
) -> dict[str, dict[str, float]]:
    evaluation = datetime.fromisoformat(evaluated_at)
    timezone = market_timezone(universe.market)
    evaluation = (
        evaluation.replace(tzinfo=timezone)
        if evaluation.tzinfo is None
        else evaluation.astimezone(timezone)
    )

    def is_fresh(snapshot: MarketSnapshot) -> bool:
        try:
            timestamp = datetime.fromisoformat(snapshot.timestamp)
        except (TypeError, ValueError):
            return False
        timestamp = (
            timestamp.replace(tzinfo=timezone)
            if timestamp.tzinfo is None
            else timestamp.astimezone(timezone)
        )
        age = evaluation - timestamp
        return timedelta(0) <= age <= maximum_age

    result: dict[str, dict[str, float]] = {}
    for sector in universe.sectors:
        constituent_moves: list[float] = []
        leader_moves: list[float] = []
        for member in sector.members:
            if member.role not in {"leader", "constituent"}:
                continue
            snapshot = snapshots.get(member.code)
            if snapshot is None or snapshot.prev_close <= 0 or not is_fresh(snapshot):
                continue
            move = snapshot.last_price / snapshot.prev_close - 1.0
            constituent_moves.append(move)
            if member.role == "leader":
                leader_moves.append(move)
        if constituent_moves:
            result[sector.key] = {
                "breadth": sum(move > 0 for move in constituent_moves) / len(constituent_moves),
                "leader_breadth": (
                    sum(move >= 0 for move in leader_moves) / len(leader_moves)
                    if leader_moves
                    else 0.0
                ),
                "coverage": len(constituent_moves)
                / max(
                    1,
                    sum(
                        member.role in {"leader", "constituent"}
                        for member in sector.members
                    ),
                ),
            }
    return result


def run_live_confirmation(
    universe: MarketUniverse,
    *,
    evaluated_at: str,
    discovery_store: DiscoveryStore,
    market_store: MarketStore,
    fetcher: FutuFetcher | None = None,
    analyzer=None,
) -> dict[str, Any]:
    fetcher = fetcher or FutuFetcher()
    candidates = discovery_store.list_candidates(
        market=universe.market, states=("armed", "triggered")
    )
    armed_codes = sorted({candidate.code for candidate in candidates})
    market_state_failure: str | None = None
    try:
        market_states = fetcher.get_market_states(armed_codes)
    except Exception as exc:
        market_states = {}
        market_state_failure = f"{type(exc).__name__}: {exc}"
    intraday: dict[str, list[KLineBar]] = {}
    intraday_failures: dict[str, str] = {}
    for code in armed_codes:
        try:
            intraday[code] = fetcher.get_intraday_bars(code, num=30)
        except Exception as exc:  # keep prior state and emit no false transition
            intraday_failures[code] = f"{type(exc).__name__}: {exc}"
    snapshot_failure: str | None = None
    try:
        snapshots = {
            snapshot.code: snapshot
            for snapshot in fetcher.get_snapshots(list(universe.unique_codes()))
        }
    except Exception as exc:
        snapshots = {}
        snapshot_failure = f"{type(exc).__name__}: {exc}"
    confirmation = sector_confirmation_from_snapshots(
        universe,
        snapshots,
        evaluated_at=evaluated_at,
    )
    instrument_confirmation: dict[str, dict[str, float]] = {}
    capital_failures: dict[str, str] = {}
    for code in armed_codes:
        try:
            capital = fetcher.get_capital(code)
        except Exception as exc:
            capital_failures[code] = f"{type(exc).__name__}: {exc}"
            continue
        if capital is None:
            continue
        market_store.record_capital(code, capital)
        improvement = _capital_improvement(market_store.capital_history(code, limit=3))
        if improvement is not None:
            instrument_confirmation[code] = {"capital_improvement": improvement}
    trading_sessions, calendar_failure = _trading_sessions(
        fetcher, universe.market, evaluated_at
    )
    report = confirm_discoveries(
        candidates,
        intraday,
        confirmation,
        evaluated_at=evaluated_at,
        instrument_confirmation=instrument_confirmation,
        analyzer=analyzer,
        trading_sessions=trading_sessions,
        market_states=market_states,
    )
    updated = [candidate_from_record(row) for row in report["candidates"]]
    discovery_store.upsert_many(updated)
    report["data_failures"] = {
        "snapshots": snapshot_failure,
        "trading_calendar": calendar_failure,
        "market_state": market_state_failure,
        "intraday_bars": intraday_failures,
        "capital": capital_failures,
    }
    return report


def default_evaluated_at(universe: MarketUniverse) -> str:
    return datetime.now(market_timezone(universe.market)).isoformat(timespec="seconds")
