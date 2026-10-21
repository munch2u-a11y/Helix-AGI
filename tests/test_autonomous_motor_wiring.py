import unittest
from unittest.mock import MagicMock, patch
from core.pulse_loop import PulseLoop
from core.native_motor import NativeMotorSystem


class TestAutonomousMotorWiring(unittest.TestCase):
    def test_pulse_loop_invokes_mindscape_act_on_thought(self):
        # Verify that pulse_loop does NOT hardcode native_action = None,
        # but calls self.mindscape.act(thought, pulse)
        import inspect
        source = inspect.getsource(PulseLoop._pulse)
        self.assertNotIn(
            "native_action = None",
            source,
            "PulseLoop._pulse hardcodes native_action = None, bypassing mindscape.act()",
        )
        self.assertIn(
            "self.mindscape.act(thought",
            source,
            "PulseLoop._pulse must invoke self.mindscape.act(thought, ...)",
        )

    def test_native_motor_system_accepts_self_directed_actions(self):
        # Verify NativeMotorSystem supports self-directed autonomous actions
        owner = MagicMock()
        owner.native.mind.store.get_metadata.return_value = "[]"
        owner.directory = MagicMock()
        owner.config = {"mindscape": {"sensory_interval_seconds": 1.0}}

        motor = NativeMotorSystem(owner)
        self.assertTrue(
            hasattr(motor, "submit_action") or hasattr(motor, "submit_goal"),
            "NativeMotorSystem must support self-directed action submission without user imperatives",
        )
