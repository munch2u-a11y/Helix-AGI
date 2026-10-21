"""Test suite asserting PulseLoop context_callback receives exact rendered prompt."""
import unittest
from unittest.mock import MagicMock
from core.pulse_loop import PulseLoop


class PulseLoopContextExposureTests(unittest.TestCase):
    def test_pulse_loop_notifies_context_callback(self):
        received = []
        def on_context(pulse_id, rendered_context):
            received.append((pulse_id, rendered_context))

        mock_memory = MagicMock()
        mock_beliefs = MagicMock()
        mock_physics = MagicMock()
        mock_preconscious = MagicMock()
        mock_preconscious.inject.return_value = ([], "", [], None)
        mock_scratchpad = MagicMock()
        mock_tools = MagicMock()
        mock_tools.get_active_declarations.return_value = []
        mock_router = MagicMock()
        mock_router.contacts = {}
        mock_chat = MagicMock()
        mock_chat.context_counter = None
        mock_chat.send_message.return_value = "[thought] ok"

        loop = PulseLoop(
            memory_manager=mock_memory,
            belief_store=mock_beliefs,
            physics_engine=mock_physics,
            preconscious=mock_preconscious,
            scratchpad=mock_scratchpad,
            tool_executor=mock_tools,
            channel_router=mock_router,
            context_callback=on_context,
        )
        loop._chat = mock_chat
        loop._pulse()
        self.assertTrue(len(received) > 0, "context_callback was never called during pulse")
        self.assertEqual(received[0][0], 1)
        self.assertIn("Pulse 1", received[0][1])

    def test_dual_pulse_loop_notifies_context_callback(self):
        from core.dual_pulse_loop import DualPulseLoop
        received = []
        def on_context(pulse_id, rendered_context):
            received.append((pulse_id, rendered_context))

        mock_memory = MagicMock()
        mock_beliefs = MagicMock()
        mock_physics = MagicMock()
        mock_preconscious = MagicMock()
        mock_preconscious.inject.return_value = ([], "", [], None)
        mock_scratchpad = MagicMock()
        mock_tools = MagicMock()
        mock_tools.get_active_declarations.return_value = []
        mock_router = MagicMock()
        mock_router.contacts = {}
        mock_local_chat = MagicMock()
        mock_local_chat.context_counter = None
        mock_local_chat.send_message.return_value = "[thought] dual reasoner ok"

        loop = DualPulseLoop(
            memory_manager=mock_memory,
            belief_store=mock_beliefs,
            physics_engine=mock_physics,
            preconscious=mock_preconscious,
            scratchpad=mock_scratchpad,
            tool_executor=mock_tools,
            channel_router=mock_router,
            context_callback=on_context,
        )
        loop._local_chat = mock_local_chat
        loop._pulse()
        self.assertTrue(len(received) > 0, "context_callback was never called during DualPulseLoop pulse")
        self.assertEqual(received[0][0], 1)
        self.assertIn("No new incoming events", received[0][1])



if __name__ == "__main__":
    unittest.main()

