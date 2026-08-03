import json
import unittest

from tools.stock_skills.foundation_migrate import migrate_universes


class FoundationMigrationTests(unittest.TestCase):
    def test_migration_is_deterministic_and_uses_only_explicit_company_overrides(self):
        universes = {
            "CN": {
                "schema_version": "opportunity-universe-v1",
                "market": "CN",
                "as_of": "2026-07-21T16:00:00+08:00",
                "source": "fixture",
                "sectors": [
                    {
                        "key": "chips",
                        "name": "芯片",
                        "representative": "SH.688981",
                        "benchmark": "SH.000300",
                        "members": [
                            {"code": "SH.688981", "name": "中芯国际", "role": "leader"}
                        ],
                    }
                ],
            },
            "HK": {
                "schema_version": "opportunity-universe-v1",
                "market": "HK",
                "as_of": "2026-07-21T16:00:00+08:00",
                "source": "fixture",
                "sectors": [
                    {
                        "key": "chips",
                        "name": "芯片",
                        "representative": "HK.00981",
                        "benchmark": "HK.800700",
                        "members": [
                            {
                                "code": "HK.00981",
                                "name": "中芯国际",
                                "role": "leader",
                                "shared_identity": "SMIC",
                            }
                        ],
                    }
                ],
            },
        }
        overrides = {"company:smic": ["SH.688981", "HK.00981"]}

        first_universes, first_registry = migrate_universes(
            universes, overrides, published_at="2026-08-03T18:00:00+08:00"
        )
        second_universes, second_registry = migrate_universes(
            universes, overrides, published_at="2026-08-03T18:00:00+08:00"
        )

        self.assertEqual(first_universes, second_universes)
        self.assertEqual(first_registry.to_record(), second_registry.to_record())
        self.assertEqual(
            first_registry.resolve("SH.688981", "2026-08-04T10:00:00+08:00").company_id,
            "company:smic",
        )
        self.assertEqual(
            first_registry.resolve("HK.00981", "2026-08-04T10:00:00+08:00").company_id,
            "company:smic",
        )
        self.assertEqual(first_universes["CN"]["schema_version"], "opportunity-universe-v2")
        self.assertEqual(
            first_universes["CN"]["identity_registry_version"], first_registry.version_id
        )
        self.assertEqual(
            first_universes["HK"]["sectors"][0]["members"][0]["shared_identity"],
            "SMIC",
        )

        persisted = json.loads(json.dumps(first_universes))
        remigrated, _ = migrate_universes(
            persisted, overrides, published_at="2026-08-03T18:00:00+08:00"
        )
        self.assertEqual(persisted, remigrated)

    def test_classifies_members_and_benchmark_only_codes(self):
        universes = {
            "US": {
                "schema_version": "opportunity-universe-v1",
                "market": "US",
                "as_of": "2026-07-21T16:00:00-04:00",
                "source": "fixture",
                "sectors": [
                    {
                        "key": "chips",
                        "name": "Chips",
                        "representative": "US.SMH",
                        "benchmark": "US.QQQ",
                        "members": [
                            {"code": "US.SMH", "name": "SMH", "role": "etf"},
                            {"code": "US.NVDA", "name": "NVIDIA", "role": "leader"},
                        ],
                    }
                ],
            }
        }

        migrated, registry = migrate_universes(
            universes, {}, published_at="2026-08-03T18:00:00+08:00"
        )

        identities = {item.code: item for item in registry.identities}
        self.assertEqual(identities["US.SMH"].instrument_type, "unleveraged-etf")
        self.assertEqual(identities["US.NVDA"].instrument_type, "ordinary-stock")
        self.assertEqual(identities["US.QQQ"].instrument_type, "benchmark-index")
        self.assertEqual(identities["US.QQQ"].security_id, "benchmark:US.QQQ")
        self.assertEqual(identities["US.SMH"].currency, "USD")
        self.assertEqual(
            migrated["US"]["sectors"][0]["members"][0]["member_from"],
            "2026-07-21T16:00:00-04:00",
        )

    def test_duplicate_override_assignment_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "assigned to multiple company IDs"):
            migrate_universes(
                {},
                {"company:first": ["HK.00700"], "company:second": ["HK.00700"]},
                published_at="2026-08-03T18:00:00+08:00",
            )


if __name__ == "__main__":
    unittest.main()
