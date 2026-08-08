"""Replay journalled exit plans through the price path that actually followed.

`backtest` measures where price sat a fixed number of sessions after a call, with no stop,
no target and no trailing rule -- so its expectancy answers "act on this call and hold
blind", which is not what the recommendation says to do. The plan's own
`maximum_holding_days` is 20 while the review window is 5, so it was being graded a
quarter of the way through.

`path_backtest` already replays a structured exit plan bar by bar, but it only ever took a
hand-built scenario file and was never pointed at the journal. It never needed to be: the
`exit_plan` written into every recommendation carries exactly the fields
`exit_plan_from_record` requires, field for field. This module is the missing wire.

Bars come from the local market store, so a replay reads the same completed daily bars the
rest of the system does and needs no network.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import KLineBar
from .store import MarketStore


def _entry_date(timestamp: str) -> str:
    return datetime.fromisoformat(timestamp).date().isoformat()


def _bar_date(bar: KLineBar) -> str:
    return datetime.fromisoformat(bar.time).date().isoformat()


def forward_bars(
    store: MarketStore, code: str, after: str, limit: int
) -> list[KLineBar]:
    """Completed daily bars strictly after the call's own session.

    Strictly after: the call was made from that session's data, so including it would
    settle the trade on a bar the recommendation had already seen.
    """

    bars = [bar for bar in store.get_bars(code, "1d") if _bar_date(bar) > after]
    bars.sort(key=_bar_date)
    return bars[:limit]


def scenarios_from_journal(
    recommendations: list[dict[str, Any]],
    store: MarketStore,
    *,
    costs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a path-backtest scenario payload from journalled recommendations.

    Returns the serialized `{"trades": [...]}` payload -- deliberately not the converted
    objects -- so the journal path goes through the same `scenarios_from_record` validation
    a hand-written scenario file does, rather than a second, looser conversion.

    The second return value reports what could not be replayed: a silently short list would
    read as "the plans did fine" when it means "most were skipped".
    """

    scenarios: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for record in sorted(recommendations, key=lambda row: str(row.get("timestamp"))):
        code = record.get("code")
        timestamp = record.get("timestamp")
        plan = record.get("exit_plan")
        if not isinstance(code, str) or not isinstance(timestamp, str):
            skip("missing-code-or-timestamp")
            continue
        if not isinstance(plan, dict) or plan.get("initial_stop") is None:
            skip("no-exit-plan")
            continue
        try:
            entry = _entry_date(timestamp)
        except ValueError:
            skip("unparsable-timestamp")
            continue
        # One replay per instrument per entry session: the same plan re-journalled the
        # same day would otherwise weight that trade twice, the flaw `independent_reviews`
        # fixes on the review side.
        if (code, entry) in seen:
            skip("duplicate-entry-session")
            continue

        holding = plan.get("maximum_holding_days")
        horizon = int(holding) if isinstance(holding, (int, float)) else 20
        bars = forward_bars(store, code, entry, horizon)
        if len(bars) < 2:
            skip("insufficient-forward-bars")
            continue

        seen.add((code, entry))
        trade: dict[str, Any] = {
            "trade_id": record.get("trade_id") or f"{code}@{entry}",
            "exit_plan": plan,
            "bars": [
                {
                    "time": bar.time,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "turnover": bar.turnover,
                }
                for bar in bars
            ],
            "leveraged": bool(record.get("leveraged", False)),
        }
        if costs is not None:
            trade["costs"] = costs
        scenarios.append(trade)

    return {"trades": scenarios}, {
        "replayed": len(scenarios),
        "skipped": dict(sorted(skipped.items())),
        "skipped_total": sum(skipped.values()),
    }
