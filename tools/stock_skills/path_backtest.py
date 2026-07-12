from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .exit_engine import next_trailing_stop
from .models import (
    ExitPlan,
    ExitTarget,
    KLineBar,
    RiskSizing,
    TimeStop,
    TrailingRule,
)


@dataclass(frozen=True)
class ExecutionCosts:
    commission_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0

    def total_bps(self) -> float:
        values = (self.commission_bps, self.spread_bps, self.slippage_bps)
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("execution costs must be finite non-negative basis points")
        return float(sum(values))


@dataclass(frozen=True)
class AddOnRule:
    trigger_r: float
    fraction: float
    stop_after_add: float


@dataclass(frozen=True)
class PathAddOn:
    bar_time: str
    fraction: float
    raw_price: float
    price: float
    stop_after_add: float
    open_risk_r: float


@dataclass(frozen=True)
class PathFill:
    bar_time: str
    reason: str
    fraction: float
    raw_price: float
    price: float
    gross_r: float
    net_r: float


@dataclass(frozen=True)
class PathBacktestResult:
    realized_r: float
    gross_r: float
    total_cost: float
    exit_reason: str
    fills: tuple[PathFill, ...]
    add_ons: tuple[PathAddOn, ...]
    bars_held: int
    max_favorable_r: float
    max_adverse_r: float
    mfe_capture_ratio: float | None
    profit_giveback_ratio: float | None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HeatDecision:
    allowed: bool
    proposed_risk_pct: float
    allowed_risk_pct: float
    scaled: bool
    portfolio_headroom_pct: float
    theme_headroom_pct: float
    reasons: tuple[str, ...]


LEVERAGED_DEFAULT_COSTS = ExecutionCosts(spread_bps=5.0, slippage_bps=10.0)


def _finite_non_negative(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


def assess_portfolio_heat(
    *,
    proposed_risk_pct: float,
    portfolio_open_risk_pct: float,
    theme_open_risk_pct: float,
    maximum_portfolio_risk_pct: float = 6.0,
    maximum_theme_risk_pct: float = 3.0,
) -> HeatDecision:
    proposed = _finite_non_negative("proposed_risk_pct", proposed_risk_pct)
    portfolio_open = _finite_non_negative("portfolio_open_risk_pct", portfolio_open_risk_pct)
    theme_open = _finite_non_negative("theme_open_risk_pct", theme_open_risk_pct)
    portfolio_max = _finite_non_negative("maximum_portfolio_risk_pct", maximum_portfolio_risk_pct)
    theme_max = _finite_non_negative("maximum_theme_risk_pct", maximum_theme_risk_pct)
    if portfolio_max <= 0 or theme_max <= 0:
        raise ValueError("risk limits must be positive")

    portfolio_headroom = max(0.0, portfolio_max - portfolio_open)
    theme_headroom = max(0.0, theme_max - theme_open)
    allowed_risk = min(proposed, portfolio_headroom, theme_headroom)
    reasons: list[str] = []
    if portfolio_headroom < proposed:
        reasons.append("portfolio-risk-headroom")
    if theme_headroom < proposed:
        reasons.append("theme-risk-headroom")
    allowed = allowed_risk > 0 or proposed == 0
    return HeatDecision(
        allowed=allowed,
        proposed_risk_pct=round(proposed, 4),
        allowed_risk_pct=round(allowed_risk, 4),
        scaled=allowed and allowed_risk + 1e-9 < proposed,
        portfolio_headroom_pct=round(portfolio_headroom, 4),
        theme_headroom_pct=round(theme_headroom, 4),
        reasons=tuple(reasons),
    )


def simulate_exit_plan(
    exit_plan: ExitPlan,
    bars: Iterable[KLineBar],
    *,
    costs: ExecutionCosts | None = None,
    leveraged: bool = False,
    add_ons: Iterable[AddOnRule] = (),
) -> PathBacktestResult:
    sequence = list(bars)
    if not sequence:
        raise ValueError("at least one OHLC bar is required")
    execution_costs = costs or (LEVERAGED_DEFAULT_COSTS if leveraged else ExecutionCosts())
    cost_rate = execution_costs.total_bps() / 10_000.0
    add_on_rules = list(add_ons)
    for rule in add_on_rules:
        if (
            isinstance(rule.trigger_r, bool)
            or not isinstance(rule.trigger_r, (int, float))
            or not math.isfinite(rule.trigger_r)
            or rule.trigger_r <= 0
            or isinstance(rule.fraction, bool)
            or not isinstance(rule.fraction, (int, float))
            or not math.isfinite(rule.fraction)
            or not 0 < rule.fraction <= 1
            or isinstance(rule.stop_after_add, bool)
            or not isinstance(rule.stop_after_add, (int, float))
            or not math.isfinite(rule.stop_after_add)
        ):
            raise ValueError("add-on rules require positive finite trigger/fraction and finite stop")
    add_on_rules.sort(key=lambda rule: rule.trigger_r)
    entry = exit_plan.entry_price
    entry_fill = entry * (1.0 + cost_rate)
    risk = exit_plan.risk_per_share
    if risk <= 0:
        raise ValueError("exit plan risk_per_share must be positive")

    remaining = 1.0
    active_stop = exit_plan.initial_stop
    trailing_active = False
    next_target = 0
    fills: list[PathFill] = []
    add_on_fills: list[PathAddOn] = []
    lots: list[dict[str, float]] = [
        {"quantity": 1.0, "raw_entry": entry, "entry": entry_fill}
    ]
    next_add_on = 0
    gross_r = 0.0
    net_r = 0.0
    total_cost = entry_fill - entry
    highest_close = entry
    observed_lows: list[float] = []
    max_high = entry
    min_low = entry
    exit_reason = "end-of-data"
    bars_held = 0

    def fill(bar: KLineBar, reason: str, fraction: float, raw_price: float) -> None:
        nonlocal remaining, gross_r, net_r, total_cost, exit_reason
        fraction = min(fraction, remaining)
        if fraction <= 0:
            return
        executed = raw_price * (1.0 - cost_rate)
        to_close = fraction
        gross_piece = 0.0
        net_piece = 0.0
        for lot in lots:
            if to_close <= 1e-9:
                break
            quantity = min(lot["quantity"], to_close)
            if quantity <= 0:
                continue
            gross_piece += ((raw_price - lot["raw_entry"]) / risk) * quantity
            net_piece += ((executed - lot["entry"]) / risk) * quantity
            lot["quantity"] = round(lot["quantity"] - quantity, 9)
            to_close -= quantity
        exit_cost = (raw_price - executed) * fraction
        fills.append(
            PathFill(
                bar_time=bar.time,
                reason=reason,
                fraction=round(fraction, 6),
                raw_price=round(raw_price, 6),
                price=round(executed, 6),
                gross_r=round(gross_piece, 6),
                net_r=round(net_piece, 6),
            )
        )
        remaining = round(max(0.0, remaining - fraction), 6)
        gross_r += gross_piece
        net_r += net_piece
        total_cost += exit_cost
        exit_reason = reason

    for index, bar in enumerate(sequence):
        bars_held = index + 1
        max_high = max(max_high, bar.high)
        min_low = min(min_low, bar.low)

        if bar.open <= active_stop:
            reason = "gap-trailing-stop" if trailing_active else "gap-stop"
            fill(bar, reason, remaining, bar.open)
            break

        # Conservative same-bar ordering: an already-active stop is assumed to fire
        # before any target when both prices lie inside the same OHLC range.
        if bar.low <= active_stop:
            reason = "trailing-stop" if trailing_active else "initial-stop"
            fill(bar, reason, remaining, active_stop)
            break

        while next_target < len(exit_plan.targets):
            target = exit_plan.targets[next_target]
            if bar.high < target.price:
                break
            fill(bar, target.name, target.fraction, target.price)
            next_target += 1

        if remaining <= 0:
            break

        highest_close = max(highest_close, bar.close)
        observed_lows.append(bar.low)
        activation_price = entry + exit_plan.trailing_rule.activation_r * risk
        if next_target == len(exit_plan.targets) or max_high >= activation_price:
            if len(observed_lows) >= 2:
                prior_two_bar_low = min(observed_lows[-2:])
                active_stop = next_trailing_stop(
                    previous_stop=active_stop if trailing_active else None,
                    prior_two_bar_low=prior_two_bar_low,
                    highest_close=highest_close,
                    atr=exit_plan.atr,
                    atr_multiple=exit_plan.trailing_rule.atr_multiple,
                )
                active_stop = max(exit_plan.initial_stop, active_stop)
                trailing_active = True

        progress_price = entry + exit_plan.time_stop.progress_r * risk
        if index + 1 >= exit_plan.time_stop.sessions and max_high < progress_price:
            fill(bar, "time-stop", remaining, bar.close)
            break
        if index + 1 >= exit_plan.maximum_holding_days:
            fill(bar, "maximum-holding-period", remaining, bar.close)
            break

        # Add only from a completed close, after every same-bar stop/target/time decision.
        # The raised stop must keep total open risk at or below the original 1R budget.
        while next_add_on < len(add_on_rules):
            rule = add_on_rules[next_add_on]
            trigger_price = entry + rule.trigger_r * risk
            if bar.close < trigger_price:
                break
            candidate_stop = max(active_stop, rule.stop_after_add)
            if candidate_stop >= bar.close:
                raise ValueError("add-on stop must remain below the add-on price")
            projected_risk = sum(
                lot["quantity"] * (lot["raw_entry"] - candidate_stop)
                for lot in lots
            ) + rule.fraction * (bar.close - candidate_stop)
            if projected_risk > risk + 1e-9:
                raise ValueError("add-on would increase open risk beyond the original 1R budget")
            add_entry = bar.close * (1.0 + cost_rate)
            lots.append(
                {
                    "quantity": float(rule.fraction),
                    "raw_entry": bar.close,
                    "entry": add_entry,
                }
            )
            remaining = round(remaining + rule.fraction, 6)
            active_stop = candidate_stop
            total_cost += (add_entry - bar.close) * rule.fraction
            add_on_fills.append(
                PathAddOn(
                    bar_time=bar.time,
                    fraction=round(rule.fraction, 6),
                    raw_price=round(bar.close, 6),
                    price=round(add_entry, 6),
                    stop_after_add=round(active_stop, 6),
                    open_risk_r=round(projected_risk / risk, 6),
                )
            )
            next_add_on += 1
    else:
        fill(sequence[-1], "end-of-data", remaining, sequence[-1].close)

    max_favorable_r = (max_high - entry) / risk
    max_adverse_r = (min_low - entry) / risk
    capture = None
    giveback = None
    if max_favorable_r > 0:
        capture = min(1.0, max(0.0, net_r) / max_favorable_r)
        giveback = min(
            1.0,
            max(0.0, max_favorable_r - max(0.0, net_r)) / max_favorable_r,
        )
    return PathBacktestResult(
        realized_r=round(net_r, 4),
        gross_r=round(gross_r, 4),
        total_cost=round(total_cost, 6),
        exit_reason=exit_reason,
        fills=tuple(fills),
        add_ons=tuple(add_on_fills),
        bars_held=bars_held,
        max_favorable_r=round(max_favorable_r, 4),
        max_adverse_r=round(max_adverse_r, 4),
        mfe_capture_ratio=None if capture is None else round(capture, 4),
        profit_giveback_ratio=None if giveback is None else round(giveback, 4),
    )


def run_path_backtest(scenarios: Iterable[dict[str, Any]]) -> dict[str, Any]:
    results: list[PathBacktestResult] = []
    seen_trade_ids: set[str] = set()
    deduplicated_trades = 0
    for scenario in scenarios:
        trade_id = scenario.get("trade_id")
        if trade_id is not None:
            if not isinstance(trade_id, str) or not trade_id:
                raise ValueError("scenario trade_id must be a non-empty string")
            if trade_id in seen_trade_ids:
                deduplicated_trades += 1
                continue
            seen_trade_ids.add(trade_id)
        plan = scenario.get("exit_plan")
        bars = scenario.get("bars")
        if not isinstance(plan, ExitPlan) or not isinstance(bars, list):
            raise ValueError("each scenario requires an ExitPlan and a list of bars")
        costs = scenario.get("costs")
        if costs is not None and not isinstance(costs, ExecutionCosts):
            raise ValueError("scenario costs must be ExecutionCosts")
        leveraged = scenario.get("leveraged", False)
        if not isinstance(leveraged, bool):
            raise ValueError("scenario leveraged flag must be boolean")
        add_ons = scenario.get("add_ons", [])
        if not isinstance(add_ons, list) or any(not isinstance(rule, AddOnRule) for rule in add_ons):
            raise ValueError("scenario add_ons must be a list of AddOnRule values")
        results.append(simulate_exit_plan(plan, bars, costs=costs, leveraged=leveraged, add_ons=add_ons))

    returns = [result.realized_r for result in results]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    consecutive_losses = 0
    maximum_consecutive_losses = 0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
        if value < 0:
            consecutive_losses += 1
            maximum_consecutive_losses = max(maximum_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    total_mfe = sum(max(0.0, result.max_favorable_r) for result in results)
    captured = sum(max(0.0, result.realized_r) for result in results)
    giveback_values = [
        result.profit_giveback_ratio
        for result in results
        if result.profit_giveback_ratio is not None
    ]
    count = len(results)
    summary = {
        "trades": count,
        "win_rate": round(len(wins) / count, 4) if count else None,
        "expectancy_r": round(sum(returns) / count, 4) if count else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "average_win_r": round(sum(wins) / len(wins), 4) if wins else None,
        "average_loss_r": round(sum(losses) / len(losses), 4) if losses else None,
        "maximum_drawdown_r": round(max_drawdown, 4),
        "average_holding_bars": round(sum(result.bars_held for result in results) / count, 2) if count else None,
        "maximum_consecutive_losses": maximum_consecutive_losses,
        "mfe_capture_ratio": round(captured / total_mfe, 4) if total_mfe else None,
        "average_profit_giveback_ratio": round(sum(giveback_values) / len(giveback_values), 4)
        if giveback_values
        else None,
    }
    return {
        "summary": summary,
        "deduplicated_trades": deduplicated_trades,
        "trades": [result.to_record() for result in results],
    }


def exit_plan_from_record(payload: dict[str, Any]) -> ExitPlan:
    try:
        return ExitPlan(
            strategy_id=str(payload["strategy_id"]),
            side=str(payload["side"]),
            entry_price=float(payload["entry_price"]),
            structural_invalidation=float(payload["structural_invalidation"]),
            initial_stop=float(payload["initial_stop"]),
            risk_per_share=float(payload["risk_per_share"]),
            atr=float(payload["atr"]),
            risk_budget_pct=float(payload["risk_budget_pct"]),
            targets=tuple(ExitTarget(**target) for target in payload["targets"]),
            runner_fraction=float(payload["runner_fraction"]),
            trailing_rule=TrailingRule(**payload["trailing_rule"]),
            time_stop=TimeStop(**payload["time_stop"]),
            maximum_holding_days=int(payload["maximum_holding_days"]),
            gap_handling=str(payload["gap_handling"]),
            event_handling=str(payload["event_handling"]),
            risk_sizing=RiskSizing(**payload["risk_sizing"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid serialized exit plan: {exc}") from exc


def scenarios_from_record(payload: dict[str, Any]) -> list[dict[str, Any]]:
    trades = payload.get("trades")
    if not isinstance(trades, list):
        raise ValueError("path-backtest scenario must contain a trades list")
    scenarios: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict):
            raise ValueError("each path-backtest trade must be an object")
        raw_bars = trade.get("bars")
        if not isinstance(raw_bars, list):
            raise ValueError("each path-backtest trade requires a bars list")
        try:
            bars = [KLineBar(**bar) for bar in raw_bars]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid serialized OHLC bars: {exc}") from exc
        raw_costs = trade.get("costs")
        if raw_costs is not None and not isinstance(raw_costs, dict):
            raise ValueError("costs must be an object")
        leveraged = trade.get("leveraged", False)
        if not isinstance(leveraged, bool):
            raise ValueError("leveraged must be boolean")
        trade_id = trade.get("trade_id")
        if trade_id is not None and (not isinstance(trade_id, str) or not trade_id):
            raise ValueError("trade_id must be a non-empty string")
        try:
            raw_plan = trade["exit_plan"]
            costs = None if raw_costs is None else ExecutionCosts(**raw_costs)
            raw_add_ons = trade.get("add_ons", [])
            if not isinstance(raw_add_ons, list):
                raise TypeError("add_ons must be a list")
            add_ons = [AddOnRule(**rule) for rule in raw_add_ons]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Invalid serialized path scenario: {exc}") from exc
        scenarios.append(
            {
                "exit_plan": exit_plan_from_record(raw_plan),
                "bars": bars,
                "costs": costs,
                "leveraged": leveraged,
                "add_ons": add_ons,
                "trade_id": trade_id,
            }
        )
    return scenarios
