import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.config import load_watchlist, load_weights, save_weights


class ConfigTests(unittest.TestCase):
    def test_load_watchlist_returns_enabled_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "core.json"
            path.write_text(
                json.dumps(
                    {
                        "watchlist": [
                            {"code": "SZ.002463", "name": "沪电股份", "enabled": True, "tags": ["pcb"]},
                            {"code": "US.SOXS", "name": "Direxion Daily Semiconductor Bear 3X", "enabled": False, "tags": ["hedge"]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            entries = load_watchlist(path)

        self.assertEqual([entry["code"] for entry in entries], ["SZ.002463"])
        self.assertEqual(entries[0]["tags"], ["pcb"])

    def test_load_weights_requires_all_components_and_sum_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weights.json"
            path.write_text(
                json.dumps(
                    {
                        "trend": 0.20,
                        "capital_flow": 0.13,
                        "sector": 0.14,
                        "cross_market": 0.11,
                        "macro_risk": 0.11,
                        "market_regime": 0.12,
                        "fundamental": 0.10,
                        "position_fit": 0.09,
                    }
                ),
                encoding="utf-8",
            )

            weights = load_weights(path)

        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertEqual(weights["trend"], 0.20)
        self.assertEqual(weights["fundamental"], 0.10)

    def test_load_weights_rejects_missing_component(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weights.json"
            path.write_text(json.dumps({"trend": 1.0}), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_weights(path)

    def test_load_weights_rejects_nan_component(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weights.json"
            path.write_text(
                """
                {
                  "trend": NaN,
                  "capital_flow": 0.13,
                  "sector": 0.14,
                  "cross_market": 0.11,
                  "macro_risk": 0.11,
                  "market_regime": 0.12,
                  "fundamental": 0.10,
                  "position_fit": 0.09
                }
                """,
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_weights(path)

    def test_load_weights_rejects_infinity_component(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weights.json"
            path.write_text(
                """
                {
                  "trend": Infinity,
                  "capital_flow": 0.13,
                  "sector": 0.14,
                  "cross_market": 0.11,
                  "macro_risk": 0.11,
                  "market_regime": 0.12,
                  "fundamental": 0.10,
                  "position_fit": 0.09
                }
                """,
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_weights(path)

    def test_load_weights_rejects_boolean_component(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weights.json"
            path.write_text(
                json.dumps(
                    {
                        "trend": True,
                        "capital_flow": 0.13,
                        "sector": 0.14,
                        "cross_market": 0.11,
                        "macro_risk": 0.11,
                        "market_regime": 0.12,
                        "fundamental": 0.10,
                        "position_fit": 0.09,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_weights(path)

    def test_load_weights_rejects_string_numeric_component(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "weights.json"
            path.write_text(
                json.dumps(
                    {
                        "trend": "0.22",
                        "capital_flow": 0.13,
                        "sector": 0.14,
                        "cross_market": 0.11,
                        "macro_risk": 0.11,
                        "market_regime": 0.12,
                        "fundamental": 0.10,
                        "position_fit": 0.09,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_weights(path)


    def test_save_weights_backs_up_and_records_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal_weights.json"
            original = {"trend": 0.20, "capital_flow": 0.13, "sector": 0.14, "cross_market": 0.11, "macro_risk": 0.11, "market_regime": 0.12, "fundamental": 0.10, "position_fit": 0.09}
            path.write_text(json.dumps(original), encoding="utf-8")

            updated = {"trend": 0.18, "capital_flow": 0.13, "sector": 0.14, "cross_market": 0.11, "macro_risk": 0.11, "market_regime": 0.12, "fundamental": 0.12, "position_fit": 0.09}
            entry = save_weights(path, updated, reason="fundamental failures")

            reloaded = load_weights(path)
            backup = load_weights(path.with_suffix(".json.bak"))
            history_lines = (Path(tmpdir) / "weight_history.jsonl").read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(reloaded["fundamental"], 0.12)
        self.assertEqual(backup, original)  # backup preserves the pre-change weights (reversible)
        self.assertEqual(entry["reason"], "fundamental failures")
        self.assertEqual(entry["previous"]["fundamental"], 0.10)
        self.assertEqual(len(history_lines), 1)

    def test_save_weights_rejects_invalid_sum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal_weights.json"
            bad = {"trend": 0.9, "capital_flow": 0.13, "sector": 0.14, "cross_market": 0.11, "macro_risk": 0.11, "market_regime": 0.12, "fundamental": 0.10, "position_fit": 0.09}
            with self.assertRaises(ValueError):
                save_weights(path, bad)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
