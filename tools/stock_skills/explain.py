"""Render a recommendation as plain Chinese.

The JSON a recommendation carries is complete but not readable: field names are English
technical terms, scores arrive without the weights that produced them, and the answer to
"can I open a position" sits next to the answer to "what do I do with the one I have" with
nothing marking them as different questions. In one working session the same few questions
came up eight times — what `probe` means, what the number next to it is, why a portfolio
heat figure appeared in what was meant to be a quality read.

This module answers those once, in the output itself. It performs no analysis: everything
here is a re-presentation of fields already decided elsewhere, so it can never disagree
with the record it renders.
"""

from __future__ import annotations

from typing import Any, Mapping

CLUSTER_LABELS = {
    "thesis": "论点",
    "market_behavior": "价格行为",
    "environment": "宏观背景",
    "risk_fit": "风险适配",
}

HORIZON_LABELS = {
    "short": "1–3 天",
    "swing": "1–4 周",
    "core": "多季度",
}

ENTRY_LABELS = {
    "enter": ("可建仓", "全部门通过，按风险测算的完整仓位"),
    "add": ("可加仓", "全部门通过"),
    "probe": ("仅小额试探", "证据只够一次封顶的试探，不够完整建仓"),
    "watch": ("观察", "有证据缺失，等数据补齐再谈"),
    "reject": ("否决", "有门失守或被方法层限制"),
}

LABEL_LABELS = {
    "hold": "继续持有",
    "trim-on-strength": "强势时可减一部分",
    "risk-reduce": "降低风险",
    "avoid": "回避",
    "strong-watch": "重点观察",
    "low-buy-zone": "低吸区",
}

POSITION_LABELS = {
    "hold": "继续持有",
    "add": "可加仓",
    "trim": "减仓",
    "partial-exit": "部分退出",
    "full-exit": "全部退出",
}

GATE_LABELS = {
    "data-confidence": "数据可信度",
    "structured-exit-plan": "退出计划完整",
    "session-ready": "交易时段就绪",
    "trend-regime": "趋势方向",
    "relative-strength": "相对强度",
    "volume-confirmation": "量能确认",
    "entry-trigger": "入场触发",
    "resistance-room": "阻力空间",
    "market-regime": "市场机制",
    "liquidity": "流动性",
    "portfolio-heat": "组合风险额度",
    "independent-clusters": "独立证据数",
    "weekly-alignment": "周线对齐",
    "event-window": "事件窗口",
    "underlying-confirmation": "杠杆标的确认",
}

# The one gate that is a function of price, so the one a lower entry can fix.
PRICE_SOLVABLE_GATES = frozenset({"resistance-room"})


def _fmt(value: object, digits: int = 2) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return "—"


def _gate_line(names: list[str]) -> str:
    return "、".join(GATE_LABELS.get(name, name) for name in names) or "无"


def explain_recommendation(
    record: Mapping[str, Any], *, cost_basis: float | None = None, shares: float | None = None
) -> str:
    """Format one recommendation. `cost_basis`/`shares` come from the book, not the record."""

    strategy = record.get("strategy_assessment") or {}
    exit_plan = record.get("exit_plan") or {}
    clusters = strategy.get("factor_clusters") or {}
    horizon = strategy.get("horizon") or record.get("horizon") or "—"
    price = record.get("entry_price")
    lines: list[str] = []

    header = f"{record.get('code','')} {record.get('name','')} · {horizon} 轨道"
    if horizon in HORIZON_LABELS:
        header += f"（{HORIZON_LABELS[horizon]}）"
    lines.append(header)

    if cost_basis and price:
        pnl = (price - cost_basis) / cost_basis * 100
        holding = f"持仓 {shares:,.0f} 股 " if shares else "持仓 "
        lines.append(f"{holding}@{_fmt(cost_basis)} → 现价 {_fmt(price)}，浮动 {pnl:+.1f}%")
    elif price:
        lines.append(f"现价 {_fmt(price)}")

    quality = record.get("data_quality") or {}
    if quality.get("session_phase") in {"pre-open", "intraday", "closed"}:
        lines.append(f"⚠ 数据时段：{quality['session_phase']}，读数为临时值，收盘后需重判")

    lines.append("")
    lines.append("▎结论")
    label = record.get("label")
    if label:
        lines.append(f"  已有仓位：{LABEL_LABELS.get(label, label)}（{label}）")
    position_decision = strategy.get("position_decision")
    if position_decision:
        lines.append(
            f"  持仓动作：{POSITION_LABELS.get(position_decision, position_decision)}"
            f"（{position_decision}）"
        )
    entry = strategy.get("entry_decision")
    if entry:
        name, why = ENTRY_LABELS.get(entry, (entry, ""))
        allocation = strategy.get("suggested_allocation_pct")
        size = f"，上限 {allocation}% NAV" if allocation else ""
        lines.append(f"  要不要新建/加仓：{name}{size} —— {why}")
    lines.append(f"  综合分 setup={strategy.get('setup_score','—')}")

    lines.append("")
    lines.append("▎为什么是这个结论")
    for cluster, score in sorted(clusters.items(), key=lambda kv: -kv[1]):
        mark = "✓" if score >= 60 else "~"
        note = "  ← 本轨道权重最高，最关键" if cluster == "thesis" and horizon == "core" else ""
        lines.append(f"  {mark} {CLUSTER_LABELS.get(cluster, cluster):<6}{score:>7.2f}{note}")

    failed = list(strategy.get("gates_failed") or [])
    missing = list(strategy.get("gates_missing") or [])
    if failed:
        solvable = [g for g in failed if g in PRICE_SOLVABLE_GATES]
        blocking = [g for g in failed if g not in PRICE_SOLVABLE_GATES]
        if blocking:
            lines.append(f"  ✗ 失守（价格解决不了）：{_gate_line(blocking)}")
        if solvable:
            lines.append(f"  ✗ 失守（等更低的价格即可）：{_gate_line(solvable)}")
    if missing:
        lines.append(f"  ? 证据缺失：{_gate_line(missing)}")

    restrictions = (record.get("method_assessment") or {}).get("restrictions") or []
    for restriction in restrictions:
        lines.append(
            f"  ! 方法层限制：{restriction.get('code')} → {restriction.get('effect')}"
        )

    lines.append("")
    lines.append("▎盯这几个数就够")
    invalidation = exit_plan.get("structural_invalidation") or record.get("invalidation_level")
    if invalidation:
        gap = f"（距现价 {(price - invalidation) / invalidation * 100:+.1f}%）" if price else ""
        lines.append(f"  {_fmt(invalidation):>10}  跌破 = 论点的价格底线{gap}")
    stop = exit_plan.get("initial_stop")
    if stop:
        lines.append(f"  {_fmt(stop):>10}  止损")
    for target in exit_plan.get("targets") or []:
        lines.append(
            f"  {_fmt(target.get('price')):>10}  {target.get('name')} 目标"
            f"（{target.get('r_multiple')}R，减 {float(target.get('fraction', 0)) * 100:.0f}%）"
        )
    risk_per_share = exit_plan.get("risk_per_share")
    if risk_per_share and cost_basis and price:
        lines.append(f"  {(price - cost_basis) / risk_per_share:>9.2f}R  当前进展")
    time_stop = exit_plan.get("time_stop") or {}
    if time_stop.get("sessions"):
        lines.append(
            f"  {time_stop['sessions']:>8} 场  时间止损"
            f"（进展 <{time_stop.get('progress_r')}R 则 {time_stop.get('action')}）"
        )

    lines.append("")
    lines.append("注：「要不要新建/加仓」与已有持仓无关；已有仓位只看「已有仓位」和「持仓动作」两行。")
    return "\n".join(lines)
