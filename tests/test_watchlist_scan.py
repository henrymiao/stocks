import unittest

from tools.stock_skills.models import MarketSnapshot
from tools.stock_skills.watchlist_scan import run_watchlist_scan


def _snapshot(code, change_pct=1.0, turnover=10_000_000.0):
    previous = 100.0
    last = previous * (1.0 + change_pct / 100.0)
    return MarketSnapshot(
        code=code,
        name=code,
        last_price=last,
        open=previous,
        high=max(last, previous),
        low=min(last, previous),
        prev_close=previous,
        volume=100_000,
        turnover=turnover,
        timestamp="2026-07-10T16:10:00-04:00",
    )


class FakeFetcher:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.calls = []

    def get_snapshots(self, codes):
        self.calls.append(list(codes))
        return [self.snapshots[code] for code in codes if code in self.snapshots]


class WatchlistScanTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"code": "US.CORE", "name": "Core", "tier": "core", "priority": 100, "strategy_profiles": ["short", "swing"], "benchmark": "US.SPY", "underlying_proxy": None, "tags": ["holding"]},
            {"code": "US.FAST", "name": "Fast", "tier": "thematic", "priority": 70, "strategy_profiles": ["short", "swing"], "benchmark": "US.SPY", "underlying_proxy": None, "tags": ["ai"]},
            {"code": "US.SLOW", "name": "Slow", "tier": "thematic", "priority": 50, "strategy_profiles": ["short", "swing"], "benchmark": "US.SPY", "underlying_proxy": None, "tags": ["ai"]},
            {"code": "US.SPY", "name": "SPY", "tier": "proxy", "priority": 25, "strategy_profiles": [], "benchmark": "US.SPY", "underlying_proxy": None, "tags": ["index"]},
            {"code": "US.NEW", "name": "New", "tier": "discovery", "priority": 25, "strategy_profiles": ["short"], "benchmark": "US.SPY", "underlying_proxy": None, "tags": ["discovery"]},
        ]

    def test_one_batch_snapshot_is_shared_and_ranked_by_profile(self):
        fetcher = FakeFetcher(
            {
                "US.CORE": _snapshot("US.CORE", 0.5),
                "US.FAST": _snapshot("US.FAST", 4.0),
                "US.SLOW": _snapshot("US.SLOW", -1.0),
                "US.SPY": _snapshot("US.SPY", 1.0),
                "US.NEW": _snapshot("US.NEW", 8.0),
            }
        )

        result = run_watchlist_scan(self.entries, fetcher, deep_top=1, deep_horizons=())

        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual(set(fetcher.calls[0]), {entry["code"] for entry in self.entries})
        self.assertEqual(result["rankings"]["short"][0]["code"], "US.FAST")
        self.assertEqual(result["rankings"]["swing"][0]["code"], "US.FAST")
        discovery = next(row for row in result["candidates"] if row["code"] == "US.NEW")
        self.assertEqual(discovery["treatment"], "snapshot-only")
        self.assertNotIn("recommendation", discovery)

    def test_shared_context_codes_are_included_in_the_same_batch(self):
        snapshots = {
            "US.CORE": _snapshot("US.CORE"),
            "US.FAST": _snapshot("US.FAST"),
            "US.SLOW": _snapshot("US.SLOW"),
            "US.SPY": _snapshot("US.SPY"),
            "US.NEW": _snapshot("US.NEW"),
            "US.VIXY": _snapshot("US.VIXY"),
            "US.TLT": _snapshot("US.TLT"),
        }
        fetcher = FakeFetcher(snapshots)

        run_watchlist_scan(
            self.entries,
            fetcher,
            deep_horizons=(),
            context_codes=("US.VIXY", "US.TLT"),
        )

        self.assertEqual(len(fetcher.calls), 1)
        self.assertIn("US.VIXY", fetcher.calls[0])
        self.assertIn("US.TLT", fetcher.calls[0])

    def test_deep_analysis_runs_for_core_and_only_top_thematic(self):
        fetcher = FakeFetcher(
            {
                "US.CORE": _snapshot("US.CORE", 0.5),
                "US.FAST": _snapshot("US.FAST", 4.0),
                "US.SLOW": _snapshot("US.SLOW", -1.0),
                "US.SPY": _snapshot("US.SPY", 1.0),
                "US.NEW": _snapshot("US.NEW", 8.0),
            }
        )
        calls = []

        def analyze(entry, horizon, shared_context):
            calls.append((entry["code"], horizon, set(shared_context)))
            return {"code": entry["code"], "strategy_assessment": {"horizon": horizon}}

        result = run_watchlist_scan(
            self.entries,
            fetcher,
            analyzer=analyze,
            deep_top=1,
            deep_horizons=("short",),
        )

        self.assertEqual([call[:2] for call in calls], [("US.CORE", "short"), ("US.FAST", "short")])
        self.assertIn("US.SPY", calls[0][2])
        self.assertEqual(len(result["deep_analysis"]), 2)
        slow = next(row for row in result["candidates"] if row["code"] == "US.SLOW")
        self.assertEqual(slow["treatment"], "rank-only")

    def test_missing_and_illiquid_snapshots_are_rejected_without_recommendation(self):
        fetcher = FakeFetcher(
            {
                "US.CORE": _snapshot("US.CORE", 0.5),
                "US.FAST": _snapshot("US.FAST", 4.0, turnover=0.0),
                "US.SPY": _snapshot("US.SPY", 1.0),
            }
        )
        calls = []

        result = run_watchlist_scan(
            self.entries,
            fetcher,
            analyzer=lambda entry, horizon, shared: calls.append(entry["code"]) or {},
            deep_top=2,
            deep_horizons=("short",),
        )

        fast = next(row for row in result["candidates"] if row["code"] == "US.FAST")
        slow = next(row for row in result["candidates"] if row["code"] == "US.SLOW")
        self.assertEqual(fast["filter_status"], "rejected")
        self.assertIn("non-positive-turnover", fast["rejection_reasons"])
        self.assertEqual(slow["filter_status"], "rejected")
        self.assertIn("missing-snapshot", slow["rejection_reasons"])
        self.assertNotIn("US.FAST", calls)
        self.assertNotIn("US.SLOW", calls)

    def test_stale_live_snapshot_is_rejected_before_ranking(self):
        stale = MarketSnapshot(
            "US.FAST", "Fast", 104.0, 100.0, 105.0, 99.0, 100.0, 100_000, 10_000_000.0,
            "2026-07-10T10:00:00-04:00", "2026-07-10T10:20:00-04:00",
        )
        fetcher = FakeFetcher(
            {
                "US.CORE": _snapshot("US.CORE"),
                "US.FAST": stale,
                "US.SLOW": _snapshot("US.SLOW"),
                "US.SPY": _snapshot("US.SPY"),
                "US.NEW": _snapshot("US.NEW"),
            }
        )

        result = run_watchlist_scan(self.entries, fetcher, deep_horizons=())

        fast = next(row for row in result["candidates"] if row["code"] == "US.FAST")
        self.assertEqual(fast["filter_status"], "rejected")
        self.assertIn("stale-snapshot", fast["rejection_reasons"])
        self.assertNotIn("US.FAST", [row["code"] for row in result["rankings"]["short"]])


if __name__ == "__main__":
    unittest.main()
