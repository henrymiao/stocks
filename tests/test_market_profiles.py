import unittest

from tools.stock_skills.market_profiles import resolve_market_profile


class MarketProfileTests(unittest.TestCase):
    def test_routes_three_equity_markets_without_reusing_us_assumptions(self):
        us = resolve_market_profile("US.NVDA")
        a_share = resolve_market_profile("SH.600309")
        hk = resolve_market_profile("HK.00700")

        self.assertEqual(us.profile_id, "us-equity-v1")
        self.assertEqual(a_share.profile_id, "a-share-equity-v1")
        self.assertEqual(hk.profile_id, "hk-equity-v1")
        self.assertEqual(a_share.benchmark_codes, ("SH.000001", "SZ.399006"))
        self.assertNotEqual(us.buy_zone_extension_pct, a_share.buy_zone_extension_pct)
        self.assertEqual(a_share.price_limit_policy, "board-aware")
        self.assertEqual(hk.lot_policy, "board-lot")

    def test_unknown_prefix_is_non_actionable_instead_of_us_default(self):
        profile = resolve_market_profile("CC.BTCUSD", asset_type="crypto")
        self.assertEqual(profile.profile_id, "unknown-market-v1")
        self.assertEqual(profile.allowed_valuation_methods, ())


if __name__ == "__main__":
    unittest.main()
