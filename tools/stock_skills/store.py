from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .models import CapitalSnapshot, KLineBar, MarketSnapshot

DEFAULT_DB_PATH = "data/market.db"

# The store is a *cache and monitoring* layer, never the source of truth:
# journals stay in JSONL (git-diffable, feeds review/backtest/evidence as-is),
# and everything here can be rebuilt by re-fetching from Futu.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    code TEXT NOT NULL,
    ktype TEXT NOT NULL,
    time TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    turnover REAL NOT NULL,
    PRIMARY KEY (code, ktype, time)
);
CREATE TABLE IF NOT EXISTS snapshots (
    code TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    last_price REAL NOT NULL,
    prev_close REAL NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    volume INTEGER NOT NULL,
    turnover REAL NOT NULL,
    PRIMARY KEY (code, captured_at)
);
CREATE TABLE IF NOT EXISTS capital_flow (
    code TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    net REAL NOT NULL,
    super_net REAL NOT NULL,
    big_net REAL NOT NULL,
    mid_net REAL NOT NULL,
    small_net REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (code, captured_at)
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('below', 'above')),
    level REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    triggered_at TEXT,
    triggered_price REAL
);
CREATE TABLE IF NOT EXISTS earnings (
    code TEXT NOT NULL,
    event_date TEXT NOT NULL,
    session TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (code, event_date)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _event_date(value: object) -> str:
    text = _text("event_date", value)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"event_date must be YYYY-MM-DD: {text!r}") from exc
    return text


class MarketStore:
    """SQLite-backed market-data cache, alert book, and earnings calendar."""

    def __init__(self, path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MarketStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- bars ------------------------------------------------------------

    def upsert_bars(self, code: str, ktype: str, bars: list[KLineBar]) -> int:
        code = _text("code", code)
        ktype = _text("ktype", ktype)
        rows = [
            (
                code,
                ktype,
                _text("bar.time", bar.time),
                _finite("bar.open", bar.open),
                _finite("bar.high", bar.high),
                _finite("bar.low", bar.low),
                _finite("bar.close", bar.close),
                int(bar.volume),
                _finite("bar.turnover", bar.turnover),
            )
            for bar in bars
        ]
        self._conn.executemany(
            "INSERT INTO bars (code, ktype, time, open, high, low, close, volume, turnover)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (code, ktype, time) DO UPDATE SET"
            " open=excluded.open, high=excluded.high, low=excluded.low,"
            " close=excluded.close, volume=excluded.volume, turnover=excluded.turnover",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def get_bars(self, code: str, ktype: str = "1d", limit: int | None = None) -> list[KLineBar]:
        query = "SELECT time, open, high, low, close, volume, turnover FROM bars WHERE code = ? AND ktype = ?"
        if limit is None:
            rows = self._conn.execute(query + " ORDER BY time", (code, ktype)).fetchall()
        else:
            # Newest `limit` rows, returned in chronological order.
            rows = self._conn.execute(
                query + " ORDER BY time DESC LIMIT ?", (code, ktype, int(limit))
            ).fetchall()[::-1]
        return [
            KLineBar(
                time=row["time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                turnover=row["turnover"],
            )
            for row in rows
        ]

    def bar_count(self, code: str, ktype: str = "1d") -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM bars WHERE code = ? AND ktype = ?", (code, ktype)
        ).fetchone()
        return int(row["n"])

    # -- snapshots / capital flow ---------------------------------------

    def record_snapshot(self, snapshot: MarketSnapshot, captured_at: str | None = None) -> None:
        moment = captured_at or snapshot.captured_at or snapshot.timestamp or _now_iso()
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots"
            " (code, captured_at, last_price, prev_close, open, high, low, volume, turnover)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _text("code", snapshot.code),
                _text("captured_at", moment),
                _finite("last_price", snapshot.last_price),
                _finite("prev_close", snapshot.prev_close),
                _finite("open", snapshot.open),
                _finite("high", snapshot.high),
                _finite("low", snapshot.low),
                int(snapshot.volume),
                _finite("turnover", snapshot.turnover),
            ),
        )
        self._conn.commit()

    def record_capital(self, code: str, capital: CapitalSnapshot, captured_at: str | None = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO capital_flow"
            " (code, captured_at, net, super_net, big_net, mid_net, small_net, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _text("code", code),
                _text("captured_at", captured_at or capital.timestamp or _now_iso()),
                _finite("net", capital.net_inflow),
                _finite("super_net", capital.super_inflow),
                _finite("big_net", capital.big_inflow),
                _finite("mid_net", capital.mid_inflow),
                _finite("small_net", capital.small_inflow),
                capital.source,
            ),
        )
        self._conn.commit()

    def capital_history(self, code: str, limit: int = 30) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM capital_flow WHERE code = ? ORDER BY captured_at DESC LIMIT ?",
            (code, int(limit)),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    # -- alerts ----------------------------------------------------------

    def add_alert(self, code: str, direction: str, level: float, note: str = "") -> int:
        if direction not in {"below", "above"}:
            raise ValueError(f"direction must be 'below' or 'above', got {direction!r}")
        cursor = self._conn.execute(
            "INSERT INTO alerts (code, direction, level, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (_text("code", code), direction, _finite("level", level), str(note), _now_iso()),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def active_alerts(self, code: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM alerts WHERE triggered_at IS NULL"
        params: tuple[Any, ...] = ()
        if code is not None:
            query += " AND code = ?"
            params = (code,)
        rows = self._conn.execute(query + " ORDER BY code, level", params).fetchall()
        return [dict(row) for row in rows]

    def check_alerts(self, snapshots: dict[str, MarketSnapshot]) -> list[dict[str, Any]]:
        """One-shot alert check: a triggered alert is marked and never fires again."""
        triggered: list[dict[str, Any]] = []
        for alert in self.active_alerts():
            snapshot = snapshots.get(alert["code"])
            if snapshot is None:
                continue
            price = snapshot.last_price
            hit = price <= alert["level"] if alert["direction"] == "below" else price >= alert["level"]
            if not hit:
                continue
            moment = _now_iso()
            self._conn.execute(
                "UPDATE alerts SET triggered_at = ?, triggered_price = ? WHERE id = ?",
                (moment, price, alert["id"]),
            )
            alert.update(triggered_at=moment, triggered_price=price)
            triggered.append(alert)
        self._conn.commit()
        return triggered

    # -- earnings calendar ------------------------------------------------

    def upsert_earnings(self, code: str, event_date: str, session: str = "", note: str = "") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO earnings (code, event_date, session, note) VALUES (?, ?, ?, ?)",
            (_text("code", code), _event_date(event_date), str(session), str(note)),
        )
        self._conn.commit()

    def upcoming_earnings(self, within_days: int = 14, today: str | None = None) -> list[dict[str, Any]]:
        anchor = date.fromisoformat(today) if today else date.today()
        rows = self._conn.execute(
            "SELECT * FROM earnings WHERE event_date >= ? ORDER BY event_date", (anchor.isoformat(),)
        ).fetchall()
        results = []
        for row in rows:
            days = (date.fromisoformat(row["event_date"]) - anchor).days
            if days <= within_days:
                record = dict(row)
                record["days_until"] = days
                results.append(record)
        return results


def sync_daily_bars(store: MarketStore, fetcher: Any, code: str, num: int = 60) -> list[KLineBar]:
    """Fetch daily bars from Futu and upsert them into the cache (idempotent).

    Offline consumers should read store.get_bars() directly; this helper is the
    single write path so the cache never diverges from what the fetcher saw.
    """
    bars = fetcher.get_daily_bars(code, num=num)
    if bars:
        store.upsert_bars(code, "1d", bars)
    return bars
