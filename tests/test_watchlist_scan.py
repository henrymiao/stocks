import unittest

from tools.stock_skills.models import MarketSnapshot
from tools.stock_skills.watchlist_scan import _entry_theme, run_watchlist_scan


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
            deep_bottom=0,
            deep_horizons=("short",),
        )

        self.assertEqual([call[:2] for call in calls], [("US.CORE", "short"), ("US.FAST", "short")])
        self.assertIn("US.SPY", calls[0][2])
        self.assertEqual(len(result["deep_analysis"]), 2)
        slow = next(row for row in result["candidates"] if row["code"] == "US.SLOW")
        self.assertEqual(slow["treatment"], "rank-only")

    def test_always_top_and_bottom_candidates_receive_deep_analysis(self):
        entries = self.entries + [
            {
                "code": "US.REDUCED",
                "name": "Reduced",
                "tier": "thematic",
                "priority": 90,
                "strategy_profiles": ["short"],
                "benchmark": "US.SPY",
                "underlying_proxy": None,
                "tags": ["holding"],
                "scan_policy": "always",
                "position_status": "reduced-holding",
            }
        ]
        fetcher = FakeFetcher(
            {
                "US.CORE": _snapshot("US.CORE", 0.5),
                "US.FAST": _snapshot("US.FAST", 4.0),
                "US.SLOW": _snapshot("US.SLOW", -6.0),
                "US.SPY": _snapshot("US.SPY", 1.0),
                "US.NEW": _snapshot("US.NEW", 8.0),
                "US.REDUCED": _snapshot("US.REDUCED", -0.5),
            }
        )
        calls = []

        result = run_watchlist_scan(
            entries,
            fetcher,
            analyzer=lambda entry, horizon, shared: calls.append(entry["code"]) or {},
            deep_top=1,
            deep_bottom=1,
            deep_horizons=("short",),
        )

        self.assertEqual(set(calls), {"US.CORE", "US.REDUCED", "US.FAST", "US.SLOW"})
        reasons = {
            item["code"]: item["selection_reasons"]
            for item in result["selections"]["short"]
        }
        self.assertIn("always", reasons["US.REDUCED"])
        self.assertIn("top", reasons["US.FAST"])
        self.assertIn("bottom", reasons["US.SLOW"])

    def test_negative_deep_bottom_is_rejected(self):
        fetcher = FakeFetcher({})

        with self.assertRaisesRegex(ValueError, "deep_bottom"):
            run_watchlist_scan(self.entries, fetcher, deep_bottom=-1)

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


class ThemeQuotaTests(unittest.TestCase):
    """Momentum ranking starves low-volatility themes; the quota is the counterweight."""

    def setUp(self):
        def entry(code, tags, priority=50):
            return {
                "code": code, "name": code, "tier": "thematic", "priority": priority,
                "strategy_profiles": ["short", "swing"], "benchmark": "US.SPY",
                "underlying_proxy": None, "tags": tags,
            }
        # Three semiconductors that move several percent a day, one bank and one staple
        # that barely move. A Top-2/Bottom-0 selection can only ever see the semis.
        self.entries = [
            entry("US.SEMI1", ["us", "semiconductor"], 90),
            entry("US.SEMI2", ["us", "semiconductor"], 80),
            entry("US.SEMI3", ["us", "semiconductor"], 70),
            entry("US.BANK", ["us", "bank", "value"], 60),
            entry("US.STAPLE", ["us", "consumer", "defensive"], 60),
        ]
        self.snapshots = {
            "US.SEMI1": _snapshot("US.SEMI1", change_pct=6.0),
            "US.SEMI2": _snapshot("US.SEMI2", change_pct=5.0),
            "US.SEMI3": _snapshot("US.SEMI3", change_pct=4.0),
            "US.BANK": _snapshot("US.BANK", change_pct=0.2),
            "US.STAPLE": _snapshot("US.STAPLE", change_pct=-0.1),
        }

    def _selected(self, **kwargs):
        result = run_watchlist_scan(
            self.entries, FakeFetcher(self.snapshots), deep_horizons=("swing",), **kwargs
        )
        return {row["code"]: row["selection_reasons"] for row in result["selections"]["swing"]}

    def test_momentum_ranking_alone_never_reaches_the_slow_themes(self):
        selected = self._selected(deep_top=2, deep_bottom=0)
        self.assertEqual(set(selected), {"US.SEMI1", "US.SEMI2"})
        self.assertNotIn("US.BANK", selected)
        self.assertNotIn("US.STAPLE", selected)

    def test_quota_pulls_one_name_from_every_starved_theme(self):
        selected = self._selected(deep_top=2, deep_bottom=0, deep_per_theme=1)
        self.assertIn("US.BANK", selected)
        self.assertIn("US.STAPLE", selected)
        self.assertEqual(selected["US.BANK"], ["theme-quota"])
        self.assertEqual(selected["US.STAPLE"], ["theme-quota"])
        # A theme already represented by the momentum ranking is not topped up further.
        self.assertNotIn("US.SEMI3", selected)

    def test_quota_takes_each_theme_best_ranked_name_first(self):
        selected = self._selected(deep_top=0, deep_bottom=0, deep_per_theme=1)
        self.assertIn("US.SEMI1", selected)
        self.assertNotIn("US.SEMI2", selected)

    def test_negative_quota_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "deep_per_theme must be non-negative"):
            run_watchlist_scan(self.entries, FakeFetcher(self.snapshots), deep_per_theme=-1)


class EntryThemeTests(unittest.TestCase):
    def test_explicit_theme_wins_and_market_or_position_tags_are_skipped(self):
        self.assertEqual(_entry_theme({"theme": "ai-compute", "tags": ["us", "bank"]}), "ai-compute")
        self.assertEqual(_entry_theme({"tags": ["us", "holding", "bank", "value"]}), "bank")
        self.assertEqual(_entry_theme({"tags": ["a-share", "semiconductor"]}), "semiconductor")
        # A name described only by where it trades and what we hold has no theme to group on.
        self.assertEqual(_entry_theme({"tags": ["us", "holding", "growth"]}), "unclassified")
        self.assertEqual(_entry_theme({}), "unclassified")
