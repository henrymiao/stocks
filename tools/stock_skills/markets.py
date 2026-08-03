from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


MARKET_TIMEZONES = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}
MARKET_PREFIXES = {
    "CN": frozenset({"SH", "SZ"}),
    "HK": frozenset({"HK"}),
    "US": frozenset({"US"}),
}
MARKET_CURRENCIES = {"CN": "CNY", "HK": "HKD", "US": "USD"}
MARKET_CLOSE_TIMES = {"CN": time(15, 0), "HK": time(16, 0), "US": time(16, 0)}
DAILY_BAR_INTERVAL = "1d"
INTRADAY_BAR_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "60m": 60}


def normalize_market(value: str) -> str:
    market = str(value).upper()
    if market not in MARKET_TIMEZONES:
        raise ValueError(f"Unsupported market: {value!r}")
    return market


def market_from_code(code: str) -> str:
    if "." not in code or not code.split(".", 1)[1]:
        raise ValueError(f"Malformed market code: {code!r}")
    prefix = code.split(".", 1)[0].upper()
    for market, prefixes in MARKET_PREFIXES.items():
        if prefix in prefixes:
            return market
    raise ValueError(f"Unsupported market prefix: {prefix!r}")


def market_timezone(market: str) -> ZoneInfo:
    return ZoneInfo(MARKET_TIMEZONES[normalize_market(market)])


def market_currency(market: str) -> str:
    return MARKET_CURRENCIES[normalize_market(market)]


def market_moment(value: str, market: str) -> datetime:
    moment = datetime.fromisoformat(value)
    timezone = market_timezone(market)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone)
    return moment.astimezone(timezone)


def market_close_time(market: str) -> time:
    return MARKET_CLOSE_TIMES[normalize_market(market)]


def bar_close_moment(value: str, market: str, interval: str) -> datetime:
    """Return the local moment a K-line bar finished forming.

    OpenD stamps every bar with the START of its interval: a daily bar carries the
    session date and a five-minute bar carries 09:50, not 09:55.  A bar is therefore
    only observable once its interval has elapsed, and comparing its start against a
    cutoff would admit the still-forming current session.  The regular-schedule close
    is used without exchange holidays or early closes, which can only make the result
    conservative (an early-closing session is treated as unfinished for longer).
    """

    market = normalize_market(market)
    start = market_moment(value, market)
    if interval == DAILY_BAR_INTERVAL:
        close = MARKET_CLOSE_TIMES[market]
        return start.replace(
            hour=close.hour, minute=close.minute, second=0, microsecond=0
        )
    if interval not in INTRADAY_BAR_MINUTES:
        raise ValueError(f"Unsupported bar interval: {interval!r}")
    return start + timedelta(minutes=INTRADAY_BAR_MINUTES[interval])
