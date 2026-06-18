import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.cli import main


class CliTests(unittest.TestCase):
    def test_dry_run_analyze_prints_recommendation_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recommendation.json"
            exit_code = main(["dry-run", "--code", "SZ.002463", "--output", str(output)])

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["code"], "SZ.002463")
        self.assertIn(payload["label"], {"hold", "trim-on-strength", "risk-reduce", "strong-watch", "low-buy-zone", "avoid"})
        self.assertIn("investment hypothesis", payload["analyst_hypothesis"])


if __name__ == "__main__":
    unittest.main()
