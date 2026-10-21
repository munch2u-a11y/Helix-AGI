"""Tests for native subconscious exploration, internal intention admission, and self-directed agency."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from habitus_ai.types import OutputTrunk

from core.mindscape_intention import (
    resolve_subconscious_action,
    ability_awareness,
)
from core.native_motor import NativeMotorSystem, MotorOpcode


class TestNativeSubconsciousDrive(unittest.TestCase):
    def test_resolve_subconscious_action_explores_unsensed_room_on_look(self):
        # 1. No user obligations pending, but OutputTrunk.LOOK is active in subconscious cortex
        obligations = {}
        observations = []
        action = resolve_subconscious_action(
            obligations,
            observations,
            current_position=".",
            active_trunks={OutputTrunk.LOOK},
        )
        self.assertIsNotNone(action, "Expected autonomous exploration action on OutputTrunk.LOOK")
        self.assertEqual(action["action"], "sense")
        self.assertEqual(action["arguments"]["path"], ".")

    def test_resolve_subconscious_action_opens_unopened_staged_file_on_look(self):
        # 2. Room has already been sensed; an un-opened file exists in surroundings
        obligations = {}
        observations = [
            {
                "action": "sense",
                "status": "success",
                "output": {
                    "entries": [
                        {"name": "experiment_notes.txt", "kind": "file"},
                    ]
                },
            }
        ]
        action = resolve_subconscious_action(
            obligations,
            observations,
            current_position="thinking",
            active_trunks={OutputTrunk.LOOK},
        )
        self.assertIsNotNone(action, "Expected autonomous open action for newly discovered file")
        self.assertEqual(action["action"], "open")
        self.assertIn("experiment_notes.txt", action["arguments"]["path"])

    def test_native_motor_admit_accepts_internal_cognitive_intentions(self):
        # 3. NativeMotorSystem.admit() accepts internal cognitive intentions
        mock_owner = SimpleNamespace(
            native=SimpleNamespace(
                mind=SimpleNamespace(
                    store=SimpleNamespace(
                        get_metadata=lambda k, d: "[]",
                        set_metadata=lambda k, v: None,
                    )
                )
            ),
            body=SimpleNamespace(workspace=SimpleNamespace(root=Path("/tmp"))),
            config={"mindscape": {"sensory_interval_seconds": 1.0}},
            session_id="test_session",
            directory=Path("/tmp"),
            _receipt=lambda *a, **kw: None,
        )

        motor = NativeMotorSystem(mock_owner)

        # A) Direct wire dict intention
        wire_intention = {"action": "sense", "arguments": {"path": "."}}
        admitted_ids = motor.admit([wire_intention], pulse=1)
        self.assertEqual(len(admitted_ids), 1, "Failed to admit internal wire dict intention")
        admitted_job = next(j for j in motor.jobs if j["id"] == admitted_ids[0])
        self.assertEqual(admitted_job["steps"][0]["opcode"], int(MotorOpcode.SENSE))
        self.assertEqual(admitted_job["steps"][0]["target"], ".")
        self.assertIn(admitted_job["status"], {"ready", "awaiting_context"})

        # B) Direct natural command string from agent cognition
        natural_intention = "sense ."
        admitted_ids2 = motor.admit([natural_intention], pulse=2)
        self.assertEqual(len(admitted_ids2), 1, "Failed to admit internal natural string intention")
        admitted_job2 = next(j for j in motor.jobs if j["id"] == admitted_ids2[0])
        self.assertEqual(admitted_job2["steps"][0]["opcode"], int(MotorOpcode.SENSE))

    def test_ability_awareness_prompt_permits_agent_initiative(self):
        # 4. Prompt framing reflects autonomous initiative, not strictly passive user-driven execution
        prompt = ability_awareness("/home/ada", ".")
        self.assertNotIn("A request to perform an action calls for performing it, rather than a tutorial", prompt)
        self.assertTrue(
            "autonomously" in prompt.lower() or "initiative" in prompt.lower() or "exploratory" in prompt.lower(),
            f"Prompt does not reflect autonomous initiative: {prompt}",
        )


if __name__ == "__main__":
    unittest.main()
