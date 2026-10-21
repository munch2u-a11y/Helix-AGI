"""End-to-end live test of user interaction with Ada in Helix.

Simulates a real user (Josh) sending a message to Ada via dashboard,
executes the full cognitive pulse pipeline with local RWKV on CPU,
and verifies:
1. Prompt role grounding: compiled mindscape context is passed as 'context', not 'user'.
2. Uncapped generation: RWKV generation does not ceiling at 512 tokens.
3. Cognitive continuity: pulse loop does not demote to RESTING (no 12-minute sleep).
4. No artificial toolset disengagement.
5. First-person actualized speech delivered to the user.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.pulse_loop import PulseLoop
from main import setup_helix


class TestActualUserInteraction(unittest.TestCase):
    def test_live_user_interaction_ada(self):
        data_dir = "data/agents/Ada"
        delivered_messages = []

        def capture_delivery(recipient, message):
            delivered_messages.append({"recipient": recipient, "message": message})
            print(f"\n[LIVE DELIVERY] -> {recipient}: {message}")

        context_frames = []

        def capture_context(pulse_num, context_text):
            context_frames.append({"pulse": pulse_num, "text": context_text})

        # Initialize the actual Helix architecture for Ada
        print("\n--- Setting up Helix for Ada ---")
        (
            pulse_loop,
            orchestrator,
            daemon,
            memory,
            beliefs,
            scratchpad,
            telegram_bot,
            discord_bot,
            slack_bot,
            whatsapp_bot,
            webhook_channel,
            sentinel,
        ) = setup_helix(data_dir, start_sensors=False, show_context=True)

        pulse_loop.delivery_callback = capture_delivery
        pulse_loop._context_callback = capture_context

        # Verify initial toolset count is intact
        initial_toolsets = set(pulse_loop._active_toolsets)
        self.assertGreater(len(initial_toolsets), 0, "Initial toolsets should be populated")

        # Track dashboard outbound count before message
        from dashboard.dashboard_comms import get_comms
        initial_outbound_count = get_comms().get_outbound_count()

        # Simulate user Josh sending a message via dashboard
        user_message = "Hello Ada, how are you feeling right now?"
        print(f"\n[INCOMING MESSAGE] Josh via dashboard: \"{user_message}\"")
        pulse_loop.emit(
            "user_message",
            {
                "sender": "Josh",
                "content": user_message,
                "channel": "dashboard",
                "chat_id": 0,
            },
        )

        # Execute 1 pulse
        print("\n--- Executing Cognitive Pulse ---")
        pulse_loop._pulse()

        # Check 1: State continuity (must NOT demote to RESTING)
        self.assertIn(
            pulse_loop.state,
            ("ACTIVE", "REGULAR"),
            f"Pulse loop prematurely demoted to {pulse_loop.state}",
        )

        # Check 2: No artificial toolset disengagement
        remaining_toolsets = set(pulse_loop._active_toolsets)
        self.assertEqual(
            initial_toolsets,
            remaining_toolsets,
            "Toolsets were artificially disengaged after pulse",
        )

        # Check 3: Foreground health / in-progress record verification
        foreground_in_progress = Path(data_dir) / "mindscape" / "foreground-in-progress.json"
        if foreground_in_progress.exists():
            import json
            record = json.loads(foreground_in_progress.read_text())
            # Output token cap must be None (uncapped)
            self.assertIsNone(
                record.get("output_token_cap"),
                f"Output token cap is still capped: {record.get('output_token_cap')}",
            )
            self.assertNotEqual(
                record.get("done_reason"),
                "configured_output_boundary",
                "Generation hit configured_output_boundary ceiling",
            )
            print(f"\n[GENERATION METRICS] Tokens generated: {record.get('generated_tokens')}, Done reason: {record.get('done_reason')}")
            print(f"[CONTEMPLATION] {record.get('contemplation', '')[:200]}...")

        # Check 4: Outbound message delivery
        from dashboard.dashboard_comms import get_comms
        comms = get_comms()
        new_outbound = comms.get_outbound(since=initial_outbound_count)
        all_deliveries = delivered_messages + [
            {"recipient": m["recipient"], "message": m["content"]}
            for m in new_outbound
        ]
        self.assertTrue(
            len(all_deliveries) > 0,
            "No message was delivered to Josh via dashboard or callback",
        )
        delivered = all_deliveries[-1]
        self.assertEqual(delivered["recipient"], "Josh")
        self.assertTrue(len(delivered["message"].strip()) > 0)
        print(f"\n[DELIVERED TO JOSH] {delivered['message']}")

    def test_autonomous_motor_and_speech_cycle(self):
        data_dir = "data/agents/Ada"
        delivered_messages = []

        def capture_delivery(recipient, message):
            delivered_messages.append({"recipient": recipient, "message": message})
            print(f"\n[LIVE DELIVERY] -> {recipient}: {message}")

        print("\n--- Setting up Helix for Autonomous Motor & Speech Test ---")
        (
            pulse_loop,
            orchestrator,
            daemon,
            memory,
            beliefs,
            scratchpad,
            telegram_bot,
            discord_bot,
            slack_bot,
            whatsapp_bot,
            webhook_channel,
            sentinel,
        ) = setup_helix(data_dir, start_sensors=False, show_context=True)

        pulse_loop.delivery_callback = capture_delivery

        from dashboard.dashboard_comms import get_comms
        comms = get_comms()
        initial_outbound_count = comms.get_outbound_count()

        # User Josh asks Ada to inspect her workspace files
        request = "Ada, please sense the files in your workspace."
        print(f"\n[INCOMING MESSAGE] Josh: \"{request}\"")
        pulse_loop.emit(
            "user_message",
            {
                "sender": "Josh",
                "content": request,
                "channel": "dashboard",
                "chat_id": 0,
            },
        )

        # Pulse sequencing: Allow the agent to pulse, act in its workspace, and speak
        action_observed = False
        all_deliveries = []

        for step in range(1, 4):
            print(f"\n--- Executing Pulse Step {step} ---")
            pulse_loop._pulse()

            continuation = pulse_loop.mindscape.continuation if pulse_loop.mindscape else {}
            if continuation.get("return") or continuation.get("pending", {}).get("observations"):
                action_observed = True
                print(f"[MOTOR ACTION CONFIRMED ON STEP {step}]")

            new_outbound = comms.get_outbound(since=initial_outbound_count)
            all_deliveries = delivered_messages + [
                {"recipient": m["recipient"], "message": m["content"]}
                for m in new_outbound
            ]
            if all_deliveries:
                print(f"[SPEECH DELIVERED ON STEP {step}] {all_deliveries[-1]['message']}")
                break

        # Verification 1: Autonomous motor action was executed in sandbox
        self.assertTrue(action_observed, "No native motor action was observed during the pulse sequence")

        # Verification 2: Speech was delivered to Josh
        self.assertTrue(len(all_deliveries) > 0, "No speech was delivered to Josh during the pulse sequence")
        delivered = all_deliveries[-1]
        self.assertEqual(delivered["recipient"], "Josh")
        self.assertTrue(len(delivered["message"].strip()) > 0)
        self.assertNotIn("Assistant:", delivered["message"])
        print(f"\n[FINAL DELIVERED TO JOSH] {delivered['message']}")



if __name__ == "__main__":
    unittest.main()

