from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .capital import analyze_capital
from .config import load_watchlist, load_weights, save_weights
from .engine import build_recommendation
from .fundamental import analyze_fundamental, infer_profile
from .journal import append_record, read_records
from .macro import analyze_cross_market, analyze_macro_from_proxies, analyze_macro_risk
from .market import analyze_market
from .models import CapitalSnapshot, FundamentalSnapshot, InstrumentState, KLineBar, MarketSnapshot, Recommendation
from .position import analyze_position, compute_atr
from .review import evaluate_recommendation, suggest_weight_adjustments
from .sector import analyze_sector
from .trend import analyze_trend

FIXTURE_CODE = "SZ.002463"
DEFAULT_WEIGHTS = {
    "trend": 0.22,
    "capital_flow": 0.15,
    "sector": 0.15,
    "cross_market": 0.12,
    "macro_risk": 0.12,
    "market_regime": 0.14,
    "position_fit": 0.10,
}
# A-share broad indices used as the default market backdrop.
DEFAULT_INDEX_CODES = ["SH.000001", "SZ.399006"]
# Live macro proxies (ETFs) fetched by default for the macro-risk component.
DEFAULT_MACRO_CODES = ["US.VIXY", "US.TLT", "US.UUP", "US.USO", "US.GLD"]
DEFAULT_RECOMMENDATIONS = "data/journal/recommendations.jsonl"
DEFAULT_REVIEWS = "data/journal/reviews.jsonl"
DEFAULT_WEIGHTS_PATH = "data/models/signal_weights.json"
DEFAULT_WATCHLIST_PATH = "data/watchlists/core.json"
REVIEW_WINDOW_DAYS = {"1d": 1, "3d": 3, "5d": 5, "10d": 10}


def _fixture_state() -> InstrumentState:
    """A frozen 沪电股份 sample used only to verify the scoring pipeline offline."""
    snapshot = MarketSnapshot(FIXTURE_CODE, "沪电股份", 147.9, 146.0, 149.36, 142.81, 146.55, 83_679_015, 12_271_729_868.41, "2026-06-18T15:00:00+08:00")
    bars = [
        KLineBar("2026-06-16", 134.2, 144.65, 134.04, 140.64, 110_149_555, 15_332_666_433.54),
        KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
        KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83_679_015, 12_271_729_868.41),
    ]
    capital = CapitalSnapshot(24_492_584.5, 744_236_606.14, -411_741_404.48, -210_842_830.36, -97_159_786.8, "2026-06-18T15:00:00+08:00")
    return InstrumentState(snapshot=snapshot, daily_bars=bars, intraday_bars=[], capital=capital, user_context={"last_trim_price": 149.5})


def _instrument_change(state: InstrumentState) -> float | None:
    prev = state.snapshot.prev_close
    if prev <= 0:
        return None
    return (state.snapshot.last_price - prev) / prev


def _profile_for_code(code: str, watchlist_path: str) -> str:
    """Infer growth/value/neutral from the code's watchlist tags; neutral if not listed."""
    try:
        entries = load_watchlist(watchlist_path)
    except (OSError, ValueError):
        return "neutral"
    for entry in entries:
        if entry.get("code") == code:
            return infer_profile(entry.get("tags"))
    return "neutral"


def _recommend(
    state: InstrumentState,
    weights: dict[str, float],
    macro_inputs: dict[str, object],
    macro_snapshots: dict[str, MarketSnapshot] | None,
    cross_snapshots: dict[str, MarketSnapshot],
    sector_changes: list[float] | None,
    index_snapshots: dict[str, MarketSnapshot] | None,
    source_refs: list[str],
    fundamentals: FundamentalSnapshot | None = None,
    profile: str = "neutral",
    risk_budget_pct: float = 1.0,
    atr_multiple: float = 2.0,
    cost_basis: float | None = None,
) -> Recommendation:
    """Run every analyzer over `state`. Missing components score a neutral 50 and are flagged in source_refs."""
    trend = analyze_trend(state.snapshot, state.daily_bars)
    capital = analyze_capital(state.capital)
    # Live proxies take precedence; hand-typed inputs are a fallback/override for offline use.
    if macro_snapshots:
        macro = analyze_macro_from_proxies(macro_snapshots)
    else:
        macro = analyze_macro_risk(macro_inputs)
    cross = analyze_cross_market(cross_snapshots)
    sector = analyze_sector(_instrument_change(state), sector_changes or [])
    market = analyze_market(index_snapshots or {})
    fundamental = analyze_fundamental(fundamentals, profile=profile)
    atr = compute_atr(state.daily_bars)
    position = analyze_position(
        last_price=state.snapshot.last_price,
        atr=atr,
        invalidation_level=trend.invalidation_level,
        risk_budget_pct=risk_budget_pct,
        atr_multiple=atr_multiple,
        last_trim_price=state.user_context.get("last_trim_price"),
        cost_basis=cost_basis,
    )

    refs = list(source_refs)
    if not macro_snapshots and not macro_inputs:
        refs.append("macro: neutral default (no macro feed supplied)")
    if not cross_snapshots:
        refs.append("cross_market: neutral default (no cross-market snapshots supplied)")
    if not sector_changes:
        refs.append("sector: neutral default (no sector constituent data)")
    if not index_snapshots:
        refs.append("market_regime: neutral default (no index snapshots)")
    if fundamentals is None:
        refs.append("fundamental: neutral default (no valuation data)")
    if atr is None:
        refs.append("position_fit: neutral (no ATR; need >=2 daily bars)")

    return build_recommendation(
        state=state,
        trend=trend,
        capital=capital,
        macro=macro,
        cross_market=cross,
        sector_score=sector.score,
        position_fit_score=position.score,
        weights=weights,
        source_refs=refs,
        market_score=market.score,
        market_regime=market.regime,
        sector_stance=sector.stance,
        fundamental_score=fundamental.score,
        fundamental_stance=fundamental.stance,
        position_stop_price=position.stop_price,
        position_size_pct=position.suggested_size_pct,
        position_stance=position.stance,
    )


def _write(output: str, recommendation: Recommendation) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recommendation.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")


def _cmd_dry_run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.code != FIXTURE_CODE:
        parser.error(
            f"dry-run only replays a frozen {FIXTURE_CODE} (沪电股份) fixture to verify the scoring "
            f"pipeline offline; it cannot analyze {args.code}. Use `analyze --code {args.code}` "
            "(requires Futu OpenD) for a real instrument."
        )
    state = _fixture_state()
    recommendation = _recommend(
        state=state,
        weights=DEFAULT_WEIGHTS,
        macro_inputs={"fed_bias": "hike", "geopolitical_risk": "elevated"},
        macro_snapshots=None,
        cross_snapshots={},
        sector_changes=[0.031, 0.018, -0.004, 0.022, 0.009, 0.015],
        index_snapshots=None,
        source_refs=["fixture"],
        fundamentals=FundamentalSnapshot(FIXTURE_CODE, pe_ttm=66.1, pb=18.0, eps=1.99, dividend_ratio=0.34, market_val=2.85e11, eps_growth=40.0),
        profile="growth",
        cost_basis=140.0,
    )
    _write(args.output, recommendation)
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    # Imported lazily so dry-run and unit tests never require the live adapter.
    from .futu_fetcher import FutuFetcher

    fetcher = FutuFetcher()
    user_context = {"last_trim_price": args.last_trim_price} if args.last_trim_price is not None else {}
    state = fetcher.build_state(args.code, num_bars=args.bars, user_context=user_context)

    cross_snapshots: dict[str, MarketSnapshot] = {}
    for ref_code in args.cross or []:
        cross_snapshots[ref_code] = fetcher.get_snapshot(ref_code)

    refs = [f"futu:snapshot+kline+capital:{args.code}"]

    sector_changes: list[float] | None = None
    if not args.no_sector:
        core_plate = fetcher.pick_core_plate(args.code)
        if core_plate:
            sector_changes = fetcher.get_plate_constituent_changes(core_plate["plate_code"], limit=args.sector_limit)
            refs.append(f"sector:{core_plate.get('plate_name')}({core_plate['plate_code']}) x{len(sector_changes)}")

    index_snapshots: dict[str, MarketSnapshot] | None = None
    if not args.no_market:
        index_codes = args.indices or DEFAULT_INDEX_CODES
        index_snapshots = fetcher.get_index_snapshots(index_codes)
        refs.append(f"market:{','.join(index_snapshots)}")

    macro_snapshots: dict[str, MarketSnapshot] | None = None
    macro_inputs: dict[str, object] = {}
    if args.macro_json:
        macro_inputs = json.loads(args.macro_json)
        refs.append("macro:manual-override")
    elif not args.no_macro:
        macro_snapshots = fetcher.get_index_snapshots(args.macro_codes or DEFAULT_MACRO_CODES)
        if macro_snapshots:
            refs.append(f"macro:proxies:{','.join(macro_snapshots)}")

    fundamentals: FundamentalSnapshot | None = None
    profile = args.profile or _profile_for_code(args.code, args.watchlist)
    if not args.no_fundamental:
        fundamentals = fetcher.get_fundamentals(args.code, eps_growth=args.eps_growth)
        if fundamentals:
            peg_note = f", eps_growth={args.eps_growth}%" if args.eps_growth is not None else ""
            refs.append(f"fundamental:profile={profile},pe_ttm={fundamentals.pe_ttm}{peg_note}")

    weights = load_weights(args.weights) if args.weights else DEFAULT_WEIGHTS
    recommendation = _recommend(
        state=state,
        weights=weights,
        macro_inputs=macro_inputs,
        macro_snapshots=macro_snapshots,
        cross_snapshots=cross_snapshots,
        sector_changes=sector_changes,
        index_snapshots=index_snapshots,
        source_refs=refs,
        fundamentals=fundamentals,
        profile=profile,
        risk_budget_pct=args.risk_budget_pct,
        atr_multiple=args.atr_multiple,
        cost_basis=args.cost_basis,
    )
    _write(args.output, recommendation)
    if not args.no_journal:
        append_record(args.journal, recommendation.to_record())
    return 0


def _entry_date(timestamp: str) -> date:
    return datetime.fromisoformat(timestamp).date()


def _cmd_review(args: argparse.Namespace) -> int:
    from .futu_fetcher import FutuFetcher

    fetcher = FutuFetcher()
    recommendations = read_records(args.recommendations)
    if args.code:
        recommendations = [rec for rec in recommendations if rec.get("code") == args.code]

    window_days = REVIEW_WINDOW_DAYS[args.window]
    reviews: list[dict] = []
    for rec in recommendations:
        timestamp = rec.get("timestamp")
        entry_price = rec.get("entry_price") or 0.0
        if not timestamp or entry_price <= 0:
            continue
        entry = _entry_date(str(timestamp))
        # Pull a generous calendar span so weekends/holidays still yield enough trading bars.
        start = (entry + timedelta(days=1)).isoformat()
        end = (entry + timedelta(days=window_days * 2 + 7)).isoformat()
        future_bars = fetcher.get_history_bars(rec["code"], start=start, end=end)[:window_days]
        if not future_bars:
            continue
        outcome = evaluate_recommendation(rec, entry_price=float(entry_price), future_bars=future_bars, review_window=args.window)
        reviews.append(outcome)
        append_record(args.reviews, outcome)

    if not reviews:
        print("No reviewable recommendations (need a timestamp, positive entry_price, and available future bars).")
        return 0

    current = load_weights(args.weights)
    suggestion = suggest_weight_adjustments(current, reviews)
    print(json.dumps({"reviewed": len(reviews), "suggestion": suggestion}, ensure_ascii=False, indent=2))

    if args.apply:
        reason = f"Auto-adjust from {len(reviews)} review(s) over {args.window}: " + "; ".join(suggestion["notes"])
        entry = save_weights(args.weights, suggestion["weights"], reason=reason)
        print(f"Applied new weights (backup at {args.weights}.bak). History: {entry['timestamp']}")
    else:
        print("Suggestion only. Re-run with --apply to write weights back (a .bak backup and history entry are created).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-evolving stock skill tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser("dry-run", help=f"Replay the frozen {FIXTURE_CODE} fixture offline (pipeline check only)")
    dry_run.add_argument("--code", required=True, help=f"Must be {FIXTURE_CODE}; the fixture is not a real-data analysis of other codes")
    dry_run.add_argument("--output", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze a real instrument via Futu OpenD (snapshot + daily K-line + capital flow)")
    analyze.add_argument("--code", required=True, help="Instrument code, e.g. SZ.002463, US.NVDA, CC.BTC")
    analyze.add_argument("--output", required=True)
    analyze.add_argument("--bars", type=int, default=30, help="Number of daily bars to fetch (default: 30)")
    analyze.add_argument("--cross", nargs="*", default=None, help="Cross-market reference codes to fetch, e.g. US.QQQ US.NVDA")
    analyze.add_argument("--last-trim-price", type=float, default=None, help="Prior partial-trim price for position context")
    analyze.add_argument("--weights", default=None, help="Path to a signal_weights.json; defaults to built-in weights")
    analyze.add_argument("--journal", default=DEFAULT_RECOMMENDATIONS, help=f"Recommendation journal path (default: {DEFAULT_RECOMMENDATIONS})")
    analyze.add_argument("--no-journal", action="store_true", help="Do not append this recommendation to the journal")
    analyze.add_argument("--indices", nargs="*", default=None, help=f"Market index codes for the market regime (default: {' '.join(DEFAULT_INDEX_CODES)})")
    analyze.add_argument("--no-market", action="store_true", help="Skip the market-regime fetch (scores neutral)")
    analyze.add_argument("--no-sector", action="store_true", help="Skip the sector-strength fetch (scores neutral)")
    analyze.add_argument("--sector-limit", type=int, default=30, help="Top N plate constituents to sample for sector strength (default: 30)")
    analyze.add_argument("--macro-codes", nargs="*", default=None, help=f"Macro proxy codes for the macro-risk score (default: {' '.join(DEFAULT_MACRO_CODES)})")
    analyze.add_argument("--no-macro", action="store_true", help="Skip the macro-proxy fetch (scores neutral)")
    analyze.add_argument("--macro-json", default=None, help='Hand-typed macro override, e.g. \'{"fed_bias":"hike"}\' (bypasses proxy fetch)')
    analyze.add_argument("--no-fundamental", action="store_true", help="Skip the fundamental fetch (scores neutral)")
    analyze.add_argument("--eps-growth", type=float, default=None, help="YoY EPS growth %% for PEG (e.g. 40 = +40%%); enables PEG scoring")
    analyze.add_argument("--profile", choices=["growth", "value", "neutral"], default=None, help="Valuation profile; default inferred from watchlist tags")
    analyze.add_argument("--watchlist", default=DEFAULT_WATCHLIST_PATH, help=f"Watchlist path for profile inference (default: {DEFAULT_WATCHLIST_PATH})")
    analyze.add_argument("--risk-budget-pct", type=float, default=1.0, help="Account %% to risk per trade for position sizing (default: 1.0)")
    analyze.add_argument("--atr-multiple", type=float, default=2.0, help="ATR multiple for the volatility stop (default: 2.0)")
    analyze.add_argument("--cost-basis", type=float, default=None, help="Existing cost basis, to report open P&L in the plan")

    review = subparsers.add_parser("review", help="Review past recommendations against later price action and suggest weight changes")
    review.add_argument("--window", choices=sorted(REVIEW_WINDOW_DAYS), default="3d", help="Review horizon in trading days (default: 3d)")
    review.add_argument("--code", default=None, help="Only review recommendations for this code")
    review.add_argument("--recommendations", default=DEFAULT_RECOMMENDATIONS, help=f"Recommendation journal path (default: {DEFAULT_RECOMMENDATIONS})")
    review.add_argument("--reviews", default=DEFAULT_REVIEWS, help=f"Reviews output path (default: {DEFAULT_REVIEWS})")
    review.add_argument("--weights", default=DEFAULT_WEIGHTS_PATH, help=f"Signal weights path (default: {DEFAULT_WEIGHTS_PATH})")
    review.add_argument("--apply", action="store_true", help="Write suggested weights back (creates a .bak backup and a history entry)")

    args = parser.parse_args(argv)

    if args.command == "dry-run":
        return _cmd_dry_run(args, parser)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "review":
        return _cmd_review(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
