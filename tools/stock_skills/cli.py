from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from .backtest import run_backtest
from .capital import analyze_capital
from .config import load_watchlist, load_weights, save_weights
from .data_quality import assess_data_quality, detect_stale_components
from .engine import build_recommendation, is_inverse_instrument
from .fundamental import analyze_fundamental, infer_profile
from .journal import append_record, ensure_journal, read_records
from .macro import (
    analyze_cross_market,
    analyze_macro_from_proxies,
    analyze_macro_risk,
    has_cross_market_evidence,
    has_macro_input_evidence,
    has_macro_proxy_evidence,
)
from .market import analyze_market, has_market_evidence
from .models import (
    SCHEMA_VERSION,
    CapitalSnapshot,
    FundamentalSnapshot,
    InstrumentState,
    KLineBar,
    MarketSnapshot,
    PositionStateSnapshot,
    Recommendation,
)
from .position import analyze_position, analyze_structured_position, compute_atr
from .path_backtest import assess_portfolio_heat
from .review import evaluate_recommendation, suggest_weight_adjustments
from .sector import analyze_sector
from .session import classify_session_phase
from .strategy import (
    StrategyEvidence,
    build_profile_exit_plan,
    evaluate_strategy,
    get_strategy_profile,
)
from .trend import analyze_trend

FIXTURE_CODE = "SZ.002463"
# Backdrop factors (cross_market/macro_risk/market_regime) are de-duplicated in the
# engine (see backdrop_blend), so their summed weight (0.28) behaves like ~one factor
# when they agree. Weight is tilted toward the stock-specific signals — trend (now
# MA-contextualised) and the richer fundamental score.
DEFAULT_WEIGHTS = {
    "trend": 0.22,
    "capital_flow": 0.12,
    "sector": 0.15,
    "cross_market": 0.09,
    "macro_risk": 0.09,
    "market_regime": 0.10,
    "fundamental": 0.13,
    "position_fit": 0.10,
}
A_SHARE_INDEX_CODES = ["SH.000001", "SZ.399006"]
US_INDEX_CODES = ["US.QQQ", "US.SPY"]
HK_INDEX_CODES = ["HK.800000", "HK.800700"]  # 恒生指数 / 恒生科技指数 (Futu codes; HSI/HSTECH aliases are not recognized)
# Live macro proxies (ETFs) fetched by default for the macro-risk component.
# FXY captures yen appreciation/carry unwind, while HYG versus LQD detects
# whether a rates/FX shock is spreading into credit risk. Raw JP10Y/JP30Y and
# MOVE are external confirmation series because Futu does not expose reliable
# symbols for those indices (US.MOVE is an unrelated listed equity).
DEFAULT_MACRO_CODES = [
    "US.VIXY",
    "US.TLT",
    "US.UUP",
    "US.USO",
    "US.GLD",
    "US.FXY",
    "US.HYG",
    "US.LQD",
]
DEFAULT_RECOMMENDATIONS = "data/journal/recommendations.jsonl"
DEFAULT_REVIEWS = "data/journal/reviews.jsonl"
DEFAULT_WEIGHTS_PATH = "data/models/signal_weights.json"
DEFAULT_WATCHLIST_PATH = "data/watchlists/core.json"
REVIEW_WINDOW_DAYS = {"1d": 1, "3d": 3, "5d": 5, "10d": 10}


def _evidence_codes(
    snapshots: dict[str, MarketSnapshot],
    predicate: Callable[[dict[str, MarketSnapshot]], bool],
) -> list[str]:
    return [
        code
        for code, snapshot in snapshots.items()
        if predicate({code: snapshot})
    ]


def _load_shared_snapshots(path: str | None) -> dict[str, MarketSnapshot]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = payload.get("snapshots", payload) if isinstance(payload, dict) else {}
    if not isinstance(records, dict):
        raise ValueError("shared context must contain a snapshots object")
    snapshots: dict[str, MarketSnapshot] = {}
    for code, record in records.items():
        if not isinstance(record, dict):
            continue
        try:
            snapshot = MarketSnapshot(**record)
        except (TypeError, ValueError):
            continue
        snapshots[code] = snapshot
    return snapshots


def _snapshots_for_codes(fetcher, codes: list[str], shared: dict[str, MarketSnapshot]) -> dict[str, MarketSnapshot]:
    selected = {code: shared[code] for code in codes if code in shared}
    missing = [code for code in codes if code not in selected]
    if missing:
        selected.update(fetcher.get_index_snapshots(missing))
    return selected


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
    return infer_profile(_tags_for_code(code, watchlist_path))


def _tags_for_code(code: str, watchlist_path: str) -> list[str]:
    try:
        entries = load_watchlist(watchlist_path)
    except (OSError, ValueError):
        return []
    for entry in entries:
        if entry.get("code") == code:
            tags = entry.get("tags")
            return tags if isinstance(tags, list) else []
    return []


def _is_leveraged(name: str, tags: list[str]) -> bool:
    lowered = name.lower()
    return "leveraged" in {str(tag).lower() for tag in tags} or any(
        marker in lowered for marker in ("2x", "3x", "ultra", "daily bull", "daily bear")
    )


def _volume_ratio(bars: list[KLineBar]) -> float | None:
    if len(bars) < 2:
        return None
    previous = bars[-21:-1]
    if not previous:
        return None
    average = sum(bar.volume for bar in previous) / len(previous)
    if average <= 0:
        return None
    return round(bars[-1].volume / average, 4)


def _weekly_alignment(bars: list[KLineBar]) -> bool | None:
    if len(bars) < 30:
        return None
    weekly_closes = [
        bars[index : index + 5][-1].close
        for index in range(0, len(bars), 5)
        if bars[index : index + 5]
    ]
    if len(weekly_closes) < 6:
        return None
    fast = sum(weekly_closes[-3:]) / 3.0
    slow = sum(weekly_closes[-6:]) / 6.0
    return fast > slow and weekly_closes[-1] >= weekly_closes[-2]


def _resistance_room_r(entry_price: float, resistance_levels: list[float], risk_per_share: float, breakout: bool) -> float | None:
    if risk_per_share <= 0:
        return None
    overhead = sorted(level for level in resistance_levels if level > entry_price)
    if overhead:
        return round((overhead[0] - entry_price) / risk_per_share, 4)
    if breakout:
        return float("inf")
    return None


def _prefix_for_code(code: str) -> str:
    return code.split(".", 1)[0].upper() if "." in code else ""


def _default_index_codes_for(code: str) -> list[str]:
    prefix = _prefix_for_code(code)
    if prefix == "US":
        return US_INDEX_CODES
    if prefix == "HK":
        return HK_INDEX_CODES
    if prefix in {"SH", "SZ"}:
        return A_SHARE_INDEX_CODES
    return A_SHARE_INDEX_CODES


def _default_cross_codes_for(code: str, tags: list[str]) -> list[str]:
    prefix = _prefix_for_code(code)
    lowered = {str(tag).lower() for tag in tags}
    refs: list[str] = []
    if prefix == "US":
        refs.extend(["US.QQQ", "US.SPY"])
        if lowered & {"ai", "ai-hardware", "ai-infrastructure", "semiconductor", "growth-proxy"}:
            refs.extend(["US.NVDA", "US.SMH"])
        if lowered & {"crypto-equity", "stablecoin"}:
            refs.extend(["CC.BTC", "CC.ETH"])
    elif prefix == "HK":
        refs.extend(["HK.800000", "HK.800700"])

    seen: set[str] = set()
    unique: list[str] = []
    for ref in refs:
        if ref != code and ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


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
    stop_buffer_atr: float | None = None,
    cost_basis: float | None = None,
    inverse: bool = False,
    leveraged: bool = False,
    horizon: str = "short",
    event_days: int | None = None,
    underlying_confirmed: bool | None = None,
    portfolio_open_risk_pct: float | None = None,
    theme_open_risk_pct: float | None = None,
    trade_id: str | None = None,
    position_stage: str | None = None,
) -> Recommendation:
    """Run every analyzer over `state`. Missing components score a neutral 50 and are flagged in source_refs."""
    trend = analyze_trend(state.snapshot, state.daily_bars)
    capital = analyze_capital(state.capital, price_change=_instrument_change(state))
    # Live proxies take precedence; hand-typed inputs are a fallback/override for offline use.
    if macro_snapshots:
        macro = analyze_macro_from_proxies(macro_snapshots)
    else:
        macro = analyze_macro_risk(macro_inputs)
    cross = analyze_cross_market(cross_snapshots)
    sector = analyze_sector(_instrument_change(state), sector_changes or [])
    market = analyze_market(index_snapshots or {})
    fundamental = analyze_fundamental(fundamentals, profile=profile)
    session_phase = classify_session_phase(
        state.snapshot.code,
        state.snapshot.captured_at or state.snapshot.timestamp,
    )
    atr = compute_atr(state.daily_bars)
    structural_invalidation = trend.invalidation_level
    opening_range_fallback = False
    if (
        atr is None
        and session_phase == "intraday"
        and 0 < state.snapshot.low < state.snapshot.last_price
        and state.snapshot.high > state.snapshot.low
    ):
        # New listings and event-driven dislocations may not have enough daily
        # history for ATR.  The live opening range supplies a provisional stop
        # geometry so opportunity mode can size a small probe instead of turning
        # missing history into a permanent no-trade verdict.
        opening_range = state.snapshot.high - state.snapshot.low
        gap_range = abs(state.snapshot.open - state.snapshot.prev_close)
        atr = max(opening_range, gap_range * 0.35, state.snapshot.last_price * 0.01)
        structural_invalidation = state.snapshot.low
        opening_range_fallback = True
    strategy_profile = get_strategy_profile(horizon, leveraged=leveraged)
    effective_trade_id = trade_id or f"{strategy_profile.strategy_id}:{state.snapshot.code}:{state.snapshot.timestamp}"
    exit_plan = None
    exit_plan_error = None
    try:
        exit_plan = build_profile_exit_plan(
            strategy_profile,
            entry_price=state.snapshot.last_price,
            structural_invalidation=structural_invalidation,
            atr=atr,
            risk_budget_pct=risk_budget_pct,
            stop_buffer_atr=stop_buffer_atr,
        )
    except ValueError as exc:
        exit_plan_error = str(exc)
    heat_allowed: bool | None = None
    heat_note: str | None = None
    if exit_plan is not None and portfolio_open_risk_pct is not None and theme_open_risk_pct is not None:
        heat = assess_portfolio_heat(
            proposed_risk_pct=exit_plan.risk_sizing.planned_risk_pct,
            portfolio_open_risk_pct=portfolio_open_risk_pct,
            theme_open_risk_pct=theme_open_risk_pct,
        )
        heat_allowed = heat.allowed
        heat_note = (
            f"portfolio_heat: allowed={heat.allowed}, planned={heat.allowed_risk_pct}%, "
            f"portfolio_headroom={heat.portfolio_headroom_pct}%, theme_headroom={heat.theme_headroom_pct}%"
        )
        if heat.allowed and heat.scaled:
            sizing = exit_plan.risk_sizing
            reduced_size = heat.allowed_risk_pct / sizing.stop_distance_pct * 100.0
            exit_plan = replace(
                exit_plan,
                risk_sizing=replace(
                    sizing,
                    suggested_size_pct=round(reduced_size, 2),
                    planned_risk_pct=heat.allowed_risk_pct,
                    capped=True,
                ),
            )
    # Keep the legacy position-fit score frozen so Phase 2 can be compared against
    # historical totals. Execution guidance and sizing come exclusively from ExitPlan.
    legacy_position = analyze_position(
        last_price=state.snapshot.last_price,
        atr=atr,
        invalidation_level=structural_invalidation,
        risk_budget_pct=risk_budget_pct,
        last_trim_price=state.user_context.get("last_trim_price"),
        cost_basis=cost_basis,
    )
    position = analyze_structured_position(
        exit_plan,
        atr,
        exit_plan_error,
        last_trim_price=state.user_context.get("last_trim_price"),
        cost_basis=cost_basis,
    )
    macro_available = (
        has_macro_proxy_evidence(macro_snapshots)
        if macro_snapshots
        else has_macro_input_evidence(macro_inputs)
    )
    availability = {
        "trend": len(state.daily_bars) >= 2,
        "capital_flow": state.capital is not None,
        "sector": bool(sector_changes),
        "cross_market": has_cross_market_evidence(cross_snapshots),
        "macro_risk": macro_available,
        "market_regime": has_market_evidence(index_snapshots or {}),
        "fundamental": fundamentals is not None and fundamentals.pe_ttm is not None,
        "position_fit": exit_plan is not None,
    }
    data_quality = assess_data_quality(
        availability,
        session_phase,
        stale_components=detect_stale_components(state.snapshot, state.capital, session_phase),
    )

    refs = list(source_refs)
    if heat_note:
        refs.append(heat_note)
    if not availability["trend"]:
        refs.append("trend: neutral default (no usable K-line evidence; need >=2 daily bars)")
    if not availability["capital_flow"]:
        refs.append("capital_flow: neutral default (no usable capital evidence)")
    if not availability["macro_risk"]:
        refs.append("macro: neutral default (no usable macro evidence)")
    if not availability["cross_market"]:
        refs.append("cross_market: neutral default (no usable cross-market evidence)")
    if not availability["sector"]:
        refs.append("sector: neutral default (no usable sector constituent evidence)")
    if not availability["market_regime"]:
        refs.append("market_regime: neutral default (no usable index evidence)")
    if not availability["fundamental"]:
        refs.append("fundamental: neutral default (no usable valuation evidence)")
    if not availability["position_fit"]:
        if atr is None:
            refs.append("position_fit: neutral (no usable ATR evidence; need >=2 daily bars)")
        else:
            refs.append(
                "position_fit: neutral (no valid structured exit plan"
                + (f": {exit_plan_error}" if exit_plan_error else "")
                + ")"
            )
    if opening_range_fallback:
        refs.append(
            "opportunity-mode: provisional opening-range stop used because daily ATR history is unavailable"
        )
    if inverse:
        refs.append("inverse-etf: backdrop (market/cross/macro) scores inverted")

    recommendation = build_recommendation(
        state=state,
        trend=trend,
        capital=capital,
        macro=macro,
        cross_market=cross,
        sector_score=sector.score,
        position_fit_score=legacy_position.score,
        weights=weights,
        source_refs=refs,
        data_quality=data_quality,
        market_score=market.score,
        market_regime=market.regime,
        sector_stance=sector.stance,
        fundamental_score=fundamental.score,
        fundamental_stance=fundamental.stance,
        position_stop_price=position.stop_price,
        position_size_pct=position.suggested_size_pct,
        position_stance=position.stance,
        inverse=inverse,
        exit_plan=exit_plan,
        position_state=PositionStateSnapshot(
            state="entered" if cost_basis is not None else "flat",
            remaining_fraction=1.0 if cost_basis is not None else 0.0,
            trade_id=effective_trade_id,
        ),
    )
    volume_ratio = _volume_ratio(state.daily_bars)
    if opening_range_fallback and state.snapshot.last_price >= state.snapshot.open:
        range_position = (
            (state.snapshot.last_price - state.snapshot.low)
            / (state.snapshot.high - state.snapshot.low)
        )
        volume_score = 80.0 if range_position >= 0.60 else 60.0
    elif volume_ratio is None:
        volume_score = 50.0
    elif volume_ratio >= strategy_profile.minimum_volume_ratio:
        volume_score = 80.0
    elif volume_ratio >= 0.8:
        volume_score = 50.0
    else:
        volume_score = 30.0
    relative_strength_positive = (
        None if sector.relative_strength is None else sector.relative_strength >= 0
    )
    if (
        opening_range_fallback
        and state.snapshot.last_price > state.snapshot.open
        and state.snapshot.last_price
        >= state.snapshot.low + 0.60 * (state.snapshot.high - state.snapshot.low)
    ):
        trigger_confirmed = True
    elif trend.status == "breakout-confirmed":
        trigger_confirmed: bool | None = True
    elif trend.status in {"breakdown-risk", "breakout-vs-downtrend"}:
        trigger_confirmed = False
    else:
        trigger_confirmed = None
    resistance_room_r = (
        None
        if exit_plan is None
        else _resistance_room_r(
            state.snapshot.last_price,
            trend.resistance_levels,
            exit_plan.risk_per_share,
            trigger_confirmed is True,
        )
    )
    backdrop_score = round((market.score + macro.score + cross.score) / 3.0, 2)
    liquidity_ok = state.snapshot.volume > 0 and state.snapshot.turnover > 0
    # Factor names describe the evidence ROLE in the strategy profile; the mapping
    # below records the actual provenance so the two are never confused:
    #   relative_strength   <- sector.score (stock vs its own sector constituents);
    #                          the relative-strength GATE reads sector.relative_strength
    #   volume_accumulation <- capital.score (net-flow proxy; no OBV-style series yet)
    #   backdrop            <- plain mean of market/macro/cross (the legacy total instead
    #                          uses backdrop_blend's de-duplicated version)
    factor_scores = {
        "price_volume": round((trend.score + volume_score) / 2.0, 2),
        "relative_strength": sector.score,
        "market_regime": market.score,
        "capital_flow": capital.score,
        "liquidity_event": 70.0 if liquidity_ok else 20.0,
        "position_fit": legacy_position.score,
        "trend_quality": trend.score,
        "fundamental": fundamental.score,
        "backdrop": backdrop_score,
        "volume_accumulation": capital.score,
    }
    evidence = StrategyEvidence(
        factor_scores=factor_scores,
        data_confidence=data_quality.confidence,
        data_entry_eligible=data_quality.entry_eligible,
        exit_plan_valid=exit_plan is not None,
        session_phase=data_quality.session_phase,
        trend_regime=trend.trend_regime,
        relative_strength_positive=relative_strength_positive,
        volume_ratio=volume_ratio,
        trigger_confirmed=trigger_confirmed,
        resistance_room_r=resistance_room_r,
        market_regime=market.regime,
        liquidity_ok=liquidity_ok,
        weekly_aligned=_weekly_alignment(state.daily_bars),
        event_days=event_days,
        underlying_confirmed=underlying_confirmed,
        portfolio_heat_allowed=heat_allowed,
        data_probe_eligible=data_quality.probe_eligible,
        planned_allocation_pct=(
            None if exit_plan is None else exit_plan.risk_sizing.suggested_size_pct
        ),
    )
    strategy_assessment = evaluate_strategy(
        strategy_profile,
        evidence,
        has_position=cost_basis is not None,
        legacy_label=recommendation.label,
        position_stage=position_stage,
    )
    missing_text = (
        f" missing={','.join(strategy_assessment.gates_missing)}"
        if strategy_assessment.gates_missing
        else ""
    )
    strategy_text = (
        f" Authoritative execution decision ({strategy_assessment.decision_policy}): "
        f"setup={strategy_assessment.setup_score}, entry={strategy_assessment.entry_decision}, "
        f"allocation={strategy_assessment.suggested_allocation_pct}. "
        f"Legacy action label is retained for historical compatibility only.{missing_text}"
    )
    return replace(
        recommendation,
        trader_plan=recommendation.trader_plan + strategy_text,
        schema_version=SCHEMA_VERSION,
        strategy_assessment=strategy_assessment,
        strategy_id=strategy_assessment.strategy_id,
        strategy_version="v1",
        horizon=horizon,
        trade_id=effective_trade_id,
        leveraged=leveraged,
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
        trade_id="fixture-trade",
        horizon=args.horizon,
        event_days=args.event_days,
    )
    _write(args.output, recommendation)
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    # Imported lazily so dry-run and unit tests never require the live adapter.
    from .futu_fetcher import FutuFetcher

    fetcher = FutuFetcher()
    shared_snapshots = _load_shared_snapshots(args.shared_context)
    user_context = {"last_trim_price": args.last_trim_price} if args.last_trim_price is not None else {}
    state = fetcher.build_state(args.code, num_bars=args.bars, user_context=user_context)

    tags = _tags_for_code(args.code, args.watchlist)
    cross_codes = args.cross if args.cross is not None else _default_cross_codes_for(args.code, tags)
    cross_snapshots: dict[str, MarketSnapshot] = _snapshots_for_codes(fetcher, cross_codes, shared_snapshots) if cross_codes else {}

    refs = [f"futu:snapshot:{args.code}"]
    if len(state.daily_bars) >= 2:
        refs.append(f"futu:kline:{args.code}")
    if state.capital is not None:
        refs.append(f"futu:capital:{args.code}")
    cross_evidence_codes = _evidence_codes(cross_snapshots, has_cross_market_evidence)
    if cross_evidence_codes:
        refs.append(f"cross_market:{','.join(cross_evidence_codes)}")

    sector_changes: list[float] | None = None
    if not args.no_sector:
        core_plate = fetcher.pick_core_plate(args.code)
        if core_plate:
            sector_changes = fetcher.get_plate_constituent_changes(core_plate["plate_code"], limit=args.sector_limit)
            if sector_changes:
                refs.append(f"sector:{core_plate.get('plate_name')}({core_plate['plate_code']}) x{len(sector_changes)}")

    index_snapshots: dict[str, MarketSnapshot] | None = None
    if not args.no_market:
        index_codes = args.indices or _default_index_codes_for(args.code)
        index_snapshots = _snapshots_for_codes(fetcher, index_codes, shared_snapshots)
        market_evidence_codes = _evidence_codes(index_snapshots, has_market_evidence)
        if market_evidence_codes:
            refs.append(f"market:{','.join(market_evidence_codes)}")

    macro_snapshots: dict[str, MarketSnapshot] | None = None
    macro_inputs: dict[str, object] = {}
    if args.macro_json:
        macro_inputs = json.loads(args.macro_json)
        if has_macro_input_evidence(macro_inputs):
            refs.append("macro:manual-override")
    elif not args.no_macro:
        macro_snapshots = _snapshots_for_codes(fetcher, args.macro_codes or DEFAULT_MACRO_CODES, shared_snapshots)
        macro_evidence_codes = _evidence_codes(macro_snapshots, has_macro_proxy_evidence)
        if macro_evidence_codes:
            refs.append(f"macro:proxies:{','.join(macro_evidence_codes)}")

    fundamentals: FundamentalSnapshot | None = None
    profile = args.profile or infer_profile(tags)
    if not args.no_fundamental:
        # Business-quality inputs: hand-typed --flags win; any left unset are auto-filled
        # from the latest income statement so analyze no longer needs them by hand.
        eps_growth, revenue_growth = args.eps_growth, args.revenue_growth
        gross_margin, net_margin = args.gross_margin, args.net_margin
        financials = None
        if not args.no_financials and any(
            value is None for value in (eps_growth, revenue_growth, gross_margin, net_margin)
        ):
            financials = fetcher.get_financials(args.code)
        if financials:
            eps_growth = eps_growth if eps_growth is not None else financials.eps_growth
            revenue_growth = revenue_growth if revenue_growth is not None else financials.revenue_growth
            gross_margin = gross_margin if gross_margin is not None else financials.gross_margin
            net_margin = net_margin if net_margin is not None else financials.net_margin

        fundamentals = fetcher.get_fundamentals(
            args.code,
            eps_growth=eps_growth,
            revenue_growth=revenue_growth,
            gross_margin=gross_margin,
            net_margin=net_margin,
            roe=args.roe,
        )
        if fundamentals:
            # ROE is absent from the income statement, but trailing ROE == PB / PE (E/BV),
            # so derive it from the multiples we already have when the user didn't pass one.
            if fundamentals.roe is None and fundamentals.pb and fundamentals.pe_ttm:
                fundamentals = replace(fundamentals, roe=round(fundamentals.pb / fundamentals.pe_ttm * 100, 1))
            peg_note = f", eps_growth={eps_growth}%" if eps_growth is not None else ""
            quality_inputs = [
                f"{name}={value}"
                for name, value in (
                    ("rev_growth", revenue_growth),
                    ("gross_margin", gross_margin),
                    ("net_margin", net_margin),
                    ("roe", fundamentals.roe),
                )
                if value is not None
            ]
            quality_note = (", quality:" + ",".join(quality_inputs)) if quality_inputs else ""
            origin = f"auto@{financials.period}" if financials else "manual"
            if fundamentals.pe_ttm is not None:
                refs.append(f"fundamental:profile={profile},pe_ttm={fundamentals.pe_ttm}{peg_note}{quality_note}({origin})")
            if fundamentals.pe_ttm is not None and financials and financials.revenue_breakdown:
                refs.append("revenue_breakdown:" + ",".join(f"{name}={pct:g}%" for name, pct in financials.revenue_breakdown))

    inverse = args.inverse if args.inverse is not None else is_inverse_instrument(state.snapshot.name, tags)
    leveraged = _is_leveraged(state.snapshot.name, tags)
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
        stop_buffer_atr=args.stop_buffer_atr,
        cost_basis=args.cost_basis,
        inverse=inverse,
        leveraged=leveraged,
        horizon=args.horizon,
        event_days=args.event_days,
        underlying_confirmed=args.underlying_confirmed,
        portfolio_open_risk_pct=args.portfolio_open_risk_pct,
        theme_open_risk_pct=args.theme_open_risk_pct,
        trade_id=args.trade_id,
        position_stage=args.position_stage,
    )
    _write(args.output, recommendation)
    if not args.no_journal:
        append_record(args.journal, recommendation.to_record())
    return 0


def _entry_date(timestamp: str) -> date:
    return datetime.fromisoformat(timestamp).date()


def _has_static_review_inputs(recommendation: dict) -> bool:
    entry_price = recommendation.get("entry_price")
    return (
        bool(recommendation.get("timestamp"))
        and not isinstance(entry_price, bool)
        and isinstance(entry_price, (int, float))
        and entry_price > 0
    )


def _cmd_review(args: argparse.Namespace) -> int:
    from .futu_fetcher import FutuFetcher

    ensure_journal(args.reviews)
    recommendations = read_records(args.recommendations)
    if args.code:
        recommendations = [rec for rec in recommendations if rec.get("code") == args.code]
    candidates = [rec for rec in recommendations if _has_static_review_inputs(rec)]
    if not candidates:
        print("No reviewable recommendations (need a timestamp, positive entry_price, and available future bars).")
        return 0

    fetcher = FutuFetcher()
    window_days = REVIEW_WINDOW_DAYS[args.window]
    reviews: list[dict] = []
    for rec in candidates:
        timestamp = rec["timestamp"]
        entry_price = rec["entry_price"]
        entry = _entry_date(str(timestamp))
        # Pull a generous calendar span so weekends/holidays still yield enough trading bars.
        start = (entry + timedelta(days=1)).isoformat()
        end = (entry + timedelta(days=window_days * 2 + 7)).isoformat()
        future_bars = fetcher.get_history_bars(rec["code"], start=start, end=end)
        if len(future_bars) < window_days:
            continue
        future_bars = future_bars[:window_days]
        outcome = evaluate_recommendation(rec, entry_price=float(entry_price), future_bars=future_bars, review_window=args.window)
        reviews.append(outcome)
        append_record(args.reviews, outcome)

    if not reviews:
        print("No reviewable recommendations (need a timestamp, positive entry_price, and available future bars).")
        return 0

    current = load_weights(args.weights)
    suggestion = suggest_weight_adjustments(current, reviews)
    print(json.dumps({"reviewed": len(reviews), "suggestion": suggestion}, ensure_ascii=False, indent=2))

    if args.apply and suggestion["eligible"]:
        reason = f"Auto-adjust from {len(reviews)} review(s) over {args.window}: " + "; ".join(suggestion["notes"])
        entry = save_weights(args.weights, suggestion["weights"], reason=reason)
        print(f"Applied new weights (backup at {args.weights}.bak). History: {entry['timestamp']}")
    elif args.apply:
        print("Weights not applied: the legacy suggestion is ineligible; use the advisory evidence-optimize report.")
    else:
        print("Outcome review complete. Legacy weight mutation is frozen; use evidence-optimize for advisory evaluation.")
    return 0


def _cmd_analyze_offline(args: argparse.Namespace) -> int:
    """Score an instrument from pre-fetched futuapi JSON — no OpenD, no network.

    Run the futuapi quote scripts on a machine that can reach OpenD (the host), redirect
    their `--json` output into the mounted workspace, then point this command at those
    files. Backdrop components (sector/market/macro/cross) have no offline feed, so they
    score a neutral 50 and are flagged in source_refs; trend, capital, position and
    (if supplied) fundamental are fully scored.
    """
    from .offline_loader import load_bars, load_capital, load_snapshot

    snapshot = load_snapshot(args.snapshot, code=args.code)
    bars = load_bars(args.kline)
    capital = load_capital(args.capital) if args.capital else None
    user_context = {"last_trim_price": args.last_trim_price} if args.last_trim_price is not None else {}
    state = InstrumentState(snapshot=snapshot, daily_bars=bars, intraday_bars=[], capital=capital, user_context=user_context)

    tags = _tags_for_code(args.code, args.watchlist)
    profile = args.profile or infer_profile(tags)
    fundamentals: FundamentalSnapshot | None = None
    if args.pe_ttm is not None:
        fundamentals = FundamentalSnapshot(
            code=args.code, pe_ttm=args.pe_ttm, pb=args.pb, eps=args.eps,
            dividend_ratio=args.dividend, market_val=None, eps_growth=args.eps_growth,
            revenue_growth=args.revenue_growth, gross_margin=args.gross_margin,
            net_margin=args.net_margin, roe=args.roe,
        )

    refs = [f"offline:snapshot={Path(args.snapshot).name},kline={Path(args.kline).name}(bars={len(bars)})"]
    if capital is not None:
        refs.append("offline:capital")
    if fundamentals is not None:
        refs.append(f"offline:fundamental(profile={profile},pe_ttm={fundamentals.pe_ttm})")

    inverse = args.inverse if args.inverse is not None else is_inverse_instrument(state.snapshot.name, tags)
    leveraged = _is_leveraged(state.snapshot.name, tags)
    weights = load_weights(args.weights) if args.weights else DEFAULT_WEIGHTS
    recommendation = _recommend(
        state=state,
        weights=weights,
        macro_inputs={},
        macro_snapshots=None,
        cross_snapshots={},
        sector_changes=None,
        index_snapshots=None,
        source_refs=refs,
        fundamentals=fundamentals,
        profile=profile,
        risk_budget_pct=args.risk_budget_pct,
        stop_buffer_atr=args.stop_buffer_atr,
        cost_basis=args.cost_basis,
        inverse=inverse,
        leveraged=leveraged,
        horizon=args.horizon,
        event_days=args.event_days,
        underlying_confirmed=args.underlying_confirmed,
        portfolio_open_risk_pct=args.portfolio_open_risk_pct,
        theme_open_risk_pct=args.theme_open_risk_pct,
        trade_id=args.trade_id,
        position_stage=args.position_stage,
    )
    _write(args.output, recommendation)
    if not args.no_journal:
        append_record(args.journal, recommendation.to_record())
    print(f"{recommendation.label}  total_score={recommendation.total_score}  → {args.output}")
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    """Aggregate past reviews into win rate, expectancy and per-component edge.

    Offline: it reads the journals written by `analyze` and `review` (no OpenD).
    Run `review` first to populate reviews from price action that followed each call.
    """
    recommendations = read_records(args.recommendations)
    reviews = read_records(args.reviews)
    if args.code:
        recommendations = [r for r in recommendations if r.get("code") == args.code]
        reviews = [r for r in reviews if r.get("code") == args.code]

    report = run_backtest(recommendations, reviews)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


def _cmd_path_backtest(args: argparse.Namespace) -> int:
    from .path_backtest import run_path_backtest, scenarios_from_record

    source = Path(args.scenario)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("path-backtest scenario must be a JSON object")
    report = run_path_backtest(scenarios_from_record(payload))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(text)
    return 0


def _cmd_evidence_optimize(args: argparse.Namespace) -> int:
    from .evidence_optimization import build_evidence_report

    report = build_evidence_report(
        read_records(args.recommendations),
        read_records(args.reviews),
        load_weights(args.weights),
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(text)
    return 0


def _cmd_prepost(args: argparse.Namespace) -> int:
    """Print pre-market / after-hours price and change for one or more US codes."""
    from .futu_fetcher import FutuFetcher

    fetcher = FutuFetcher()
    rows = []
    for code in args.codes:
        eh = fetcher.get_extended_hours(code)
        if eh is None:
            rows.append({"code": code, "error": "no snapshot"})
            continue
        rows.append(
            {
                "code": eh.code,
                "prev_close": eh.prev_close,
                "pre_price": eh.pre_price,
                "pre_change_rate": eh.pre_change_rate,
                "pre_volume": eh.pre_volume,
                "after_price": eh.after_price,
                "after_change_rate": eh.after_change_rate,
                "after_volume": eh.after_volume,
            }
        )
    if args.json:
        print(json.dumps({"data": rows}, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            if "error" in r:
                print(f"{r['code']:10s} {r['error']}")
                continue
            pre = f"pre {r['pre_price']} ({r['pre_change_rate']:+.2f}%)" if r["pre_price"] is not None else "pre —"
            post = f"after {r['after_price']} ({r['after_change_rate']:+.2f}%)" if r["after_price"] is not None else "after —"
            print(f"{r['code']:10s} prev_close {r['prev_close']}  |  {pre}  |  {post}")
    return 0


def _parse_alert_spec(spec: str) -> tuple[str, str, float, str]:
    parts = spec.split(":", 3)
    if len(parts) < 3:
        raise ValueError(f"alert spec must be CODE:DIRECTION:LEVEL[:NOTE], got {spec!r}")
    code, direction, level = parts[0], parts[1], parts[2]
    note = parts[3] if len(parts) == 4 else ""
    try:
        parsed_level = float(level)
    except ValueError:
        raise ValueError(f"alert LEVEL must be a number, got {level!r} in {spec!r}") from None
    return code, direction, parsed_level, note


def _parse_earnings_spec(spec: str) -> tuple[str, str, str, str]:
    parts = spec.split(":", 3)
    if len(parts) < 2:
        raise ValueError(f"earnings spec must be CODE:DATE[:SESSION[:NOTE]], got {spec!r}")
    code, event_date = parts[0], parts[1]
    session = parts[2] if len(parts) >= 3 else ""
    note = parts[3] if len(parts) == 4 else ""
    return code, event_date, session, note


def _cmd_monitor(args: argparse.Namespace) -> int:
    """Record snapshots/capital flow into the market store and fire price alerts."""
    from .store import MarketStore, sync_daily_bars

    with MarketStore(args.db) as store:
        try:
            for spec in args.add or []:
                code, direction, level, note = _parse_alert_spec(spec)
                alert_id = store.add_alert(code, direction, level, note)
                print(f"armed alert #{alert_id}: {code} {direction} {level} {note}".rstrip())
            for spec in args.earnings_add or []:
                code, event_date, session, note = _parse_earnings_spec(spec)
                store.upsert_earnings(code, event_date, session, note)
                print(f"earnings: {code} {event_date} {session} {note}".rstrip())
        except ValueError as exc:
            print(f"monitor: {exc}", file=sys.stderr)
            return 2

        armed = store.active_alerts()
        upcoming = store.upcoming_earnings(within_days=args.earnings_window)
        if args.list:
            print(f"-- armed alerts ({len(armed)}) --")
            for alert in armed:
                print(f"  #{alert['id']} {alert['code']:10s} {alert['direction']:5s} {alert['level']:<10g} {alert['note']}")
            print(f"-- earnings within {args.earnings_window}d ({len(upcoming)}) --")
            for row in upcoming:
                print(f"  {row['code']:10s} {row['event_date']} ({row['days_until']}d) {row['session']} {row['note']}")
            return 0

        codes: list[str] = []
        for code in [alert["code"] for alert in armed] + list(args.codes or []):
            if code not in codes:
                codes.append(code)
        if not codes:
            print("nothing to monitor: no armed alerts and no --codes")
            return 0

        from .futu_fetcher import FutuFetcher

        fetcher = FutuFetcher()
        snapshots = {snapshot.code: snapshot for snapshot in fetcher.get_snapshots(codes)}
        for code in codes:
            snapshot = snapshots.get(code)
            if snapshot is None:
                print(f"{code:10s} no snapshot")
                continue
            store.record_snapshot(snapshot)
            change = (
                (snapshot.last_price - snapshot.prev_close) / snapshot.prev_close * 100.0
                if snapshot.prev_close > 0
                else 0.0
            )
            print(f"{code:10s} last {snapshot.last_price:<10g} ({change:+.2f}%)")
            if not args.no_capital:
                capital = fetcher.get_capital_distribution(code)
                if capital is not None:
                    store.record_capital(code, capital)
                    print(f"{'':10s} capital net {capital.net_inflow:+,.0f} (super {capital.super_inflow:+,.0f})")
            if args.sync_bars:
                cached = sync_daily_bars(store, fetcher, code, num=args.sync_bars)
                print(f"{'':10s} cached {len(cached)} daily bars (total {store.bar_count(code)})")

        triggered = store.check_alerts(snapshots)
        for alert in triggered:
            print(
                f"⚠ TRIGGERED #{alert['id']}: {alert['code']} {alert['direction']} {alert['level']}"
                f" @ {alert['triggered_price']} {alert['note']}".rstrip()
            )
        for row in upcoming:
            print(f"📅 earnings {row['code']} {row['event_date']} ({row['days_until']}d) {row['session']} {row['note']}".rstrip())
        if args.output:
            payload = {
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "codes": codes,
                "triggered": triggered,
                "armed": store.active_alerts(),
                "upcoming_earnings": upcoming,
            }
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-evolving stock skill tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser("dry-run", help=f"Replay the frozen {FIXTURE_CODE} fixture offline (pipeline check only)")
    dry_run.add_argument("--code", required=True, help=f"Must be {FIXTURE_CODE}; the fixture is not a real-data analysis of other codes")
    dry_run.add_argument("--output", required=True)
    dry_run.add_argument("--horizon", choices=["short", "swing"], default="short", help="Strategy horizon for the frozen fixture")
    dry_run.add_argument("--event-days", type=int, default=None, help="Trading days until a known event for swing-gate verification")

    analyze = subparsers.add_parser("analyze", help="Analyze a real instrument via Futu OpenD (snapshot + daily K-line + capital flow)")
    analyze.add_argument("--code", required=True, help="Instrument code, e.g. SZ.002463, US.NVDA, CC.BTC")
    analyze.add_argument("--output", required=True)
    analyze.add_argument("--bars", type=int, default=30, help="Number of daily bars to fetch (default: 30)")
    analyze.add_argument("--cross", nargs="*", default=None, help="Cross-market reference codes to fetch, e.g. US.QQQ US.NVDA")
    analyze.add_argument("--last-trim-price", type=float, default=None, help="Prior partial-trim price for position context")
    analyze.add_argument("--weights", default=None, help="Path to a signal_weights.json; defaults to built-in weights")
    analyze.add_argument("--journal", default=DEFAULT_RECOMMENDATIONS, help=f"Recommendation journal path (default: {DEFAULT_RECOMMENDATIONS})")
    analyze.add_argument("--no-journal", action="store_true", help="Do not append this recommendation to the journal")
    analyze.add_argument("--indices", nargs="*", default=None, help="Market index codes for the market regime (default: inferred from instrument market)")
    analyze.add_argument("--no-market", action="store_true", help="Skip the market-regime fetch (scores neutral)")
    analyze.add_argument("--no-sector", action="store_true", help="Skip the sector-strength fetch (scores neutral)")
    analyze.add_argument("--sector-limit", type=int, default=30, help="Top N plate constituents to sample for sector strength (default: 30)")
    analyze.add_argument("--macro-codes", nargs="*", default=None, help=f"Macro proxy codes for the macro-risk score (default: {' '.join(DEFAULT_MACRO_CODES)})")
    analyze.add_argument("--no-macro", action="store_true", help="Skip the macro-proxy fetch (scores neutral)")
    analyze.add_argument("--macro-json", default=None, help='Hand-typed macro override, e.g. \'{"fed_bias":"hike"}\' (bypasses proxy fetch)')
    analyze.add_argument("--no-fundamental", action="store_true", help="Skip the fundamental fetch (scores neutral)")
    analyze.add_argument("--no-financials", action="store_true", help="Skip auto-fetching financial statements (growth/margins/ROE); valuation multiples only")
    analyze.add_argument("--eps-growth", type=float, default=None, help="YoY EPS growth %% for PEG (e.g. 40 = +40%%); enables PEG scoring")
    analyze.add_argument("--revenue-growth", type=float, default=None, help="YoY revenue growth %% for the business-quality sub-score")
    analyze.add_argument("--gross-margin", type=float, default=None, help="Gross margin %% for the business-quality sub-score")
    analyze.add_argument("--net-margin", type=float, default=None, help="Net margin %% for the business-quality sub-score")
    analyze.add_argument("--roe", type=float, default=None, help="Return on equity %% for the business-quality sub-score")
    analyze.add_argument("--profile", choices=["growth", "value", "neutral"], default=None, help="Valuation profile; default inferred from watchlist tags")
    analyze.add_argument("--watchlist", default=DEFAULT_WATCHLIST_PATH, help=f"Watchlist path for profile inference (default: {DEFAULT_WATCHLIST_PATH})")
    analyze.add_argument("--shared-context", default=None, help=argparse.SUPPRESS)
    analyze.add_argument("--risk-budget-pct", type=float, default=1.0, help="Account %% to risk per trade for position sizing (default: 1.0)")
    analyze.add_argument(
        "--stop-buffer-atr", "--atr-multiple", dest="stop_buffer_atr", type=float, default=None,
        help="Override the profile ATR buffer beyond structural invalidation (short 0.25, swing 0.5; --atr-multiple is a compatibility alias)",
    )
    analyze.add_argument("--horizon", choices=["short", "swing"], default="short", help="Strategy horizon (default: short, 1-3 trading days)")
    analyze.add_argument("--event-days", type=int, default=None, help="Trading days until the next known major event; required to clear the swing event gate")
    analyze.add_argument("--underlying-confirmed", action=argparse.BooleanOptionalAction, default=None, help="Whether a leveraged ETF is confirmed by its underlying proxy")
    analyze.add_argument("--portfolio-open-risk-pct", type=float, default=None, help="Current total open portfolio risk %% for the 6%% heat gate")
    analyze.add_argument("--theme-open-risk-pct", type=float, default=None, help="Current correlated-theme open risk %% for the 3%% heat gate")
    analyze.add_argument("--cost-basis", type=float, default=None, help="Existing cost basis, to report open P&L in the plan")
    analyze.add_argument("--position-stage", choices=["probe", "core"], default=None, help="Existing position stage; a confirmed probe may become an add candidate")
    analyze.add_argument("--trade-id", default=None, help="Existing trade id for position-management records; new entries get a deterministic id")
    analyze.add_argument("--inverse", action=argparse.BooleanOptionalAction, default=None, help="Treat as an inverse/short ETF (invert backdrop scores); default auto-detected from name/tags")

    review = subparsers.add_parser("review", help="Review past recommendations against later price action and record outcomes")
    review.add_argument("--window", choices=sorted(REVIEW_WINDOW_DAYS), default="3d", help="Review horizon in trading days (default: 3d)")
    review.add_argument("--code", default=None, help="Only review recommendations for this code")
    review.add_argument("--recommendations", default=DEFAULT_RECOMMENDATIONS, help=f"Recommendation journal path (default: {DEFAULT_RECOMMENDATIONS})")
    review.add_argument("--reviews", default=DEFAULT_REVIEWS, help=f"Reviews output path (default: {DEFAULT_REVIEWS})")
    review.add_argument("--weights", default=DEFAULT_WEIGHTS_PATH, help=f"Signal weights path (default: {DEFAULT_WEIGHTS_PATH})")
    review.add_argument("--apply", action="store_true", help="Deprecated compatibility flag; legacy weight mutation is frozen")

    offline = subparsers.add_parser("analyze-offline", help="Score from pre-fetched futuapi JSON (snapshot + kline), no OpenD")
    offline.add_argument("--code", required=True, help="Instrument code, e.g. US.SOXL")
    offline.add_argument("--snapshot", required=True, help="Path to get_snapshot.py --json output")
    offline.add_argument("--kline", required=True, help="Path to get_kline.py --json output (daily bars)")
    offline.add_argument("--capital", default=None, help="Optional path to get_capital_flow.py --json output")
    offline.add_argument("--output", required=True)
    offline.add_argument("--profile", choices=["growth", "value", "neutral"], default=None, help="Valuation profile; default inferred from watchlist tags")
    offline.add_argument("--watchlist", default=DEFAULT_WATCHLIST_PATH, help=f"Watchlist path for profile inference (default: {DEFAULT_WATCHLIST_PATH})")
    offline.add_argument("--pe-ttm", type=float, default=None, help="PE-TTM (enables the fundamental component offline)")
    offline.add_argument("--pb", type=float, default=None, help="Price-to-book")
    offline.add_argument("--eps", type=float, default=None, help="EPS")
    offline.add_argument("--dividend", type=float, default=None, help="Trailing dividend yield %%")
    offline.add_argument("--eps-growth", type=float, default=None, help="YoY EPS growth %% → enables PEG")
    offline.add_argument("--revenue-growth", type=float, default=None, help="YoY revenue growth %% (business-quality)")
    offline.add_argument("--gross-margin", type=float, default=None, help="Gross margin %% (business-quality)")
    offline.add_argument("--net-margin", type=float, default=None, help="Net margin %% (business-quality)")
    offline.add_argument("--roe", type=float, default=None, help="ROE %% (business-quality)")
    offline.add_argument("--risk-budget-pct", type=float, default=1.0, help="Account %% to risk per trade (default: 1.0)")
    offline.add_argument(
        "--stop-buffer-atr", "--atr-multiple", dest="stop_buffer_atr", type=float, default=None,
        help="Override the profile ATR buffer beyond structural invalidation (short 0.25, swing 0.5; --atr-multiple is a compatibility alias)",
    )
    offline.add_argument("--horizon", choices=["short", "swing"], default="short", help="Strategy horizon (default: short, 1-3 trading days)")
    offline.add_argument("--event-days", type=int, default=None, help="Trading days until the next known major event; required to clear the swing event gate")
    offline.add_argument("--underlying-confirmed", action=argparse.BooleanOptionalAction, default=None, help="Whether a leveraged ETF is confirmed by its underlying proxy")
    offline.add_argument("--portfolio-open-risk-pct", type=float, default=None, help="Current total open portfolio risk %% for the 6%% heat gate")
    offline.add_argument("--theme-open-risk-pct", type=float, default=None, help="Current correlated-theme open risk %% for the 3%% heat gate")
    offline.add_argument("--cost-basis", type=float, default=None, help="Existing cost basis, to report open P&L")
    offline.add_argument("--position-stage", choices=["probe", "core"], default=None, help="Existing position stage; a confirmed probe may become an add candidate")
    offline.add_argument("--trade-id", default=None, help="Existing trade id for position-management records; new entries get a deterministic id")
    offline.add_argument("--inverse", action=argparse.BooleanOptionalAction, default=None, help="Treat as an inverse/short ETF (invert backdrop scores); default auto-detected from name/tags")
    offline.add_argument("--last-trim-price", type=float, default=None, help="Prior partial-trim price for position context")
    offline.add_argument("--weights", default=None, help="Path to a signal_weights.json; defaults to built-in weights")
    offline.add_argument("--journal", default=DEFAULT_RECOMMENDATIONS, help=f"Recommendation journal path (default: {DEFAULT_RECOMMENDATIONS})")
    offline.add_argument("--no-journal", action="store_true", help="Do not append this recommendation to the journal")

    backtest = subparsers.add_parser("backtest", help="Aggregate past reviews into win rate, expectancy and per-component edge (offline)")
    backtest.add_argument("--recommendations", default=DEFAULT_RECOMMENDATIONS, help=f"Recommendation journal path (default: {DEFAULT_RECOMMENDATIONS})")
    backtest.add_argument("--reviews", default=DEFAULT_REVIEWS, help=f"Reviews path written by `review` (default: {DEFAULT_REVIEWS})")
    backtest.add_argument("--code", default=None, help="Only back-test this code")
    backtest.add_argument("--output", default=None, help="Optional path to also write the JSON report")

    path_backtest = subparsers.add_parser("path-backtest", help="Replay structured exit plans through chronological OHLC bars")
    path_backtest.add_argument("--scenario", required=True, help="JSON file containing serialized exit plans, bars, and optional execution costs")
    path_backtest.add_argument("--output", required=True, help="Path for the JSON path-backtest report")

    evidence_optimize = subparsers.add_parser(
        "evidence-optimize",
        help="Build an advisory strategy-versioned walk-forward optimisation report",
    )
    evidence_optimize.add_argument("--recommendations", default=DEFAULT_RECOMMENDATIONS)
    evidence_optimize.add_argument("--reviews", default=DEFAULT_REVIEWS)
    evidence_optimize.add_argument("--weights", default=DEFAULT_WEIGHTS_PATH)
    evidence_optimize.add_argument("--output", required=True)

    prepost = subparsers.add_parser("prepost", help="Show pre-market / after-hours price and change for US codes (via Futu OpenD)")
    prepost.add_argument("codes", nargs="+", help="One or more codes, e.g. US.SOXL US.SMH US.NVDA")
    prepost.add_argument("--json", action="store_true", help="Emit JSON instead of a text table")

    monitor = subparsers.add_parser(
        "monitor",
        help="Record snapshots/capital flow into the market store (SQLite cache) and fire one-shot price alerts",
    )
    monitor.add_argument("--db", default="data/market.db", help="Market store path (default: data/market.db)")
    monitor.add_argument("--add", action="append", default=None, metavar="CODE:DIR:LEVEL[:NOTE]", help="Arm an alert, e.g. US.COIN:below:150:价值区上沿")
    monitor.add_argument("--earnings-add", action="append", default=None, metavar="CODE:DATE[:SESSION[:NOTE]]", help="Record an earnings date, e.g. US.COIN:2026-08-12:盘后:Q2财报")
    monitor.add_argument("--codes", nargs="*", default=None, help="Extra codes to record beyond armed-alert codes")
    monitor.add_argument("--list", action="store_true", help="List armed alerts and upcoming earnings without fetching")
    monitor.add_argument("--sync-bars", type=int, default=0, help="Also cache N daily bars per monitored code (default: 0 = skip)")
    monitor.add_argument("--no-capital", action="store_true", help="Skip capital-distribution recording")
    monitor.add_argument("--earnings-window", type=int, default=14, help="Days ahead to surface earnings (default: 14)")
    monitor.add_argument("--output", default=None, help="Optional JSON report path")

    args = parser.parse_args(argv)

    if args.command in {"analyze", "analyze-offline"} and args.cost_basis is not None and not args.trade_id:
        parser.error("--cost-basis position management requires --trade-id to link the original trade")
    if args.command in {"analyze", "analyze-offline"} and args.position_stage is not None and args.cost_basis is None:
        parser.error("--position-stage requires --cost-basis and --trade-id for an existing position")

    if args.command == "dry-run":
        return _cmd_dry_run(args, parser)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "review":
        return _cmd_review(args)
    if args.command == "analyze-offline":
        return _cmd_analyze_offline(args)
    if args.command == "backtest":
        return _cmd_backtest(args)
    if args.command == "path-backtest":
        return _cmd_path_backtest(args)
    if args.command == "evidence-optimize":
        return _cmd_evidence_optimize(args)
    if args.command == "prepost":
        return _cmd_prepost(args)
    if args.command == "monitor":
        return _cmd_monitor(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
