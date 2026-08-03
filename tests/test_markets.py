import unittest

from tools.stock_skills.markets import (
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


if __name__ == "__main__":
    unittest.main()
