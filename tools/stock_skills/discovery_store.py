from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .discovery_engine import DiscoveryCandidate, candidate_from_record


DEFAULT_DISCOVERY_DB = "data/discovery.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS discovery_candidates (
    discovery_id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    sector TEXT NOT NULL,
    code TEXT NOT NULL,
    track TEXT NOT NULL,
    state TEXT NOT NULL,
    score REAL NOT NULL,
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS discovery_candidates_market_state
    ON discovery_candidates (market, state, updated_at);
CREATE TABLE IF NOT EXISTS discovery_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovery_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    transition_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE (discovery_id, from_state, to_state, transition_at, reason)
);
CREATE TABLE IF NOT EXISTS discovery_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovery_id TEXT NOT NULL,
    state TEXT NOT NULL,
    notified_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS discovery_notifications_latest
    ON discovery_notifications (discovery_id, id);
CREATE TABLE IF NOT EXISTS discovery_reviews (
    discovery_id TEXT PRIMARY KEY,
    reviewed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class DiscoveryStore:
    def __init__(self, path: str | Path = DEFAULT_DISCOVERY_DB) -> None:
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "DELETE FROM discovery_transitions WHERE id NOT IN ("
            " SELECT MIN(id) FROM discovery_transitions"
            " GROUP BY discovery_id, COALESCE(from_state, ''), to_state, transition_at, reason"
            ")"
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS discovery_transitions_deduplicated"
            " ON discovery_transitions"
            " (discovery_id, COALESCE(from_state, ''), to_state, transition_at, reason)"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DiscoveryStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upsert(self, candidate: DiscoveryCandidate) -> None:
        payload = json.dumps(candidate.to_record(), ensure_ascii=False, sort_keys=True)
        self._conn.execute(
            "INSERT INTO discovery_candidates"
            " (discovery_id, market, sector, code, track, state, score, first_seen_at, updated_at, expires_at, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (discovery_id) DO UPDATE SET"
            " market=excluded.market, sector=excluded.sector, code=excluded.code,"
            " track=excluded.track, state=excluded.state, score=excluded.score,"
            " updated_at=excluded.updated_at, expires_at=excluded.expires_at, payload=excluded.payload",
            (
                candidate.discovery_id,
                candidate.market,
                candidate.sector,
                candidate.code,
                candidate.track,
                candidate.state,
                candidate.score,
                candidate.first_seen_at,
                candidate.updated_at,
                candidate.expires_at,
                payload,
            ),
        )
        for transition in candidate.transition_history:
            self._conn.execute(
                "INSERT OR IGNORE INTO discovery_transitions"
                " (discovery_id, from_state, to_state, transition_at, reason)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    candidate.discovery_id,
                    transition.get("from"),
                    transition["to"],
                    transition["at"],
                    transition.get("reason", ""),
                ),
            )
        self._conn.commit()

    def upsert_many(self, candidates: list[DiscoveryCandidate]) -> None:
        for candidate in candidates:
            self.upsert(candidate)

    def get(self, discovery_id: str) -> DiscoveryCandidate | None:
        row = self._conn.execute(
            "SELECT payload FROM discovery_candidates WHERE discovery_id = ?",
            (discovery_id,),
        ).fetchone()
        return None if row is None else candidate_from_record(json.loads(row["payload"]))

    def list_candidates(
        self,
        *,
        market: str | None = None,
        states: tuple[str, ...] | None = None,
    ) -> list[DiscoveryCandidate]:
        conditions: list[str] = []
        params: list[Any] = []
        if market is not None:
            conditions.append("market = ?")
            params.append(market.upper())
        if states:
            placeholders = ",".join("?" for _ in states)
            conditions.append(f"state IN ({placeholders})")
            params.extend(states)
        query = "SELECT payload FROM discovery_candidates"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY score DESC, sector, code"
        rows = self._conn.execute(query, tuple(params)).fetchall()
        return [candidate_from_record(json.loads(row["payload"])) for row in rows]

    def latest_by_key(
        self, market: str
    ) -> dict[tuple[str, str, str], DiscoveryCandidate]:
        candidates = self.list_candidates(market=market)
        result: dict[tuple[str, str, str], DiscoveryCandidate] = {}

        def generation_key(candidate: DiscoveryCandidate) -> tuple[float, float, int, str]:
            def timestamp(value: str) -> float:
                moment = datetime.fromisoformat(value)
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=timezone.utc)
                return moment.timestamp()

            active = int(candidate.state in {"forming", "armed", "triggered"})
            return (
                timestamp(candidate.updated_at),
                timestamp(candidate.first_seen_at),
                active,
                candidate.discovery_id,
            )

        for candidate in candidates:
            key = (candidate.sector, candidate.code, candidate.track)
            current = result.get(key)
            if current is None or generation_key(candidate) > generation_key(current):
                result[key] = candidate
        return result

    def should_notify(
        self,
        candidate: DiscoveryCandidate,
        *,
        no_notify: bool = False,
        notification_state: str | None = None,
    ) -> bool:
        """Deduplicate unchanged states while permitting later re-established states."""

        if no_notify:
            return False
        state = notification_state or candidate.state
        row = self._conn.execute(
            "SELECT state FROM discovery_notifications WHERE discovery_id = ? ORDER BY id DESC LIMIT 1",
            (candidate.discovery_id,),
        ).fetchone()
        if row is not None and row["state"] == state:
            return False
        self._conn.execute(
            "INSERT INTO discovery_notifications (discovery_id, state, notified_at) VALUES (?, ?, ?)",
            (candidate.discovery_id, state, _now_iso()),
        )
        self._conn.commit()
        return True

    def transition_history(self, discovery_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT from_state, to_state, transition_at, reason"
            " FROM discovery_transitions WHERE discovery_id = ? ORDER BY id",
            (discovery_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_review(self, review: dict[str, Any]) -> None:
        discovery_id = str(review["discovery_id"])
        self._conn.execute(
            "INSERT OR REPLACE INTO discovery_reviews (discovery_id, reviewed_at, payload)"
            " VALUES (?, ?, ?)",
            (
                discovery_id,
                _now_iso(),
                json.dumps(review, ensure_ascii=False, sort_keys=True),
            ),
        )
        self._conn.commit()

    def reviews(self, market: str | None = None) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT payload FROM discovery_reviews ORDER BY reviewed_at"
        ).fetchall()
        reviews = [json.loads(row["payload"]) for row in rows]
        if market is not None:
            reviews = [review for review in reviews if review.get("market") == market.upper()]
        return reviews
