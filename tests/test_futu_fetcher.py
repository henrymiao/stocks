import json
import unittest

from tools.stock_skills.futu_fetcher import FutuFetcher


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


def _fetcher(runner):
    return FutuFetcher(
        python_bin="/Users/shuren/.futu-venv/bin/python",
        skill_dir="/Users/shuren/.agents/skills/futuapi",
        runner=runner,
    )


class FutuFetcherTests(unittest.TestCase):
    def test_snapshot_uses_existing_futu_script(self):
        runner = FakeRunner()
        snapshot = _fetcher(runner).get_snapshot("SZ.002463")

        self.assertEqual(snapshot.code, "SZ.002463")
        self.assertEqual(snapshot.last_price, 147.9)
        self.assertIn("get_snapshot.py", runner.commands[0][1])

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
        runner = FakeRunner({"get_capital_flow.py": {"code": "SZ.002463", "data": []}})
        self.assertIsNone(_fetcher(runner).get_capital("SZ.002463"))

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


if __name__ == "__main__":
    unittest.main()
