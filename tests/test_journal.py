import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.journal import append_record, ensure_journal, read_records


class JournalTests(unittest.TestCase):
    def test_append_and_read_jsonl_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "recommendations.jsonl"

            append_record(path, {"code": "SZ.002463", "label": "hold"})
            append_record(path, {"code": "US.NVDA", "label": "strong-watch"})
            records = read_records(path)

        self.assertEqual([record["code"] for record in records], ["SZ.002463", "US.NVDA"])

    def test_read_missing_journal_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            records = read_records(Path(tmpdir) / "missing.jsonl")

        self.assertEqual(records, [])


class JournalEnsureTests(unittest.TestCase):
    def test_ensure_journal_creates_empty_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "reviews.jsonl"

            ensure_journal(path)

            self.assertTrue(path.exists())
            self.assertEqual(read_records(path), [])


if __name__ == "__main__":
    unittest.main()
