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

CN_PLANS = [
    # Semiconductors, electronic parts and electronic chemicals: the AI-hardware chain
    # runs from wafers through PCB substrate to assembly, and the sector was carrying 35
    # names while 247 of the 341 most-traded A-shares sat outside the file entirely --
    # CXMT, GigaDevice, Montage, TongFu, Shengyi, Victory Giant, Hua Hong, AMEC, and the
    # holder's own WuXi AppTec and Foxconn Industrial among them.
    # The chain is wafer -> packaging -> substrate -> optical module -> server, and the
    # exchange files those last two under "telecommunication equipment", "computer
    # equipment" and "consumer electronics" rather than semiconductors. Reading the
    # semiconductor plate alone left Zhongji Innolight, Eoptolink and Accelink filed
    # under power-grid equipment, and Foxconn Industrial, Inspur, Sugon and TFC Optical
    # outside the universe entirely -- Foxconn is a CNY 1.35tn company the holder owned.
    # Membership follows the chain, not the exchange's filing convention.
    SectorPlan(
        "semiconductor-ai-hardware",
        (
            "SH.LIST0002",  # 半导体
            "SH.LIST0096",  # 电子元件（覆铜板、PCB 材料）
            "SH.LIST0923",  # 电子化学品
            "SH.LIST0061",  # 通信设备（光模块）
            "SH.LIST0049",  # 计算机设备（AI 服务器）
            "SH.LIST0022",  # 消费电子（工业富联所在）
        ),
    ),
    SectorPlan("innovative-medicine", ("SH.LIST0068",)),
    SectorPlan("financials", ("SH.LIST0948", "SH.LIST0949")),
    SectorPlan("resources-defence", ("SH.LIST0044", "SH.LIST0041", "SH.LIST0958")),
    SectorPlan("power-grid-equipment", ("SH.LIST0006", "SH.LIST0089")),
]

PLANS_BY_MARKET = {"HK": HK_PLANS, "CN": CN_PLANS}

# Industry plates with no configured sector to receive them. Kweichow Moutai, Haier,
# China Telecom and iFlytek are all among the most-traded A-shares and none of them can
# enter the universe until a sector exists, so a scan cannot surface them however they
# trade. Left unhoused deliberately: the owner's mandate is semiconductors and the tech
# chain, and a sector added here would spend a scan slot on something outside it.
CN_UNHOUSED_PLATES = {
    "SH.LIST0001": "White Goods",
    "SH.LIST0943": "Tourism Retail",
    "SH.LIST0961": "Gaming",
    "SH.LIST0088": "Telecommunication Services",
    "SH.LIST0960": "Software Development",
    "SH.LIST0007": "Glass & Fiberglass",
}
