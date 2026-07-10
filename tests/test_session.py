import unittest

from tools.stock_skills.session import classify_session_phase


class SessionTests(unittest.TestCase):
    def test_us_weekday_phases(self):
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T09:00:00"), "pre-open")
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T10:00:00"), "intraday")
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T17:00:00"), "after-close")

    def test_exchange_prefix_is_case_insensitive(self):
        self.assertEqual(classify_session_phase("us.AAPL", "2026-07-08T12:00:00"), "intraday")

    def test_unsupported_or_malformed_codes_raise_value_error(self):
        for code in ("XX.WHAT", "US"):
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    classify_session_phase(code, "2026-07-08T10:00:00")

    def test_hk_weekend_is_closed(self):
        self.assertEqual(classify_session_phase("HK.00700", "2026-07-11T10:00:00"), "closed")

    def test_crypto_weekend_is_continuous(self):
        self.assertEqual(classify_session_phase("CC.BTC", "2026-07-11T10:00:00"), "continuous")

    def test_us_open_and_close_boundaries(self):
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T09:30:00"), "intraday")
        self.assertEqual(classify_session_phase("US.AAPL", "2026-07-08T16:00:00"), "after-close")

    def test_aware_timestamp_is_converted_to_us_market_timezone(self):
        cases = (
            ("2026-07-08T13:00:00+00:00", "pre-open"),
            ("2026-01-07T14:00:00+00:00", "pre-open"),
        )
        for timestamp, expected in cases:
            with self.subTest(timestamp=timestamp):
                self.assertEqual(classify_session_phase("US.AAPL", timestamp), expected)

    def test_hk_weekday_boundaries(self):
        cases = (
            ("09:29:59", "pre-open"),
            ("09:30:00", "intraday"),
            ("12:00:00", "midday-break"),
            ("13:00:00", "intraday"),
            ("16:00:00", "after-close"),
        )
        for clock, expected in cases:
            with self.subTest(clock=clock):
                self.assertEqual(classify_session_phase("HK.00700", f"2026-07-08T{clock}"), expected)

    def test_a_share_weekday_boundaries(self):
        cases = (
            ("09:29:59", "pre-open"),
            ("09:30:00", "intraday"),
            ("11:30:00", "midday-break"),
            ("13:00:00", "intraday"),
            ("15:00:00", "after-close"),
        )
        for code in ("SH.600519", "SZ.002463"):
            for clock, expected in cases:
                with self.subTest(code=code, clock=clock):
                    self.assertEqual(classify_session_phase(code, f"2026-07-08T{clock}"), expected)


if __name__ == "__main__":
    unittest.main()
