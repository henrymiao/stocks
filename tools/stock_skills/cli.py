from __future__ import annotations

import argparse
import json
from pathlib import Path

from .capital import analyze_capital
from .engine import build_recommendation
from .macro import analyze_cross_market, analyze_macro_risk
from .models import CapitalSnapshot, InstrumentState, KLineBar, MarketSnapshot
from .trend import analyze_trend


def _sample_state(code: str) -> InstrumentState:
    name = "沪电股份" if code == "SZ.002463" else code
    snapshot = MarketSnapshot(code, name, 147.9, 146.0, 149.36, 142.81, 146.55, 83_679_015, 12_271_729_868.41, "2026-06-18T15:00:00+08:00")
    bars = [
        KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
        KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
        KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83_679_015, 12_271_729_868.41),
    ]
    capital = CapitalSnapshot(24_492_584.5, 744_236_606.14, -411_741_404.48, -210_842_830.36, -97_159_786.8, "2026-06-18T15:00:00+08:00")
    return InstrumentState(snapshot=snapshot, daily_bars=bars, intraday_bars=[], capital=capital, user_context={"last_trim_price": 149.5})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-evolving stock skill tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run", help="Run fixture-based analysis without Futu OpenD")
    dry_run.add_argument("--code", required=True)
    dry_run.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    if args.command == "dry-run":
        state = _sample_state(args.code)
        trend = analyze_trend(state.snapshot, state.daily_bars)
        capital = analyze_capital(state.capital)
        macro = analyze_macro_risk({"fed_bias": "hike", "geopolitical_risk": "elevated"})
        cross = analyze_cross_market({})
        weights = {"trend": 0.25, "capital_flow": 0.20, "sector": 0.15, "cross_market": 0.15, "macro_risk": 0.15, "position_fit": 0.10}
        recommendation = build_recommendation(
            state=state,
            trend=trend,
            capital=capital,
            macro=macro,
            cross_market=cross,
            sector_score=60,
            position_fit_score=70,
            weights=weights,
            source_refs=["fixture"],
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(recommendation.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
