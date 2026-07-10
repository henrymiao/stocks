import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.stock_skills.cli import DEFAULT_WEIGHTS, _recommend, main
from tools.stock_skills.journal import append_record, read_records
from tools.stock_skills.models import (
    CapitalSnapshot,
    FinancialsSnapshot,
    FundamentalSnapshot,
    InstrumentState,
    KLineBar,
    MarketSnapshot,
)


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

    def get_fundamentals(self, code, eps_growth=None, revenue_growth=None, gross_margin=None, net_margin=None, roe=None):
        return FundamentalSnapshot(
            code, pe_ttm=66.1, pb=18.0, eps=1.99, dividend_ratio=0.34, market_val=2.85e11,
            eps_growth=eps_growth, revenue_growth=revenue_growth, gross_margin=gross_margin,
            net_margin=net_margin, roe=roe,
        )

    def get_financials(self, code):
        return None  # no statement feed in the fake; analyze falls back to valuation-only


class BreakdownFetcher(FakeFetcher):
    def get_financials(self, code):
        return FinancialsSnapshot(
            code=code,
            period="2026/Q1",
            revenue_growth=12.0,
            eps_growth=15.0,
            gross_margin=45.0,
            net_margin=18.0,
            revenue_breakdown=[("Cloud", 60.0), ("Hardware", 40.0)],
        )


class MissingSectorAndValuationFetcher(BreakdownFetcher):
    def get_plate_constituent_changes(self, plate_code, limit=30):
        return []

    def get_fundamentals(self, code, **kwargs):
        return FundamentalSnapshot(
            code, pe_ttm=None, pb=18.0, eps=1.99,
            dividend_ratio=0.34, market_val=2.85e11,
        )


class MissingTrendCapitalFetcher(FakeFetcher):
    def build_state(self, code, num_bars=30, user_context=None):
        state = super().build_state(code, num_bars=num_bars, user_context=user_context)
        return InstrumentState(
            snapshot=state.snapshot,
            daily_bars=state.daily_bars[:1],
            intraday_bars=[],
            capital=None,
            user_context=state.user_context,
        )


class NoValidStopFetcher(FakeFetcher):
    def build_state(self, code, num_bars=30, user_context=None):
        snapshot = MarketSnapshot(
            code, code, 1.0, 100.0, 200.0, 0.0, 100.0,
            1_000, 1_000.0, "2026-06-18T15:00:00+08:00",
        )
        bars = [
            KLineBar("2026-06-17", 100.0, 200.0, 0.0, 100.0, 1_000, 100_000.0),
            KLineBar("2026-06-18", 100.0, 200.0, 0.0, 1.0, 1_000, 1_000.0),
        ]
        capital = CapitalSnapshot(0.0, 0.0, 0.0, 0.0, 0.0, snapshot.timestamp)
        return InstrumentState(
            snapshot=snapshot,
            daily_bars=bars,
            intraday_bars=[],
            capital=capital,
            user_context=user_context or {},
        )


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
        source_refs = payload["source_refs"]
        refs = " ".join(source_refs)
        self.assertIn("futu:snapshot:SZ.002463", source_refs)
        self.assertIn("futu:kline:SZ.002463", source_refs)
        self.assertIn("futu:capital:SZ.002463", source_refs)
        self.assertNotIn("futu:snapshot+kline+capital:SZ.002463", source_refs)
        # All seven data-fed components are populated by the fake fetcher → none flagged as defaults.
        self.assertNotIn("sector: neutral default", refs)
        self.assertNotIn("market_regime: neutral default", refs)
        self.assertNotIn("macro: neutral default", refs)
        self.assertNotIn("fundamental: neutral default", refs)
        self.assertNotIn("position_fit: neutral", refs)
        self.assertIn("5G concept", refs)
        self.assertIn("macro:proxies", refs)
        self.assertIn("fundamental:profile=", refs)
        self.assertIsNotNone(payload["data_quality"])
        self.assertEqual(payload["data_quality"]["session_phase"], "after-close")
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
        self.assertEqual(payload["data_quality"]["missing_components"], ["cross_market", "macro_risk"])
        self.assertEqual(payload["data_quality"]["confidence"], 0.75)
        self.assertFalse(payload["data_quality"]["entry_eligible"])

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
        self.assertNotIn("cross_market", payload["data_quality"]["missing_components"])

    def test_analyze_nonempty_unusable_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--output",
                        str(output),
                        "--journal",
                        str(journal),
                        "--cross",
                        "HK.800700",
                        "--indices",
                        "HK.800000",
                        "--macro-codes",
                        "HK.800000",
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        quality = payload["data_quality"]
        self.assertEqual(
            quality["missing_components"],
            ["cross_market", "macro_risk", "market_regime"],
        )
        self.assertEqual(quality["confidence"], 0.625)
        self.assertFalse(quality["entry_eligible"])
        refs = " ".join(payload["source_refs"])
        self.assertIn("cross_market: neutral default", refs)
        self.assertIn("macro: neutral default", refs)
        self.assertIn("market_regime: neutral default", refs)
        self.assertNotIn("cross_market:HK.800700", refs)
        self.assertNotIn("macro:proxies:HK.800000", refs)
        self.assertNotIn("market:HK.800000", refs)

    def test_analyze_source_refs_include_only_consumed_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--output",
                        str(output),
                        "--journal",
                        str(journal),
                        "--cross",
                        "US.QQQ",
                        "HK.800700",
                        "--indices",
                        "US.SPY",
                        "HK.800000",
                        "--macro-codes",
                        "US.VIXY",
                        "HK.800000",
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        refs = payload["source_refs"]
        self.assertIn("cross_market:US.QQQ", refs)
        self.assertIn("market:US.SPY", refs)
        self.assertIn("macro:proxies:US.VIXY", refs)
        self.assertFalse(any("HK.800700" in ref or "HK.800000" in ref for ref in refs))

    def test_analyze_unknown_manual_macro_input_records_only_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--output",
                        str(output),
                        "--journal",
                        str(journal),
                        "--macro-json",
                        '{"weather":"sunny"}',
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        refs = payload["source_refs"]
        self.assertNotIn("macro:manual-override", refs)
        self.assertIn("macro: neutral default (no usable macro evidence)", refs)

    def test_analyze_empty_sector_and_missing_valuation_record_only_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch(
                "tools.stock_skills.futu_fetcher.FutuFetcher",
                MissingSectorAndValuationFetcher,
            ):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--output",
                        str(output),
                        "--journal",
                        str(journal),
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        refs = payload["source_refs"]
        self.assertFalse(any(ref.startswith("sector:5G concept") for ref in refs))
        self.assertFalse(any(ref.startswith("fundamental:profile=") for ref in refs))
        self.assertIn("sector: neutral default (no usable sector constituent evidence)", refs)
        self.assertIn("fundamental: neutral default (no usable valuation evidence)", refs)
        self.assertFalse(any(ref.startswith("revenue_breakdown:") for ref in refs))

    def test_analyze_missing_trend_and_capital_do_not_claim_live_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch(
                "tools.stock_skills.futu_fetcher.FutuFetcher",
                MissingTrendCapitalFetcher,
            ):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--output",
                        str(output),
                        "--journal",
                        str(journal),
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        refs = payload["source_refs"]
        self.assertIn("futu:snapshot:SZ.002463", refs)
        self.assertNotIn("futu:kline:SZ.002463", refs)
        self.assertNotIn("futu:capital:SZ.002463", refs)
        self.assertIn(
            "trend: neutral default (no usable K-line evidence; need >=2 daily bars)",
            refs,
        )
        self.assertIn(
            "capital_flow: neutral default (no usable capital evidence)",
            refs,
        )
        self.assertIn(
            "position_fit: neutral (no usable ATR evidence; need >=2 daily bars)",
            refs,
        )

    def test_analyze_atr_without_valid_stop_uses_distinct_position_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch(
                "tools.stock_skills.futu_fetcher.FutuFetcher",
                NoValidStopFetcher,
            ):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--output",
                        str(output),
                        "--journal",
                        str(journal),
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        refs = payload["source_refs"]
        self.assertIn(
            "position_fit: neutral (ATR available but no valid stop below price)",
            refs,
        )
        self.assertFalse(any("no usable ATR evidence" in ref for ref in refs))

    def test_analyze_usable_valuation_emits_revenue_breakdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch(
                "tools.stock_skills.futu_fetcher.FutuFetcher",
                BreakdownFetcher,
            ):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--output",
                        str(output),
                        "--journal",
                        str(journal),
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn(
            "revenue_breakdown:Cloud=60%,Hardware=40%",
            payload["source_refs"],
        )

    def test_recommend_aligns_fallback_refs_with_effective_availability(self):
        complete_state = FakeFetcher().build_state("SZ.002463")
        state = InstrumentState(
            snapshot=complete_state.snapshot,
            daily_bars=complete_state.daily_bars[:1],
            intraday_bars=[],
            capital=complete_state.capital,
        )
        flat_cross = MarketSnapshot(
            "US.QQQ", "US.QQQ", 100.0, 100.0, 100.0, 100.0, 100.0,
            1, 100.0, "2026-06-18T15:00:00+08:00",
        )
        flat_market = MarketSnapshot(
            "US.SPY", "US.SPY", 100.0, 100.0, 100.0, 100.0, 100.0,
            1, 100.0, "2026-06-18T15:00:00+08:00",
        )
        fundamentals = FundamentalSnapshot(
            "SZ.002463", pe_ttm=None, pb=18.0, eps=1.99,
            dividend_ratio=0.34, market_val=2.85e11,
        )

        recommendation = _recommend(
            state=state,
            weights=DEFAULT_WEIGHTS,
            macro_inputs={"weather": "sunny"},
            macro_snapshots=None,
            cross_snapshots={"US.QQQ": flat_cross},
            sector_changes=[0.0],
            index_snapshots={"US.SPY": flat_market},
            source_refs=[],
            fundamentals=fundamentals,
        )

        quality = recommendation.data_quality
        self.assertIsNotNone(quality)
        assert quality is not None
        self.assertEqual(
            quality.missing_components,
            ("trend", "macro_risk", "fundamental", "position_fit"),
        )
        refs = " ".join(recommendation.source_refs)
        self.assertIn("macro: neutral default", refs)
        self.assertIn("fundamental: neutral default", refs)
        self.assertIn("position_fit: neutral", refs)
        self.assertNotIn("cross_market: neutral default", refs)
        self.assertNotIn("market_regime: neutral default", refs)

    def test_us_analyze_uses_us_market_and_theme_cross_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main(["analyze", "--code", "US.MRVL", "--output", str(output), "--journal", str(journal)])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        refs = " ".join(payload["source_refs"])
        self.assertIn("cross_market:US.QQQ,US.SPY,US.NVDA", refs)
        self.assertNotIn("US.SMH", refs)
        self.assertIn("market:US.QQQ,US.SPY", refs)
        self.assertNotIn("market:SH.000001", refs)
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
