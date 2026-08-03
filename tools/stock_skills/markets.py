from __future__ import annotations

from datetime import datetime
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
