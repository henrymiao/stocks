import unittest

from tools.stock_skills.markets import (
    bar_close_moment,
    market_close_time,
    market_currency,
    market_from_code,
    market_timezone,
    normalize_market,
)


class MarketContractTests(unittest.TestCase):
    def test_routes_cn_hk_us_prefixes_to_one_contract(self):
        self.assertEqual(market_from_code("SH.600309"), "CN")
        self.assertEqual(market_from_code("SZ.300750"), "CN")
        self.assertEqual(market_from_code("HK.00700"), "HK")
        self.assertEqual(market_from_code("US.NVDA"), "US")
        self.assertEqual(market_currency("CN"), "CNY")
        self.assertEqual(market_currency("HK"), "HKD")
        self.assertEqual(market_currency("US"), "USD")

    def test_uses_exchange_local_timezones_and_rejects_unknowns(self):
        self.assertEqual(str(market_timezone("CN")), "Asia/Shanghai")
        self.assertEqual(str(market_timezone("HK")), "Asia/Hong_Kong")
        self.assertEqual(str(market_timezone("US")), "America/New_York")
        with self.assertRaisesRegex(ValueError, "Unsupported market"):
            normalize_market("CC")
        with self.assertRaisesRegex(ValueError, "Malformed market code"):
            market_from_code("NVDA")

    def test_bar_close_uses_the_interval_end_not_its_start(self):
        self.assertEqual(str(market_close_time("CN")), "15:00:00")
        self.assertEqual(str(market_close_time("HK")), "16:00:00")

        daily = bar_close_moment("2026-08-03T00:00:00+08:00", "CN", "1d")
        self.assertEqual(daily.isoformat(), "2026-08-03T15:00:00+08:00")
        self.assertEqual(
            bar_close_moment("2026-08-03", "HK", "1d").isoformat(),
            "2026-08-03T16:00:00+08:00",
        )

        five_minute = bar_close_moment("2026-08-03T09:50:00-04:00", "US", "5m")
        self.assertEqual(five_minute.isoformat(), "2026-08-03T09:55:00-04:00")

        with self.assertRaisesRegex(ValueError, "Unsupported bar interval"):
            bar_close_moment("2026-08-03T09:50:00-04:00", "US", "4h")


if __name__ == "__main__":
    unittest.main()
