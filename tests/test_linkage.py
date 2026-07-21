import unittest

from tools.stock_skills.linkage import analyze_linkage
from tools.stock_skills.models import KLineBar


def _series(returns, scale=1.0):
    close = 100.0
    bars = [KLineBar("000", close, close, close, close, 1_000, 100_000.0)]
    for index, value in enumerate(returns, start=1):
        close *= 1.0 + value * scale
        bars.append(
            KLineBar(
                f"{index:03d}",
                close,
                close,
                close,
                close,
                1_000,
                close * 1_000,
            )
        )
    return bars


class LinkageTests(unittest.TestCase):
    def test_aligned_scaled_returns_produce_expected_correlation_and_beta(self):
        returns = [
            -0.006 - (index % 4) * 0.001
            if index % 3 == 0
            else 0.008 + (index % 5) * 0.001
            for index in range(65)
        ]
        result = analyze_linkage(_series(returns, 1.5), {"US.QQQ": _series(returns)})
        row = result.references[0]
        self.assertAlmostEqual(row.correlation_60d, 1.0, places=6)
        self.assertAlmostEqual(row.beta_60d, 1.5, places=1)
        self.assertAlmostEqual(row.downside_correlation, 1.0, places=6)

    def test_misaligned_or_short_history_is_unknown(self):
        result = analyze_linkage(
            _series([0.01] * 10),
            {"HK.800000": _series([0.01] * 10)},
        )
        self.assertEqual(result.references[0].stance, "unknown")
        self.assertEqual(result.coverage, 0.0)

    def test_correlation_regime_change_is_unstable(self):
        reference = [0.01 if index % 2 else -0.01 for index in range(70)]
        target = reference[:35] + [-value for value in reference[35:]]
        result = analyze_linkage(_series(target), {"SH.000001": _series(reference)})
        self.assertEqual(result.references[0].stability, "unstable")


if __name__ == "__main__":
    unittest.main()
