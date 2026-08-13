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

from datetime import date, datetime, timedelta
from math import ceil
from typing import Any

from .models import KLineBar
from .store import MarketStore

# How far the first forward bar may sit from the call's own session before the replay is
# no longer a replay of that call. Daily bars are synced with a bounded `num`, so a
# recommendation older than the store's coverage would otherwise be settled against a
# window starting weeks later while `exit_plan.entry_price` is still the original -- an
# instant gap-stop and a fabricated loss, counted as `closed_by_plan`. Five calendar days
# spans a weekend plus a holiday without admitting a genuine coverage hole.
MAXIMUM_ENTRY_GAP_DAYS = 5


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

    Returns nothing when the first available bar is not adjacent to that session, so a
    call the store no longer covers is skipped rather than replayed against a later,
    unrelated window.
    """

    bars = [bar for bar in store.get_bars(code, "1d") if _bar_date(bar) > after]
    bars.sort(key=_bar_date)
    if not bars:
        return []
    if date.fromisoformat(_bar_date(bars[0])) - date.fromisoformat(after) > timedelta(
        days=MAXIMUM_ENTRY_GAP_DAYS
    ):
        return []
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
    # Per instrument, the end of the window the last accepted replay occupies. A held
    # position is re-journalled every session it is reviewed, and keying only on the entry
    # date drops just the same-day repeats: `baba-09988-20260718` still replayed three
    # times over overlapping windows at entry prices 112.6, 116.8 and 125.2, so whichever
    # position was reviewed most often dominated expectancy. This is the same
    # non-overlapping rule `independent_reviews` applies on the review side, measured
    # against the plan's own holding period rather than a fixed review window.
    window_end: dict[str, date] = {}

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
        holding = plan.get("maximum_holding_days")
        horizon = int(holding) if isinstance(holding, (int, float)) else 20

        # One replay per instrument per non-overlapping holding period. Records are
        # processed in timestamp order, so the first call of a window is the one kept.
        entry_day = date.fromisoformat(entry)
        occupied = window_end.get(code)
        if occupied is not None and entry_day < occupied:
            skip("overlapping-holding-window")
            continue

        bars = forward_bars(store, code, entry, horizon)
        if len(bars) < 2:
            skip("insufficient-forward-bars")
            continue

        # Calendar span of the trading-day horizon, the same widest-span convention
        # `independent_reviews` uses, so a pair is dropped only when it certainly overlaps.
        window_end[code] = entry_day + timedelta(days=ceil(horizon * 7 / 5))
        trade: dict[str, Any] = {
            # Unique per replayed call, not per position. A position id like
            # `xpeng-09868-core83` recurs across entry sessions, and `run_path_backtest`
            # drops repeated trade_ids -- which would silently shorten its trades list and
            # misalign it against the scenarios it was built from.
            "trade_id": f"{record.get('trade_id') or code}@{entry}",
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


# The replay reports this when it runs out of bars before the plan reaches an exit: the
# trade is still open, not closed at the last price we happen to hold.
UNDECIDED_EXIT = "end-of-data"


def replay_journal(
    recommendations: list[dict[str, Any]],
    store: MarketStore,
    *,
    costs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay journalled exit plans, counting only the trades the plan actually closed.

    A position whose horizon has not elapsed is open, and marking it to the last bar we
    hold is not a result. The first pass over the 2026-08 journal closed 7 of 14 trades on
    `end-of-data` after 3 to 5 bars against a 20-day plan -- they were cut short by the
    calendar, not by the plan, and blending them in reported a capture ratio that partly
    measured when we stopped watching. That is the same error the fixed-window backtest
    makes, so it must not be repeated here.
    """

    from .path_backtest import run_path_backtest, scenarios_from_record

    payload, coverage = scenarios_from_journal(recommendations, store, costs=costs)
    if not payload["trades"]:
        return {"summary": {"trades": 0}, "trades": [], "journal_coverage": coverage}

    scenarios = scenarios_from_record(payload)
    provisional = run_path_backtest(scenarios)
    if len(provisional["trades"]) != len(scenarios):
        raise RuntimeError(
            "path replay returned a different number of trades than scenarios; "
            "the result-to-scenario pairing below would be misaligned"
        )
    decided = [
        scenario
        for scenario, trade in zip(scenarios, provisional["trades"])
        if trade.get("exit_reason") != UNDECIDED_EXIT
    ]
    still_open = len(provisional["trades"]) - len(decided)

    report = (
        run_path_backtest(decided)
        if decided
        else {"summary": {"trades": 0}, "trades": []}
    )
    report["journal_coverage"] = coverage | {
        "closed_by_plan": len(decided),
        "still_open": still_open,
    }
    report["provisional_including_open"] = provisional["summary"]
    return report
