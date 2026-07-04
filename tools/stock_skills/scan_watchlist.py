#!/usr/bin/env python3
"""Batch-score the watchlist into one compact table — token-cheap daily 复盘.

The heavy data-gathering (per-code `analyze` via OpenD) happens inside this one
command; only a small summary table comes back, so a full-pool review costs far
fewer tokens than fetching each name in prose.

Usage:
    python3 tools/stock_skills/scan_watchlist.py                 # whole watchlist
    python3 tools/stock_skills/scan_watchlist.py --tag defensive # one bucket
    python3 tools/stock_skills/scan_watchlist.py --market HK      # one market
    python3 tools/stock_skills/scan_watchlist.py --codes HK.09868,SZ.002463
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch-score the watchlist into one compact table")
    ap.add_argument("--watchlist", default="data/watchlists/core.json")
    ap.add_argument("--tag", help="only codes carrying this tag (e.g. defensive, robotics, index)")
    ap.add_argument("--market", help="only codes with this prefix: HK / US / SH / SZ / CC")
    ap.add_argument("--codes", help="comma-separated codes overriding the watchlist")
    ap.add_argument("--bars", default="60")
    args = ap.parse_args()

    if args.codes:
        entries = [{"code": c.strip(), "name": c.strip()} for c in args.codes.split(",") if c.strip()]
    else:
        entries = [e for e in json.load(open(args.watchlist))["watchlist"] if e.get("enabled", True)]
        if args.tag:
            entries = [e for e in entries if args.tag in e.get("tags", [])]
        if args.market:
            entries = [e for e in entries if e["code"].split(".")[0] == args.market]

    rows = []
    for e in entries:
        code = e["code"]
        out = f"/tmp/scan_{code.replace('.', '_')}.json"
        subprocess.run(
            [sys.executable, "-m", "tools.stock_skills.cli", "analyze",
             "--code", code, "--bars", args.bars, "--no-journal", "--output", out],
            capture_output=True,
        )
        try:
            p = json.load(open(out))
            cs = p["component_scores"]
            rows.append((round(p["total_score"], 1), code, p.get("name", ""), p["label"],
                         cs.get("trend", 0), cs.get("capital_flow", 0), cs.get("fundamental", 0),
                         p.get("entry_price"), p.get("invalidation_level")))
        except Exception:
            rows.append((-1.0, code, e.get("name", ""), "ERR", 0, 0, 0, None, None))

    rows.sort(reverse=True)
    print(f"{'code':<10} {'name':<14} {'label':<16} {'tot':>5} | {'trn':>3} {'cap':>3} {'fun':>3} | {'price':>7} {'stop':>7}")
    print("-" * 74)
    for t, code, name, label, tr, cap, fu, px, inv in rows:
        print(f"{code:<10} {str(name)[:14]:<14} {label:<16} {t:>5} | {tr:>3.0f} {cap:>3.0f} {fu:>3.0f} | {str(px):>7} {str(inv):>7}")
    print(f"\n{len(rows)} names scored. Report only deltas/triggers vs the stored plan; do not re-derive per stock.")


if __name__ == "__main__":
    main()
