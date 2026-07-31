import unittest

from tools.stock_skills import market
from tools.stock_skills.market import analyze_market
from tools.stock_skills.models import MarketSnapshot


def index(code, last, prev):
    return MarketSnapshot(code, code, last, last, last, last, prev, 1, 1.0, "2026-06-18T15:00:00+08:00")


class MarketTests(unittest.TestCase):
    def test_market_evidence_requires_recognized_code(self):
        snapshots = {"XX.UNKNOWN": index("XX.UNKNOWN", 25_000.0, 24_900.0)}

        self.assertFalse(market.has_market_evidence(snapshots))

    def test_hk_indices_are_recognized_market_evidence(self):
        # Regression: HK.800000/800700 were fetched for HK.* instruments but absent
        # from _MARKET_WEIGHTS, so every HK analysis scored a fake-neutral regime.
        snapshots = {
            "HK.800000": index("HK.800000", 24_562.0, 25_008.0),  # -1.78%
            "HK.800700": index("HK.800700", 4_623.0, 4_834.0),    # -4.37%
        }

        self.assertTrue(market.has_market_evidence(snapshots))
        analysis = analyze_market(snapshots)
        self.assertEqual(analysis.regime, "risk-off")
        self.assertLess(analysis.score, 42.0)

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

    def test_rotation_does_not_veto_the_side_winning_it(self):
        # 2026-07-30: ChiNext -3.97% while the SSE fell only 0.62%. The blended
        # regime read 37.4 (risk-off) and vetoed new risk in banks that were
        # rallying on exactly that rotation. A value name must not be judged
        # mainly by the growth index.
        snapshots = {
            "SH.000001": index("SH.000001", 3804.69, 3828.43),   # -0.62%
            "SZ.399006": index("SZ.399006", 3243.62, 3377.72),   # -3.97%
        }

        neutral = analyze_market(snapshots)
        value = analyze_market(snapshots, profile="value")
        growth = analyze_market(snapshots, profile="growth")

        # The tilt reduces how much a value name is punished by the growth index
        # (37.40 → 41.18 on this tape) and punishes a growth name more. It does
        # not by itself flip that day's verdict: the SSE was down too, so the
        # regime stays risk-off — the fix removes a distortion, not the headwind.
        self.assertGreater(value.score, neutral.score)
        self.assertLess(growth.score, neutral.score)
        self.assertGreater(value.score - growth.score, 5.0)

    def test_broad_selloff_still_reads_risk_off_for_value(self):
        # Both indices down hard: the tilt must not rescue anyone.
        snapshots = {
            "SH.000001": index("SH.000001", 3600.0, 3800.0),   # -5.3%
            "SZ.399006": index("SZ.399006", 3200.0, 3380.0),   # -5.3%
        }

        self.assertEqual(analyze_market(snapshots, profile="value").regime, "risk-off")

    def test_no_indices_is_neutral(self):
        result = analyze_market({})

        self.assertEqual(result.score, 50.0)
        self.assertEqual(result.regime, "neutral")


if __name__ == "__main__":
    unittest.main()
