import copy
import unittest

from tools.stock_skills.point_in_time import (
    EvidenceStamp,
    ModelRelease,
    PointInTimeInput,
    bind_shadow_pair,
    point_in_time_input_from_record,
)


class PointInTimeTests(unittest.TestCase):
    def _stamp(self, component="snapshot", status="available", observed_at=None):
        missing = status == "missing"
        conflicting = status == "conflicting"
        return EvidenceStamp(
            component=component,
            status=status,
            source=None if missing else "futu-opend",
            observed_at=None if missing else (observed_at or "2026-08-03T10:00:00+08:00"),
            published_at=None,
            captured_at="2026-08-03T10:00:02+08:00",
            source_ref=None if missing else "futu:snapshot",
            adjustment_basis=None if missing else "none",
            conflict_refs=("futu:snapshot", "exchange:filing") if conflicting else (),
        )

    def _package(self, **overrides):
        arguments = {
            "code": "HK.00700",
            "security_id": "listing:HK.00700",
            "company_id": "security:HK.00700",
            "market": "HK",
            "as_of": "2026-08-03T10:00:00+08:00",
            "captured_at": "2026-08-03T10:00:02+08:00",
            "session_phase": "intraday",
            "universe_version": "universe:test",
            "identity_version": "identity:test",
            "payload": {},
            "evidence": (self._stamp(),),
        }
        arguments.update(overrides)
        return PointInTimeInput.build(**arguments)

    def test_package_digest_is_order_stable_and_source_payload_is_copied(self):
        source = {"snapshot": {"last_price": 445.0, "code": "HK.00700"}}
        first = self._package(payload=source)
        second = self._package(
            payload={"snapshot": {"code": "HK.00700", "last_price": 445.0}}
        )
        source["snapshot"]["last_price"] = 999.0

        self.assertEqual(first.input_digest, second.input_digest)
        self.assertEqual(first.package_id, second.package_id)
        self.assertEqual(first.payload()["snapshot"]["last_price"], 445.0)

    def test_future_observation_and_future_publication_are_rejected(self):
        future_observation = self._stamp(observed_at="2026-08-03T10:00:01+08:00")
        future_publication = EvidenceStamp(
            component="financials",
            status="available",
            source="official-filing",
            observed_at="2026-06-30T00:00:00+08:00",
            published_at="2026-08-03T10:00:01+08:00",
            captured_at="2026-08-03T10:00:02+08:00",
            source_ref="exchange:filing",
            adjustment_basis="reported",
            conflict_refs=(),
        )

        for stamp in (future_observation, future_publication):
            with self.subTest(component=stamp.component):
                with self.assertRaisesRegex(ValueError, "after package as_of"):
                    self._package(evidence=(stamp,))

    def test_missing_stale_and_conflicting_are_preserved_as_states(self):
        package = self._package(
            evidence=(
                self._stamp("capital", "stale"),
                self._stamp("financials", "missing"),
                self._stamp("identity", "conflicting"),
            )
        )

        self.assertEqual(package.missing_components, ("financials",))
        self.assertEqual(package.stale_components, ("capital",))
        self.assertEqual(package.conflicting_components, ("identity",))

    def test_champion_and_challenger_bind_to_identical_input(self):
        package = self._package()
        champion, challenger = bind_shadow_pair(
            package,
            ModelRelease(
                "stock-analysis-v6", "logic-first-method-evidence-v6", "recommendation-v6"
            ),
            ModelRelease(
                "stock-analysis-v7-shadow",
                "stock-analysis-v7-shadow-v1",
                "recommendation-v7-shadow-v1",
            ),
        )

        self.assertEqual(champion.input_package_id, challenger.input_package_id)
        self.assertEqual(champion.input_digest, challenger.input_digest)
        self.assertNotEqual(champion.model_release, challenger.model_release)

    def test_record_roundtrip_recomputes_and_rejects_tampering(self):
        package = self._package(payload={"snapshot": {"last_price": 445.0}})
        record = package.to_record()
        self.assertEqual(point_in_time_input_from_record(record), package)

        tampered = copy.deepcopy(record)
        tampered["payload"]["snapshot"]["last_price"] = 999.0
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            point_in_time_input_from_record(tampered)

        malformed_id = copy.deepcopy(record)
        malformed_id["package_id"] = "input:not-the-digest"
        with self.assertRaisesRegex(ValueError, "package_id mismatch"):
            point_in_time_input_from_record(malformed_id)

    def test_duplicate_components_and_impossible_capture_times_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate evidence component"):
            self._package(evidence=(self._stamp(), self._stamp()))

        late_capture = EvidenceStamp(
            component="snapshot",
            status="available",
            source="futu-opend",
            observed_at="2026-08-03T09:59:59+08:00",
            published_at=None,
            captured_at="2026-08-03T10:00:03+08:00",
            source_ref="futu:snapshot",
            adjustment_basis="none",
        )
        with self.assertRaisesRegex(ValueError, "after package captured_at"):
            self._package(evidence=(late_capture,))

    def test_bar_payload_rejects_any_bar_after_as_of(self):
        with self.assertRaisesRegex(ValueError, "bar is after package as_of"):
            PointInTimeInput.build_market_payload(
                code="US.NVDA",
                security_id="listing:US.NVDA",
                company_id="security:US.NVDA",
                market="US",
                as_of="2026-08-03T16:00:00-04:00",
                captured_at="2026-08-03T16:00:02-04:00",
                session_phase="after-close",
                universe_version="universe:test",
                identity_version="identity:test",
                snapshot={"timestamp": "2026-08-03T16:00:00-04:00", "last_price": 100.0},
                daily_bars=[
                    {"time": "2026-08-03T00:00:00-04:00", "close": 100.0},
                    {"time": "2026-08-04T00:00:00-04:00", "close": 101.0},
                ],
                intraday_bars=[],
                daily_adjustment_basis="forward-adjusted",
                intraday_adjustment_basis="none",
                intraday_bar_interval="5m",
                evidence=(
                    EvidenceStamp(
                        component="snapshot",
                        status="available",
                        source="futu-opend",
                        observed_at="2026-08-03T16:00:00-04:00",
                        published_at=None,
                        captured_at="2026-08-03T16:00:02-04:00",
                        source_ref="futu:snapshot",
                        adjustment_basis="none",
                        conflict_refs=(),
                    ),
                ),
            )

    def test_market_payload_requires_explicit_bar_adjustment_basis(self):
        with self.assertRaisesRegex(ValueError, "adjustment basis"):
            PointInTimeInput.build_market_payload(
                code="HK.00700",
                security_id="listing:HK.00700",
                company_id="security:HK.00700",
                market="HK",
                as_of="2026-08-03T10:00:00+08:00",
                captured_at="2026-08-03T10:00:02+08:00",
                session_phase="intraday",
                universe_version="universe:test",
                identity_version="identity:test",
                snapshot=None,
                daily_bars=[],
                intraday_bars=[],
                daily_adjustment_basis=None,
                intraday_adjustment_basis="none",
                intraday_bar_interval="5m",
                evidence=(),
            )

    def _hk_payload(self, **overrides):
        arguments = {
            "code": "HK.00700",
            "security_id": "listing:HK.00700",
            "company_id": "security:HK.00700",
            "market": "HK",
            "as_of": "2026-08-03T10:00:00+08:00",
            "captured_at": "2026-08-03T10:00:02+08:00",
            "session_phase": "intraday",
            "universe_version": "universe:test",
            "identity_version": "identity:test",
            "snapshot": None,
            "daily_bars": [],
            "intraday_bars": [],
            "daily_adjustment_basis": "forward-adjusted",
            "intraday_adjustment_basis": "none",
            "intraday_bar_interval": "5m",
            "evidence": (),
        }
        arguments.update(overrides)
        return PointInTimeInput.build_market_payload(**arguments)

    def test_still_forming_session_bar_is_rejected_until_its_interval_closes(self):
        forming_day = [{"time": "2026-08-03T00:00:00+08:00", "close": 445.0}]
        with self.assertRaisesRegex(ValueError, "daily bar is incomplete at package as_of"):
            self._hk_payload(daily_bars=forming_day)

        after_close = self._hk_payload(
            as_of="2026-08-03T16:00:00+08:00",
            captured_at="2026-08-03T16:00:02+08:00",
            session_phase="after-close",
            daily_bars=forming_day,
        )
        self.assertEqual(len(after_close.payload()["daily_bars"]["bars"]), 1)
        self.assertEqual(after_close.payload()["daily_bars"]["interval"], "1d")

    def test_five_minute_bar_is_usable_only_after_its_interval_elapses(self):
        forming = [{"time": "2026-08-03T09:55:00+08:00", "close": 445.0}]
        with self.assertRaisesRegex(ValueError, "intraday bar is incomplete at package as_of"):
            self._hk_payload(
                as_of="2026-08-03T09:57:00+08:00",
                captured_at="2026-08-03T09:57:02+08:00",
                intraday_bars=forming,
            )

        complete = self._hk_payload(intraday_bars=forming)
        self.assertEqual(complete.payload()["intraday_bars"]["bars"], forming)
        self.assertEqual(complete.payload()["intraday_bars"]["interval"], "5m")

    def test_intraday_interval_must_be_explicit_and_supported(self):
        with self.assertRaisesRegex(ValueError, "Unsupported bar interval"):
            self._hk_payload(intraday_bar_interval="4h")

    def test_bar_interval_is_part_of_the_input_digest(self):
        five_minute = self._hk_payload(intraday_bar_interval="5m")
        one_minute = self._hk_payload(intraday_bar_interval="1m")
        self.assertNotEqual(five_minute.input_digest, one_minute.input_digest)


if __name__ == "__main__":
    unittest.main()
