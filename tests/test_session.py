import unittest

from tools.stock_skills.session import classify_session_phase


class SessionTests(unittest.TestCase):
    def test_us_weekday_phases(self):
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T09:00:00"), "pre-open")
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T10:00:00"), "intraday")
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T17:00:00"), "after-close")

    def test_sz_lunch_is_midday_break(self):
        self.assertEqual(classify_session_phase("SZ.002463", "2026-07-08T12:00:00"), "midday-break")

    def test_hk_weekend_is_closed(self):
        self.assertEqual(classify_session_phase("HK.00700", "2026-07-11T10:00:00"), "closed")

    def test_crypto_weekend_is_continuous(self):
        self.assertEqual(classify_session_phase("CC.BTC", "2026-07-11T10:00:00"), "continuous")

    def test_us_open_and_close_boundaries(self):
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T09:30:00"), "intraday")
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T16:00:00"), "after-close")

    def test_aware_timestamp_is_converted_to_market_timezone(self):
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T14:00:00+00:00"), "intraday")


if __name__ == "__main__":
    unittest.main()
