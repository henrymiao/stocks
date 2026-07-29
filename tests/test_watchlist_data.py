import unittest
from pathlib import Path

from tools.stock_skills.config import load_json, load_watchlist


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "data" / "watchlists" / "core.json"
VIEW_NAMES = (
    "a-share-broad-short.json",
    "national-tech.json",
    "hk-national-tech.json",
    "hk-tomorrow-five.json",
)


class WatchlistDataTests(unittest.TestCase):
    def test_core_is_the_only_instrument_store_and_has_expected_focus_states(self):
        entries = load_watchlist(CORE)
        by_code = {entry["code"]: entry for entry in entries}

        # The canonical store grows whenever an instrument is added, so assert the
        # invariants (not truncated, no duplicate codes) instead of an exact count
        # that every watchlist edit would have to bump by hand.
        self.assertGreater(len(entries), 100)
        self.assertEqual(len(by_code), len(entries))
        self.assertEqual(by_code["HK.00700"]["position_status"], "reduced-holding")
        self.assertEqual(by_code["HK.09988"]["position_status"], "reduced-holding")
        self.assertEqual(by_code["SZ.000021"]["position_status"], "holding")
        self.assertEqual(by_code["HK.09868"]["position_status"], "holding")
        self.assertEqual(by_code["HK.09868"]["scan_policy"], "always")
        self.assertEqual(by_code["SZ.002463"]["position_status"], "exited-watch")
        self.assertEqual(by_code["HK.03690"]["position_status"], "exited-watch")
        self.assertEqual(by_code["HK.02513"]["name"], "智谱")
        self.assertEqual(by_code["HK.07709"]["asset_type"], "leveraged-etf")
        self.assertEqual(by_code["HK.07709"]["underlying_proxy"], "US.SKHY")
        self.assertEqual(by_code["HK.07709"]["strategy_profiles"], ["short"])
        self.assertIn("oversold-watch", by_code["SH.563380"]["tags"])

        for name in VIEW_NAMES:
            payload = load_json(CORE.parent / name)
            self.assertIn("source", payload)
            self.assertNotIn("watchlist", payload)

    def test_legacy_views_resolve_nonempty_unique_subsets(self):
        for name in VIEW_NAMES:
            path = CORE.parent / name
            entries = load_watchlist(path)
            codes = [entry["code"] for entry in entries]
            self.assertTrue(codes, name)
            self.assertEqual(len(codes), len(set(codes)), name)

    def test_every_canonical_entry_has_explicit_audited_metadata(self):
        required = {
            "code",
            "name",
            "enabled",
            "tier",
            "priority",
            "strategy_profiles",
            "asset_type",
            "valuation_profile",
            "benchmark",
            "underlying_proxy",
            "event_policy",
            "position_status",
            "scan_policy",
            "tags",
        }
        payload = load_json(CORE)
        for entry in payload["watchlist"]:
            self.assertEqual(set(entry), required, entry["code"])


if __name__ == "__main__":
    unittest.main()
