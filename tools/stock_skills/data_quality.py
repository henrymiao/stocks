from __future__ import annotations

from typing import Mapping, Set

from .models import DataQuality


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
CRITICAL_COMPONENTS = {"trend", "position_fit"}
ENTRY_CONFIDENCE_THRESHOLD = 0.80


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
