"""Which exchange plates feed each configured universe sector.

The 2026-08-06 build ran from plate codes typed at a prompt and nothing recorded them, so
the universe could not be rebuilt without guessing which plates it came from -- and the
sector membership is an input to every discovery run and to the content-addressed
`version_id`. These are the plates; the build is now reproducible from the repository.

Plate codes come from Futu's INDUSTRY plate list per market and are stable identifiers,
not names, because the display names are localized and change.
"""

from __future__ import annotations

from .universe_expand import SectorPlan


HK_PLANS = [
    SectorPlan("internet-platforms", ("HK.LIST23364", "HK.LIST1100")),
    SectorPlan("semiconductors", ("HK.LIST1013", "HK.LIST1360", "HK.LIST1055")),
    SectorPlan("automobiles", ("HK.LIST1040", "HK.LIST1041", "HK.LIST1017", "HK.LIST1269")),
    SectorPlan("innovative-medicine", ("HK.LIST1050", "HK.LIST1067", "HK.LIST1086", "HK.LIST1012")),
    SectorPlan("financials", ("HK.LIST1079", "HK.LIST1003", "HK.LIST1068")),
    SectorPlan("resources-high-dividend", ("HK.LIST1084", "HK.LIST1006", "HK.LIST1042", "HK.LIST1044")),
]

PLANS_BY_MARKET = {"HK": HK_PLANS}
