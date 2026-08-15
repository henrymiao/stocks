"""Advance a held position's trailing stop from the book's recorded state.

`exit_engine.next_trailing_stop` has always existed and is monotonic, but nothing ever
called it: `analyze` rebuilt `position_state` from scratch on every run with
`remaining_fraction=1.0` and no previous stop, so a plan was always re-derived for a
position it believed had been opened yesterday and never trimmed. The visible symptom is
a book full of stops still sitting where they were placed days ago while price ran away
from them -- which is also why portfolio heat kept climbing toward its limit without a
single new position being opened.

Without a recorded entry date "highest close since entry" cannot be computed exactly, so
the window is bounded and the result is only ever a *suggestion*: this module never writes
to the book. Raising a stop is a decision with real consequences and stays explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .exit_engine import next_trailing_stop
from .models import KLineBar

# Without an entry date, a long lookback would let a stale high pull the stop above the
# current price. Sixty sessions covers a swing position's realistic life while keeping the
# reference high recent enough to mean something.
TRAILING_LOOKBACK_BARS = 60


@dataclass(frozen=True)
class TrailingSuggestion:
    code: str
    current_stop: float | None
    suggested_stop: float | None
    price: float
    activated: bool
    progress_r: float | None
    reason: str

    @property
    def should_raise(self) -> bool:
        return (
            self.suggested_stop is not None
            and self.current_stop is not None
            and self.suggested_stop > self.current_stop
        )


def suggest_trailing_stop(
    *,
    code: str,
    price: float,
    cost_basis: float,
    current_stop: float | None,
    previous_trailing_stop: float | None,
    bars: list[KLineBar],
    atr: float | None,
    atr_multiple: float,
    activation_r: float | None,
    risk_per_share: float | None,
    lookback_sessions: int = TRAILING_LOOKBACK_BARS,
    session_phase: str | None = None,
    entry_date: str | None = None,
) -> TrailingSuggestion:
    """Suggest where the trailing stop should sit now. Never lowers, never writes.

    Refuses to answer from an unfinished session. A stop derived from an intraday price is
    derived from a number that has not happened yet: written twice from intraday data in
    this book, once for GOOGL and once for Tencent, and both were breached by the close of
    the very session that produced them.
    """

    progress_r = (
        (price - cost_basis) / risk_per_share
        if risk_per_share and risk_per_share > 0
        else None
    )
    base = TrailingSuggestion(
        code=code,
        current_stop=current_stop,
        suggested_stop=None,
        price=price,
        activated=False,
        progress_r=progress_r,
        reason="",
    )

    if session_phase in {"pre-open", "intraday", "midday-break"}:
        return _with(base, reason=f"数据时段 {session_phase}，止损必须用收盘数据计算")

    if activation_r is not None:
        if progress_r is None:
            return _with(base, reason="缺少 1R 口径，无法判断是否达到启动条件")
        if progress_r < activation_r:
            return _with(
                base, reason=f"进展 {progress_r:.2f}R 未达启动线 {activation_r}R，移动止损尚未启动"
            )

    # A trailing stop locks in the best the position actually reached, so the window is
    # the holding period -- not a session count typed in by hand. `trailing_lookback_
    # sessions` was a guess ("GOOGL 约3个月=63场"), and the guess reached back before the
    # entry: JCET was bought 2026-08-03 but its 32-session window still held the
    # 2026-07-01 close of 106.64, a high the position never earned. Subtracting 2.5 ATR
    # from someone else's high is what pushed the stop above the market.
    priced = [bar for bar in bars if bar.low > 0]
    held = _bars_since(priced, entry_date) if entry_date else []
    usable = held if len(held) >= 3 else priced[-max(3, lookback_sessions):]
    if len(usable) < 3 or not atr or atr <= 0:
        return _with(base, reason="K线或 ATR 不足，无法计算")

    suggested = next_trailing_stop(
        previous_stop=previous_trailing_stop,
        prior_two_bar_low=min(usable[-3].low, usable[-2].low),
        highest_close=max(bar.close for bar in usable),
        atr=atr,
        atr_multiple=atr_multiple,
    )
    if suggested >= price:
        # A stale high inside the window can push the stop through the current price. That
        # is an artefact of not knowing the entry date, not a signal to exit at market.
        return _with(
            base,
            activated=True,
            reason=f"算出的止损 {suggested:.2f} 已高于现价，窗口内的旧高点失真，本次不建议",
        )
    return _with(base, suggested_stop=suggested, activated=True, reason="移动止损已启动")


def _bars_since(bars: list[KLineBar], entry_date: str) -> list[KLineBar]:
    """Bars from the entry session onward. Empty when the date is unusable.

    Falling back to the session-count window is deliberate: a position whose entry
    predates the cached history would otherwise get a window of two bars and an
    arbitrarily tight stop.
    """

    try:
        entry = datetime.fromisoformat(entry_date).date()
    except (TypeError, ValueError):
        return []
    kept: list[KLineBar] = []
    for bar in bars:
        try:
            if datetime.fromisoformat(bar.time).date() >= entry:
                kept.append(bar)
        except ValueError:
            continue
    return kept


def _with(base: TrailingSuggestion, **changes) -> TrailingSuggestion:
    from dataclasses import replace

    return replace(base, **changes)
