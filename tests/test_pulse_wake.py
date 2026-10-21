"""Scheduler implementation regressions, not live-agent competence tests."""
import threading
import unittest
from core.pulse_loop import PulseLoop


class PulseWakeTests(unittest.TestCase):
    def test_incoming_message_wakes_every_running_state(self):
        for state in ("DORMANT", "RESTING", "REGULAR", "ACTIVE"):
            with self.subTest(state=state):
                pulse = PulseLoop.__new__(PulseLoop)
                pulse._paused = False
                pulse.mindscape = None
                pulse._state = state
                pulse._wake_event = threading.Event()
                pulse._event_lock = threading.Lock()
                pulse._event_queue = []
                pulse._office_first_enabled = False
                pulse._memory_session_id = ""
                pulse._last_incoming_time = 0
                pulse._consolidation_ran_this_idle = True
                pulse.sentinel = None
                pulse.channel_router = None
                pulse.emit("user_message", {"sender": "Mira", "content": "Please inspect the folder.", "channel": "terminal"})
                self.assertEqual(pulse._state, "ACTIVE")
                self.assertTrue(pulse._wake_event.is_set())
                self.assertEqual(pulse._consolidation_ran_this_idle, state == "ACTIVE")
                self.assertEqual(len(pulse._event_queue), 1)
                self.assertIn("inspect the folder", pulse._event_queue[0])

    def test_active_wake_signals_but_failed_state_is_not_revived(self):
        for state in ("ACTIVE", "FAILED"):
            pulse = PulseLoop.__new__(PulseLoop)
            pulse._paused = False
            pulse._state = state
            pulse._wake_event = threading.Event()
            pulse.wake()
            self.assertEqual(pulse._state, state)
            self.assertEqual(pulse._wake_event.is_set(), state == "ACTIVE")
