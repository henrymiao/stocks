"""Reverse-solve the price at which a blocked candidate would clear its price gate.

A rejection alone ("resistance-room failed") tells you nothing actionable — it is
the same output whether the name is 1% or 30% away from being buyable. This module
answers the follow-up question: *at what price would it pass?*

Only the resistance-room gate is a function of price, so only it can be solved.
The remaining gates (trend regime, volume, market regime, weekly alignment) are
reported as conditions that must clear separately — a price alert is not a licence
to skip them.
"""

from __future__ import annotations

from dataclasses import dataclass


# Gates whose outcome moves with the entry price; everything else needs its own
# confirmation and cannot be waited into by price alone.
PRICE_SOLVABLE_GATES = ("resistance-room",)


@dataclass(frozen=True)
class EntryZone:
    code: str
    horizon: str
    current_price: float
    entry_ceiling: float | None
    distance_pct: float | None
    resistance: float | None
    stop: float | None
    minimum_resistance_r: float
    blocking_gates: tuple[str, ...]
    non_price_gates: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def actionable(self) -> bool:
        """True when a pullback alone would clear every gate that price can fix."""
        return self.entry_ceiling is not None and not self.non_price_gates


def resistance_room_ceiling(
    resistance: float,
    stop: float,
    minimum_resistance_r: float,
) -> float | None:
    """Highest entry price at which (resistance - price) / (price - stop) >= minimum.

    Solving the gate inequality for price:
        (R - P) / (P - S) >= m
        R - P >= m * (P - S)          [P > S, so the denominator is positive]
        R + m*S >= P * (1 + m)
        P <= (R + m*S) / (1 + m)
    """
    if minimum_resistance_r <= 0 or resistance <= stop:
        return None
    ceiling = (resistance + minimum_resistance_r * stop) / (1.0 + minimum_resistance_r)
    if ceiling <= stop:
        # The structure is too tight to ever satisfy the gate: any price with room
        # above it sits below the stop. Report no zone rather than a bogus number.
        return None
    return round(ceiling, 4)


def build_entry_zone(
    *,
    code: str,
    horizon: str,
    current_price: float,
    resistance_levels: list[float],
    stop: float | None,
    minimum_resistance_r: float,
    gates_failed: tuple[str, ...] | list[str],
    gates_missing: tuple[str, ...] | list[str] = (),
) -> EntryZone:
    """Describe how far a candidate is from clearing its price-based gate."""
    blocking = tuple(gates_failed)
    non_price = tuple(
        gate
        for gate in blocking
        if gate not in PRICE_SOLVABLE_GATES
    )
    notes: list[str] = []

    overhead = sorted(level for level in resistance_levels if level > current_price)
    resistance = overhead[0] if overhead else None
    ceiling: float | None = None
    distance: float | None = None

    if "resistance-room" not in blocking:
        notes.append("resistance-room already clears at the current price.")
    elif resistance is None:
        notes.append("No overhead resistance recorded; the gate needs a confirmed breakout, not a pullback.")
    elif stop is None or stop <= 0:
        notes.append("No valid stop, so no risk-per-share and no solvable zone.")
    else:
        ceiling = resistance_room_ceiling(resistance, stop, minimum_resistance_r)
        if ceiling is None:
            notes.append("Structure too tight: no price satisfies the gate above the stop.")
        else:
            distance = round((ceiling / current_price - 1.0) * 100, 2)

    if non_price:
        notes.append(
            "A pullback alone is not enough — these still need their own confirmation: "
            + ", ".join(non_price)
        )
    return EntryZone(
        code=code,
        horizon=horizon,
        current_price=round(current_price, 4),
        entry_ceiling=ceiling,
        distance_pct=distance,
        resistance=resistance,
        stop=stop,
        minimum_resistance_r=minimum_resistance_r,
        blocking_gates=blocking,
        non_price_gates=non_price,
        notes=tuple(notes),
    )


def entry_zone_from_recommendation(payload: dict, minimum_resistance_r: float | None = None) -> EntryZone | None:
    """Build a zone straight from a serialized recommendation payload."""
    assessment = payload.get("strategy_assessment") or {}
    exit_plan = payload.get("exit_plan") or {}
    price = payload.get("entry_price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    horizon = str(assessment.get("horizon") or "short")
    if minimum_resistance_r is None:
        minimum_resistance_r = 2.5 if horizon == "swing" else 1.8
    stop = exit_plan.get("initial_stop")
    return build_entry_zone(
        code=str(payload.get("code") or ""),
        horizon=horizon,
        current_price=float(price),
        resistance_levels=[
            float(level)
            for level in (payload.get("resistance_levels") or [])
            if isinstance(level, (int, float))
        ],
        stop=float(stop) if isinstance(stop, (int, float)) else None,
        minimum_resistance_r=float(minimum_resistance_r),
        gates_failed=tuple(assessment.get("gates_failed") or ()),
        gates_missing=tuple(assessment.get("gates_missing") or ()),
    )
