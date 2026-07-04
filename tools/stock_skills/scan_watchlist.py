#!/usr/bin/env python3
"""Batch-score the watchlist into one compact table — token-cheap daily 复盘.

The heavy data-gathering (per-code `analyze` via OpenD) happens inside this one
command; only a small summary table comes back, so a full-pool review costs far
fewer tokens than fetching each name in prose.

The score (`tot`) measures momentum + quality; it is NOT a cheap/expensive read.
Pass --valuation to add the historical valuation percentile (`val%`) so you can
tell a "cheap high" from an "expensive high" — a high score at a 99th-percentile
valuation is chasing, a high score at a low percentile is a real value entry.

Usage:
    python3 tools/stock_skills/scan_watchlist.py                       # whole watchlist
    python3 tools/stock_skills/scan_watchlist.py --tag defensive       # one bucket
    python3 tools/stock_skills/scan_watchlist.py --market HK           # one market
    python3 tools/stock_skills/scan_watchlist.py --codes HK.09868,...  # explicit list
    python3 tools/stock_skills/scan_watchlist.py --tag bank --valuation  # add val percentile
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

_VAL_SCRIPT_CANDIDATES = [
    "skills/futuapi/scripts/quote/get_valuation_detail.py",
    os.path.expanduser("~/.claude/skills/futuapi/scripts/quote/get_valuation_detail.py"),
    os.path.expanduser("~/.cursor/skills/futuapi/scripts/quote/get_valuation_detail.py"),
]
_VAL_TYPE = {1: "PE", 2: "PB", 3: "PS"}


def _find_valuation_script() -> str | None:
    for c in _VAL_SCRIPT_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def _valuation(code: str, script: str | None) -> tuple[str, float] | None:
    """Return (metric, percentile 0-100) from the server-recommended valuation, or None."""
    if not script:
        return None
    try:
        out = subprocess.run(
            [sys.executable, script, code, "--interval-type", "7", "--json"],
            capture_output=True, text=True, timeout=45,
        )
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            data = json.loads(line).get("data", {})
            trend = data.get("trend") or {}
            pct = trend.get("valuation_percentile")
            if pct is None:
                return None
            pct = pct * 100 if pct <= 1.0 else pct  # feed mixes 0-1 and 0-100 scales
            return (_VAL_TYPE.get(data.get("valuation_type"), "?"), round(pct))
    except Exception:
        return None
    return None


def _val_flag(pct: float | None) -> str:
    if pct is None:
        return "  -"
    if pct <= 30:
        return "便宜"
    if pct >= 70:
        return " 贵 "
    return " 中 "


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch-score the watchlist into one compact table")
    ap.add_argument("--watchlist", default="data/watchlists/core.json")
    ap.add_argument("--tag", help="only codes carrying this tag (e.g. defensive, robotics, index)")
    ap.add_argument("--market", help="only codes with this prefix: HK / US / SH / SZ / CC")
    ap.add_argument("--codes", help="comma-separated codes overriding the watchlist")
    ap.add_argument("--bars", default="60")
    ap.add_argument("--valuation", action="store_true",
                    help="also fetch each name's historical valuation percentile (slower)")
    args = ap.parse_args()

    if args.codes:
        entries = [{"code": c.strip(), "name": c.strip()} for c in args.codes.split(",") if c.strip()]
    else:
        entries = [e for e in json.load(open(args.watchlist))["watchlist"] if e.get("enabled", True)]
        if args.tag:
            entries = [e for e in entries if args.tag in e.get("tags", [])]
        if args.market:
            entries = [e for e in entries if e["code"].split(".")[0] == args.market]

    val_script = _find_valuation_script() if args.valuation else None

    rows = []
    for e in entries:
        code = e["code"]
        out = f"/tmp/scan_{code.replace('.', '_')}.json"
        subprocess.run(
            [sys.executable, "-m", "tools.stock_skills.cli", "analyze",
             "--code", code, "--bars", args.bars, "--no-journal", "--output", out],
            capture_output=True,
        )
        val = _valuation(code, val_script) if args.valuation else None
        try:
            p = json.load(open(out))
            cs = p["component_scores"]
            rows.append([round(p["total_score"], 1), code, p.get("name", ""), p["label"],
                         cs.get("trend", 0), cs.get("capital_flow", 0), cs.get("fundamental", 0),
                         p.get("entry_price"), p.get("invalidation_level"), val])
        except Exception:
            rows.append([-1.0, code, e.get("name", ""), "ERR", 0, 0, 0, None, None, val])

    rows.sort(reverse=True, key=lambda r: r[0])
    header = f"{'code':<10} {'name':<14} {'label':<16} {'tot':>5} | {'trn':>3} {'cap':>3} {'fun':>3} | {'price':>7} {'stop':>7}"
    if args.valuation:
        header += f" | {'val':>4} {'val%':>4} {'读':>4}"
    print(header)
    print("-" * (len(header) + 2))
    for r in rows:
        t, code, name, label, tr, cap, fu, px, inv, val = r
        line = (f"{code:<10} {str(name)[:14]:<14} {label:<16} {t:>5} | "
                f"{tr:>3.0f} {cap:>3.0f} {fu:>3.0f} | {str(px):>7} {str(inv):>7}")
        if args.valuation:
            metric = val[0] if val else "-"
            pct = val[1] if val else None
            line += f" | {metric:>4} {('' if pct is None else str(pct)):>4} {_val_flag(pct):>4}"
        print(line)
    print(f"\n{len(rows)} names scored. Score = momentum+quality; "
          f"{'val% = historical valuation percentile (低=便宜). ' if args.valuation else 'add --valuation for cheap/expensive. '}"
          f"Report only deltas/triggers vs the stored plan; do not re-derive per stock.")


if __name__ == "__main__":
    main()
