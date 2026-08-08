#!/usr/bin/env python3
"""Regression tests for the persistent Codex App Server backend."""

import json
import os
import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.providers.base import detect_available_provider
from llm.providers.codex_cli_provider import (
    CodexCliSession,
    _ACTION_SCHEMA,
    _parse_action_envelope,
)
from llm.tool_schema import (
    normalize_function_declarations,
    to_anthropic_tools,
    validate_tool_arguments,
)
from llm.providers.base import ProviderConfig
from core.auxiliary_llm import AuxiliaryLLM


class _FakeTransport:
    next_response = {
        "response_type": "thought",
        "text": "quiet cognition",
        "tool_name": "",
        "tool_arguments": "{}",
    }
    instances = []

    def __init__(self, _codex_path, _workspace):
        self.events = queue.Queue()
        self.sent = []
        self.closed = False
        type(self).instances.append(self)

    def send(self, payload):
        self.sent.append(payload)
        request_id = payload.get("id")
        method = payload.get("method")
        if request_id is None:
            return
        if method == "initialize":
            self.events.put({"id": request_id, "result": {"userAgent": "fake"}})
        elif method == "thread/start":
            self.events.put({
                "id": request_id,
                "result": {"thread": {"id": "thread-test"}},
            })
        elif method == "turn/start":
            self.events.put({
                "id": request_id,
                "result": {"turn": {"id": "turn-test", "status": "inProgress"}},
            })
            self.events.put({
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "agentMessage",
                        "text": json.dumps(type(self).next_response),
                    }
                },
            })
            self.events.put({
                "method": "thread/tokenUsage/updated",
                "params": {
                    "tokenUsage": {
                        "last": {"inputTokens": 321},
                        "total": {"totalTokens": 999},
                    }
                },
            })
            self.events.put({
                "method": "turn/completed",
                "params": {"turn": {"id": "turn-test", "status": "completed", "items": []}},
            })

    def receive(self, _timeout):
        return self.events.get_nowait()

    def close(self):
        self.closed = True


class _Executor:
    def __init__(self):
        self.calls = []

    def execute_function_call(self, name, args):
        self.calls.append((name, args))
        return f"looked up {args['topic']}"


class ToolSchemaTests(unittest.TestCase):
    def test_legacy_gemini_shape_normalizes_for_other_providers(self):
        declarations = [{
            "name": "memory_recall",
            "description": "Recall memory",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }]
        normalized = normalize_function_declarations(declarations)
        self.assertEqual(normalized[0]["name"], "memory_recall")
        self.assertNotIn("parameters", normalized[0])
        self.assertEqual(
            normalized[0]["input_schema"]["properties"]["query"]["type"],
            "string",
        )
        self.assertEqual(to_anthropic_tools(declarations), normalized)

    def test_invalid_and_duplicate_names_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_function_declarations([{"name": "bad tool"}])
        with self.assertRaises(ValueError):
            normalize_function_declarations([{"name": "same"}, {"name": "same"}])

    def test_every_registered_helix_schema_normalizes(self):
        from tools.tool_declarations import TOOLSETS
        declarations = [
            declaration
            for toolset in TOOLSETS.values()
            for declaration in toolset["tools"]
        ]
        normalized = normalize_function_declarations(declarations)
        self.assertEqual(len(normalized), len(declarations))
        self.assertEqual(len({tool["name"] for tool in normalized}), len(declarations))

    def test_codex_action_schema_is_strict_at_every_object_boundary(self):
        self.assertFalse(_ACTION_SCHEMA["additionalProperties"])
        # Arguments are encoded as a JSON string because OpenAI strict output
        # schemas cannot admit an arbitrary nested object.
        self.assertEqual(
            _ACTION_SCHEMA["properties"]["tool_arguments"]["type"], "string"
        )

    def test_host_argument_validation_enforces_required_types(self):
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        validate_tool_arguments({"query": "guilt"}, schema)
        with self.assertRaises(ValueError):
            validate_tool_arguments({}, schema)
        with self.assertRaises(ValueError):
            validate_tool_arguments({"query": 4}, schema)


class ActionEnvelopeTests(unittest.TestCase):
    def test_tool_arguments_json_is_decoded(self):
        envelope = _parse_action_envelope(json.dumps({
            "response_type": "tool_call",
            "text": "",
            "tool_name": "memory_recall",
            "tool_arguments": '{"query":"blue vase"}',
        }))
        self.assertEqual(envelope["tool_arguments"], {"query": "blue vase"})

    def test_plain_text_degrades_to_thought(self):
        self.assertEqual(_parse_action_envelope("hello")["text"], "hello")


class CodexSessionTests(unittest.TestCase):
    def setUp(self):
        _FakeTransport.instances = []
        _FakeTransport.next_response = {
            "response_type": "thought",
            "text": "quiet cognition",
            "tool_name": "",
            "tool_arguments": "{}",
        }
        self.patches = [
            patch("llm.providers.codex_cli_provider.shutil.which", return_value="/fake/codex"),
            patch("llm.providers.codex_cli_provider._AppServerTransport", _FakeTransport),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_thought_turn_uses_ephemeral_read_only_app_server(self):
        session = CodexCliSession(system_instruction="identity", options={"timeout": 2})
        try:
            self.assertEqual(session.send_message("pulse"), "quiet cognition")
            transport = _FakeTransport.instances[0]
            starts = [p for p in transport.sent if p.get("method") == "thread/start"]
            self.assertTrue(starts[0]["params"]["ephemeral"])
            self.assertEqual(starts[0]["params"]["sandbox"], "read-only")
            turns = [p for p in transport.sent if p.get("method") == "turn/start"]
            self.assertEqual(turns[0]["params"]["outputSchema"], _ACTION_SCHEMA)
            self.assertEqual(session.get_last_token_count(), 321)
        finally:
            session.close()
        self.assertTrue(_FakeTransport.instances[0].closed)

    def test_tool_call_dispatches_once_and_queues_grounded_result(self):
        _FakeTransport.next_response = {
            "response_type": "tool_call",
            "text": "A related memory may help.",
            "tool_name": "memory_recall",
            "tool_arguments": '{"topic":"brindle"}',
        }
        executor = _Executor()
        declaration = [{
            "name": "memory_recall",
            "description": "Recall",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        }]
        session = CodexCliSession(
            system_instruction="identity",
            tool_declarations=declaration,
            tool_executor=executor,
            options={"timeout": 2},
        )
        try:
            response = session.send_message("pulse")
            self.assertEqual(response, "A related memory may help.")
            self.assertEqual(executor.calls, [("memory_recall", {"topic": "brindle"})])
            self.assertEqual(session.get_last_tool_calls()[0]["name"], "memory_recall")
            pending = session.get_pending_tool_results()
            self.assertEqual(pending[0]["result"], "looked up brindle")
        finally:
            session.close()


class ProviderSelectionTests(unittest.TestCase):
    def test_codex_alias_selects_app_server_and_legacy_name_stays_benchmark(self):
        with patch("shutil.which", return_value="/fake/codex"):
            with patch.dict(os.environ, {"HELIX_PROVIDER": "codex", "HELIX_MODEL": ""}, clear=False):
                self.assertEqual(detect_available_provider().provider_type, "codex_cli")
            with patch.dict(
                os.environ,
                {"HELIX_PROVIDER": "codex_subscription", "HELIX_MODEL": ""},
                clear=False,
            ):
                self.assertEqual(
                    detect_available_provider().provider_type,
                    "codex_subscription",
                )

    def test_auxiliary_jobs_use_and_close_isolated_codex_session(self):
        class Session:
            def __init__(self):
                self.closed = False

            def send_message(self, prompt):
                return f"summary:{prompt}"

            def close(self):
                self.closed = True

        session = Session()
        config = ProviderConfig(provider_type="codex_cli", model="")
        client = AuxiliaryLLM(config)
        with patch("core.auxiliary_llm.create_session", return_value=session) as create:
            self.assertEqual(client.generate("memory"), "summary:memory")
        self.assertTrue(session.closed)
        self.assertEqual(create.call_args.kwargs["config"].provider_type, "codex_cli")


if __name__ == "__main__":
    unittest.main(verbosity=2)
