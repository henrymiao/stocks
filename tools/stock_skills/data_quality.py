from __future__ import annotations

from collections.abc import Mapping, Set
from datetime import datetime, time
from zoneinfo import ZoneInfo

from .models import CapitalSnapshot, DataQuality, MarketSnapshot


COMPONENTS = (
    "trend",
    "capital_flow",
    "sector",
    "cross_market",
    "macro_risk",
    "market_regime",
    "fundamental",
    "position_fit",
)
CRITICAL_COMPONENTS = frozenset({"trend", "position_fit"})
ENTRY_CONFIDENCE_THRESHOLD = 0.80


def _market_datetime(code: str, value: str) -> datetime | None:
    prefix = code.split(".", 1)[0].upper()
    timezone = ZoneInfo("America/New_York" if prefix == "US" else "Asia/Shanghai")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def detect_stale_components(
    snapshot: MarketSnapshot,
    capital: CapitalSnapshot | None,
    session_phase: str,
) -> frozenset[str]:
    """Identify stale price/flow evidence using market update time vs capture time.

    Previous-session closes are expected during pre-open/weekends, so they are not
    treated as stale. During a live session an update older than 15 minutes blocks the
    critical trend input; after the close, a same-day update must reach near the regular
    close. Capital receives a wider 30-minute live tolerance.
    """
    if not snapshot.captured_at or session_phase in {"pre-open", "closed"}:
        return frozenset()
    captured = _market_datetime(snapshot.code, snapshot.captured_at)
    observed = _market_datetime(snapshot.code, snapshot.timestamp)
    if captured is None or observed is None or observed > captured:
        return frozenset()

    prefix = snapshot.code.split(".", 1)[0].upper()
    stale: set[str] = set()
    if session_phase in {"intraday", "midday-break", "continuous"}:
        if (captured - observed).total_seconds() > 15 * 60:
            stale.add("trend")
    elif session_phase == "after-close":
        market_close = time(16) if prefix in {"US", "HK"} else time(15)
        close_floor_minutes = market_close.hour * 60 + market_close.minute - 30
        observed_minutes = observed.hour * 60 + observed.minute
        if observed.date() != captured.date() or observed_minutes < close_floor_minutes:
            stale.add("trend")

    if capital is not None:
        capital_time = _market_datetime(snapshot.code, capital.timestamp)
        if capital_time is not None:
            if session_phase in {"intraday", "midday-break", "continuous"}:
                if (captured - capital_time).total_seconds() > 30 * 60:
                    stale.add("capital_flow")
            elif session_phase == "after-close":
                market_close = time(16) if prefix in {"US", "HK"} else time(15)
                close_floor_minutes = market_close.hour * 60 + market_close.minute - 30
                capital_minutes = capital_time.hour * 60 + capital_time.minute
                if capital_time.date() != captured.date() or capital_minutes < close_floor_minutes:
                    stale.add("capital_flow")
    return frozenset(stale)


def assess_data_quality(
    availability: Mapping[str, bool],
    session_phase: str,
    stale_components: Set[str] | None = None,
) -> DataQuality:
    component_names = set(COMPONENTS)
    unknown_availability = set(availability) - component_names
    if unknown_availability:
        raise ValueError(
            f"Unknown availability components: {', '.join(sorted(unknown_availability))}"
        )

    stale_names = set(stale_components or ())
    unknown_stale = stale_names - component_names
    if unknown_stale:
        raise ValueError(f"Unknown stale components: {', '.join(sorted(unknown_stale))}")

    available = tuple(
        component for component in COMPONENTS if availability.get(component, False)
    )
    missing = tuple(
        component for component in COMPONENTS if not availability.get(component, False)
    )
    stale = tuple(
        component
        for component in COMPONENTS
        if component in stale_names and component in available
    )

    confidence = round(
        max(
            0.0,
            min(1.0, (len(available) - 0.5 * len(stale)) / len(COMPONENTS)),
        ),
        4,
    )
    entry_eligible = (
        confidence >= ENTRY_CONFIDENCE_THRESHOLD
        and not CRITICAL_COMPONENTS.intersection(missing)
        and not CRITICAL_COMPONENTS.intersection(stale)
    )

    return DataQuality(
        confidence=confidence,
        available_components=available,
        missing_components=missing,
        stale_components=stale,
        session_phase=session_phase,
        entry_eligible=entry_eligible,
    )
