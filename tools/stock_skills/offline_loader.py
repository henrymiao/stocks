"""Load the raw JSON emitted by the futuapi scripts, without OpenD.

The futuapi quote scripts (`get_snapshot.py`, `get_kline.py`, `get_capital_flow.py`)
print `{"data": [...]}` to stdout. When OpenD lives on a machine this process cannot
reach (e.g. the Cowork sandbox), run those scripts on the host, redirect their JSON into
the mounted workspace, and load them here. This module only parses already-fetched JSON —
it never imports the futu SDK or touches the network.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import CapitalSnapshot, KLineBar, MarketSnapshot


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if payload.get("error"):
            raise RuntimeError(f"futuapi script reported an error in {path}: {payload['error']}")
        rows = payload.get("data", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    if not isinstance(rows, list):
        raise ValueError(f"Unexpected JSON shape in {path}: expected a list under 'data'.")
    return rows


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_snapshot(path: str | Path, code: str | None = None) -> MarketSnapshot:
    """Parse `get_snapshot.py --json` output into a MarketSnapshot."""
    rows = _load_rows(path)
    if not rows:
        raise ValueError(f"No snapshot rows in {path}.")
    row = rows[0]
    if code is not None:
        row = next((r for r in rows if r.get("code") == code), row)
    captured_at = _now_iso()
    return MarketSnapshot(
        code=row.get("code", code or "N/A"),
        name=row.get("name", row.get("code", code or "")),
        last_price=float(row["last_price"]),
        open=float(row.get("open", 0) or 0),
        high=float(row.get("high", 0) or 0),
        low=float(row.get("low", 0) or 0),
        prev_close=float(row.get("prev_close", 0) or 0),
        volume=int(row.get("volume", 0) or 0),
        turnover=float(row.get("turnover", 0) or 0),
        timestamp=str(row.get("update_time") or captured_at),
        captured_at=captured_at,
    )


def load_bars(path: str | Path) -> list[KLineBar]:
    """Parse `get_kline.py --json` output into daily bars (chronological)."""
    bars: list[KLineBar] = []
    for row in _load_rows(path):
        bars.append(
            KLineBar(
                time=str(row.get("time", "")),
                open=float(row.get("open", 0) or 0),
                high=float(row.get("high", 0) or 0),
                low=float(row.get("low", 0) or 0),
                close=float(row.get("close", 0) or 0),
                volume=int(row.get("volume", 0) or 0),
                turnover=float(row.get("turnover", 0) or 0),
            )
        )
    return bars


def load_capital(path: str | Path) -> CapitalSnapshot | None:
    """Parse `get_capital_flow.py --json` output into a CapitalSnapshot.

    Mirrors the live fetcher: the last row is the full-day total, and comparing the
    second half of the intraday series against the first half denoises the read.
    """
    rows = _load_rows(path)
    if not rows:
        return None

    def _flow(row: dict[str, Any], key: str) -> float:
        value = row.get(key, 0)
        if value in (None, "N/A", ""):
            return 0.0
        return float(value)

    last = rows[-1]
    intraday_trend: str | None = None
    if len(rows) >= 4:
        mid = len(rows) // 2
        first_half = _flow(rows[mid - 1], "in_flow")
        second_half = _flow(last, "in_flow") - first_half
        if second_half > abs(first_half) * 0.1:
            intraday_trend = "accelerating-in"
        elif second_half < -abs(first_half) * 0.1:
            intraday_trend = "accelerating-out"
        else:
            intraday_trend = "flat"

    return CapitalSnapshot(
        net_inflow=_flow(last, "in_flow"),
        super_inflow=_flow(last, "super_in_flow"),
        big_inflow=_flow(last, "big_in_flow"),
        mid_inflow=_flow(last, "mid_in_flow"),
        small_inflow=_flow(last, "sml_in_flow"),
        timestamp=str(last.get("last_valid_time") or last.get("capital_flow_item_time") or _now_iso()),
        intraday_trend=intraday_trend,
    )
