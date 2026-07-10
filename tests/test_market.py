import unittest

from tools.stock_skills import market
from tools.stock_skills.market import analyze_market
from tools.stock_skills.models import MarketSnapshot


def index(code, last, prev):
    return MarketSnapshot(code, code, last, last, last, last, prev, 1, 1.0, "2026-06-18T15:00:00+08:00")


class MarketTests(unittest.TestCase):
    def test_market_evidence_requires_recognized_code(self):
        snapshots = {"HK.800000": index("HK.800000", 25_000.0, 24_900.0)}

        self.assertFalse(market.has_market_evidence(snapshots))

    def test_market_evidence_requires_usable_previous_close(self):
        snapshots = {"US.SPY": index("US.SPY", 750.0, 0.0)}

        self.assertFalse(market.has_market_evidence(snapshots))

    def test_flat_recognized_index_is_market_evidence(self):
        snapshots = {"US.SPY": index("US.SPY", 750.0, 750.0)}

        self.assertTrue(market.has_market_evidence(snapshots))

    def test_rising_indices_are_risk_on(self):
        result = analyze_market({"SH.000001": index("SH.000001", 4130.0, 4090.0), "SZ.399006": index("SZ.399006", 4260.0, 4200.0)})

        self.assertGreater(result.score, 60)
        self.assertEqual(result.regime, "risk-on")

    def test_falling_indices_are_risk_off(self):
        result = analyze_market({"SH.000001": index("SH.000001", 4040.0, 4108.0), "SZ.399006": index("SZ.399006", 4100.0, 4200.0)})

        self.assertLess(result.score, 42)
        self.assertEqual(result.regime, "risk-off")

    def test_no_indices_is_neutral(self):
        result = analyze_market({})

        self.assertEqual(result.score, 50.0)
        self.assertEqual(result.regime, "neutral")


if __name__ == "__main__":
    unittest.main()
