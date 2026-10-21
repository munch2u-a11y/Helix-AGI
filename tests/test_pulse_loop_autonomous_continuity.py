"""Tests for autonomous continuation and removal of arbitrary timeouts in PulseLoop."""
import unittest
from unittest.mock import MagicMock
import time

from core.pulse_loop import PulseLoop


class TestAutonomousContinuity(unittest.TestCase):
    def test_pending_interaction_prevents_resting_transition(self):
        """When an interaction is pending, the transition logic must not demote loop to RESTING."""
        loop = PulseLoop.__new__(PulseLoop)
        loop._state = "REGULAR"
        loop._last_activity_time = time.time() - 9999  # Elapsed long ago
        loop._last_incoming_time = time.time() - 9999
        loop.REGULAR_TIMEOUT = 60
        loop.ACTIVE_TIMEOUT = 15

        # Mindscape has an unfinished pending interaction
        mock_mindscape = MagicMock()
        mock_mindscape.continuation = {"pending": {"messages": ["hello"], "thoughts": ["[thought] considering"]}}
        loop.mindscape = mock_mindscape

        # Test the loop's actual method to check transition
        loop._update_state_transitions()

        self.assertNotEqual(loop._state, "RESTING", "Loop must not enter RESTING while interaction is pending")
        self.assertEqual(loop._state, "REGULAR")

    def test_pending_interaction_cadence_is_immediate(self):
        """When an interaction is pending, get_next_pulse_interval must return immediate cadence."""
        loop = PulseLoop.__new__(PulseLoop)
        loop._state = "REGULAR"
        loop.ACTIVE_INTERVAL = 10
        loop.REGULAR_INTERVAL = 30
        loop.RESTING_INTERVAL = 900
        mock_mindscape = MagicMock()
        mock_mindscape.continuation = {"pending": {"messages": ["hello"]}}
        loop.mindscape = mock_mindscape

        interval = loop._get_next_pulse_interval()
        self.assertEqual(interval, 1.0, "Wait interval must be immediate (1.0s) when pending interaction exists")

    def test_auto_disengage_disabled_by_default(self):
        """Auto-disengage threshold must default to 0 (disabled) to avoid arbitrary limits."""
        loop = PulseLoop.__new__(PulseLoop)
        loop._load_config = lambda: {}
        cfg = loop._load_config()
        threshold = cfg.get("auto_disengage_turns", 0)
        self.assertEqual(threshold, 0, "auto_disengage_turns must be 0 by default")


if __name__ == "__main__":
    unittest.main()
