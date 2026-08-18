import unittest

from tools.stock_skills.models import ExtendedHoursSnapshot


def _snapshot(**kw):
    base = dict(
        code="US.SMH", prev_close=None, pre_price=None, pre_change_rate=None,
        pre_volume=None, after_price=None, after_change_rate=None, after_volume=None,
    )
    base.update(kw)
    return ExtendedHoursSnapshot(**base)


class ExtendedHoursBaselineTests(unittest.TestCase):
    """The feed's `prev_close_price` lags during the pre-market session.

    On 2026-08-18 it returned the 08-14 close for every US name while both change rates
    were measured against 08-17: SMH read 587.82 against a real reference of 594.07, so a
    -3.23% pre-market print looked like -2.20%. It refreshed to 594.07 later the same
    morning, which makes the error a timing window rather than a constant offset -- the
    kind that is right often enough to be trusted and wrong exactly when it is read early.
    """

    def test_the_baseline_is_recovered_from_the_change_rate_not_the_feed(self):
        eh = _snapshot(prev_close=587.82, pre_price=574.91, pre_change_rate=-3.225)
        self.assertAlmostEqual(eh.baseline(), 594.07, places=1)
        self.assertNotAlmostEqual(eh.baseline(), eh.prev_close, places=1)

    def test_after_hours_carries_the_baseline_when_there_is_no_pre_market(self):
        eh = _snapshot(prev_close=587.82, after_price=595.0, after_change_rate=0.156)
        self.assertAlmostEqual(eh.baseline(), 594.07, places=1)

    def test_pre_market_wins_when_both_sessions_have_traded(self):
        # Pre-market is the later of the two, so it reflects the newer reference.
        eh = _snapshot(prev_close=1.0, pre_price=110.0, pre_change_rate=10.0,
                       after_price=204.0, after_change_rate=2.0)
        self.assertAlmostEqual(eh.baseline(), 100.0, places=4)

    def test_the_feed_value_is_the_fallback_when_neither_session_traded(self):
        self.assertEqual(_snapshot(prev_close=587.82).baseline(), 587.82)

    def test_a_total_wipeout_rate_cannot_divide_by_zero(self):
        eh = _snapshot(prev_close=50.0, pre_price=0.0, pre_change_rate=-100.0)
        self.assertEqual(eh.baseline(), 50.0)

    def test_no_data_at_all_yields_none(self):
        self.assertIsNone(_snapshot().baseline())


if __name__ == "__main__":
    unittest.main()
