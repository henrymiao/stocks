import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.config import load_watchlist, load_weights


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
                        "trend": 0.25,
                        "capital_flow": 0.20,
                        "sector": 0.15,
                        "cross_market": 0.15,
                        "macro_risk": 0.15,
                        "position_fit": 0.10,
                    }
                ),
                encoding="utf-8",
            )

            weights = load_weights(path)

        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertEqual(weights["trend"], 0.25)

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
                  "capital_flow": 0.20,
                  "sector": 0.15,
                  "cross_market": 0.15,
                  "macro_risk": 0.15,
                  "position_fit": 0.10
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
                  "capital_flow": 0.20,
                  "sector": 0.15,
                  "cross_market": 0.15,
                  "macro_risk": 0.15,
                  "position_fit": 0.10
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
                        "capital_flow": 0.20,
                        "sector": 0.15,
                        "cross_market": 0.15,
                        "macro_risk": 0.15,
                        "position_fit": 0.10,
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
                        "trend": "0.25",
                        "capital_flow": 0.20,
                        "sector": 0.15,
                        "cross_market": 0.15,
                        "macro_risk": 0.15,
                        "position_fit": 0.10,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_weights(path)


if __name__ == "__main__":
    unittest.main()
