import unittest

from tools.stock_skills.foundation_validation import validate_foundation
from tools.stock_skills.identity import IdentityRegistry, SecurityIdentity
from tools.stock_skills.universe import MarketUniverse, SectorUniverse, UniverseMember


class FoundationValidationTests(unittest.TestCase):
    def _registry(self):
        return IdentityRegistry(
            published_at="2026-08-03T08:00:00+08:00",
            identities=(
                SecurityIdentity(
                    "listing:HK.00700",
                    "company:tencent",
                    "HK.00700",
                    "腾讯控股",
                    "HK",
                    "ordinary-stock",
                    "HKD",
                    "2004-06-16T09:30:00+08:00",
                ),
                SecurityIdentity(
                    "benchmark:HK.800000",
                    "benchmark:hsi",
                    "HK.800000",
                    "恒生指数",
                    "HK",
                    "benchmark-index",
                    "HKD",
                    "1969-11-24T09:30:00+08:00",
                ),
            ),
        )

    def _universe(self, identity_version):
        return MarketUniverse(
            market="HK",
            as_of="2026-08-03T08:00:00+08:00",
            source="fixture",
            sectors=(
                SectorUniverse(
                    "internet",
                    "互联网",
                    "HK.00700",
                    "HK.800000",
                    (
                        UniverseMember(
                            "HK.00700",
                            "腾讯控股",
                            "leader",
                            1.0,
                            None,
                            "listing:HK.00700",
                            "2026-08-03T08:00:00+08:00",
                            None,
                        ),
                    ),
                ),
            ),
            schema_version="opportunity-universe-v2",
            published_at="2026-08-03T08:00:00+08:00",
            identity_registry_version=identity_version,
        )

    def test_valid_foundation_reports_active_investable_and_reference_counts(self):
        registry = self._registry()
        report = validate_foundation(
            registry,
            (self._universe(registry.version_id),),
            as_of="2026-08-03T10:00:00+08:00",
        )

        self.assertTrue(report["ready"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["markets"][0]["investable_members"], 1)
        self.assertEqual(report["markets"][0]["reference_codes"], 1)

    def test_missing_identity_and_version_mismatch_are_errors(self):
        registry = self._registry()
        universe = self._universe("identity:wrong")
        sector = universe.sectors[0]
        broken = MarketUniverse(
            market=universe.market,
            as_of=universe.as_of,
            source=universe.source,
            sectors=(
                SectorUniverse(
                    sector.key,
                    sector.name,
                    "HK.MISSING",
                    sector.benchmark,
                    sector.members
                    + (
                        UniverseMember(
                            "HK.MISSING",
                            "Missing",
                            "constituent",
                            1.0,
                            None,
                            "listing:HK.MISSING",
                            universe.as_of,
                            None,
                        ),
                    ),
                ),
            ),
            schema_version=universe.schema_version,
            published_at=universe.published_at,
            identity_registry_version=universe.identity_registry_version,
        )

        report = validate_foundation(
            registry, (broken,), as_of="2026-08-03T10:00:00+08:00"
        )

        self.assertFalse(report["ready"])
        self.assertTrue(any("identity registry version" in error for error in report["errors"]))
        self.assertTrue(any("HK.MISSING" in error for error in report["errors"]))

    def test_zero_active_members_and_future_publications_are_errors(self):
        registry = self._registry()
        universe = self._universe(registry.version_id)
        member = universe.sectors[0].members[0]
        expired = UniverseMember(
            member.code,
            member.name,
            member.role,
            member.weight,
            member.shared_identity,
            member.security_id,
            member.member_from,
            "2026-08-03T09:00:00+08:00",
        )
        future = MarketUniverse(
            market=universe.market,
            as_of=universe.as_of,
            source=universe.source,
            sectors=(
                SectorUniverse(
                    "internet", "互联网", expired.code, "HK.800000", (expired,)
                ),
            ),
            schema_version=universe.schema_version,
            published_at="2026-08-03T11:00:00+08:00",
            identity_registry_version=universe.identity_registry_version,
        )

        report = validate_foundation(
            registry, (future,), as_of="2026-08-03T10:00:00+08:00"
        )

        self.assertFalse(report["ready"])
        self.assertTrue(any("published after" in error for error in report["errors"]))
        self.assertTrue(any("zero active members" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
