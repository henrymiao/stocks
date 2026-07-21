import unittest

from tools.stock_skills.method_models import EvidenceValue
from tools.stock_skills.provenance import resolve_evidence


class ProvenanceTests(unittest.TestCase):
    def test_opend_wins_and_material_disagreement_is_exposed(self):
        live = EvidenceValue(
            100.0,
            "opend",
            "2026-07-21T10:00:00+08:00",
            "live",
            1.0,
            "futu:snapshot",
        )
        manual = EvidenceValue(
            92.0,
            "official-manual",
            "2026-07-21",
            "current",
            0.9,
            "exchange:filing",
        )

        resolved, conflict = resolve_evidence(
            "last_price",
            live,
            manual,
            relative_tolerance=0.05,
        )

        self.assertEqual(resolved, live)
        self.assertEqual(conflict, "last_price:opend!=official-manual")

    def test_unknown_never_becomes_zero_or_neutral(self):
        resolved, conflict = resolve_evidence("eps_growth", None, None)
        self.assertIsNone(resolved)
        self.assertIsNone(conflict)


if __name__ == "__main__":
    unittest.main()
