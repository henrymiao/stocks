import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.stock_skills.cli import main
from tools.stock_skills.journal import append_record, read_records
from tools.stock_skills.models import CapitalSnapshot, FundamentalSnapshot, InstrumentState, KLineBar, MarketSnapshot


class FakeFetcher:
    """Stands in for FutuFetcher so `analyze`/`review` can be tested without OpenD."""

    def build_state(self, code, num_bars=30, user_context=None):
        snapshot = MarketSnapshot(code, code, 147.9, 146.0, 149.36, 142.81, 146.55, 83_679_015, 12_271_729_868.41, "2026-06-18T15:00:00+08:00")
        bars = [
            KLineBar("2026-06-17", 138.0, 149.9, 137.1, 146.55, 99_154_170, 14_460_550_533.78),
            KLineBar("2026-06-18", 146.0, 149.36, 142.81, 147.9, 83_679_015, 12_271_729_868.41),
        ]
        capital = CapitalSnapshot(24_492_584.5, 744_236_606.14, -411_741_404.48, -210_842_830.36, -97_159_786.8, "2026-06-18T15:00:00+08:00")
        return InstrumentState(snapshot=snapshot, daily_bars=bars, intraday_bars=[], capital=capital, user_context=user_context or {})

    def get_snapshot(self, code):
        return MarketSnapshot(code, code, 750.0, 740.0, 752.0, 738.0, 729.86, 1, 1.0, "2026-06-18T15:00:00+08:00")

    def pick_core_plate(self, code):
        return {"plate_code": "SH.LIST0534", "plate_name": "5G concept", "plate_type": "CONCEPT"}

    def get_plate_constituent_changes(self, plate_code, limit=30):
        return [0.02, 0.015, -0.005, 0.03, 0.01]

    def get_index_snapshots(self, codes):
        # Return a snapshot per requested code so both the index backdrop and the
        # macro-proxy fetch (which reuse this method) get sensible data.
        prices = {
            "SH.000001": (4120.0, 4090.0),
            "SZ.399006": (4250.0, 4200.0),
            "US.VIXY": (21.0, 22.7),   # fear down → risk-on tilt
            "US.TLT": (88.0, 86.3),    # bonds up → yields down
            "US.UUP": (28.1, 28.2),
            "US.USO": (110.0, 111.0),
            "US.GLD": (388.0, 388.6),
        }
        out = {}
        for code in codes:
            last, prev = prices.get(code, (100.0, 100.0))
            out[code] = MarketSnapshot(code, code, last, last, last, last, prev, 1, 1.0, "2026-06-18T15:00:00+08:00")
        return out

    def get_history_bars(self, code, start, end):
        # Drop below the recommendation's invalidation level so the call fails.
        return [
            KLineBar("2026-06-19", 147.0, 147.5, 140.0, 141.0, 90_000_000, 13_000_000_000.0),
            KLineBar("2026-06-22", 141.0, 142.0, 138.0, 139.0, 90_000_000, 13_000_000_000.0),
        ]

    def get_fundamentals(self, code, eps_growth=None):
        return FundamentalSnapshot(code, pe_ttm=66.1, pb=18.0, eps=1.99, dividend_ratio=0.34, market_val=2.85e11, eps_growth=eps_growth)


class CliTests(unittest.TestCase):
    def test_dry_run_replays_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recommendation.json"
            exit_code = main(["dry-run", "--code", "SZ.002463", "--output", str(output)])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["code"], "SZ.002463")
        self.assertIn(payload["label"], {"hold", "trim-on-strength", "risk-reduce", "strong-watch", "low-buy-zone", "avoid"})
        self.assertIn("investment hypothesis", payload["analyst_hypothesis"])

    def test_dry_run_rejects_non_fixture_code(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recommendation.json"
            with self.assertRaises(SystemExit):
                main(["dry-run", "--code", "US.NVDA", "--output", str(output)])
            self.assertFalse(output.exists())

    def test_analyze_uses_fetched_state_and_flags_missing_components(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main(["analyze", "--code", "SZ.002463", "--output", str(output), "--journal", str(journal)])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["code"], "SZ.002463")
        self.assertEqual(payload["entry_price"], 147.9)
        refs = " ".join(payload["source_refs"])
        # All seven data-fed components are populated by the fake fetcher → none flagged as defaults.
        self.assertNotIn("sector: neutral default", refs)
        self.assertNotIn("market_regime: neutral default", refs)
        self.assertNotIn("macro: neutral default", refs)
        self.assertNotIn("fundamental: neutral default", refs)
        self.assertNotIn("position_fit: neutral", refs)
        self.assertIn("5G concept", refs)
        self.assertIn("macro:proxies", refs)
        self.assertIn("fundamental:profile=", refs)
        # Position management appears in the trader plan (stop + suggested size).
        self.assertIn("Risk plan: stop near", payload["trader_plan"])

    def test_analyze_no_macro_flags_neutral(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                main(["analyze", "--code", "SZ.002463", "--output", str(output), "--journal", str(journal), "--no-macro"])
            payload = json.loads(output.read_text(encoding="utf-8"))

        refs = " ".join(payload["source_refs"])
        self.assertIn("macro: neutral default", refs)

    def test_analyze_appends_to_journal_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                main(["analyze", "--code", "SZ.002463", "--output", str(output), "--journal", str(journal)])
            records = read_records(journal)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["code"], "SZ.002463")

    def test_analyze_no_journal_skips_journal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                main(["analyze", "--code", "SZ.002463", "--output", str(output), "--journal", str(journal), "--no-journal"])

            self.assertFalse(journal.exists())

    def test_analyze_with_cross_market_does_not_flag_cross_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main(["analyze", "--code", "SZ.002463", "--output", str(output), "--journal", str(journal), "--cross", "US.QQQ"])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        refs = " ".join(payload["source_refs"])
        self.assertNotIn("cross_market: neutral default", refs)

    def test_review_evaluates_journal_and_only_applies_with_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recommendations = Path(tmpdir) / "recommendations.jsonl"
            reviews = Path(tmpdir) / "reviews.jsonl"
            weights = Path(tmpdir) / "signal_weights.json"
            weights.write_text(
                json.dumps({"trend": 0.20, "capital_flow": 0.13, "sector": 0.14, "cross_market": 0.11, "macro_risk": 0.11, "market_regime": 0.12, "fundamental": 0.10, "position_fit": 0.09}),
                encoding="utf-8",
            )
            append_record(
                recommendations,
                {
                    "code": "SZ.002463",
                    "label": "hold",
                    "timestamp": "2026-06-18T15:00:00+08:00",
                    "entry_price": 147.9,
                    "invalidation_level": 142.0,
                    "component_scores": {"trend": 70, "capital_flow": 65, "sector": 60, "cross_market": 38, "macro_risk": 55, "market_regime": 50, "fundamental": 48, "position_fit": 75},
                },
            )

            # Without --apply: reviews are written, weights untouched.
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                code1 = main(["review", "--window", "3d", "--recommendations", str(recommendations), "--reviews", str(reviews), "--weights", str(weights)])
            weights_after_suggest = json.loads(weights.read_text(encoding="utf-8"))
            review_rows = read_records(reviews)

            # With --apply: weights change, backup created.
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                code2 = main(["review", "--window", "3d", "--recommendations", str(recommendations), "--reviews", str(reviews), "--weights", str(weights), "--apply"])
            weights_after_apply = json.loads(weights.read_text(encoding="utf-8"))
            backup_exists = weights.with_suffix(".json.bak").exists()

        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        self.assertEqual(len(review_rows), 1)
        self.assertFalse(review_rows[0]["directional_success"])
        self.assertEqual(review_rows[0]["dominant_failure"], "cross_market")
        self.assertEqual(weights_after_suggest["cross_market"], 0.11)  # unchanged before --apply
        self.assertGreater(weights_after_apply["cross_market"], 0.11)  # bumped after --apply
        self.assertTrue(backup_exists)


if __name__ == "__main__":
    unittest.main()
