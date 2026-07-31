import unittest

from tools.stock_skills.entry_zone import (
    build_entry_zone,
    entry_zone_from_recommendation,
    resistance_room_ceiling,
)


class ResistanceCeilingTests(unittest.TestCase):
    def test_ceiling_satisfies_the_gate_it_solves(self):
        resistance, stop, minimum = 40.07, 38.95, 1.8
        ceiling = resistance_room_ceiling(resistance, stop, minimum)

        # At the ceiling the room is exactly the minimum, so the gate just passes.
        room = (resistance - ceiling) / (ceiling - stop)
        self.assertAlmostEqual(room, minimum, places=4)

    def test_a_penny_above_the_ceiling_fails_the_gate(self):
        resistance, stop, minimum = 40.07, 38.95, 1.8
        ceiling = resistance_room_ceiling(resistance, stop, minimum)
        higher = ceiling + 0.05

        self.assertLess((resistance - higher) / (higher - stop), minimum)

    def test_no_ceiling_when_structure_is_too_tight(self):
        # Resistance sits below the stop: no price can have room above it.
        self.assertIsNone(resistance_room_ceiling(38.0, 38.95, 1.8))

    def test_no_ceiling_without_a_positive_minimum(self):
        self.assertIsNone(resistance_room_ceiling(40.07, 38.95, 0.0))


class EntryZoneTests(unittest.TestCase):
    def test_pullback_distance_is_reported_for_a_price_blocked_candidate(self):
        zone = build_entry_zone(
            code="SH.600036",
            horizon="swing",
            current_price=40.55,
            resistance_levels=[41.26],
            stop=38.95,
            minimum_resistance_r=2.5,
            gates_failed=("resistance-room",),
        )

        self.assertIsNotNone(zone.entry_ceiling)
        self.assertLess(zone.entry_ceiling, 40.55)
        self.assertLess(zone.distance_pct, 0)  # needs a pullback
        self.assertTrue(zone.actionable)       # nothing but price is blocking

    def test_non_price_gates_make_the_zone_non_actionable(self):
        zone = build_entry_zone(
            code="SH.601899",
            horizon="swing",
            current_price=32.95,
            resistance_levels=[33.68],
            stop=31.03,
            minimum_resistance_r=2.5,
            gates_failed=("resistance-room", "market-regime", "volume-confirmation"),
        )

        self.assertIsNotNone(zone.entry_ceiling)
        self.assertEqual(zone.non_price_gates, ("market-regime", "volume-confirmation"))
        self.assertFalse(zone.actionable)  # a pullback alone would not authorize it

    def test_breakout_candidate_without_overhead_resistance_has_no_zone(self):
        zone = build_entry_zone(
            code="US.SMH",
            horizon="swing",
            current_price=615.0,
            resistance_levels=[540.0],  # all below price
            stop=560.0,
            minimum_resistance_r=2.5,
            gates_failed=("resistance-room",),
        )

        self.assertIsNone(zone.entry_ceiling)
        self.assertFalse(zone.actionable)

    def test_zone_is_built_from_a_serialized_recommendation(self):
        payload = {
            "code": "US.SMH",
            "entry_price": 538.9,
            "resistance_levels": [561.0, 586.89],
            "exit_plan": {"initial_stop": 490.4},
            "strategy_assessment": {
                "horizon": "swing",
                "gates_failed": ["resistance-room"],
                "gates_missing": ["entry-trigger"],
            },
        }

        zone = entry_zone_from_recommendation(payload)

        self.assertEqual(zone.code, "US.SMH")
        self.assertEqual(zone.resistance, 561.0)
        self.assertEqual(zone.minimum_resistance_r, 2.5)  # swing default
        self.assertIsNotNone(zone.entry_ceiling)

    def test_missing_price_yields_no_zone(self):
        self.assertIsNone(entry_zone_from_recommendation({"code": "X", "entry_price": 0}))


if __name__ == "__main__":
    unittest.main()
