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
from core.task_cognition.controller import TaskCognitionController
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

    def test_direct_request_becomes_task_without_model_commitment_phrase(self):
        found = IntentionDetector().detect(
            "This request is clear.",
            ['[12:00] Alex is talking to me via dashboard. They said: "Please find the report and email it to me."'],
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].task_type, "action")
        self.assertEqual(found[0].authorization_scope, "explicit")
        self.assertIn("find the report", found[0].objective)

    def test_non_action_direct_message_only_authorizes_response(self):
        found = IntentionDetector().detect(
            "I understand the question.",
            ['[12:00] Alex is talking to me via dashboard. They said: "How are you feeling today?"'],
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].task_type, "respond")
        self.assertEqual(found[0].authorization_scope, "direct_response")


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


class _ScriptedFocusSession:
    """Provider session that returns explicit calls/results per turn."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.results = []
        self.closed = False

    def send_message(self, _message):
        thought, calls, results = self.turns.pop(0)
        self.calls = list(calls)
        self.results = list(results)
        return thought

    def get_last_tool_calls(self):
        return list(self.calls)

    def get_pending_tool_results(self):
        results, self.results = self.results, []
        return results

    def close(self):
        self.closed = True


def _focus_manager(tmp, registry, executor, max_depth=3):
    task_dir = os.path.join(tmp, "tasks")
    store = TaskStore(task_dir)
    manager = FocusManager(
        store=store,
        capabilities=CapabilityRegistry(registry),
        orchestrators=OrchestratorSpace(task_dir, semantic_dim=32),
        procedures=ProceduralMemory(task_dir),
        context_builder=_Context(),
        provider_config=ProviderConfig("codex_cli", "", context_window=128_000),
        tool_executor=executor,
        identity="I am Helix.",
        max_workers=1,
        max_depth=max_depth,
    )
    return store, manager


class FocusManagerTests(unittest.TestCase):
    def test_identity_kernel_is_conditional(self):
        manager = FocusManager.__new__(FocusManager)
        manager.identity = "I am Helix, with a continuing personal history."
        ordinary = TaskRecord(objective="calculate the invoice total")
        personal = TaskRecord(objective="explain your values and personal preferences")

        ordinary_kernel = manager._focus_kernel(ordinary)
        personal_kernel = manager._focus_kernel(personal)
        self.assertNotIn("I am Helix", ordinary_kernel)
        self.assertIn("I am Helix", personal_kernel)

    def test_task_prompt_omits_empty_template_filler(self):
        prompt = FocusManager._task_prompt(
            TaskRecord(objective="calculate the invoice total"),
            "one exact memory",
            SimpleNamespace(reliability=0.8),
            [],
        )
        self.assertNotIn("none", prompt.lower())
        self.assertNotIn("<task>", prompt)
        self.assertNotIn("Details:", prompt)
        self.assertIn("Context:\none exact memory", prompt)

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

    def test_plain_model_claim_with_no_receipt_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry()
            registry.register(
                name="reply", toolset="core", schema=_reply_schema(),
                handler=lambda args: "Sent to Mara.",
            )
            executor = _Executor()
            store, manager = _focus_manager(tmp, registry, executor, max_depth=1)
            task = store.create(TaskRecord(
                objective="reply to Mara",
                task_type="respond",
                authorization_scope="direct_response",
            ))
            session = _ScriptedFocusSession([
                ("Done — I sent it.", [], []),
            ])
            with patch("core.task_cognition.focus.create_session", return_value=session):
                outcome = manager._run(task.task_id, {"core"})
            manager.shutdown()

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.verification["status"], "no_action")
            self.assertEqual(store.get(task.task_id).status, TaskStatus.FAILED)
            self.assertEqual(executor.calls, [])

    def test_failed_attempt_can_recover_before_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry()
            registry.register(
                name="reply", toolset="core", schema=_reply_schema(),
                handler=lambda args: "unused",
            )
            executor = _Executor()
            store, manager = _focus_manager(tmp, registry, executor, max_depth=3)
            task = store.create(TaskRecord(
                objective="reply to Mara",
                task_type="respond",
                authorization_scope="direct_response",
            ))
            failed_args = {"recipient": "unknown", "message": "Hi"}
            good_args = {"recipient": "Mara", "message": "Hi"}
            session = _ScriptedFocusSession([
                (
                    "I tried the remembered address.",
                    [{"name": "reply", "args": failed_args}],
                    [{"name": "reply", "args": failed_args, "result": "Error: invalid recipient"}],
                ),
                (
                    "I corrected the recipient.",
                    [{"name": "reply", "args": good_args}],
                    [{"name": "reply", "args": good_args, "result": "Sent to Mara."}],
                ),
                ("The reply is now delivered.", [], []),
            ])
            with patch("core.task_cognition.focus.create_session", return_value=session):
                outcome = manager._run(task.task_id, {"core"})
            manager.shutdown()

            self.assertTrue(outcome.success)
            self.assertEqual(outcome.verification["status"], "verified")
            self.assertEqual(len(outcome.receipts), 2)
            self.assertEqual(store.get(task.task_id).status, TaskStatus.COMPLETE)

    def test_missing_material_input_pauses_without_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry()
            registry.register(
                name="reply", toolset="core", schema=_reply_schema(),
                handler=lambda args: "Sent.",
            )
            executor = _Executor()
            store, manager = _focus_manager(tmp, registry, executor, max_depth=1)
            task = store.create(TaskRecord(
                objective="send the report to Alex",
                task_type="respond",
                authorization_scope="direct_response",
            ))
            session = _ScriptedFocusSession([
                ("NEED_INPUT: Which Alex should receive the report?", [], []),
            ])
            with patch("core.task_cognition.focus.create_session", return_value=session):
                outcome = manager._run(task.task_id, {"core"})
            manager.shutdown()

            stored = store.get(task.task_id)
            self.assertTrue(outcome.waiting_for_input)
            self.assertEqual(stored.status, TaskStatus.WAITING_INPUT)
            self.assertEqual(stored.question, "Which Alex should receive the report?")
            self.assertEqual(executor.calls, [])

    def test_unverified_file_write_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry()
            schema = {
                "name": "write_file",
                "description": "Write and update a local file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            }
            registry.register(
                name="write_file", toolset="files", schema=schema,
                handler=lambda args: "ok",
            )
            executor = _Executor()
            store, manager = _focus_manager(tmp, registry, executor, max_depth=2)
            task = store.create(TaskRecord(
                objective="update the project file",
                task_type="action",
                authorization_scope="explicit",
            ))
            args = {"path": "/tmp/project.txt", "content": "updated"}
            session = _ScriptedFocusSession([
                (
                    "I wrote the file.",
                    [{"name": "write_file", "args": args}],
                    [{"name": "write_file", "args": args, "result": "ok"}],
                ),
                ("Done.", [], []),
            ])
            with patch("core.task_cognition.focus.create_session", return_value=session):
                outcome = manager._run(task.task_id, {"files"})
            manager.shutdown()

            self.assertFalse(outcome.success)
            self.assertEqual(outcome.verification["status"], "partial")
            self.assertEqual(store.get(task.task_id).status, TaskStatus.PARTIAL)


class ClarificationResumeTests(unittest.TestCase):
    class _Focus:
        def __init__(self):
            self.submissions = []

        def submit(self, task, active):
            self.submissions.append((task.task_id, set(active)))
            return True

    def test_answer_resumes_same_durable_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(tmp)
            task = store.create(TaskRecord(objective="send report to Alex"))
            store.transition(
                task.task_id,
                TaskStatus.WAITING_INPUT,
                question="Which Alex?",
            )
            focus = self._Focus()
            controller = TaskCognitionController.__new__(TaskCognitionController)
            controller.mode = "active"
            controller.focus = focus
            controller.store = store
            controller.pulse_loop = SimpleNamespace(_active_toolsets={"email"})

            self.assertTrue(controller.provide_input(task.task_id, "Alex Rivera"))
            restored = store.get(task.task_id)
            self.assertEqual(restored.status, TaskStatus.WAITING_INPUT)
            self.assertEqual(restored.question, "")
            self.assertIn("Alex Rivera", restored.source_events[-1])
            self.assertEqual(focus.submissions, [(task.task_id, {"email"})])

    def test_resumed_answer_does_not_spawn_a_second_reply_task(self):
        controller = TaskCognitionController.__new__(TaskCognitionController)
        controller.mode = "active"
        controller.focus = self._Focus()
        controller._pending_resumed = True
        controller._resume_waiting_from_events = lambda _ctx: True

        class _Detector:
            def detect(self, _thought, _events):
                raise AssertionError("clarification answer was detected as a new task")

        controller.detector = _Detector()
        ctx = SimpleNamespace(thought="Alex Rivera", events=[], active_toolsets={"email"})
        controller.observe_pulse(ctx)


class ProceduralMemoryVerificationTests(unittest.TestCase):
    def test_only_verified_routes_become_recommendations(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = ProceduralMemory(tmp)
            task = TaskRecord(objective="email Mara the weekly report", task_type="action")
            memory.observe(
                task, ["desktop_open", "desktop_type"],
                success=False, verified=False, error_codes=["window_not_found"],
            )
            memory.observe(
                task, ["email_send"], success=True, verified=True,
            )
            routes = memory.relevant(task)
            recommended = [item for item in routes if item.get("recommended")]
            avoided = [item for item in routes if item.get("avoid")]

            self.assertEqual(recommended[0]["tool_sequence"], ["email_send"])
            self.assertEqual(avoided[0]["tool_sequence"], ["desktop_open", "desktop_type"])
            self.assertIn("window_not_found", avoided[0]["error_codes"])


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
