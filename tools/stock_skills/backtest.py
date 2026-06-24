from __future__ import annotations

from statistics import mean
from typing import Any

from .review import NEGATIVE_LABELS

# Components whose recorded score we test for predictive edge.
_COMPONENTS = (
    "trend",
    "capital_flow",
    "sector",
    "cross_market",
    "macro_risk",
    "market_regime",
    "fundamental",
    "position_fit",
)

_BULLISH = 55.0  # component score at/above this counts as a bullish vote
_BEARISH = 45.0  # at/below this counts as a bearish vote


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _directional_pnl(review: dict[str, Any]) -> float | None:
    """Direction-aware P&L in percent.

    A long/observe call (positive label) profits when price rises; a reduce/avoid call
    (negative label) profits when price falls, so its raw return is flipped. This keeps
    win/loss/expectancy coherent across a mix of bullish and bearish calls instead of
    pretending everything is long-only.
    """
    ret = _num(review.get("final_return_pct"))
    if ret is None:
        return None
    return -ret if str(review.get("label", "")) in NEGATIVE_LABELS else ret


def _bucket_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_return_pct": None}
    wins = sum(1 for r in rows if r.get("directional_success") is True)
    returns = [v for v in (_num(r.get("final_return_pct")) for r in rows) if v is not None]
    return {
        "n": n,
        "win_rate": round(wins / n, 4),
        "avg_return_pct": round(mean(returns), 4) if returns else None,
    }


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key)), []).append(row)
    return {name: _bucket_stats(items) for name, items in sorted(groups.items())}


def summarize_outcomes(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate review outcomes into win rate, expectancy, MFE/MAE and groupings.

    Input is the list of records written by `review` (review.evaluate_recommendation).
    This makes the system's accuracy a measured number instead of an assumption.
    """
    usable = [r for r in reviews if _num(r.get("final_return_pct")) is not None]
    if not usable:
        return {"reviewed": 0, "notes": ["No reviews with a usable final_return_pct."]}

    n = len(usable)
    wins = [r for r in usable if r.get("directional_success") is True]
    losses = [r for r in usable if r.get("directional_success") is False]
    raw_returns = [float(r["final_return_pct"]) for r in usable]
    pnl = [v for v in (_directional_pnl(r) for r in usable) if v is not None]
    win_pnl = [v for v in (_directional_pnl(r) for r in wins) if v is not None]
    loss_pnl = [v for v in (_directional_pnl(r) for r in losses) if v is not None]

    win_rate = round(len(wins) / n, 4)
    avg_win = round(mean(win_pnl), 4) if win_pnl else 0.0
    avg_loss = round(mean(loss_pnl), 4) if loss_pnl else 0.0
    payoff_ratio = round(abs(avg_win / avg_loss), 4) if avg_loss else None
    # Direction-aware expectancy per call, in percent (average realised P&L).
    expectancy_pct = round(mean(pnl), 4) if pnl else 0.0

    mfe = [v for v in (_num(r.get("maximum_favorable_pct")) for r in usable) if v is not None]
    mae = [v for v in (_num(r.get("maximum_adverse_pct")) for r in usable) if v is not None]

    return {
        "reviewed": n,
        "win_rate": win_rate,
        "wins": len(wins),
        "losses": len(losses),
        "invalidated": sum(1 for r in usable if r.get("invalidated") is True),
        "avg_return_pct": round(mean(raw_returns), 4),       # raw price move, long-only frame
        "expectancy_pct": expectancy_pct,                    # direction-aware avg P&L per call
        "avg_win_pct": avg_win,                              # avg P&L of successful calls
        "avg_loss_pct": avg_loss,                            # avg P&L of failed calls
        "payoff_ratio": payoff_ratio,
        "avg_mfe_pct": round(mean(mfe), 4) if mfe else None,
        "avg_mae_pct": round(mean(mae), 4) if mae else None,
        "by_label": _group_by(usable, "label"),
        "by_code": _group_by(usable, "code"),
    }


def component_edge(
    recommendations: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure each component's predictive edge.

    Joins reviews back to the recommendation that produced them (by code + timestamp),
    then for every component compares the win rate when that component was bullish
    (score >= 55) versus bearish (score <= 45). `edge` = bullish win rate minus bearish
    win rate: positive means a high score for that factor genuinely preceded better
    outcomes — i.e. the factor is earning its weight.
    """
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in recommendations:
        code = rec.get("code")
        ts = rec.get("timestamp")
        if code is not None and ts is not None:
            index[(str(code), str(ts))] = rec

    joined: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for review in reviews:
        key = (str(review.get("code")), str(review.get("source_timestamp")))
        rec = index.get(key)
        if rec is not None and _num(review.get("final_return_pct")) is not None:
            joined.append((rec, review))

    result: dict[str, Any] = {"joined": len(joined), "components": {}}
    if not joined:
        result["notes"] = ["No recommendation/review pairs could be joined (need matching code+timestamp)."]
        return result

    for component in _COMPONENTS:
        bullish: list[dict[str, Any]] = []
        bearish: list[dict[str, Any]] = []
        for rec, review in joined:
            scores = rec.get("component_scores")
            score = _num(scores.get(component)) if isinstance(scores, dict) else None
            if score is None:
                continue
            if score >= _BULLISH:
                bullish.append(review)
            elif score <= _BEARISH:
                bearish.append(review)
        b_stats = _bucket_stats(bullish)
        r_stats = _bucket_stats(bearish)
        edge = None
        if b_stats["win_rate"] is not None and r_stats["win_rate"] is not None:
            edge = round(b_stats["win_rate"] - r_stats["win_rate"], 4)
        result["components"][component] = {
            "bullish": b_stats,
            "bearish": r_stats,
            "edge": edge,
        }
    return result


def run_backtest(
    recommendations: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    """Full backtest report: outcome summary + per-component predictive edge."""
    return {
        "summary": summarize_outcomes(reviews),
        "component_edge": component_edge(recommendations, reviews),
    }
