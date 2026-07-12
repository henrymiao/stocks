import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tools.stock_skills.futu_fetcher import FutuFetcher, _default_skill_dir


class FakeRunner:
    def __init__(self, responses=None):
        self.commands = []
        self.responses = responses

    def __call__(self, command):
        self.commands.append(command)
        if self.responses is not None:
            # Dispatch on the script name so one runner can serve several calls.
            script = next((part for part in command if part.endswith(".py")), "")
            for key, payload in self.responses.items():
                if key in script:
                    return json.dumps(payload, ensure_ascii=False)
            raise AssertionError(f"No fake response for {script}")
        return json.dumps(
            {
                "data": [
                    {
                        "code": "SZ.002463",
                        "name": "沪电股份",
                        "last_price": 147.9,
                        "open": 146.0,
                        "high": 149.36,
                        "low": 142.81,
                        "prev_close": 146.55,
                        "volume": 83679015,
                        "turnover": 12271729868.41,
                    }
                ]
            },
            ensure_ascii=False,
        )


SNAPSHOT_PAYLOAD = {
    "data": [
        {
            "code": "SZ.002463",
            "name": "沪电股份",
            "last_price": 147.9,
            "open": 146.0,
            "high": 149.36,
            "low": 142.81,
            "prev_close": 146.55,
            "volume": 83679015,
            "turnover": 12271729868.41,
        }
    ]
}
KLINE_PAYLOAD = {
    "code": "SZ.002463",
    "ktype": "1d",
    "data": [
        {"time": "2026-06-17 00:00:00", "open": 138.0, "high": 149.9, "low": 137.1, "close": 146.55, "volume": 99154170, "turnover": 14460550533.78},
        {"time": "2026-06-18 00:00:00", "open": 146.0, "high": 149.36, "low": 142.81, "close": 147.9, "volume": 83679015, "turnover": 12271729868.41},
    ],
}
CAPITAL_PAYLOAD = {
    "code": "SZ.002463",
    "data": [
        {"last_valid_time": "2026-06-18 15:00:00", "in_flow": 24492584.5, "super_in_flow": 744236606.14, "big_in_flow": -411741404.48, "mid_in_flow": -210842830.36, "sml_in_flow": -97159786.8, "main_in_flow": "N/A", "capital_flow_item_time": "2026-06-18 15:00:00"},
    ],
}


STATEMENTS_PAYLOAD = {
    "code": "HK.00700",
    "data": {
        "report_list": [
            # Latest quarter (highest date_time) — the row get_financials should distill.
            {"date_time": 1774886400, "period_text": "2026/Q1", "item_list": [
                {"field_id": 5001, "display_name": "Total Revenue", "data": 200_000_000_000.0, "yoy": 9.13},
                {"field_id": 5010, "display_name": "Gross Profit", "data": 113_000_000_000.0},
                {"field_id": 5051, "display_name": "Net Income to Parent", "data": 59_000_000_000.0},
                {"field_id": 5054, "display_name": "Basic EPS", "data": 6.43, "yoy": 22.42},
            ]},
            # An older annual row that must be ignored in favour of the latest quarter.
            {"date_time": 1700000000, "period_text": "2025/FY", "item_list": [
                {"field_id": 5001, "display_name": "Total Revenue", "data": 751_800_000_000.0, "yoy": 13.9},
            ]},
        ]
    },
}
BREAKDOWN_PAYLOAD = {
    "code": "HK.00700",
    "data": {
        "breakdown_list": [
            {"type": 4, "item_list": [{"name": "Mainland China", "ratio": 88.1}]},  # geographic — skipped
            {"type": 1, "item_list": [  # by-business-segment — the group we want
                {"name": "Value-added services", "ratio": 49.1},
                {"name": "Fintech and business services", "ratio": 30.5},
                {"name": "Marketing service", "ratio": 19.3},
                {"name": "Other", "ratio": 1.1},
            ]},
        ]
    },
}


def _fetcher(runner):
    return FutuFetcher(
        python_bin="python3",
        skill_dir="/fake/futuapi",
        runner=runner,
    )


class FutuSkillPathTests(unittest.TestCase):
    @staticmethod
    def _install_snapshot_script(skill_dir):
        script = skill_dir / "scripts" / "quote" / "get_snapshot.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.touch()
        return script

    def test_default_skill_dir_uses_installed_candidate_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex = home / ".codex" / "skills" / "futuapi"
            agents = home / ".agents" / "skills" / "futuapi"
            claude = home / ".claude" / "skills" / "futuapi"

            claude_script = self._install_snapshot_script(claude)
            agents_script = self._install_snapshot_script(agents)
            codex.mkdir(parents=True)
            self.assertEqual(_default_skill_dir(home), agents)

            codex_script = self._install_snapshot_script(codex)
            self.assertEqual(_default_skill_dir(home), codex)

            codex_script.unlink()
            agents_script.unlink()
            self.assertEqual(_default_skill_dir(home), claude)
            self.assertTrue(claude_script.exists())

    def test_default_skill_dir_missing_installation_lists_attempted_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            attempted = [
                home / ".codex" / "skills" / "futuapi",
                home / ".agents" / "skills" / "futuapi",
                home / ".claude" / "skills" / "futuapi",
            ]

            with self.assertRaises(FileNotFoundError) as ctx:
                _default_skill_dir(home)

            for path in attempted:
                self.assertIn(str(path), str(ctx.exception))

    def test_default_skill_dir_skips_directory_at_script_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex = home / ".codex" / "skills" / "futuapi"
            agents = home / ".agents" / "skills" / "futuapi"
            malformed_marker = codex / "scripts" / "quote" / "get_snapshot.py"
            malformed_marker.mkdir(parents=True)
            self._install_snapshot_script(agents)

            self.assertEqual(_default_skill_dir(home), agents)

    def test_explicit_skill_dir_beats_environment_override(self):
        with patch.dict(os.environ, {"FUTUAPI_SKILL_DIR": "/environment/futuapi"}):
            fetcher = FutuFetcher(skill_dir="/explicit/futuapi", runner=FakeRunner())

        self.assertEqual(fetcher.skill_dir, Path("/explicit/futuapi"))

    def test_environment_override_beats_default_discovery(self):
        with (
            patch.dict(os.environ, {"FUTUAPI_SKILL_DIR": "/environment/futuapi"}),
            patch("tools.stock_skills.futu_fetcher._default_skill_dir") as default_discovery,
        ):
            fetcher = FutuFetcher(runner=FakeRunner())

        self.assertEqual(fetcher.skill_dir, Path("/environment/futuapi"))
        default_discovery.assert_not_called()


class FutuFetcherTests(unittest.TestCase):
    def test_snapshot_uses_existing_futu_script(self):
        runner = FakeRunner()
        snapshot = _fetcher(runner).get_snapshot("SZ.002463")

        self.assertEqual(snapshot.code, "SZ.002463")
        self.assertEqual(snapshot.last_price, 147.9)
        self.assertIn("get_snapshot.py", runner.commands[0][1])

    def test_snapshot_preserves_market_update_time_and_capture_time(self):
        payload = {"data": [{**SNAPSHOT_PAYLOAD["data"][0], "update_time": "2026-07-10 14:59:00"}]}
        snapshot = _fetcher(FakeRunner({"get_snapshot.py": payload})).get_snapshot("SZ.002463")

        self.assertEqual(snapshot.timestamp, "2026-07-10 14:59:00")
        self.assertIsNotNone(snapshot.captured_at)

    def test_get_daily_bars_parses_kline_records(self):
        runner = FakeRunner({"get_kline.py": KLINE_PAYLOAD})
        bars = _fetcher(runner).get_daily_bars("SZ.002463", num=2)

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1].close, 147.9)
        self.assertIn("--ktype", runner.commands[0])
        self.assertIn("1d", runner.commands[0])

    def test_get_history_bars_passes_date_range(self):
        runner = FakeRunner({"get_kline.py": KLINE_PAYLOAD})
        bars = _fetcher(runner).get_history_bars("SZ.002463", start="2026-06-19", end="2026-06-30")

        self.assertEqual(len(bars), 2)
        command = runner.commands[0]
        self.assertIn("--start", command)
        self.assertIn("2026-06-19", command)
        self.assertIn("--end", command)
        self.assertIn("2026-06-30", command)

    def test_get_capital_maps_last_row_and_handles_na(self):
        runner = FakeRunner({"get_capital_flow.py": CAPITAL_PAYLOAD})
        capital = _fetcher(runner).get_capital("SZ.002463")

        self.assertIsNotNone(capital)
        self.assertEqual(capital.super_inflow, 744236606.14)
        self.assertEqual(capital.small_inflow, -97159786.8)

    def test_get_capital_returns_none_when_empty(self):
        # No intraday rows AND no distribution → genuinely no capital data → None (neutral downstream).
        runner = FakeRunner(
            {
                "get_capital_flow.py": {"code": "SZ.002463", "data": []},
                "get_capital_distribution.py": {"code": "SZ.002463", "data": {}},
            }
        )
        self.assertIsNone(_fetcher(runner).get_capital("SZ.002463"))

    def test_get_capital_falls_back_to_distribution_when_intraday_frozen(self):
        # The intraday feed froze at 11:09 on a finished session, so its partial-day point
        # reads net outflow; get_capital must fall back to the authoritative full-day
        # distribution, which shows the true super/big inflow. Mirrors the SH.688046 incident.
        # The bar time (capital_flow_item_time) stops at 11:09; last_valid_time is the post-close
        # fetch time and must NOT make the feed look fresh.
        frozen_flow = {
            "code": "SH.688046",
            "data": [
                {"in_flow": -6_810_000, "super_in_flow": -6_810_000, "big_in_flow": 0, "mid_in_flow": 0, "sml_in_flow": 0, "capital_flow_item_time": "2024-06-18 11:09:00", "last_valid_time": "2024-06-18 23:07:00"},
            ],
        }
        distribution = {
            "code": "SH.688046",
            "capital_in_super": 20_000_000, "capital_out_super": 9_320_000,  # +1068万
            "capital_in_big": 30_000_000, "capital_out_big": 17_850_000,     # +1215万
            "capital_in_mid": 5_000_000, "capital_out_mid": 6_000_000,
            "capital_in_small": 4_000_000, "capital_out_small": 5_000_000,
        }
        runner = FakeRunner({"get_capital_flow.py": frozen_flow, "get_capital_distribution.py": distribution})
        capital = _fetcher(runner).get_capital("SH.688046")

        self.assertEqual(capital.source, "distribution")
        self.assertAlmostEqual(capital.super_inflow, 10_680_000)
        self.assertAlmostEqual(capital.big_inflow, 12_150_000)
        self.assertGreater(capital.net_inflow, 0)  # corrected: full day is inflow, not the frozen -681万
        self.assertIsNone(capital.intraday_trend)  # distribution carries no time series
        scripts = [next((p for p in cmd if p.endswith(".py")), "") for cmd in runner.commands]
        self.assertTrue(any("get_capital_flow.py" in s for s in scripts))
        self.assertTrue(any("get_capital_distribution.py" in s for s in scripts))

    def test_intraday_feed_stale_detection(self):
        fetcher = _fetcher(FakeRunner())
        tz = ZoneInfo("Asia/Shanghai")
        # last_valid_time is the (post-close) fetch time and must be ignored; the bar time
        # in capital_flow_item_time is what reveals the freeze.
        frozen = [{"capital_flow_item_time": "2026-06-18 11:09:00", "last_valid_time": "2026-06-18 23:07:00"}]
        # Queried after the close the same evening → a feed stuck at 11:09 is stale.
        self.assertTrue(fetcher._intraday_feed_is_stale("SH.688046", frozen, now=datetime(2026, 6, 18, 23, 7, tzinfo=tz)))
        # Queried mid-session (before close) → the partial reading is just the live cumulative.
        self.assertFalse(fetcher._intraday_feed_is_stale("SH.688046", frozen, now=datetime(2026, 6, 18, 11, 30, tzinfo=tz)))
        # A feed that reached the 15:00 close is never stale, even queried late.
        complete = [{"capital_flow_item_time": "2026-06-18 15:00:00", "last_valid_time": "2026-06-18 23:07:00"}]
        self.assertFalse(fetcher._intraday_feed_is_stale("SH.688046", complete, now=datetime(2026, 6, 18, 23, 7, tzinfo=tz)))
        # Unparseable timestamps (e.g. fixtures) are trusted, not flagged stale.
        self.assertFalse(fetcher._intraday_feed_is_stale("SH.688046", [{"capital_flow_item_time": "t4"}], now=datetime(2026, 6, 18, 23, 7, tzinfo=tz)))

    def test_get_capital_distribution_parses_net_by_size(self):
        distribution = {
            "code": "HK.00700",
            "capital_in_super": 100, "capital_out_super": 40,
            "capital_in_big": 50, "capital_out_big": 70,
            "capital_in_mid": 0, "capital_out_mid": 0,
            "capital_in_small": 10, "capital_out_small": 5,
        }
        runner = FakeRunner({"get_capital_distribution.py": distribution})
        capital = _fetcher(runner).get_capital_distribution("HK.00700")

        self.assertEqual(capital.super_inflow, 60)   # 100 - 40
        self.assertEqual(capital.big_inflow, -20)    # 50 - 70
        self.assertEqual(capital.net_inflow, 45)     # 60 - 20 + 0 + 5
        self.assertEqual(capital.source, "distribution")

    def test_get_capital_distribution_returns_none_on_error(self):
        runner = FakeRunner({"get_capital_distribution.py": {"error": "interface does not support this type"}})
        self.assertIsNone(_fetcher(runner).get_capital_distribution("SH.510300"))

    def test_build_state_combines_snapshot_bars_and_capital(self):
        runner = FakeRunner(
            {
                "get_snapshot.py": SNAPSHOT_PAYLOAD,
                "get_kline.py": KLINE_PAYLOAD,
                "get_capital_flow.py": CAPITAL_PAYLOAD,
            }
        )
        state = _fetcher(runner).build_state("SZ.002463", num_bars=2, user_context={"last_trim_price": 149.5})

        self.assertEqual(state.snapshot.code, "SZ.002463")
        self.assertEqual(len(state.daily_bars), 2)
        self.assertEqual(state.capital.super_inflow, 744236606.14)
        self.assertEqual(state.user_context["last_trim_price"], 149.5)

    def test_error_payload_is_surfaced(self):
        runner = FakeRunner({"get_snapshot.py": {"error": "OpenD not connected"}})
        with self.assertRaises(RuntimeError) as ctx:
            _fetcher(runner).get_snapshot("SZ.002463")
        self.assertIn("OpenD not connected", str(ctx.exception))

    def test_get_capital_detects_intraday_acceleration(self):
        # First half net = 10m, full day = 50m → second half (40m) accelerating in.
        series = {
            "code": "SZ.002463",
            "data": [
                {"in_flow": 5_000_000, "super_in_flow": 0, "big_in_flow": 0, "mid_in_flow": 0, "sml_in_flow": 0, "capital_flow_item_time": "t1"},
                {"in_flow": 10_000_000, "super_in_flow": 0, "big_in_flow": 0, "mid_in_flow": 0, "sml_in_flow": 0, "capital_flow_item_time": "t2"},
                {"in_flow": 30_000_000, "super_in_flow": 0, "big_in_flow": 0, "mid_in_flow": 0, "sml_in_flow": 0, "capital_flow_item_time": "t3"},
                {"in_flow": 50_000_000, "super_in_flow": 0, "big_in_flow": 0, "mid_in_flow": 0, "sml_in_flow": 0, "last_valid_time": "t4"},
            ],
        }
        runner = FakeRunner({"get_capital_flow.py": series})
        capital = _fetcher(runner).get_capital("SZ.002463")

        self.assertEqual(capital.net_inflow, 50_000_000)  # full-day total, not a mid-session point
        self.assertEqual(capital.intraday_trend, "accelerating-in")

    def test_pick_core_plate_prefers_industry_and_skips_noise(self):
        plates = {
            "data": [
                {"plate_code": "SH.LIST24135", "plate_name": "High amplitude yesterday", "plate_type": "CONCEPT"},
                {"plate_code": "SH.IND001", "plate_name": "PCB Industry", "plate_type": "INDUSTRY"},
                {"plate_code": "SH.LIST0534", "plate_name": "5G concept", "plate_type": "CONCEPT"},
            ]
        }
        runner = FakeRunner({"get_owner_plate.py": plates})
        core = _fetcher(runner).pick_core_plate("SZ.002463")

        self.assertEqual(core["plate_code"], "SH.IND001")  # INDUSTRY beats CONCEPT, noise skipped

    def test_pick_core_plate_returns_none_for_etf(self):
        # Futu's sector interface rejects ETFs; analyze should fall back to neutral, not crash.
        etf_error = {
            "ret": -1,
            "action": "获取所属板块",
            "error": "Get Stock's Sector interface does not support ETFs type.",
        }
        runner = FakeRunner({"get_owner_plate.py": etf_error})
        self.assertIsNone(_fetcher(runner).pick_core_plate("US.SOXL"))

    def test_get_owner_plates_surfaces_non_etf_error(self):
        runner = FakeRunner({"get_owner_plate.py": {"error": "OpenD not connected"}})
        with self.assertRaises(RuntimeError):
            _fetcher(runner).get_owner_plates("SZ.002463")

    def test_get_plate_constituent_changes_computes_pct(self):
        plate_stock = {"data": [{"code": "SZ.000001", "name": "A"}, {"code": "SZ.000002", "name": "B"}]}
        snapshot_batch = {
            "data": [
                {"code": "SZ.000001", "name": "A", "last_price": 103.0, "open": 100, "high": 104, "low": 99, "prev_close": 100.0, "volume": 1, "turnover": 1.0},
                {"code": "SZ.000002", "name": "B", "last_price": 99.0, "open": 100, "high": 101, "low": 98, "prev_close": 100.0, "volume": 1, "turnover": 1.0},
            ]
        }
        runner = FakeRunner({"get_plate_stock.py": plate_stock, "get_snapshot.py": snapshot_batch})
        changes = _fetcher(runner).get_plate_constituent_changes("SH.IND001", limit=10)

        self.assertEqual(len(changes), 2)
        self.assertAlmostEqual(changes[0], 0.03)
        self.assertAlmostEqual(changes[1], -0.01)

    def test_get_snapshots_salvages_good_codes_when_batch_rejected(self):
        # Futu rejects the whole batch if any code lacks an entitlement (e.g. CC.* crypto).
        # get_index_snapshots must drop the bad codes and keep the good ones, not crash.
        good = {
            "US.QQQ": {"code": "US.QQQ", "name": "QQQ", "last_price": 717.0, "open": 715, "high": 720, "low": 710, "prev_close": 713.0, "volume": 1, "turnover": 1.0},
            "US.SPY": {"code": "US.SPY", "name": "SPY", "last_price": 739.0, "open": 734, "high": 740, "low": 734, "prev_close": 733.0, "volume": 1, "turnover": 1.0},
        }

        def runner(command):
            codes = [p for p in command[2:] if p != "--json"]
            if any(c.startswith("CC.") for c in codes):  # whole batch rejected
                raise subprocess.CalledProcessError(1, command, stderr="No permission to get quotes for CC.BTC")
            return json.dumps({"data": [good[c] for c in codes if c in good]})

        snaps = _fetcher(runner).get_index_snapshots(["US.QQQ", "US.SPY", "CC.BTC", "CC.ETH"])

        self.assertEqual(set(snaps), {"US.QQQ", "US.SPY"})  # crypto dropped, equities kept
        self.assertEqual(snaps["US.QQQ"].last_price, 717.0)

    def test_get_snapshots_returns_empty_when_all_codes_fail(self):
        def runner(command):
            raise subprocess.CalledProcessError(1, command, stderr="Unknown stock")

        self.assertEqual(_fetcher(runner).get_snapshots(["X.BAD1", "X.BAD2"]), [])

    def test_get_fundamentals_parses_valuation(self):
        # The fundamentals snippet runs via `python -c`, so dispatch on the -c marker.
        fund_payload = {"data": [{"code": "SZ.002463", "pe_ttm": 66.14, "pb": 17.98, "eps": 1.99, "dividend_ratio": 0.34, "market_val": 2.8e11}]}

        class CRunner:
            def __init__(self):
                self.commands = []

            def __call__(self, command):
                self.commands.append(command)
                import json as _json
                return _json.dumps(fund_payload)

        runner = CRunner()
        fund = _fetcher(runner).get_fundamentals("SZ.002463", eps_growth=40.0)

        self.assertEqual(fund.pe_ttm, 66.14)
        self.assertEqual(fund.pb, 17.98)
        self.assertEqual(fund.eps_growth, 40.0)  # passed through, not from the feed
        self.assertEqual(runner.commands[0][1], "-c")

    def test_get_extended_hours_parses_pre_and_after(self):
        # Like fundamentals, the extended-hours snippet runs via `python -c`.
        payload = {"data": [{
            "code": "US.SOXL", "prev_close": 266.71,
            "pre_price": 239.5, "pre_change_rate": -10.2, "pre_volume": 1772357.0,
            "after_price": 269.25, "after_change_rate": 0.95, "after_volume": 1329114.0,
        }]}

        class CRunner:
            def __init__(self):
                self.commands = []

            def __call__(self, command):
                self.commands.append(command)
                import json as _json
                return _json.dumps(payload)

        runner = CRunner()
        eh = _fetcher(runner).get_extended_hours("US.SOXL")

        self.assertEqual(eh.pre_price, 239.5)
        self.assertEqual(eh.pre_change_rate, -10.2)
        self.assertEqual(eh.after_price, 269.25)
        self.assertEqual(eh.prev_close, 266.71)
        self.assertEqual(runner.commands[0][1], "-c")


    def test_get_financials_distills_quality_and_breakdown(self):
        runner = FakeRunner({
            "get_financials_statements.py": STATEMENTS_PAYLOAD,
            "get_financials_revenue_breakdown.py": BREAKDOWN_PAYLOAD,
        })
        fin = _fetcher(runner).get_financials("HK.00700")

        self.assertEqual(fin.period, "2026/Q1")        # latest by date_time, not the FY row
        self.assertEqual(fin.revenue_growth, 9.1)
        self.assertEqual(fin.eps_growth, 22.4)
        self.assertEqual(fin.gross_margin, 56.5)       # 113000 / 200000
        self.assertEqual(fin.net_margin, 29.5)         # 59000 / 200000
        self.assertEqual(len(fin.revenue_breakdown), 4)
        self.assertEqual(fin.revenue_breakdown[0], ("Value-added services", 49.1))  # type-1 group, not geographic

    def test_get_financials_returns_none_when_no_reports(self):
        runner = FakeRunner({"get_financials_statements.py": {"code": "HK.00700", "data": {"report_list": []}}})
        self.assertIsNone(_fetcher(runner).get_financials("HK.00700"))


if __name__ == "__main__":
    unittest.main()
