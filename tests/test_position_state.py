import unittest

from tools.stock_skills.exit_engine import transition_position
from tools.stock_skills.models import PositionStateSnapshot


class PositionStateTests(unittest.TestCase):
    def test_happy_path_and_exit_reasons(self):
        state = PositionStateSnapshot(state="flat", remaining_fraction=0.0)
        state = transition_position(state, "entry-filled")
        self.assertEqual(state.state, "entered")
        self.assertEqual(state.remaining_fraction, 1.0)

        state = transition_position(state, "tp1-filled", target_fraction=0.25)
        self.assertEqual(state.state, "profit-protected")
        self.assertEqual(state.remaining_fraction, 0.75)

        state = transition_position(state, "tp2-filled", target_fraction=0.25)
        self.assertEqual(state.state, "trend-runner")
        self.assertEqual(state.remaining_fraction, 0.5)

        state = transition_position(state, "trailing-stop")
        self.assertEqual(state.state, "exited")
        self.assertEqual(state.remaining_fraction, 0.0)
        self.assertEqual(state.exit_reason, "trailing-stop")

    def test_any_open_state_can_exit(self):
        for open_state in ("entered", "profit-protected", "trend-runner"):
            with self.subTest(open_state=open_state):
                state = PositionStateSnapshot(state=open_state, remaining_fraction=0.5)
                exited = transition_position(state, "thesis-invalidation")
                self.assertEqual(exited.state, "exited")
                self.assertEqual(exited.exit_reason, "thesis-invalidation")

    def test_entry_requires_gates_and_illegal_jumps_are_rejected(self):
        flat = PositionStateSnapshot(state="flat", remaining_fraction=0.0)
        with self.assertRaises(ValueError):
            transition_position(flat, "entry-filled", gates_passed=False)
        with self.assertRaises(ValueError):
            transition_position(flat, "tp1-filled", target_fraction=0.25)

        entered = PositionStateSnapshot(state="entered", remaining_fraction=1.0)
        with self.assertRaises(ValueError):
            transition_position(entered, "tp2-filled", target_fraction=0.25)

        exited = PositionStateSnapshot(state="exited", remaining_fraction=0.0)
        with self.assertRaises(ValueError):
            transition_position(exited, "entry-filled")

    def test_repeated_target_and_exit_events_are_idempotent(self):
        protected = PositionStateSnapshot(
            state="profit-protected",
            remaining_fraction=0.75,
            filled_targets=("tp1",),
            last_event="tp1-filled",
        )
        self.assertEqual(
            transition_position(protected, "tp1-filled", target_fraction=0.25),
            protected,
        )

        exited = PositionStateSnapshot(
            state="exited", remaining_fraction=0.0,
            last_event="initial-stop", exit_reason="initial-stop",
        )
        self.assertEqual(transition_position(exited, "initial-stop"), exited)


if __name__ == "__main__":
    unittest.main()
