#!/usr/bin/env python3
"""Tests for natural task inception and identity-shared focus routing."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.task_cognition.capabilities import CapabilityRegistry
from core.task_cognition.focus import FocusManager
from core.task_cognition.inception import IntentionDetector
from core.task_cognition.models import TaskRecord, TaskStatus
from core.task_cognition.orchestrators import OrchestratorSpace
from core.task_cognition.procedures import ProceduralMemory
from core.task_cognition.store import TaskStore
from core.pulse_loop import PulseLoop
from llm.providers.base import ProviderConfig
from tools.tool_registry import ToolRegistry


def _reply_schema():
    return {
        "name": "reply",
        "description": "Reply to the person who is currently talking to me.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["recipient", "message"],
        },
    }


class IntentionDetectorTests(unittest.TestCase):
    def test_committed_natural_thought_becomes_response_task(self):
        detector = IntentionDetector()
        found = detector.detect(
            "Mara needs the result. I should reply to Mara with the final total.",
            ['[10:00] Mara is talking to me via dashboard. They said: "What is the total?"'],
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].task_type, "respond")
        self.assertEqual(found[0].authorization_scope, "direct_response")
        self.assertGreaterEqual(found[0].commitment, detector.threshold)

    def test_hypothesis_does_not_become_task(self):
        detector = IntentionDetector()
        self.assertEqual(
            detector.detect("Maybe I should reply someday, if it becomes useful."),
            [],
        )

    def test_deep_remembering_is_a_task(self):
        found = IntentionDetector().detect(
            "I'll recall what Mara said about the blue vase before I decide."
        )
        self.assertEqual(found[0].task_type, "remember")
        self.assertEqual(found[0].authorization_scope, "internal")

    def test_explicit_user_request_can_authorize_a_scoped_action(self):
        found = IntentionDetector().detect(
            "I will update the requested project file.",
            ['Mara is talking to me via dashboard. They said: "Please update the project file."'],
        )
        self.assertEqual(found[0].authorization_scope, "explicit")


class TaskStoreTests(unittest.TestCase):
    def test_deduplicates_open_intentions_and_persists_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)
            first = TaskRecord(objective="reply to Mara", signature="same")
            duplicate = TaskRecord(objective="reply to Mara", signature="same")
            self.assertEqual(store.create(first).task_id, first.task_id)
            self.assertEqual(store.create(duplicate).task_id, first.task_id)

            store.transition(first.task_id, TaskStatus.FOCUSING)
            store.transition(first.task_id, TaskStatus.EXECUTING)
            store.transition(first.task_id, TaskStatus.COMPLETE, result="sent")

            restored = TaskStore(tmp).get(first.task_id)
            self.assertEqual(restored.status, TaskStatus.COMPLETE)
            self.assertEqual(restored.result, "sent")
            with self.assertRaises(ValueError):
                store.transition(first.task_id, TaskStatus.EXECUTING)


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            name="reply",
            toolset="core",
            schema=_reply_schema(),
            handler=lambda args: "sent",
        )
        self.registry.register(
            name="dangerous_write",
            toolset="files",
            schema={
                "name": "dangerous_write",
                "description": "Write and overwrite a local artifact.",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda args: "written",
        )
        self.capabilities = CapabilityRegistry(self.registry)

    def test_main_awareness_hides_names_and_schema(self):
        awareness = self.capabilities.broad_awareness({"core", "files"})
        self.assertNotIn("reply", awareness)
        self.assertNotIn("dangerous_write", awareness)
        self.assertNotIn("parameters", awareness)
        self.assertIn("communicate", awareness)

    def test_focus_gets_reply_but_not_unverified_write(self):
        selected = self.capabilities.select(
            "reply to Mara",
            task_type="respond",
            authorization_scope="direct_response",
            active_toolsets={"core", "files"},
        )
        self.assertEqual([item.name for item in selected], ["reply"])


class OrchestratorSpaceTests(unittest.TestCase):
    def test_reverse_search_forms_distinct_learned_situations(self):
        with tempfile.TemporaryDirectory() as tmp:
            space = OrchestratorSpace(tmp, semantic_dim=32, cluster_threshold=0.5)
            reply = TaskRecord(objective="reply to Mara about the invoice", task_type="respond")
            research = TaskRecord(objective="research stellar spectra", task_type="action")

            reply_orch = space.select(reply)[0][0]
            reply.orchestrator_ids = [reply_orch.orchestrator_id]
            space.learn(reply, success=True, capabilities=["reply"], focus_depth=2)
            research_orch = space.select(research)[0][0]

            self.assertNotEqual(reply_orch.orchestrator_id, research_orch.orchestrator_id)
            again = space.select(reply, observe_transition=False)[0][0]
            self.assertEqual(again.orchestrator_id, reply_orch.orchestrator_id)
            self.assertEqual(space.all()[0].centroid_1024d.__len__(), 32)


class _Context:
    def render(self, *_args, **_kwargs):
        return '- [semantic; mem_1] Mara asked, "What is the total?"'


class _Executor:
    def __init__(self):
        self.calls = []

    def execute_function_call(self, name, args):
        self.calls.append((name, args))
        return "Sent to Mara."


class _FocusSession:
    def __init__(self, executor):
        self.executor = executor
        self.turn = 0
        self.calls = []
        self.results = []
        self.closed = False

    def send_message(self, _message):
        self.turn += 1
        if self.turn == 1:
            args = {"recipient": "Mara", "message": "The total is 42."}
            result = self.executor.execute_function_call("reply", args)
            self.calls = [{"name": "reply", "args": args}]
            self.results = [{"name": "reply", "args": args, "result": result}]
            return "I can answer Mara directly."
        self.calls = []
        return "I sent Mara the total of 42."

    def get_last_tool_calls(self):
        return list(self.calls)

    def get_pending_tool_results(self):
        results, self.results = self.results, []
        return results

    def close(self):
        self.closed = True


class FocusManagerTests(unittest.TestCase):
    def test_focus_thread_executes_scoped_tool_and_completes_same_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool_registry = ToolRegistry()
            tool_registry.register(
                name="reply",
                toolset="core",
                schema=_reply_schema(),
                handler=lambda args: "sent",
            )
            store = TaskStore(os.path.join(tmp, "tasks"))
            task = store.create(TaskRecord(
                objective="reply to Mara with the final total",
                task_type="respond",
                signature="reply-total",
                authorization_scope="direct_response",
                source_events=['Mara is talking to me. They said: "What is the total?"'],
            ))
            executor = _Executor()
            manager = FocusManager(
                store=store,
                capabilities=CapabilityRegistry(tool_registry),
                orchestrators=OrchestratorSpace(
                    os.path.join(tmp, "tasks"), semantic_dim=32
                ),
                procedures=ProceduralMemory(os.path.join(tmp, "tasks")),
                context_builder=_Context(),
                provider_config=ProviderConfig("codex_cli", "", context_window=128_000),
                tool_executor=executor,
                identity="I am Helix.",
                max_workers=1,
                max_depth=2,
            )
            session = _FocusSession(executor)
            with patch("core.task_cognition.focus.create_session", return_value=session):
                outcome = manager._run(task.task_id, {"core"})
            manager.shutdown()

            self.assertTrue(outcome.success)
            self.assertEqual(executor.calls[0][0], "reply")
            self.assertEqual(store.get(task.task_id).status, TaskStatus.COMPLETE)
            self.assertTrue(session.closed)


class PulseIntegrationTests(unittest.TestCase):
    def test_active_main_session_is_minimal_and_receives_no_tool_schemas(self):
        pulse = PulseLoop.__new__(PulseLoop)
        pulse._chat = None
        pulse._task_cognition = SimpleNamespace(active=True, enabled=True)
        pulse._provider_config = ProviderConfig(
            "codex_cli", "", context_window=128_000, options={"effort": "low"}
        )
        pulse._tool_format = "api"
        pulse._active_toolsets = {"core"}
        pulse.tool_executor = object()
        pulse.preconscious = object()
        pulse.physics = SimpleNamespace(attention_center=np.zeros(8, dtype=np.float32))
        pulse._session_focus_origin = None
        pulse.beliefs = SimpleNamespace(
            get_category=lambda category, limit=100: [
                {"content": "I am Helix and my identity persists through time."}
            ] if category == "premises" else []
        )

        captured = {}
        fake_session = SimpleNamespace()

        def fake_create(config, system, tool_declarations=None, **kwargs):
            captured.update({
                "config": config,
                "system": system,
                "declarations": tool_declarations,
                "executor": kwargs.get("tool_executor"),
            })
            return fake_session

        with patch("core.pulse_loop.create_session", side_effect=fake_create):
            pulse._ensure_session()

        self.assertIs(pulse._chat, fake_session)
        self.assertIsNone(captured["declarations"])
        self.assertTrue(captured["config"].options["thought_only"])
        self.assertNotIn("Communication & Actions", captured["system"])
        self.assertNotIn("Function Calling", captured["system"])
        self.assertLess(len(captured["system"]), 700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
