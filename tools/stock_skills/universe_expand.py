"""Broaden the discovery universes from exchange plate membership.

`discover` is documented as scanning a market before any name reaches the watchlist, but
the three universe files held 27, 23 and 36 members -- a hand-picked list, so "nothing in
that sector qualifies" only ever meant "nothing in that sector was in the list". This
fills them from Futu's own industry plates rather than from memory: a mistyped code would
otherwise enter the identity registry and propagate through every version digest.

Existing sector keys, benchmarks and representatives are preserved and only membership
grows, so the change is additive and the configured structure that already validates stays
intact. Members are ranked by turnover and capped, because an illiquid name would be
rejected by the investability gates anyway and only costs a snapshot to carry.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .futu_fetcher import FutuFetcher


@dataclass(frozen=True)
class SectorPlan:
    """Which exchange plates feed one universe sector."""

    key: str
    plates: tuple[str, ...]
    name: str | None = None
    benchmark: str | None = None
    representative: str | None = None


# Instruments that are not ordinary stocks. The migration types a member from its role
# alone, so a fund landing in a plate would be registered as an ordinary stock.
_FUND_MARKERS = ("ETF", "ETN", "基金", "REIT", "SPDR", "iShares", "指数")


def looks_like_fund(name: str) -> bool:
    upper = name.upper()
    return any(marker.upper() in upper for marker in _FUND_MARKERS)


def fetch_plate_members(
    fetcher: FutuFetcher, plate: str, *, limit: int = 300
) -> list[tuple[str, str]]:
    payload = fetcher._run_json(  # noqa: SLF001 - same private runner the fetcher uses
        [
            fetcher.python_bin,
            fetcher._script("quote", "get_plate_stock.py"),  # noqa: SLF001
            plate,
            "--limit",
            str(limit),
            "--json",
        ]
    )
    return [
        (str(row["code"]), str(row.get("name") or row["code"]))
        for row in (payload.get("data") or [])
        if row.get("code")
    ]


def rank_by_turnover(
    fetcher: FutuFetcher, codes: list[str], *, batch: int = 100, pause: float = 1.0
) -> dict[str, float]:
    """Turnover per code. A code the feed cannot price is dropped, never defaulted.

    A single delisted or suspended code makes the whole batch call fail, so a failed batch
    is halved and retried rather than discarded -- otherwise one bad name silently costs
    the sector every member it was grouped with.

    A failure is also what rate limiting looks like, and splitting on it multiplies the
    call rate exactly when the quota is already gone. Retries therefore back off first:
    without that, the first few sectors consume the quota and every later one silently
    returns nothing, which is how four US sectors and five HK sectors came back empty
    while their plates held hundreds of names.
    """

    turnover: dict[str, float] = {}

    def pull(chunk: list[str], depth: int = 0) -> None:
        if not chunk:
            return
        try:
            for snapshot in fetcher.get_snapshots(chunk):
                if snapshot.turnover > 0:
                    turnover[snapshot.code] = snapshot.turnover
        except Exception:
            if len(chunk) == 1 or depth >= 4:
                return
            if pause > 0:
                time.sleep(min(8.0, 2.0 ** depth))
            middle = len(chunk) // 2
            pull(chunk[:middle], depth + 1)
            pull(chunk[middle:], depth + 1)
        else:
            if pause > 0:
                time.sleep(pause)

    for start in range(0, len(codes), batch):
        pull(codes[start : start + batch])
    return turnover


def expand_universe(
    path: str | Path,
    plans: list[SectorPlan],
    fetcher: FutuFetcher,
    *,
    per_sector: int = 35,
) -> dict:
    """Return the universe record with membership broadened. Does not write."""

    record = json.loads(Path(path).read_text(encoding="utf-8"))
    market_prefixes = {"CN": ("SH.", "SZ."), "HK": ("HK.",), "US": ("US.",)}[record["market"]]
    by_key = {sector["key"]: sector for sector in record["sectors"]}
    taken = {member["code"] for sector in record["sectors"] for member in sector["members"]}
    taken |= {sector["benchmark"] for sector in record["sectors"]}

    for plan in plans:
        candidates: list[tuple[str, str]] = []
        for plate in plan.plates:
            try:
                candidates.extend(fetch_plate_members(fetcher, plate))
            except Exception:
                continue
        fresh = [
            (code, name)
            for code, name in candidates
            if code.startswith(market_prefixes)
            and code not in taken
            and not looks_like_fund(name)
        ]
        # Dedupe while keeping first appearance, then keep the most liquid.
        seen: set[str] = set()
        unique = [(c, n) for c, n in fresh if not (c in seen or seen.add(c))]
        turnover = rank_by_turnover(fetcher, [c for c, _ in unique])
        ranked = sorted(
            ((c, n) for c, n in unique if c in turnover),
            key=lambda item: -turnover[item[0]],
        )

        sector = by_key.get(plan.key)
        if sector is None:
            if not (plan.name and plan.benchmark and plan.representative):
                raise ValueError(f"New sector {plan.key} needs name, benchmark and representative")
            # Every configured sector is represented by a tradable proxy that is itself a
            # member, so a new sector is seeded with its ETF before constituents are added.
            sector = {
                "key": plan.key,
                "name": plan.name,
                "representative": plan.representative,
                "benchmark": plan.benchmark,
                "members": [
                    {
                        "code": plan.representative,
                        "name": plan.representative.split(".", 1)[-1],
                        "role": "etf",
                        "weight": 1.0,
                        "shared_identity": None,
                    }
                ],
            }
            taken.add(plan.representative)
            record["sectors"].append(sector)
            by_key[plan.key] = sector

        room = max(0, per_sector - len(sector["members"]))
        for code, name in ranked[:room]:
            sector["members"].append(
                {
                    "code": code,
                    "name": name,
                    "role": "constituent",
                    "weight": 1.0,
                    "shared_identity": None,
                }
            )
            taken.add(code)

        representative = sector["representative"]
        if representative not in {m["code"] for m in sector["members"]}:
            raise ValueError(f"{plan.key} representative {representative} is not a member")

    return record
