import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.stock_skills.cli import (
    DEFAULT_MACRO_CODES,
    DEFAULT_WEIGHTS,
    _recommend,
    _snapshots_for_codes,
    main,
)
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
            KLineBar("2026-06-23", 139.0, 140.0, 137.0, 138.0, 90_000_000, 13_000_000_000.0),
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


class StaleLiveFetcher(FakeFetcher):
    def build_state(self, code, num_bars=30, user_context=None):
        state = super().build_state(code, num_bars=num_bars, user_context=user_context)
        snapshot = MarketSnapshot(
            code=state.snapshot.code,
            name=state.snapshot.name,
            last_price=state.snapshot.last_price,
            open=state.snapshot.open,
            high=state.snapshot.high,
            low=state.snapshot.low,
            prev_close=state.snapshot.prev_close,
            volume=state.snapshot.volume,
            turnover=state.snapshot.turnover,
            timestamp="2026-06-18T10:00:00+08:00",
            captured_at="2026-06-18T10:20:00+08:00",
        )
        capital = CapitalSnapshot(0, 0, 0, 0, 0, "2026-06-18T09:40:00+08:00")
        return InstrumentState(
            snapshot=snapshot,
            daily_bars=state.daily_bars,
            intraday_bars=[],
            capital=capital,
            user_context=state.user_context,
        )


class PartialHistoryFetcher(FakeFetcher):
    def get_history_bars(self, code, start, end):
        return super().get_history_bars(code, start, end)[:2]


class CliTests(unittest.TestCase):
    def test_default_macro_context_includes_yen_and_credit_transmission(self):
        self.assertIn("US.FXY", DEFAULT_MACRO_CODES)
        self.assertIn("US.HYG", DEFAULT_MACRO_CODES)
        self.assertIn("US.LQD", DEFAULT_MACRO_CODES)
        self.assertNotIn("US.MOVE", DEFAULT_MACRO_CODES)

    def test_live_stale_trend_is_recorded_and_blocks_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recommendation.json"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", StaleLiveFetcher):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--no-journal",
                        "--output",
                        str(output),
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("trend", payload["data_quality"]["stale_components"])
        self.assertIn("capital_flow", payload["data_quality"]["stale_components"])
        self.assertFalse(payload["data_quality"]["entry_eligible"])
        self.assertNotEqual(payload["strategy_assessment"]["entry_decision"], "enter")

    def test_shared_snapshots_avoid_repeated_backdrop_fetches(self):
        cached = {
            "US.SPY": MarketSnapshot("US.SPY", "SPY", 101.0, 100.0, 101.0, 100.0, 100.0, 1, 100.0, "2026-07-10T16:10:00-04:00"),
            "US.VIXY": MarketSnapshot("US.VIXY", "VIXY", 20.0, 20.0, 20.0, 20.0, 21.0, 1, 100.0, "2026-07-10T16:10:00-04:00"),
        }
        fetcher = mock.Mock()

        selected = _snapshots_for_codes(fetcher, ["US.SPY", "US.VIXY"], cached)

        self.assertEqual(set(selected), {"US.SPY", "US.VIXY"})
        fetcher.get_index_snapshots.assert_not_called()

    def test_evidence_optimize_writes_advisory_report_without_apply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recommendations = Path(tmpdir) / "recommendations.jsonl"
            reviews = Path(tmpdir) / "reviews.jsonl"
            weights = Path(tmpdir) / "weights.json"
            output = Path(tmpdir) / "evidence.json"
            recommendations.write_text("", encoding="utf-8")
            reviews.write_text("", encoding="utf-8")
            weights.write_text(json.dumps(DEFAULT_WEIGHTS), encoding="utf-8")

            exit_code = main(
                [
                    "evidence-optimize",
                    "--recommendations",
                    str(recommendations),
                    "--reviews",
                    str(reviews),
                    "--weights",
                    str(weights),
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["automatic_apply_allowed"])
        self.assertEqual(payload["eligible_closed_trades"], 0)

    def test_dry_run_replays_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recommendation.json"
            exit_code = main(["dry-run", "--code", "SZ.002463", "--output", str(output)])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["code"], "SZ.002463")
        self.assertIn(payload["label"], {"hold", "trim-on-strength", "risk-reduce", "strong-watch", "low-buy-zone", "avoid"})
        self.assertIn("investment hypothesis", payload["analyst_hypothesis"])
        self.assertEqual(payload["strategy_assessment"]["horizon"], "short")
        self.assertEqual(payload["exit_plan"]["strategy_id"], "short-balanced-v1")
        self.assertEqual(payload["total_score"], 54.74)
        self.assertEqual(payload["trade_id"], "fixture-trade")
        self.assertEqual(payload["position_state"]["trade_id"], "fixture-trade")
        self.assertEqual(payload["position_state"]["state"], "entered")

    def test_existing_position_requires_and_preserves_trade_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recommendation.json"
            with self.assertRaises(SystemExit):
                main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--cost-basis",
                        "140",
                        "--output",
                        str(output),
                    ]
                )

            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main(
                    [
                        "analyze",
                        "--code",
                        "SZ.002463",
                        "--cost-basis",
                        "140",
                        "--trade-id",
                        "original-trade-42",
                        "--no-journal",
                        "--output",
                        str(output),
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["trade_id"], "original-trade-42")
        self.assertEqual(payload["position_state"]["trade_id"], "original-trade-42")
        self.assertEqual(payload["position_state"]["state"], "entered")

    def test_dry_run_swing_uses_distinct_profile_and_missing_weekly_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recommendation.json"
            exit_code = main([
                "dry-run", "--code", "SZ.002463", "--output", str(output),
                "--horizon", "swing", "--event-days", "10",
            ])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["strategy_assessment"]["horizon"], "swing")
        self.assertEqual(payload["exit_plan"]["strategy_id"], "swing-balanced-v1")
        self.assertEqual(payload["exit_plan"]["targets"][0]["r_multiple"], 1.5)
        self.assertEqual(payload["exit_plan"]["runner_fraction"], 0.6)
        self.assertIn("weekly-alignment", payload["strategy_assessment"]["gates_missing"])
        self.assertEqual(payload["total_score"], 54.74)

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
        self.assertEqual(payload["schema_version"], "recommendation-v5")
        self.assertEqual(payload["strategy_id"], "short-balanced-v1")
        self.assertEqual(payload["strategy_version"], "v1")
        self.assertEqual(payload["horizon"], "short")
        self.assertTrue(payload["trade_id"].startswith("short-balanced-v1:"))
        self.assertEqual(payload["position_state"]["state"], "flat")
        self.assertIsNotNone(payload["exit_plan"])
        self.assertLess(payload["exit_plan"]["initial_stop"], payload["invalidation_level"])
        self.assertLessEqual(payload["exit_plan"]["risk_sizing"]["suggested_size_pct"], 25.0)
        self.assertEqual(len(payload["exit_plan"]["targets"]), 2)
        self.assertIsNotNone(payload["strategy_assessment"])
        self.assertIn(
            payload["strategy_assessment"]["entry_decision"],
            {"enter", "probe", "watch", "reject"},
        )
        # Position management appears in the trader plan (stop + suggested size).
        self.assertIn("Risk plan: stop near", payload["trader_plan"])
        self.assertIn("TP1", payload["trader_plan"])
        self.assertIn("TP2", payload["trader_plan"])

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
        self.assertTrue(any("no valid structured exit plan" in ref for ref in refs))
        self.assertFalse(any("no usable ATR evidence" in ref for ref in refs))
        self.assertIsNone(payload["exit_plan"])
        self.assertFalse(payload["data_quality"]["entry_eligible"])

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

    def test_new_listing_opening_range_can_produce_a_capped_probe(self):
        snapshot = MarketSnapshot(
            "US.SKHY", "SK hynix", 171.16, 168.22, 171.82, 166.82, 152.35,
            12_419_985, 2_084_434_640.0,
            "2026-07-14T09:53:00-04:00", "2026-07-14T09:53:00-04:00",
        )
        state = InstrumentState(
            snapshot=snapshot,
            daily_bars=[],
            intraday_bars=[],
            capital=CapitalSnapshot(
                500_000_000.0, 260_000_000.0, 160_000_000.0,
                60_000_000.0, 20_000_000.0, snapshot.timestamp,
            ),
        )
        qqq = MarketSnapshot(
            "US.QQQ", "QQQ", 101.0, 100.0, 101.0, 100.0, 100.0,
            1_000, 100_000.0, snapshot.timestamp,
        )
        spy = MarketSnapshot(
            "US.SPY", "SPY", 101.0, 100.0, 101.0, 100.0, 100.0,
            1_000, 100_000.0, snapshot.timestamp,
        )
        fundamentals = FundamentalSnapshot(
            "US.SKHY", pe_ttm=20.0, pb=4.0, eps=8.0,
            dividend_ratio=0.2, market_val=200e9, eps_growth=35.0,
        )

        recommendation = _recommend(
            state=state,
            weights=DEFAULT_WEIGHTS,
            macro_inputs={"fed_bias": "hold", "geopolitical_risk": "normal"},
            macro_snapshots=None,
            cross_snapshots={"US.QQQ": qqq},
            sector_changes=[0.04, 0.05, 0.03],
            index_snapshots={"US.SPY": spy},
            source_refs=[],
            fundamentals=fundamentals,
            profile="growth",
        )

        self.assertIsNotNone(recommendation.exit_plan)
        self.assertTrue(recommendation.data_quality.probe_eligible)
        self.assertEqual(recommendation.strategy_assessment.entry_decision, "probe")
        self.assertLessEqual(
            recommendation.strategy_assessment.suggested_allocation_pct,
            5.0,
        )
        self.assertIn("opening-range stop", " ".join(recommendation.source_refs))

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

    def test_leveraged_cli_applies_overlay_and_allocation_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main([
                    "analyze", "--code", "US.SOXL", "--output", str(output),
                    "--journal", str(journal), "--underlying-confirmed",
                ])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["strategy_assessment"]["leveraged_overlay"])
        self.assertIn("leveraged-overlay-v1", payload["strategy_assessment"]["strategy_id"])
        self.assertEqual(payload["exit_plan"]["risk_sizing"]["allocation_cap_pct"], 15.0)
        self.assertEqual(payload["exit_plan"]["targets"][1]["r_multiple"], 1.5)

    def test_cli_scales_structured_size_to_portfolio_heat_headroom(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "rec.json"
            journal = Path(tmpdir) / "recommendations.jsonl"
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main([
                    "analyze", "--code", "SZ.002463", "--output", str(output),
                    "--journal", str(journal), "--risk-budget-pct", "2.0",
                    "--portfolio-open-risk-pct", "5.5", "--theme-open-risk-pct", "2.5",
                ])
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        sizing = payload["exit_plan"]["risk_sizing"]
        self.assertEqual(sizing["planned_risk_pct"], 0.5)
        self.assertTrue(sizing["capped"])
        self.assertIn("portfolio-heat", payload["strategy_assessment"]["gates_passed"])
        self.assertTrue(any(ref.startswith("portfolio_heat:") for ref in payload["source_refs"]))

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

            # With --apply below the evidence threshold: weights remain unchanged.
            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                code2 = main(["review", "--window", "3d", "--recommendations", str(recommendations), "--reviews", str(reviews), "--weights", str(weights), "--apply"])
            weights_after_apply = json.loads(weights.read_text(encoding="utf-8"))
            backup_exists = weights.with_suffix(".json.bak").exists()

        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        self.assertEqual(len(review_rows), 1)
        self.assertFalse(review_rows[0]["directional_success"])
        self.assertEqual(review_rows[0]["dominant_failure"], "cross_market")
        self.assertEqual(weights_after_apply, weights_after_suggest)
        self.assertFalse(backup_exists)

    def test_review_is_idempotent_for_a_reviewed_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recommendations = Path(tmpdir) / "recommendations.jsonl"
            reviews = Path(tmpdir) / "reviews.jsonl"
            weights = Path(tmpdir) / "signal_weights.json"
            weights.write_text(json.dumps(DEFAULT_WEIGHTS), encoding="utf-8")
            append_record(
                recommendations,
                {
                    "code": "SZ.002463",
                    "label": "hold",
                    "timestamp": "2026-06-18T15:00:00+08:00",
                    "entry_price": 147.9,
                    "invalidation_level": 142.0,
                },
            )
            argv = ["review", "--window", "3d", "--recommendations", str(recommendations), "--reviews", str(reviews), "--weights", str(weights)]

            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                first = main(argv)
                second = main(argv)
            rows = read_records(reviews)

        self.assertEqual(first, 0)
        self.assertEqual(second, 0)
        # The second run must not duplicate the already-reviewed (code, timestamp, window).
        self.assertEqual(len(rows), 1)

    def test_review_creates_empty_file_when_no_row_is_reviewable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recommendations = Path(tmpdir) / "recommendations.jsonl"
            reviews = Path(tmpdir) / "reviews.jsonl"
            weights = Path(tmpdir) / "signal_weights.json"
            weights.write_text(
                json.dumps({
                    "trend": 0.20,
                    "capital_flow": 0.13,
                    "sector": 0.14,
                    "cross_market": 0.11,
                    "macro_risk": 0.11,
                    "market_regime": 0.12,
                    "fundamental": 0.10,
                    "position_fit": 0.09,
                }),
                encoding="utf-8",
            )
            append_record(
                recommendations,
                {
                    "code": "SZ.002463",
                    "label": "hold",
                    "timestamp": "2026-06-18T15:00:00+08:00",
                    "entry_price": 0.0,
                },
            )

            with mock.patch(
                "tools.stock_skills.futu_fetcher.FutuFetcher",
                side_effect=AssertionError("no fetcher should be created for static non-candidates"),
            ):
                exit_code = main([
                    "review",
                    "--recommendations", str(recommendations),
                    "--reviews", str(reviews),
                    "--weights", str(weights),
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(reviews.exists())
            self.assertEqual(read_records(reviews), [])

    def test_review_skips_partial_ten_day_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recommendations = Path(tmpdir) / "recommendations.jsonl"
            reviews = Path(tmpdir) / "reviews.jsonl"
            weights = Path(tmpdir) / "signal_weights.json"
            weights.write_text(json.dumps(DEFAULT_WEIGHTS), encoding="utf-8")
            append_record(
                recommendations,
                {
                    "code": "SZ.002463",
                    "label": "hold",
                    "timestamp": "2026-06-18T15:00:00+08:00",
                    "entry_price": 147.9,
                },
            )

            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", PartialHistoryFetcher):
                exit_code = main([
                    "review",
                    "--window", "10d",
                    "--recommendations", str(recommendations),
                    "--reviews", str(reviews),
                    "--weights", str(weights),
                ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(read_records(reviews), [])
            self.assertFalse(weights.with_suffix(".json.bak").exists())

    def test_review_apply_cannot_use_legacy_failure_count_even_after_sixty_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recommendations = Path(tmpdir) / "recommendations.jsonl"
            reviews = Path(tmpdir) / "reviews.jsonl"
            weights = Path(tmpdir) / "signal_weights.json"
            weights.write_text(json.dumps(DEFAULT_WEIGHTS), encoding="utf-8")
            # Distinct timestamps: review dedups repeated (code, timestamp, window) calls,
            # so reaching the 60-sample threshold needs 60 genuinely separate calls.
            for i in range(60):
                append_record(
                    recommendations,
                    {
                        "code": "SZ.002463",
                        "label": "hold",
                        "timestamp": f"2026-06-18T15:00:{i:02d}+08:00",
                        "entry_price": 147.9,
                        "invalidation_level": 142.0,
                        "component_scores": {"trend": 70, "capital_flow": 65, "sector": 60, "cross_market": 38, "macro_risk": 55, "market_regime": 50, "fundamental": 48, "position_fit": 75},
                    },
                )

            with mock.patch("tools.stock_skills.futu_fetcher.FutuFetcher", FakeFetcher):
                exit_code = main([
                    "review",
                    "--window", "1d",
                    "--recommendations", str(recommendations),
                    "--reviews", str(reviews),
                    "--weights", str(weights),
                    "--apply",
                ])

            review_rows = read_records(reviews)
            updated_weights = json.loads(weights.read_text(encoding="utf-8"))
            history_path = weights.parent / "weight_history.jsonl"

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(review_rows), 60)
            self.assertTrue(all(row["review_complete"] for row in review_rows))
            self.assertEqual(updated_weights, DEFAULT_WEIGHTS)
            self.assertFalse(weights.with_suffix(".json.bak").exists())
            self.assertFalse(history_path.exists())


if __name__ == "__main__":
    unittest.main()
