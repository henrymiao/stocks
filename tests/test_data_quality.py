import unittest

from tools.stock_skills.data_quality import COMPONENTS, assess_data_quality, detect_stale_components
from tools.stock_skills.models import CapitalSnapshot, MarketSnapshot


class DataQualityTests(unittest.TestCase):
    def test_live_staleness_uses_market_update_time_vs_capture_time(self):
        snapshot = MarketSnapshot(
            "US.TEST", "Test", 100.0, 100.0, 101.0, 99.0, 100.0, 1_000, 100_000.0,
            "2026-07-10T10:00:00-04:00", "2026-07-10T10:20:00-04:00",
        )
        capital = CapitalSnapshot(0, 0, 0, 0, 0, "2026-07-10T09:40:00-04:00")

        stale = detect_stale_components(snapshot, capital, "intraday")

        self.assertEqual(stale, frozenset({"trend", "capital_flow"}))

    def test_after_close_update_near_close_is_fresh(self):
        snapshot = MarketSnapshot(
            "US.TEST", "Test", 100.0, 100.0, 101.0, 99.0, 100.0, 1_000, 100_000.0,
            "2026-07-10T15:55:00-04:00", "2026-07-10T18:00:00-04:00",
        )

        self.assertEqual(detect_stale_components(snapshot, None, "after-close"), frozenset())

    def test_previous_close_is_expected_during_pre_open(self):
        snapshot = MarketSnapshot(
            "US.TEST", "Test", 100.0, 100.0, 101.0, 99.0, 100.0, 1_000, 100_000.0,
            "2026-07-09T16:00:00-04:00", "2026-07-10T08:00:00-04:00",
        )

        self.assertEqual(detect_stale_components(snapshot, None, "pre-open"), frozenset())

    def test_full_availability_is_fully_confident_and_entry_eligible(self):
        quality = assess_data_quality(
            {component: True for component in COMPONENTS},
            session_phase="intraday",
        )

        self.assertEqual(quality.confidence, 1.0)
        self.assertEqual(quality.available_components, COMPONENTS)
        self.assertEqual(quality.missing_components, ())
        self.assertEqual(quality.stale_components, ())
        self.assertEqual(quality.session_phase, "intraday")
        self.assertTrue(quality.entry_eligible)

    def test_missing_cross_market_and_macro_risk_reduce_confidence(self):
        availability = {component: True for component in COMPONENTS}
        availability["cross_market"] = False
        availability["macro_risk"] = False

        quality = assess_data_quality(availability, session_phase="pre-open")

        self.assertEqual(quality.confidence, 0.75)
        self.assertEqual(quality.missing_components, ("cross_market", "macro_risk"))
        self.assertFalse(quality.entry_eligible)

    def test_available_stale_component_gets_half_credit(self):
        quality = assess_data_quality(
            {component: True for component in COMPONENTS},
            session_phase="intraday",
            stale_components={"capital_flow"},
        )

        self.assertEqual(quality.confidence, 0.9375)
        self.assertEqual(quality.stale_components, ("capital_flow",))
        self.assertTrue(quality.entry_eligible)

    def test_missing_critical_trend_is_not_entry_eligible(self):
        availability = {component: True for component in COMPONENTS}
        availability["trend"] = False

        quality = assess_data_quality(availability, session_phase="intraday")

        self.assertEqual(quality.confidence, 0.875)
        self.assertFalse(quality.entry_eligible)

    def test_unknown_availability_components_are_rejected_in_sorted_order(self):
        with self.assertRaisesRegex(ValueError, r"alpha, zeta"):
            assess_data_quality(
                {"trend": True, "zeta": True, "alpha": False},
                session_phase="intraday",
            )

    def test_unknown_stale_components_are_rejected_in_sorted_order(self):
        with self.assertRaisesRegex(ValueError, r"alpha, zeta"):
            assess_data_quality(
                {component: True for component in COMPONENTS},
                session_phase="intraday",
                stale_components={"zeta", "alpha"},
            )

    def test_stale_but_missing_component_is_not_penalized_twice(self):
        availability = {component: True for component in COMPONENTS}
        availability["capital_flow"] = False

        quality = assess_data_quality(
            availability,
            session_phase="intraday",
            stale_components={"capital_flow"},
        )

        self.assertEqual(quality.confidence, 0.875)
        self.assertEqual(quality.missing_components, ("capital_flow",))
        self.assertEqual(quality.stale_components, ())

    def test_available_stale_critical_component_blocks_entry(self):
        quality = assess_data_quality(
            {component: True for component in COMPONENTS},
            session_phase="after-close",
            stale_components={"trend"},
        )

        self.assertEqual(quality.confidence, 0.9375)
        self.assertEqual(quality.stale_components, ("trend",))
        self.assertFalse(quality.entry_eligible)


if __name__ == "__main__":
    unittest.main()
