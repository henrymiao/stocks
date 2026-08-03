import json
import tempfile
import unittest
from pathlib import Path

from tools.stock_skills.identity import (
    IdentityRegistry,
    SecurityIdentity,
    identity_registry_from_record,
    load_identity_registry,
    save_identity_registry,
)


class IdentityTests(unittest.TestCase):
    def test_cross_listings_share_company_but_not_security_identity(self):
        registry = identity_registry_from_record(
            {
                "schema_version": "security-identity-registry-v1",
                "published_at": "2026-08-01T18:00:00+08:00",
                "identities": [
                    {
                        "security_id": "listing:SH.688981",
                        "company_id": "company:smic",
                        "code": "SH.688981",
                        "name": "中芯国际",
                        "market": "CN",
                        "instrument_type": "ordinary-stock",
                        "currency": "CNY",
                        "active_from": "2020-07-16T09:30:00+08:00",
                    },
                    {
                        "security_id": "listing:HK.00981",
                        "company_id": "company:smic",
                        "code": "HK.00981",
                        "name": "中芯国际",
                        "market": "HK",
                        "instrument_type": "ordinary-stock",
                        "currency": "HKD",
                        "active_from": "2004-03-18T09:30:00+08:00",
                    },
                ],
            }
        )

        a_share = registry.resolve("SH.688981", "2026-08-03T10:00:00+08:00")
        h_share = registry.resolve("HK.00981", "2026-08-03T10:00:00+08:00")

        self.assertNotEqual(a_share.security_id, h_share.security_id)
        self.assertEqual(a_share.company_id, h_share.company_id)
        self.assertEqual(registry.company_codes("company:smic"), ("HK.00981", "SH.688981"))

    def test_only_ordinary_stocks_and_unleveraged_etfs_are_investable(self):
        stock = SecurityIdentity(
            "listing:HK.00700", "company:tencent", "HK.00700", "腾讯控股",
            "HK", "ordinary-stock", "HKD", "2004-06-16T09:30:00+08:00",
        )
        etf = SecurityIdentity(
            "listing:US.SPY", "fund:spy", "US.SPY", "SPDR S&P 500 ETF",
            "US", "unleveraged-etf", "USD", "1993-01-29T09:30:00-05:00",
        )
        index = SecurityIdentity(
            "benchmark:SH.000300", "benchmark:csi300", "SH.000300", "沪深300",
            "CN", "benchmark-index", "CNY", "2005-04-08T09:30:00+08:00",
        )

        self.assertTrue(stock.investable)
        self.assertTrue(etf.investable)
        self.assertFalse(index.investable)

    def test_future_and_ended_identity_cannot_resolve_at_as_of(self):
        registry = IdentityRegistry(
            published_at="2026-08-01T18:00:00+08:00",
            identities=(
                SecurityIdentity(
                    "listing:HK.FUTURE", "company:future", "HK.FUTURE", "Future",
                    "HK", "ordinary-stock", "HKD",
                    "2026-08-05T09:30:00+08:00", None,
                ),
                SecurityIdentity(
                    "listing:HK.ENDED", "company:ended", "HK.ENDED", "Ended",
                    "HK", "ordinary-stock", "HKD",
                    "2026-01-01T09:30:00+08:00", "2026-08-02T00:00:00+08:00",
                ),
            ),
        )

        for code in ("HK.FUTURE", "HK.ENDED"):
            with self.subTest(code=code), self.assertRaisesRegex(KeyError, "not active"):
                registry.resolve(code, "2026-08-03T10:00:00+08:00")

    def test_reissued_listing_code_resolves_by_activity_window(self):
        delisted = SecurityIdentity(
            "listing:US.XYZ@2015", "security:old-xyz", "US.XYZ", "Old XYZ",
            "US", "ordinary-stock", "USD",
            "2015-03-02T09:30:00-05:00", "2021-06-30T16:00:00-04:00",
        )
        reissued = SecurityIdentity(
            "listing:US.XYZ@2023", "security:new-xyz", "US.XYZ", "New XYZ",
            "US", "ordinary-stock", "USD",
            "2023-09-11T09:30:00-04:00", None,
        )
        registry = IdentityRegistry(
            published_at="2026-08-01T18:00:00-04:00",
            identities=(reissued, delisted),
        )

        self.assertEqual(
            registry.resolve("US.XYZ", "2018-05-04T10:00:00-04:00").company_id,
            "security:old-xyz",
        )
        self.assertEqual(
            registry.resolve("US.XYZ", "2026-08-03T10:00:00-04:00").company_id,
            "security:new-xyz",
        )
        with self.assertRaisesRegex(KeyError, "not active"):
            registry.resolve("US.XYZ", "2022-01-04T10:00:00-05:00")

    def test_overlapping_windows_for_one_code_are_rejected(self):
        first = SecurityIdentity(
            "listing:US.XYZ@2015", "security:old-xyz", "US.XYZ", "Old XYZ",
            "US", "ordinary-stock", "USD",
            "2015-03-02T09:30:00-05:00", "2023-12-31T16:00:00-05:00",
        )
        second = SecurityIdentity(
            "listing:US.XYZ@2023", "security:new-xyz", "US.XYZ", "New XYZ",
            "US", "ordinary-stock", "USD",
            "2023-09-11T09:30:00-04:00", None,
        )
        with self.assertRaisesRegex(ValueError, "overlapping windows for code US.XYZ"):
            IdentityRegistry(
                published_at="2026-08-01T18:00:00-04:00",
                identities=(first, second),
            )

        never_closed = SecurityIdentity(
            "listing:US.XYZ@open", "security:open-xyz", "US.XYZ", "Open XYZ",
            "US", "ordinary-stock", "USD",
            "2015-03-02T09:30:00-05:00", None,
        )
        with self.assertRaisesRegex(ValueError, "overlapping windows for code US.XYZ"):
            IdentityRegistry(
                published_at="2026-08-01T18:00:00-04:00",
                identities=(never_closed, second),
            )

    def test_duplicate_security_ids_are_still_rejected(self):
        duplicate = SecurityIdentity(
            "listing:US.SPY", "fund:spy", "US.SPY", "SPY", "US",
            "unleveraged-etf", "USD", "1993-01-29T09:30:00-05:00",
        )
        with self.assertRaisesRegex(ValueError, "duplicate security IDs"):
            IdentityRegistry(
                published_at="2026-08-01T18:00:00-04:00",
                identities=(duplicate, duplicate),
            )

    def test_registry_version_is_content_addressed_and_order_stable(self):
        base = {
            "schema_version": "security-identity-registry-v1",
            "published_at": "2026-08-01T18:00:00+08:00",
            "identities": [
                {
                    "security_id": "listing:US.SPY",
                    "company_id": "fund:spy",
                    "code": "US.SPY",
                    "name": "SPY",
                    "market": "US",
                    "instrument_type": "unleveraged-etf",
                    "currency": "USD",
                    "active_from": "1993-01-29T09:30:00-05:00",
                }
            ],
        }
        reordered = {
            "published_at": base["published_at"],
            "identities": [dict(reversed(list(base["identities"][0].items())))],
            "schema_version": base["schema_version"],
        }

        self.assertEqual(
            identity_registry_from_record(base).version_id,
            identity_registry_from_record(reordered).version_id,
        )

    def test_registry_roundtrip_recomputes_and_rejects_tampered_version(self):
        registry = IdentityRegistry(
            published_at="2026-08-01T18:00:00+08:00",
            identities=(
                SecurityIdentity(
                    "listing:US.SPY", "fund:spy", "US.SPY", "SPY", "US",
                    "unleveraged-etf", "USD", "1993-01-29T09:30:00-05:00",
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "identities.json"
            save_identity_registry(path, registry)
            self.assertEqual(load_identity_registry(path), registry)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["version_id"] = "identity:tampered"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "version_id mismatch"):
                load_identity_registry(path)


if __name__ == "__main__":
    unittest.main()
