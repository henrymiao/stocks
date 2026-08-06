import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.models import MarketSnapshot
from tools.stock_skills.universe_expand import (
    SectorPlan,
    expand_universe,
    looks_like_fund,
    rank_by_turnover,
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
    return {"code": code, "name": code, "role": role, "weight": 1.0, "shared_identity": None}


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


class ExpandUniverseTests(unittest.TestCase):
    def _fetcher(self):
        plates = {"P1": [("US.NEW1", "New One"), ("US.NEW2", "New Two"), ("US.ETFX", "Big ETF")]}
        turnovers = {"US.NEW1": 50.0, "US.NEW2": 900.0}
        fetcher = FakeFetcher(plates, turnovers)
        fetcher.fetch = lambda plate: plates.get(plate, [])
        return fetcher

    def _run(self, path, plans, per_sector=35):
        import tools.stock_skills.universe_expand as mod

        fetcher = self._fetcher()
        original = mod.fetch_plate_members
        mod.fetch_plate_members = lambda f, plate, limit=300: fetcher.fetch(plate)
        try:
            original_rank = mod.rank_by_turnover
            mod.rank_by_turnover = lambda f, c, **kw: original_rank(f, c, pause=0)
            try:
                return expand_universe(path, plans, fetcher, per_sector=per_sector)
            finally:
                mod.rank_by_turnover = original_rank
        finally:
            mod.fetch_plate_members = original

    def test_membership_grows_by_turnover_and_existing_structure_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [{
                "key": "semis", "name": "Semis", "representative": "US.SMH",
                "benchmark": "US.QQQ", "members": [_member("US.SMH", "etf")],
            }])

            record = self._run(path, [SectorPlan("semis", ("P1",))])
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

            record = self._run(path, [SectorPlan(
                "metals", ("P1",), name="Metals", benchmark="US.SPY", representative="US.GDX"
            )])
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
                self._run(path, [SectorPlan("metals", ("P1",))])

    def test_a_code_already_held_elsewhere_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [
                {"key": "semis", "name": "Semis", "representative": "US.SMH",
                 "benchmark": "US.QQQ", "members": [_member("US.SMH", "etf"), _member("US.NEW2")]},
                {"key": "other", "name": "Other", "representative": "US.XLI",
                 "benchmark": "US.SPY", "members": [_member("US.XLI", "etf")]},
            ])
            record = self._run(path, [SectorPlan("other", ("P1",))])
            other = next(s for s in record["sectors"] if s["key"] == "other")
            self.assertNotIn("US.NEW2", [m["code"] for m in other["members"]])

    def test_per_sector_cap_counts_existing_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            _universe(path, [{
                "key": "semis", "name": "Semis", "representative": "US.SMH",
                "benchmark": "US.QQQ", "members": [_member("US.SMH", "etf")],
            }])
            record = self._run(path, [SectorPlan("semis", ("P1",))], per_sector=2)
            self.assertEqual(len(record["sectors"][0]["members"]), 2)


class FundFilterTests(unittest.TestCase):
    def test_funds_are_recognised_across_naming_conventions(self):
        for name in ("SPDR Gold Shares", "iShares Russell", "半导体ETF", "某某基金", "Vanguard REIT"):
            self.assertTrue(looks_like_fund(name), name)
        for name in ("NVIDIA", "腾讯控股", "Freeport-McMoRan"):
            self.assertFalse(looks_like_fund(name), name)


if __name__ == "__main__":
    unittest.main()
