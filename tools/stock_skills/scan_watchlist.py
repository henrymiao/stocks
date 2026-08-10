#!/usr/bin/env python3
"""Tiered watchlist promotion scan with one shared batch snapshot."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.stock_skills.config import load_watchlist, normalize_watchlist_entry
from tools.stock_skills.cli import DEFAULT_MACRO_CODES
from tools.stock_skills.futu_fetcher import FutuFetcher, _default_skill_dir
from tools.stock_skills.watchlist_scan import run_watchlist_scan

_VAL_TYPE = {1: "PE", 2: "PB", 3: "PS"}


def _find_valuation_script() -> str | None:
    override = os.environ.get("FUTUAPI_SKILL_DIR")
    try:
        skill_dir = Path(override) if override else _default_skill_dir()
    except FileNotFoundError:
        return None
    candidate = skill_dir / "scripts" / "quote" / "get_valuation_detail.py"
    return str(candidate) if candidate.is_file() else None


def _valuation(code: str, script: str | None) -> dict[str, Any] | None:
    if not script:
        return None
    try:
        completed = subprocess.run(
            [sys.executable, script, code, "--interval-type", "7", "--json"],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        for line in completed.stdout.splitlines():
            if not line.strip().startswith("{"):
                continue
            data = json.loads(line).get("data", {})
            percentile = (data.get("trend") or {}).get("valuation_percentile")
            if percentile is None:
                return None
            percentile = percentile * 100 if percentile <= 1.0 else percentile
            return {
                "metric": _VAL_TYPE.get(data.get("valuation_type"), "?"),
                "percentile": round(percentile),
            }
    except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError):
        return None
    return None


def _explicit_entries(codes: str, watchlist: str | Path) -> list[dict[str, Any]]:
    """Resolve `--codes` against the canonical watchlist, stubbing only unknown codes.

    A stub carries no tags, so `valuation_profile` defaults to `neutral` and the
    fundamental component is scored on the wrong yardstick. On 2026-08-10 that made Zijin
    read `cheap` at 75 under a `--codes` scan and `fair` at 66 under a plain `analyze`,
    off the same PE of 15.28 -- and 9 points there is the difference between `probe` and
    `watch`. Scanning a code by name must not answer differently from scanning it as part
    of its own watchlist.
    """

    known = {entry["code"]: entry for entry in load_watchlist(watchlist)}
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in codes.split(","):
        code = raw.strip()
        if not code:
            continue
        if code in seen:
            raise ValueError(f"Duplicate watchlist code: {code}")
        seen.add(code)
        entries.append(
            known.get(code)
            or normalize_watchlist_entry(
                {"code": code, "name": code, "tags": [], "tier": "thematic"}
            )
        )
    return entries


def _analysis_command(
    entry: dict[str, Any],
    horizon: str,
    output: str | Path,
    shared_context: str | Path,
    watchlist: str | Path,
    bars: int | None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "tools.stock_skills.cli",
        "analyze",
        "--code",
        entry["code"],
        "--horizon",
        horizon,
        "--profile",
        entry["valuation_profile"],
        "--watchlist",
        str(watchlist),
        "--shared-context",
        str(shared_context),
        "--no-journal",
        "--output",
        str(output),
    ]
    effective_bars = bars if bars is not None else (60 if horizon == "short" else None)
    if effective_bars is not None:
        command.extend(["--bars", str(effective_bars)])
    return command


def _print_table(result: dict[str, Any], horizon: str) -> None:
    rows = result["candidates"]
    print(f"{'code':<11} {'tier':<10} {'status':<9} {'phase':<12} {'chg%':>7} {'RS%':>7} {'rank':>5} {'selected':<16} {'treatment':<14}")
    print("-" * 106)
    rank_by_code = {item["code"]: item["rank"] for item in result["rankings"][horizon]}
    selection_by_code = {
        item["code"]: ",".join(item["selection_reasons"])
        for item in result["selections"][horizon]
    }
    rows = sorted(
        rows,
        key=lambda row: (
            0 if row["tier"] == "core" else 1,
            rank_by_code.get(row["code"], 9999),
            row["code"],
        ),
    )
    for row in rows:
        change = "-" if row.get("change_pct") is None else f"{row['change_pct']:.2f}"
        relative = "-" if row.get("relative_strength_pct") is None else f"{row['relative_strength_pct']:.2f}"
        rank = rank_by_code.get(row["code"], "-")
        selected = selection_by_code.get(row["code"], "-")
        print(
            f"{row['code']:<11} {row['tier']:<10} {row['filter_status']:<9} "
            f"{row['session_phase']:<12} {change:>7} {relative:>7} {str(rank):>5} "
            f"{selected:<16} {row['treatment']:<14}"
        )
    print(
        f"\nBatch snapshots {result['snapshot_received_count']}/{result['snapshot_request_count']}; "
        f"deep analyses {len(result['deep_analysis'])}. Rankings only promote candidates; "
        "rejected rows do not receive trade recommendations."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tiered batch watchlist scanner")
    parser.add_argument("--watchlist", default="data/watchlists/core.json")
    parser.add_argument("--tag")
    parser.add_argument("--market", choices=["HK", "US", "SH", "SZ", "CC"])
    parser.add_argument("--tier", choices=["core", "thematic", "proxy", "discovery"])
    parser.add_argument("--codes", help="Comma-separated codes overriding the watchlist")
    parser.add_argument("--bars", type=int, default=None)
    parser.add_argument("--deep-top", type=int, default=10, help="Top thematic names per requested horizon")
    parser.add_argument("--deep-per-theme", type=int, default=0, help="Minimum deep analyses per theme, so momentum ranking cannot starve a whole sector")
    parser.add_argument(
        "--deep-bottom",
        type=int,
        default=5,
        help="Largest eligible thematic decliners per requested horizon",
    )
    parser.add_argument("--horizon", choices=["short", "swing", "both"], default="short")
    parser.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--event-days", type=int, default=None)
    parser.add_argument("--portfolio-open-risk-pct", type=float, default=None)
    parser.add_argument("--theme-open-risk-pct", type=float, default=None)
    parser.add_argument("--valuation", action="store_true", help="Fetch valuation percentile for deep-analysis names")
    parser.add_argument("--output", default=None, help="Optional JSON scan result")
    args = parser.parse_args(argv)

    entries = _explicit_entries(args.codes, args.watchlist) if args.codes else load_watchlist(args.watchlist)
    if args.tag:
        entries = [entry for entry in entries if args.tag in entry["tags"]]
    if args.market:
        entries = [entry for entry in entries if entry["code"].split(".", 1)[0] == args.market]
    if args.tier:
        entries = [entry for entry in entries if entry["tier"] == args.tier]
    if not entries:
        parser.error("No enabled watchlist entries matched the filters")

    horizons = () if args.snapshot_only else (("short", "swing") if args.horizon == "both" else (args.horizon,))
    display_horizon = "short" if args.horizon == "both" else args.horizon
    valuation_script = _find_valuation_script() if args.valuation else None
    fetcher = FutuFetcher()

    with tempfile.TemporaryDirectory(prefix="stock-watchlist-scan-") as tmpdir:
        temp_dir = Path(tmpdir)
        shared_path = temp_dir / "shared-context.json"
        shared_written = False

        def analyze(entry: dict[str, Any], horizon: str, shared) -> dict[str, Any]:
            nonlocal shared_written
            if not shared_written:
                shared_path.write_text(
                    json.dumps({"snapshots": {code: asdict(snapshot) for code, snapshot in shared.items()}}, ensure_ascii=False),
                    encoding="utf-8",
                )
                shared_written = True
            output = temp_dir / f"{entry['code'].replace('.', '_')}-{horizon}.json"
            command = _analysis_command(
                entry,
                horizon,
                output,
                shared_path,
                args.watchlist,
                args.bars,
            )
            if args.event_days is not None:
                command.extend(["--event-days", str(args.event_days)])
            if args.portfolio_open_risk_pct is not None:
                command.extend(["--portfolio-open-risk-pct", str(args.portfolio_open_risk_pct)])
            if args.theme_open_risk_pct is not None:
                command.extend(["--theme-open-risk-pct", str(args.theme_open_risk_pct)])
            underlying = entry.get("underlying_proxy")
            if underlying:
                instrument = shared.get(entry["code"])
                proxy = shared.get(underlying)
                confirmed = (
                    instrument is not None
                    and proxy is not None
                    and instrument.prev_close > 0
                    and proxy.prev_close > 0
                    and (instrument.last_price - instrument.prev_close) * (proxy.last_price - proxy.prev_close) > 0
                )
                command.append("--underlying-confirmed" if confirmed else "--no-underlying-confirmed")
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=True)
                recommendation = json.loads(output.read_text(encoding="utf-8"))
                if completed.stderr.strip():
                    recommendation["scan_stderr"] = completed.stderr.strip()
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or str(exc)).strip()
                return {"error": detail, "entry_decision": "defer"}
            except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError) as exc:
                return {"error": str(exc), "entry_decision": "defer"}
            if args.valuation:
                recommendation["valuation_percentile"] = _valuation(entry["code"], valuation_script)
            return recommendation

        result = run_watchlist_scan(
            entries,
            fetcher,
            analyzer=None if args.snapshot_only else analyze,
            deep_top=args.deep_top,
            deep_bottom=args.deep_bottom,
            deep_per_theme=args.deep_per_theme,
            deep_horizons=horizons,
            context_codes=tuple(DEFAULT_MACRO_CODES),
        )

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_table(result, display_horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
