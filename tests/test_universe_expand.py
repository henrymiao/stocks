import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.models import KLineBar, MarketSnapshot
from tools.stock_skills.universe import universe_from_record
from tools.stock_skills.universe_expand import (
    SectorPlan,
    expand_universe,
    looks_like_fund,
    median_daily_turnover,
    rank_by_turnover,
)


def _kline(turnover):
    return KLineBar(
        time="2026-08-07", open=10.0, high=10.0, low=10.0, close=10.0,
        volume=1000, turnover=turnover,
    )


def _snapshot(code, turnover):
    return MarketSnapshot(
        code=code, name=code, last_price=10.0, open=10.0, high=10.0, low=10.0,
        prev_close=10.0, volume=1000, turnover=turnover,
        timestamp="2026-08-06T16:00:00-04:00",
    )


class FakeFetcher:
    """Stands in for OpenD. `poison` fails any batch containing it, like a delisted code."""

    def __init__(self, plates, turnovers, poison=None):
        self.plates = plates
        self.turnovers = turnovers
        self.poison = poison
        self.batch_sizes = []

    def get_snapshots(self, codes):
        self.batch_sizes.append(len(codes))
        if self.poison and self.poison in codes:
            raise RuntimeError("OpenD rejected the batch")
        return [_snapshot(c, self.turnovers[c]) for c in codes if c in self.turnovers]


def _universe(path, sectors):
    payload = {
        "schema_version": "opportunity-universe-v2",
        "market": "US",
        "as_of": "2026-07-21T16:00:00-04:00",
        "published_at": "2026-08-03T18:00:00-04:00",
        "identity_registry_version": "identity:test",
        "sectors": sectors,
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def _member(code, role="constituent"):
    # `security_id`/`member_from` as a real v2 file carries them, so a record built from
    # existing members alone can be handed straight back to the loader. Members the plate
    # fill appends are stamped later, by `foundation_migrate`.
    return {
        "code": code, "name": code, "role": role, "weight": 1.0, "shared_identity": None,
        "security_id": f"listing:{code}", "member_from": "2026-07-21T16:00:00-04:00",
    }


class RankByTurnoverTests(unittest.TestCase):
    def test_a_failing_batch_is_halved_rather_than_dropped(self):
        codes = [f"US.S{i}" for i in range(8)]
        turnovers = {c: float(100 - i) for i, c in enumerate(codes)}
        fetcher = FakeFetcher({}, turnovers, poison="US.S3")

        result = rank_by_turnover(fetcher, codes, batch=8, pause=0)

        # Everything except the poisoned code survives: without the split, one bad name
        # would have cost the sector all eight.
        self.assertEqual(set(result), set(codes) - {"US.S3"})
        self.assertGreater(len(fetcher.batch_sizes), 1)

    def test_codes_the_feed_cannot_price_are_dropped_not_defaulted(self):
        fetcher = FakeFetcher({}, {"US.A": 100.0})
        self.assertEqual(
            rank_by_turnover(fetcher, ["US.A", "US.MISSING"], pause=0), {"US.A": 100.0}
        )


def _run(path, plans, fetcher, *, per_sector=35, floor=0.0):
    """Build with the network stubbed and the sleeps removed.

    `floor` defaults to 0 so the membership and structure cases do not pay a K-line call
    per code; the floor has its own tests.
    """

    import tools.stock_skills.universe_expand as mod

    original_plate = mod.fetch_plate_members
    original_rank = mod.rank_by_turnover
    original_median = mod.median_daily_turnover
    mod.fetch_plate_members = lambda f, plate, limit=300: fetcher.fetch(plate)
    mod.rank_by_turnover = lambda f, c, **kw: original_rank(f, c, pause=0)
    mod.median_daily_turnover = lambda f, c, **kw: original_median(
        f, c, pause=0, **{k: v for k, v in kw.items() if k != "pause"}
    )
    try:
        return expand_universe(
            path, plans, fetcher, per_sector=per_sector, minimum_median_turnover=floor
        )
    finally:
        mod.fetch_plate_members = original_plate
        mod.rank_by_turnover = original_rank
        mod.median_daily_turnover = original_median


class ExpandUniverseTests(unittest.TestCase):
    def _fetcher(self):
        plates = {"P1": [("US.NEW1", "New One"), ("US.NEW2", "New Two"), ("US.ETFX", "Big ETF")]}
        turnovers = {"US.NEW1": 50.0, "US.NEW2": 900.0}
        fetcher = FakeFetcher(plates, turnovers)
        fetcher.fetch = lambda plate: plates.get(plate, [])
        return fetcher

    def test_membership_grows_by_turnover_and_existing_structure_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [{
                "key": "semis", "name": "Semis", "representative": "US.SMH",
                "benchmark": "US.QQQ", "members": [_member("US.SMH", "etf")],
            }])

            record = _run(path, [SectorPlan("semis", ("P1",))], self._fetcher())
            sector = record["sectors"][0]
            codes = [m["code"] for m in sector["members"]]

            self.assertEqual(sector["benchmark"], "US.QQQ")
            self.assertEqual(sector["representative"], "US.SMH")
            self.assertEqual(codes[0], "US.SMH")           # existing member kept, and first
            self.assertEqual(codes[1:], ["US.NEW2", "US.NEW1"])  # most liquid first
            self.assertNotIn("US.ETFX", codes)             # funds filtered out

    def test_a_new_sector_is_seeded_with_its_representative(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [{
                "key": "semis", "name": "Semis", "representative": "US.SMH",
                "benchmark": "US.QQQ", "members": [_member("US.SMH", "etf")],
            }])

            record = _run(
                path,
                [SectorPlan(
                    "metals", ("P1",), name="Metals",
                    benchmark="US.SPY", representative="US.GDX",
                )],
                self._fetcher(),
            )
            metals = next(s for s in record["sectors"] if s["key"] == "metals")

            self.assertEqual(metals["members"][0]["code"], "US.GDX")
            self.assertEqual(metals["members"][0]["role"], "etf")
            self.assertIn("US.NEW2", [m["code"] for m in metals["members"]])

    def test_a_new_sector_without_a_representative_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [{
                "key": "semis", "name": "Semis", "representative": "US.SMH",
                "benchmark": "US.QQQ", "members": [_member("US.SMH", "etf")],
            }])
            with self.assertRaisesRegex(ValueError, "needs name, benchmark and representative"):
                _run(path, [SectorPlan("metals", ("P1",))], self._fetcher())

    def test_a_code_already_held_elsewhere_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [
                {"key": "semis", "name": "Semis", "representative": "US.SMH",
                 "benchmark": "US.QQQ", "members": [_member("US.SMH", "etf"), _member("US.NEW2")]},
                {"key": "other", "name": "Other", "representative": "US.XLI",
                 "benchmark": "US.SPY", "members": [_member("US.XLI", "etf")]},
            ])
            record = _run(path, [SectorPlan("other", ("P1",))], self._fetcher())
            other = next(s for s in record["sectors"] if s["key"] == "other")
            self.assertNotIn("US.NEW2", [m["code"] for m in other["members"]])

    def test_per_sector_cap_counts_existing_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [{
                "key": "semis", "name": "Semis", "representative": "US.SMH",
                "benchmark": "US.QQQ", "members": [_member("US.SMH", "etf")],
            }])
            record = _run(path, [SectorPlan("semis", ("P1",))], self._fetcher(), per_sector=2)
            self.assertEqual(len(record["sectors"][0]["members"]), 2)


class LiquidityFloorTests(unittest.TestCase):
    """The build must not hand `discover` a name `discover` will refuse.

    Ranking on one session filled the HK universe with untradable names: 141 of its 210
    members turned over under HK$100m a day, because a single busy session was enough to
    rank a shell into the top 35 and nothing ever re-checked it.
    """

    def _fetcher(self, turnovers, histories):
        plates = {
            "P1": [("US.THIN", "Thin Name"), ("US.DEEP", "Deep Name"), ("US.ETFX", "Big ETF")]
        }
        fetcher = FakeFetcher(plates, turnovers)
        fetcher.fetch = lambda plate: plates.get(plate, [])
        fetcher.get_daily_bars = lambda code, num=20: [
            _kline(value) for value in histories.get(code, [])
        ]
        return fetcher

    def _universe_with(self, path, members):
        _universe(path, [{
            "key": "semis", "name": "Semis", "representative": "US.SMH",
            "benchmark": "US.QQQ", "members": members,
        }])

    def test_a_member_whose_tape_dried_up_is_evicted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            self._universe_with(
                path,
                [_member("US.SMH", "etf"), _member("US.GONE"), _member("US.STAYS")],
            )
            fetcher = self._fetcher(
                {},
                {"US.GONE": [1_000.0] * 20, "US.STAYS": [5.0e7] * 20},
            )
            record = _run(path, [], fetcher, floor=2.0e7)
            codes = [m["code"] for m in record["sectors"][0]["members"]]
            self.assertNotIn("US.GONE", codes)
            self.assertIn("US.STAYS", codes)

    def test_a_fund_keeps_its_place_on_a_thin_tape(self):
        # An ETF is quoted against its basket, so its own turnover is not the constraint,
        # and the sector representative must survive or the sector loses its proxy.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            self._universe_with(path, [_member("US.SMH", "etf")])
            fetcher = self._fetcher({}, {"US.SMH": [1_000.0] * 20})
            record = _run(path, [], fetcher, floor=2.0e7)
            self.assertEqual(
                [m["code"] for m in record["sectors"][0]["members"]], ["US.SMH"]
            )

    def test_one_busy_session_cannot_rank_a_thin_name_in(self):
        # US.THIN out-turns US.DEEP on the snapshot and would win a single-session rank;
        # its median says otherwise, and only the median admits.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            self._universe_with(path, [_member("US.SMH", "etf")])
            fetcher = self._fetcher(
                {"US.THIN": 9.0e8, "US.DEEP": 3.0e7},
                {
                    "US.THIN": [1.0e6] * 19 + [9.0e8],
                    "US.DEEP": [3.0e7] * 20,
                },
            )
            record = _run(path, [SectorPlan("semis", ("P1",))], fetcher, floor=2.0e7)
            codes = [m["code"] for m in record["sectors"][0]["members"]]
            self.assertIn("US.DEEP", codes)
            self.assertNotIn("US.THIN", codes)

    def test_an_evicted_name_is_not_re_added_by_the_plate_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            self._universe_with(path, [_member("US.SMH", "etf"), _member("US.THIN")])
            fetcher = self._fetcher(
                {"US.THIN": 9.0e8, "US.DEEP": 3.0e7},
                {"US.THIN": [1.0e6] * 20, "US.DEEP": [3.0e7] * 20},
            )
            record = _run(path, [SectorPlan("semis", ("P1",))], fetcher, floor=2.0e7)
            self.assertNotIn(
                "US.THIN", [m["code"] for m in record["sectors"][0]["members"]]
            )

    def test_a_representative_that_is_not_a_fund_survives_a_thin_tape(self):
        # Six representatives are role `leader`, not funds -- HK.00005, HK.00981,
        # HK.01211, HK.01177, HK.02899 and SH.600406. Evicting one writes a universe
        # that `load_universe` then refuses, breaking every downstream command.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [{
                "key": "financials", "name": "Financials", "representative": "US.LEAD",
                "benchmark": "US.SPY",
                "members": [_member("US.LEAD", "leader"), _member("US.STAYS")],
            }])
            fetcher = self._fetcher(
                {}, {"US.LEAD": [1_000.0] * 20, "US.STAYS": [5.0e7] * 20}
            )

            record = _run(path, [], fetcher, floor=2.0e7)

            self.assertIn("US.LEAD", [m["code"] for m in record["sectors"][0]["members"]])
            universe_from_record(record)  # and the result still loads

    def test_an_unplanned_sector_cannot_be_emptied_by_eviction(self):
        # `PLANS_BY_MARKET` covers HK only, so the CN and US sectors reach the structure
        # check through no plan at all -- eviction there used to be unchecked.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [{
                "key": "grid", "name": "Grid", "representative": "US.LEAD",
                "benchmark": "US.SPY",
                "members": [_member("US.LEAD", "leader"), _member("US.GONE")],
            }])
            fetcher = self._fetcher(
                {}, {"US.LEAD": [1_000.0] * 20, "US.GONE": [1_000.0] * 20}
            )

            record = _run(path, [], fetcher, floor=2.0e7)
            members = [m["code"] for m in record["sectors"][0]["members"]]

            self.assertEqual(members, ["US.LEAD"])
            universe_from_record(record)

    def test_a_code_the_feed_cannot_price_is_kept_not_evicted(self):
        # Absence of evidence is not illiquidity; a feed outage must not empty the universe.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            self._universe_with(path, [_member("US.SMH", "etf"), _member("US.QUIET")])
            fetcher = self._fetcher({}, {})
            record = _run(path, [], fetcher, floor=2.0e7)
            self.assertIn(
                "US.QUIET", [m["code"] for m in record["sectors"][0]["members"]]
            )


class FundFilterTests(unittest.TestCase):
    def test_funds_are_recognised_across_naming_conventions(self):
        for name in ("SPDR Gold Shares", "iShares Russell", "半导体ETF", "某某基金", "Vanguard REIT"):
            self.assertTrue(looks_like_fund(name), name)
        for name in ("NVIDIA", "腾讯控股", "Freeport-McMoRan"):
            self.assertFalse(looks_like_fund(name), name)


if __name__ == "__main__":
    unittest.main()
