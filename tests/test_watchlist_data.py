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
        # These pin live position state, so they move whenever a position is opened or
        # closed -- HK.00700 was reduced-holding until it was sold out on 2026-08-13.
        # `BookAndWatchlistAgreeTests` is the version of this that does not need editing.
        self.assertEqual(by_code["HK.00700"]["position_status"], "exited-watch")
        self.assertEqual(by_code["HK.09988"]["position_status"], "reduced-holding")
        self.assertEqual(by_code["SZ.000021"]["position_status"], "exited-watch")
        self.assertEqual(by_code["HK.09868"]["position_status"], "holding")
        self.assertEqual(by_code["HK.09868"]["scan_policy"], "always")
        self.assertEqual(by_code["SZ.002463"]["position_status"], "holding")
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
        # `theme` is optional: the scanner's per-theme quota falls back to deriving one
        # from tags, so an entry may either state its theme or leave it inferred.
        optional = {"theme"}
        payload = load_json(CORE)
        for entry in payload["watchlist"]:
            fields = set(entry)
            self.assertTrue(required <= fields, entry["code"])
            self.assertEqual(fields - required - optional, set(), entry["code"])


if __name__ == "__main__":
    unittest.main()


class BookAndWatchlistAgreeTests(unittest.TestCase):
    """The two files drifted apart four times in one session; make it impossible.

    On 2026-08-03 the watchlist called 深科技 a holding that had been sold long before,
    called GOOGL and SMH watch-only while both were held, and on 08-04 still called CATL
    a holding after it was closed. Every one of those silently changed what the scanner
    analysed and what the heat gates measured.
    """

    def test_every_watchlist_holding_is_in_the_positions_book_and_the_reverse(self):
        from tools.stock_skills.positions import load_portfolio

        book = load_portfolio(Path("data/portfolio/positions.json"))
        booked = set(book.codes())
        flagged = {
            entry["code"]
            for entry in load_json(CORE)["watchlist"]
            if entry.get("position_status") in {"holding", "reduced-holding"}
        }

        self.assertEqual(
            flagged - booked, set(), "watchlist says held but the book has no position"
        )
        self.assertEqual(
            booked - flagged, set(), "book holds a position the watchlist does not flag"
        )


class ExplicitCodesKeepWatchlistMetadataTests(unittest.TestCase):
    """`--codes` must not answer differently from scanning the same name in its watchlist.

    The stub entry it used to build carried no tags, so `valuation_profile` fell back to
    `neutral` and the fundamental component was scored on the wrong yardstick. On
    2026-08-10 Zijin read `cheap` at 75 under `--codes` and `fair` at 66 under a plain
    `analyze`, off the same PE of 15.28 -- and those 9 points were the difference between
    `probe` and `watch`.
    """

    def test_a_known_code_keeps_its_profile_and_tags(self):
        from tools.stock_skills.scan_watchlist import _explicit_entries

        entry = _explicit_entries("SH.601899", CORE)[0]
        canonical = {e["code"]: e for e in load_watchlist(CORE)}["SH.601899"]
        self.assertEqual(entry["valuation_profile"], canonical["valuation_profile"])
        self.assertEqual(entry["tags"], canonical["tags"])
        self.assertNotEqual(entry["valuation_profile"], "neutral")

    def test_an_unknown_code_still_scans_as_a_neutral_stub(self):
        from tools.stock_skills.scan_watchlist import _explicit_entries

        entry = _explicit_entries("US.NOTINLIST", CORE)[0]
        self.assertEqual(entry["code"], "US.NOTINLIST")
        self.assertEqual(entry["valuation_profile"], "neutral")

    def test_duplicates_are_still_refused(self):
        from tools.stock_skills.scan_watchlist import _explicit_entries

        with self.assertRaisesRegex(ValueError, "Duplicate"):
            _explicit_entries("SH.601899,SH.601899", CORE)
