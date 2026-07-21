import unittest

from tools.stock_skills.market_profiles import resolve_market_profile
from tools.stock_skills.models import KLineBar
from tools.stock_skills.swing_structure import analyze_swing_structure


def _bars(closes):
    return [
        KLineBar(
            str(index),
            close,
            close * 1.01,
            close * 0.99,
            close,
            1_000 + index * 10,
            close * 1_000,
        )
        for index, close in enumerate(closes)
    ]


class SwingStructureTests(unittest.TestCase):
    def test_insufficient_history_is_unknown(self):
        result = analyze_swing_structure(
            _bars([100.0] * 219),
            100.0,
            resolve_market_profile("HK.00700"),
        )
        self.assertEqual(result.stage, "unknown")
        self.assertEqual(result.gate_effect, "none")
        self.assertEqual(result.coverage, 0.0)

    def test_ordered_rising_average_template_is_stage_two(self):
        closes = [50.0 + index * 0.4 for index in range(240)]
        result = analyze_swing_structure(
            _bars(closes),
            closes[-1],
            resolve_market_profile("US.NVDA"),
        )
        self.assertEqual(result.stage, "stage-2")
        self.assertTrue(result.checklist["ma200-rising"])
        self.assertEqual(result.gate_effect, "none")

    def test_distribution_after_an_uptrend_is_stage_three(self):
        closes = [50.0 + index * 0.4 for index in range(220)]
        closes.extend(137.6 - index * 2.0 for index in range(20))
        result = analyze_swing_structure(
            _bars(closes),
            closes[-1],
            resolve_market_profile("HK.00700"),
        )
        self.assertEqual(result.stage, "stage-3")
        self.assertEqual(result.gate_effect, "reject-new-risk")

    def test_ordered_falling_average_template_rejects_new_swing_risk(self):
        closes = [150.0 - index * 0.4 for index in range(240)]
        result = analyze_swing_structure(
            _bars(closes),
            closes[-1],
            resolve_market_profile("SH.600309"),
        )
        self.assertEqual(result.stage, "stage-4")
        self.assertEqual(result.gate_effect, "reject-new-risk")

    def test_contracting_stage_one_near_pivot_is_probe_only(self):
        bars = _bars([100.0] * 210)
        ranges = ((94.0, 106.0), (96.0, 104.0), (98.0, 102.0))
        for group, (low, high) in enumerate(ranges):
            for offset in range(10):
                close = (low + high) / 2.0
                bars.append(
                    KLineBar(
                        f"base-{group}-{offset}",
                        close,
                        high,
                        low,
                        close,
                        1_000,
                        close * 1_000,
                    )
                )
        result = analyze_swing_structure(
            bars,
            102.0,
            resolve_market_profile("HK.00700"),
        )
        self.assertEqual(result.stage, "stage-1")
        self.assertEqual(result.contraction_count, 2)
        self.assertIsNotNone(result.buy_zone)
        self.assertEqual(result.gate_effect, "probe-only")


if __name__ == "__main__":
    unittest.main()
