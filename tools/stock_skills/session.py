from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


def _local_time(prefix: str, timestamp: str) -> datetime:
    value = datetime.fromisoformat(timestamp)
    market_timezone = ZoneInfo(
        {
            "US": "America/New_York",
            "HK": "Asia/Hong_Kong",
            "SH": "Asia/Shanghai",
            "SZ": "Asia/Shanghai",
            "CC": "Asia/Shanghai",
        }[prefix]
    )
    if value.tzinfo is None:
        return value.replace(tzinfo=market_timezone)
    return value.astimezone(market_timezone)


def _inside(value: time, start: time, end: time) -> bool:
    return start <= value < end


def classify_session_phase(code: str, timestamp: str) -> str:
    """Classify a regular weekday schedule without exchange holidays or early closes."""
    code_parts = code.split(".", 1)
    if len(code_parts) != 2 or not code_parts[1]:
        raise ValueError(f"Malformed market code: {code!r}")
    prefix = code_parts[0].upper()
    if prefix not in {"US", "HK", "SH", "SZ", "CC"}:
        raise ValueError(f"Unsupported market prefix: {code_parts[0]!r}")

    local = _local_time(prefix, timestamp)
    if prefix == "CC":
        return "continuous"
    if local.weekday() >= 5:
        return "closed"

    current = local.time()
    if prefix == "US":
        if _inside(current, time(4), time(9, 30)):
            return "pre-open"
        if _inside(current, time(9, 30), time(16)):
            return "intraday"
        return "after-close"

    morning_close = time(12) if prefix == "HK" else time(11, 30)
    market_close = time(16) if prefix == "HK" else time(15)
    if current < time(9, 30):
        return "pre-open"
    if _inside(current, time(9, 30), morning_close) or _inside(current, time(13), market_close):
        return "intraday"
    if _inside(current, morning_close, time(13)):
        return "midday-break"
    return "after-close"
