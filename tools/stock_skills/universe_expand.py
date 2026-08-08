"""Broaden the discovery universes from exchange plate membership.

`discover` is documented as scanning a market before any name reaches the watchlist, but
the three universe files held 27, 23 and 36 members -- a hand-picked list, so "nothing in
that sector qualifies" only ever meant "nothing in that sector was in the list". This
fills them from Futu's own industry plates rather than from memory: a mistyped code would
otherwise enter the identity registry and propagate through every version digest.

Existing sector keys, benchmarks and representatives are preserved, and the configured
structure that already validates stays intact. Membership itself is not additive: a member
whose tape has dried up is evicted, because carrying it costs a snapshot and a feature
computation every session and it can never survive the investability gates anyway.

Liquidity is measured as the median turnover over the last completed sessions, not the
last one. Ranking on a single session is what filled the HK universe with names that could
not be traded -- 141 of its 210 members turned over less than HK$100m a day, two thirds of
the universe, because one busy session was enough to rank a shell into the top 35. The
floor is the same one `discover` applies, so the build can no longer hand discovery a name
discovery will refuse. Funds are exempt for the same reason they are exempt there: an ETF
is quoted against the basket it holds, so its own tape understates what can be traded.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .discovery_engine import MINIMUM_MEDIAN_TURNOVER
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


def median_daily_turnover(
    fetcher: FutuFetcher,
    codes: list[str],
    *,
    sessions: int = 20,
    pause: float = 0.2,
) -> dict[str, float]:
    """Median daily turnover per code. A code the feed cannot price is absent, not zero.

    One call per code, so callers shortlist first rather than asking for a whole plate.
    """

    medians: dict[str, float] = {}
    for code in codes:
        try:
            bars = fetcher.get_daily_bars(code, num=sessions)
        except Exception:
            continue
        values = sorted(bar.turnover for bar in bars[-sessions:] if bar.turnover > 0)
        if not values:
            continue
        middle = len(values) // 2
        medians[code] = (
            values[middle]
            if len(values) % 2
            else (values[middle - 1] + values[middle]) / 2.0
        )
        if pause > 0:
            time.sleep(pause)
    return medians


def _is_fund_member(member: dict) -> bool:
    return member.get("role") in {"etf", "index"}


def expand_universe(
    path: str | Path,
    plans: list[SectorPlan],
    fetcher: FutuFetcher,
    *,
    per_sector: int = 35,
    minimum_median_turnover: float | None = None,
    liquidity_sessions: int = 20,
    shortlist_multiple: int = 4,
) -> dict:
    """Return the universe record with membership rebuilt. Does not write.

    `minimum_median_turnover` defaults to the floor `discover` enforces for this market;
    pass 0 to rank on turnover without evicting or excluding anything.
    """

    record = json.loads(Path(path).read_text(encoding="utf-8"))
    market = record["market"]
    market_prefixes = {"CN": ("SH.", "SZ."), "HK": ("HK.",), "US": ("US.",)}[market]
    floor = (
        MINIMUM_MEDIAN_TURNOVER.get(market, 0.0)
        if minimum_median_turnover is None
        else minimum_median_turnover
    )

    # Evict first, so the plate fill can see the room it opens up. A fund keeps its place,
    # and so does a name the feed cannot price -- absence of evidence is not illiquidity.
    evicted: dict[str, float] = {}
    if floor > 0:
        held = [
            member["code"]
            for sector in record["sectors"]
            for member in sector["members"]
            if not _is_fund_member(member)
        ]
        measured = median_daily_turnover(
            fetcher, held, sessions=liquidity_sessions
        )
        evicted = {
            code: value for code, value in measured.items() if value < floor
        }
        for sector in record["sectors"]:
            sector["members"] = [
                member
                for member in sector["members"]
                if member["code"] not in evicted
            ]

    by_key = {sector["key"]: sector for sector in record["sectors"]}
    taken = {member["code"] for sector in record["sectors"] for member in sector["members"]}
    taken |= {sector["benchmark"] for sector in record["sectors"]}
    taken |= set(evicted)  # an evicted name must not be re-added by the plate fill

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
        if floor > 0 and room:
            # One session's turnover is cheap but noisy, and a median needs a call per
            # code. So rank on the snapshot to shortlist, then let the median decide the
            # order and who is admitted at all -- a busy session can rank a shell into the
            # top 35, but it cannot hold a median there.
            shortlist = [code for code, _ in ranked[: room * shortlist_multiple]]
            medians = median_daily_turnover(
                fetcher, shortlist, sessions=liquidity_sessions
            )
            admitted = {
                code: value for code, value in medians.items() if value >= floor
            }
            ranked = sorted(
                ((c, n) for c, n in ranked if c in admitted),
                key=lambda item: -admitted[item[0]],
            )

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
