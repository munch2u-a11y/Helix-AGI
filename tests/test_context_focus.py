"""Implementation diagnostics, not live-agent or memory competence results."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from core.action_protocol import ToolReceipt, ReceiptStatus, EvidenceLevel
from core.context_focus import ContextFocus, infer_focus, resolve_profiles
from core.pulse_context import build_pulse_context
from core.task_cognition.capabilities import CapabilityRegistry
from core.task_cognition.controller import TaskCognitionController
from core.task_cognition.models import TaskRecord
from core.task_cognition.procedures import ProceduralMemory
from tools.tool_registry import ToolRegistry


class FocusPolicyTests(unittest.TestCase):
    def test_mixed_work_and_old_memory_cannot_hijack_fresh_focus(self):
        frame = build_pulse_context(pulse=1, timestamp="now", events=["Please write a script and research its input format."],
                                    annotations=["Reflect about a conversation."])
        self.assertEqual(set(frame.focus.weights), {"conversation", "action", "writing", "inquiry"})
        plain = build_pulse_context(pulse=2, timestamp="now", events=["Hello!"],
                                    annotations=["Read files and execute commands."])
        self.assertEqual(plain.focus.weights, {"conversation": 1.0})

    def test_invalid_config_does_not_silently_disable_or_invert_a_section(self):
        for value in [0, -1, float("inf"), float("nan"), True, "3"]:
            with self.assertRaises(ValueError):
                resolve_profiles({"inquiry": {"recalled": value}})
        with self.assertRaises(ValueError):
            resolve_profiles({"inquiry": {"invented_section": 2}})
        self.assertEqual(infer_focus("", "idle").weights, {"reflection": 1.0})


class ProceduralEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.memory = ProceduralMemory(self.directory.name)

    def task(self, names, *, status=ReceiptStatus.SUCCESS):
        return TaskRecord(objective="inspect the requested document", receipts=[
            ToolReceipt(name, {"path": "sample.md"}, "observed result", status,
                        EvidenceLevel.OBSERVED).to_dict() for name in names])

    def test_flags_and_legacy_success_counts_cannot_manufacture_skill(self):
        task = TaskRecord(objective="inspect document")
        for verified in [None, True]:
            task.attempts += 1
            self.memory.observe(task, ["read_file"], success=True, verified=verified)
        self.assertFalse(self.memory.relevant(task)[0]["recommended"])
        self.memory.path.write_text(json.dumps({"procedures": [{
            "key": "action|read_file", "task_type": "action", "tool_sequence": ["read_file"],
            "examples": [task.objective], "successes": 900, "verified_successes": 900,
            "failures": 0}]}))
        self.assertFalse(ProceduralMemory(self.directory.name).relevant(task)[0]["recommended"])

    def test_replayed_outcome_does_not_reinforce_itself_and_survives_restart(self):
        task = self.task(["read_file"])
        for _ in range(2):
            self.memory.observe(task, ["read_file"], success=True, verified=True)
            task.attempts += 1
        record = ProceduralMemory(self.directory.name).relevant(task)[0]
        self.assertTrue(record["recommended"])
        self.assertEqual(record["verified_successes"], 1)
        self.assertEqual(len(record["episodes"]), 1)
        self.assertEqual(record["episodes"][0]["receipts"], task.receipts)

    def test_wrong_trajectory_failed_receipt_and_unknown_verification_are_not_skills(self):
        cases = [(self.task(["read_file"]), ["terminal"], True),
                 (self.task(["read_file"], status=ReceiptStatus.FAILED), ["read_file"], True),
                 (self.task(["read_file"]), ["read_file"], None)]
        for task, steps, verified in cases:
            self.memory.observe(task, steps, success=True, verified=verified)
            self.assertFalse(any(item["recommended"] for item in self.memory.relevant(task)))

    def test_complex_trajectory_preserves_prior_support_without_claiming_entailment(self):
        simple = self.task(["read_file"])
        self.memory.observe(simple, ["read_file"], success=True, verified=True)
        complex_task = self.task(["read_file", "search"])
        self.memory.observe(complex_task, ["read_file", "search"], success=True, verified=True)
        records = {item["key"]: item for item in self.memory.relevant(complex_task)}
        link = records["action|read_file->search"]["episodes"][0]["subprocedures"][0]
        self.assertEqual(link["key"], "action|read_file")
        self.assertEqual(link["relation"], "verified_sequence_contains")
        self.assertEqual(link["support_episode_ids"], [records["action|read_file"]["episodes"][0]["id"]])


class AwarenessTests(unittest.TestCase):
    def setUp(self):
        registry = ToolRegistry()
        for name, family in [("read_file", "files"), ("terminal", "core")]:
            registry.register(name=name, toolset=family,
                schema={"name": name, "description": "Read document contents" if name == "read_file" else "Run a command",
                        "parameters": {"type": "object", "properties": {}}}, handler=lambda args: "")
        self.controller = TaskCognitionController.__new__(TaskCognitionController)
        self.controller.mode = "observe"
        self.controller.capabilities = CapabilityRegistry(registry)
        self.controller.pulse_loop = SimpleNamespace(_provider_config=SimpleNamespace(provider_type="ollama"),
            _tool_format="api", tool_executor=object(), mindscape=object(), _tool_dispatcher=object())
        self.focus = infer_focus("Read the document", "fresh_events")

    def test_local_api_session_cannot_claim_registered_but_disconnected_abilities(self):
        awareness = self.controller.awareness({"files", "core"}, self.focus)
        self.assertIn("no connected action dispatcher", awareness)
        self.assertNotIn("I can read it", awareness)
        self.assertNotIn("I can run commands", awareness)
        self.assertIn("ask the person", awareness)

    def test_pulse_build_uses_current_focus_and_keeps_availability_out_of_retrieval_query(self):
        from core.pulse_loop import PulseLoop
        with tempfile.TemporaryDirectory() as directory:
            self.controller.procedures = ProceduralMemory(directory)
            pulse = self.controller.pulse_loop
            pulse._task_cognition = self.controller
            pulse._active_toolsets = {"core", "files"}
            pulse._pulse_count = 1
            pulse._token_warning = ""
            pulse._private_continuation = None
            event = "Mira is talking to me via terminal. They said: Read the document."
            rendered = PulseLoop._build_pulse_message(pulse, [event], [], None, "now")
            self.assertIn("no connected action dispatcher", rendered)
            self.assertEqual(pulse._last_pulse_context.query, event)
            self.assertIn("action", pulse._last_pulse_context.focus.weights)

    def test_local_system_instruction_does_not_invent_a_gemini_dispatcher(self):
        from core.pulse_loop import PulseLoop
        pulse = self.controller.pulse_loop
        pulse.mindscape = SimpleNamespace(config={"mindscape": {"context_item_limit": 8}})
        pulse._task_cognition = self.controller
        pulse.beliefs = SimpleNamespace(get_category=lambda *args, **kwargs: [])
        pulse.preconscious = SimpleNamespace()
        pulse._sysinstruction_rebuild_count = 0
        pulse._previous_thoughts = ""
        pulse._premise_blacklist = {}
        instruction = PulseLoop._build_system_instruction(pulse)
        self.assertNotIn("Gemini", instruction)
        self.assertIn("available information source", instruction)

    def test_conversation_omits_action_detail_and_dormant_families(self):
        self.controller.pulse_loop._tool_format = "local"
        conversation = self.controller.awareness({"core"}, ContextFocus({"conversation": 1}, "test"))
        self.assertNotIn("commands", conversation)
        action = self.controller.awareness({"core"}, self.focus)
        self.assertIn("run commands", action)
        self.assertNotIn("I can read it", action)

    def test_existing_orchestrated_local_route_is_recognized_only_when_wrapped(self):
        from llm.orchestrated import OrchestratedToolSession
        pulse = self.controller.pulse_loop
        pulse._tool_format = "orchestrated"
        pulse._chat = object()
        self.assertIn("no connected action dispatcher", self.controller.awareness({"files"}, self.focus))
        pulse._chat = OrchestratedToolSession(object(), object())
        self.assertIn("I can read it", self.controller.awareness({"files"}, self.focus))

    def test_learned_route_reaches_pulse_awareness_only_when_dispatch_is_connected(self):
        with tempfile.TemporaryDirectory() as directory:
            self.controller.procedures = ProceduralMemory(directory)
            task = TaskRecord(objective="read this document", receipts=[
                ToolReceipt("read_file", {}, "contents", ReceiptStatus.SUCCESS, EvidenceLevel.OBSERVED).to_dict()])
            self.controller.procedures.observe(task, ["read_file"], success=True, verified=True)
            self.assertEqual(self.controller.recalled_procedures(task.objective, self.focus, {"files"}), ())
            self.controller.pulse_loop._tool_format = "local"
            contributions = self.controller.recalled_procedures(task.objective, self.focus, {"files"})
            self.assertEqual(len(contributions), 1)
            self.assertIn("Read document contents", contributions[0].text)
            self.assertTrue(contributions[0].source_ids[0].startswith("outcome:"))


if __name__ == "__main__":
    unittest.main()
