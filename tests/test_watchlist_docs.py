import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WatchlistDocumentationTests(unittest.TestCase):
    def test_skill_documents_method_evidence_contract_and_current_policy(self):
        skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        for module in (
            "method_models.py",
            "market_profiles.py",
            "swing_structure.py",
            "linkage.py",
            "valuation_scenarios.py",
            "thesis.py",
            "method_policy.py",
        ):
            self.assertIn(module, skill)
        self.assertIn("--method-inputs-json", skill)
        self.assertIn("recommendation-v6", skill)
        self.assertIn("logic-first-method-evidence-v6", skill)
        self.assertIn("260", skill)
        self.assertIn("positive method evidence", skill.lower())
        self.assertNotIn("logic-first-correlation-aware-v3", skill)

    def test_skill_and_usage_explain_canonical_bidirectional_scan(self):
        skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
        usage = (ROOT / "docs" / "self-evolving-stock-skills-usage.md").read_text(encoding="utf-8")

        for document in (skill, usage):
            self.assertIn("--deep-bottom", document)
            self.assertIn("position_status", document)
            self.assertIn("scan_policy", document)
            self.assertIn("core.json", document)
        self.assertIn("compatibility views", skill)
        self.assertIn("兼容视图", usage)


if __name__ == "__main__":
    unittest.main()
