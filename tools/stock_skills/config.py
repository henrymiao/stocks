from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

REQUIRED_WEIGHT_KEYS = {
    "trend",
    "capital_flow",
    "sector",
    "cross_market",
    "macro_risk",
    "position_fit",
}


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
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("watchlist entries must be objects")
        if entry.get("enabled", True):
            code = entry.get("code")
            name = entry.get("name")
            tags = entry.get("tags", [])
            if not isinstance(code, str) or "." not in code:
                raise ValueError(f"Invalid watchlist code: {code!r}")
            if not isinstance(name, str) or not name:
                raise ValueError(f"Invalid watchlist name for {code}")
            if not isinstance(tags, list):
                raise ValueError(f"Invalid tags for {code}")
            enabled_entries.append(entry)
    return enabled_entries


def load_weights(path: str | Path) -> dict[str, float]:
    payload = load_json(path)
    keys = set(payload)
    if keys != REQUIRED_WEIGHT_KEYS:
        missing = sorted(REQUIRED_WEIGHT_KEYS - keys)
        extra = sorted(keys - REQUIRED_WEIGHT_KEYS)
        raise ValueError(f"Invalid weight keys. Missing={missing}, extra={extra}")

    weights: dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError(f"Invalid signal weight for {key}: {value!r}")
        weights[key] = float(value)

    total = sum(weights.values())
    if abs(total - 1.0) > 0.000001:
        raise ValueError(f"Signal weights must sum to 1.0, got {total}")
    if any(value < 0 for value in weights.values()):
        raise ValueError("Signal weights must be non-negative")
    return weights
