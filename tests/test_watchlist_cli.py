import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WatchlistCliTests(unittest.TestCase):
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
