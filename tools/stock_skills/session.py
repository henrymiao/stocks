from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


def _local_time(code: str, timestamp: str) -> datetime:
    value = datetime.fromisoformat(timestamp)
    market_timezone = ZoneInfo("America/New_York" if code.startswith("US.") else "Asia/Shanghai")
    if value.tzinfo is None:
        return value.replace(tzinfo=market_timezone)
    return value.astimezone(market_timezone)


def _inside(value: time, start: time, end: time) -> bool:
    return start <= value < end


def classify_session_phase(code: str, timestamp: str) -> str:
    local = _local_time(code, timestamp)
    if code.startswith("CC."):
        return "continuous"
    if local.weekday() >= 5:
        return "closed"

    current = local.time()
    if code.startswith("US."):
        if _inside(current, time(4), time(9, 30)):
            return "pre-open"
        if _inside(current, time(9, 30), time(16)):
            return "intraday"
        return "after-close"

    morning_close = time(12) if code.startswith("HK.") else time(11, 30)
    market_close = time(16) if code.startswith("HK.") else time(15)
    if current < time(9, 30):
        return "pre-open"
    if _inside(current, time(9, 30), morning_close) or _inside(current, time(13), market_close):
        return "intraday"
    if _inside(current, morning_close, time(13)):
        return "midday-break"
    return "after-close"
