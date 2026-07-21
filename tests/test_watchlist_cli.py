import subprocess
import sys
import unittest
from pathlib import Path

from tools.stock_skills.scan_watchlist import _analysis_command


ROOT = Path(__file__).resolve().parents[1]


class WatchlistCliTests(unittest.TestCase):
    def test_swing_child_command_uses_dynamic_default_unless_bars_are_explicit(self):
        entry = {"code": "HK.00700", "valuation_profile": "growth"}
        base = _analysis_command(
            entry,
            "swing",
            "/tmp/out.json",
            "/tmp/shared.json",
            "data/watchlists/core.json",
            None,
        )
        short = _analysis_command(
            entry,
            "short",
            "/tmp/out.json",
            "/tmp/shared.json",
            "data/watchlists/core.json",
            None,
        )
        explicit = _analysis_command(
            entry,
            "swing",
            "/tmp/out.json",
            "/tmp/shared.json",
            "data/watchlists/core.json",
            90,
        )

        self.assertNotIn("--bars", base)
        self.assertEqual(short[short.index("--bars") + 1], "60")
        self.assertEqual(explicit[explicit.index("--bars") + 1], "90")

    def test_scan_help_documents_bottom_promotion(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "stock_skills" / "scan_watchlist.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--deep-bottom", completed.stdout)


if __name__ == "__main__":
    unittest.main()
