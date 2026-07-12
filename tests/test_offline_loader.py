import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.cli import main
from tools.stock_skills.offline_loader import load_bars, load_capital, load_snapshot


def _write(path, payload):
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


class OfflineLoaderTests(unittest.TestCase):
    def test_load_snapshot_and_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snap.json"
            kl = Path(tmp) / "kl.json"
            _write(snap, {"data": [{"code": "US.SOXL", "name": "SOXL", "last_price": 300.77,
                                    "open": 290.0, "high": 302.0, "low": 288.0, "prev_close": 295.0,
                                    "volume": 1000, "turnover": 3.0e8}]})
            _write(kl, {"data": [
                {"time": "2026-06-20", "open": 280, "high": 292, "low": 279, "close": 290, "volume": 1, "turnover": 1.0},
                {"time": "2026-06-23", "open": 290, "high": 302, "low": 288, "close": 300.77, "volume": 1, "turnover": 1.0},
            ]})
            s = load_snapshot(snap, code="US.SOXL")
            bars = load_bars(kl)

        self.assertEqual(s.code, "US.SOXL")
        self.assertEqual(s.last_price, 300.77)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1].close, 300.77)

    def test_load_snapshot_preserves_market_update_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "data": [
                            {
                                "code": "US.TEST",
                                "name": "Test",
                                "last_price": 100,
                                "open": 99,
                                "high": 101,
                                "low": 98,
                                "prev_close": 99,
                                "volume": 1000,
                                "turnover": 100000,
                                "update_time": "2026-07-10 15:59:00",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            snapshot = load_snapshot(path)

        self.assertEqual(snapshot.timestamp, "2026-07-10 15:59:00")
        self.assertIsNotNone(snapshot.captured_at)

    def test_load_capital_detects_intraday_acceleration(self):
        with tempfile.TemporaryDirectory() as tmp:
            cap = Path(tmp) / "cap.json"
            _write(cap, {"data": [
                {"in_flow": 100, "super_in_flow": 10, "big_in_flow": 20, "mid_in_flow": 30, "sml_in_flow": 40},
                {"in_flow": 300, "super_in_flow": 30, "big_in_flow": 60, "mid_in_flow": 90, "sml_in_flow": 120},
                {"in_flow": 600, "super_in_flow": 60, "big_in_flow": 120, "mid_in_flow": 180, "sml_in_flow": 240},
                {"in_flow": 1000, "super_in_flow": 100, "big_in_flow": 200, "mid_in_flow": 300, "sml_in_flow": 400},
            ]})
            c = load_capital(cap)

        self.assertIsNotNone(c)
        self.assertEqual(c.net_inflow, 1000)
        self.assertEqual(c.intraday_trend, "accelerating-in")

    def test_load_rows_raises_on_script_error_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "err.json"
            _write(bad, {"error": "无法连接 OpenD (127.0.0.1:11111)"})
            with self.assertRaises(RuntimeError):
                load_snapshot(bad)

    def test_analyze_offline_cli_produces_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snap.json"
            kl = Path(tmp) / "kl.json"
            out = Path(tmp) / "rec.json"
            journal = Path(tmp) / "j.jsonl"
            _write(snap, {"data": [{"code": "US.SOXL", "name": "SOXL", "last_price": 300.77,
                                    "open": 290.0, "high": 302.0, "low": 288.0, "prev_close": 295.0,
                                    "volume": 2000, "turnover": 6.0e8}]})
            # 25 rising bars so the MA20 trend regime is exercised.
            bars = [{"time": f"d{i}", "open": 100 + i, "high": 101 + i, "low": 99 + i,
                     "close": 100 + i, "volume": 1000, "turnover": 1.0} for i in range(25)]
            _write(kl, {"data": bars})

            code = main(["analyze-offline", "--code", "US.SOXL", "--snapshot", str(snap),
                         "--kline", str(kl), "--output", str(out), "--journal", str(journal)])
            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["code"], "US.SOXL")
        self.assertEqual(payload["entry_price"], 300.77)
        self.assertIn(payload["label"], {"strong-watch", "low-buy-zone", "hold", "trim-on-strength", "risk-reduce", "avoid"})
        refs = " ".join(payload["source_refs"])
        self.assertIn("offline:snapshot=", refs)
        # No live backdrop feed offline → those components flagged neutral.
        self.assertIn("sector: neutral default", refs)


if __name__ == "__main__":
    unittest.main()
