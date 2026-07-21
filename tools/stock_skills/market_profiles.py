from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketProfile:
    profile_id: str
    benchmark_codes: tuple[str, ...]
    buy_zone_extension_pct: float
    minimum_stage_bars: int
    allowed_valuation_methods: tuple[str, ...]
    session_timezone: str
    price_limit_policy: str
    lot_policy: str
    liquidity_currency: str


_US = MarketProfile(
    "us-equity-v1",
    ("US.QQQ", "US.SPY"),
    0.05,
    220,
    ("earnings-multiple", "sotp", "dcf"),
    "America/New_York",
    "none",
    "single-share",
    "USD",
)
_A = MarketProfile(
    "a-share-equity-v1",
    ("SH.000001", "SZ.399006"),
    0.03,
    220,
    ("earnings-multiple", "sotp", "dcf"),
    "Asia/Shanghai",
    "board-aware",
    "board-lot",
    "CNY",
)
_HK = MarketProfile(
    "hk-equity-v1",
    ("HK.800000", "HK.800700"),
    0.03,
    220,
    ("earnings-multiple", "sotp", "dcf"),
    "Asia/Shanghai",
    "none",
    "board-lot",
    "HKD",
)
_UNKNOWN = MarketProfile(
    "unknown-market-v1",
    (),
    0.0,
    220,
    (),
    "UTC",
    "unknown",
    "unknown",
    "unknown",
)


def resolve_market_profile(code: str, asset_type: str = "equity") -> MarketProfile:
    del asset_type  # ETF/leveraged behavior remains a separate composable overlay.
    prefix = code.split(".", 1)[0].upper() if "." in code else ""
    if prefix == "US":
        return _US
    if prefix in {"SH", "SZ"}:
        return _A
    if prefix == "HK":
        return _HK
    return _UNKNOWN
