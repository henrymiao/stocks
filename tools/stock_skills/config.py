from __future__ import annotations

import json
import math
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_WEIGHT_KEYS = {
    "trend",
    "capital_flow",
    "sector",
    "cross_market",
    "macro_risk",
    "market_regime",
    "fundamental",
    "position_fit",
}

WATCHLIST_TIERS = {"core", "thematic", "proxy", "discovery"}
STRATEGY_PROFILES = {"short", "swing"}
VALUATION_PROFILES = {"growth", "value", "neutral"}
ASSET_TYPES = {"equity", "etf", "leveraged-etf", "crypto", "index", "fund"}


def _infer_tier(tags: list[str]) -> str:
    lowered = set(tags)
    if "holding" in lowered or "active-setup" in lowered:
        return "core"
    if lowered & {"index", "macro", "risk-appetite", "sector-proxy"}:
        return "proxy"
    if "discovery" in lowered:
        return "discovery"
    return "thematic"


def _infer_asset_type(tags: list[str], name: str) -> str:
    lowered = set(tags)
    if "leveraged" in lowered or "hedge" in lowered and "semiconductor" in lowered:
        return "leveraged-etf"
    if "crypto" in lowered:
        return "crypto"
    if lowered & {"index", "etf"} or "etf" in name.lower() or "基金" in name:
        return "etf"
    return "equity"


def _infer_valuation_profile(tags: list[str]) -> str:
    lowered = set(tags)
    if lowered & {"growth", "ai", "ai-hardware", "china-growth", "crypto-equity"}:
        return "growth"
    if lowered & {"value", "dividend", "defensive", "utility", "bank"}:
        return "value"
    return "neutral"


def _default_benchmark(code: str) -> str | None:
    market = code.split(".", 1)[0]
    return {
        "US": "US.SPY",
        "HK": "HK.800000",
        "SH": "SH.000001",
        "SZ": "SZ.399006",
        "CC": "CC.BTC",
    }.get(market)


def _default_underlying(code: str, asset_type: str) -> str | None:
    if asset_type != "leveraged-etf":
        return None
    return {
        "US.SOXL": "US.SMH",
        "US.SOXS": "US.SMH",
    }.get(code)


def normalize_watchlist_entry(entry: dict[str, Any]) -> dict[str, Any]:
    code = entry.get("code")
    name = entry.get("name")
    tags = entry.get("tags", [])
    if not isinstance(code, str) or "." not in code:
        raise ValueError(f"Invalid watchlist code: {code!r}")
    if not isinstance(name, str) or not name:
        raise ValueError(f"Invalid watchlist name for {code}")
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        raise ValueError(f"Invalid tags for {code}")
    enabled = entry.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"Invalid enabled flag for {code}: {enabled!r}")

    tier = entry.get("tier", _infer_tier(tags))
    if tier not in WATCHLIST_TIERS:
        raise ValueError(f"Invalid tier for {code}: {tier!r}")
    priority = entry.get("priority", 100 if tier == "core" else 50 if tier == "thematic" else 25)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100:
        raise ValueError(f"Invalid priority for {code}: {priority!r}")
    strategies = entry.get("strategy_profiles", ["short", "swing"] if tier in {"core", "thematic"} else [])
    if (
        not isinstance(strategies, list)
        or any(strategy not in STRATEGY_PROFILES for strategy in strategies)
        or len(strategies) != len(set(strategies))
    ):
        raise ValueError(f"Invalid strategy_profiles for {code}: {strategies!r}")
    asset_type = entry.get("asset_type", _infer_asset_type(tags, name))
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"Invalid asset_type for {code}: {asset_type!r}")
    valuation_profile = entry.get("valuation_profile", _infer_valuation_profile(tags))
    if valuation_profile not in VALUATION_PROFILES:
        raise ValueError(f"Invalid valuation_profile for {code}: {valuation_profile!r}")
    benchmark = entry.get("benchmark", _default_benchmark(code))
    underlying = entry.get("underlying_proxy", _default_underlying(code, asset_type))
    for field_name, related_code in (("benchmark", benchmark), ("underlying_proxy", underlying)):
        if related_code is not None and (not isinstance(related_code, str) or "." not in related_code):
            raise ValueError(f"Invalid {field_name} for {code}: {related_code!r}")
    event_policy = entry.get("event_policy", "none" if tier == "proxy" else "standard")
    if not isinstance(event_policy, str) or not event_policy:
        raise ValueError(f"Invalid event_policy for {code}: {event_policy!r}")

    normalized = dict(entry)
    normalized.update(
        code=code,
        name=name,
        tags=list(dict.fromkeys(tags)),
        enabled=enabled,
        tier=tier,
        priority=priority,
        strategy_profiles=strategies,
        asset_type=asset_type,
        valuation_profile=valuation_profile,
        benchmark=benchmark,
        underlying_proxy=underlying,
        event_policy=event_policy,
    )
    return normalized


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def load_watchlist(path: str | Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    entries = payload.get("watchlist")
    if not isinstance(entries, list):
        raise ValueError("watchlist must be a list")

    enabled_entries: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("watchlist entries must be objects")
        normalized = normalize_watchlist_entry(entry)
        code = normalized["code"]
        if code in seen_codes:
            raise ValueError(f"Duplicate watchlist code: {code}")
        seen_codes.add(code)
        if not normalized["enabled"]:
            continue
        enabled_entries.append(normalized)
    return enabled_entries


def validate_weights(payload: dict[str, Any]) -> dict[str, float]:
    keys = set(payload)
    if keys != REQUIRED_WEIGHT_KEYS:
        missing = sorted(REQUIRED_WEIGHT_KEYS - keys)
        extra = sorted(keys - REQUIRED_WEIGHT_KEYS)
        raise ValueError(f"Invalid weight keys. Missing={missing}, extra={extra}")

    weights: dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Invalid signal weight for {key}: {value!r}")
        weights[key] = float(value)

    total = sum(weights.values())
    if abs(total - 1.0) > 0.000001:
        raise ValueError(f"Signal weights must sum to 1.0, got {total}")
    if any(value < 0 for value in weights.values()):
        raise ValueError("Signal weights must be non-negative")
    return weights


def load_weights(path: str | Path) -> dict[str, float]:
    return validate_weights(load_json(path))


def save_weights(
    path: str | Path,
    weights: dict[str, float],
    reason: str = "",
    history_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist new signal weights, keeping the change reversible and explainable.

    Before overwriting, the current file is copied to `<path>.bak` (reversible).
    The change (old, new, reason, timestamp) is appended to a JSONL history file
    next to the weights, defaulting to `weight_history.jsonl` (explainable).
    """
    validated = validate_weights(dict(weights))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    previous: dict[str, float] | None = None
    if target.exists():
        previous = load_weights(target)
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))

    target.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")

    history = Path(history_path) if history_path else target.parent / "weight_history.jsonl"
    entry = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "previous": previous,
        "new": validated,
        "reason": reason,
    }
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return entry
