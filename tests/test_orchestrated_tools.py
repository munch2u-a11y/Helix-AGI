"""Tests for orchestrated local tool use.

Covers the path that makes fully-local mode viable: two-layer schema
rendering, grammar-constrained decoding, directed tool passes, and the
session wrapper that presents all of it to the pulse loop as an ordinary
ChatSession.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_orchestrator import ToolOrchestrator
from core.tool_task_runner import INCOMPLETE_MARKER, ToolTaskRunner
from llm.constrained_decoding import FSMLogitsProcessor, parse_action_tags
from llm.orchestrated import OrchestratedToolSession
from llm.tool_pass import ToolPass
from tools.tool_registry import ToolRegistry


def build_registry():
    registry = ToolRegistry()
    registry.register(
        name="read_file",
        toolset="files",
        schema={
            "name": "read_file",
            "description": "Read a local file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to read"},
                },
                "required": ["path"],
            },
        },
        handler=lambda args: f"contents of {args.get('path')}",
    )
    registry.register(
        name="write_file",
        toolset="files",
        schema={
            "name": "write_file",
            "description": "Write a local file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        handler=lambda args: "written",
    )
    registry.register(
        name="search",
        toolset="web",
        schema={
            "name": "search",
            "description": "Search the web.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        handler=lambda args: "a search result",
    )
    registry.register_toolset_description("files", "Local filesystem operations")
    registry.register_toolset_description("web", "Web search")
    return registry


class ScriptedPass(ToolPass):
    """A pass that replays canned model output."""

    def __init__(self, script):
        self.script = list(script)
        self.scoped = None
        self.closed = False

    def send(self, message):
        return self.script.pop(0) if self.script else "Nothing further."

    def scope_tools(self, names):
        self.scoped = list(names)

    def close(self):
        self.closed = True


class RecordingExecutor:
    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    def execute_function_call(self, name, args):
        self.calls.append((name, args))
        return self.results.get(name, f"ran {name}")


class TwoLayerRenderingTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()

    def test_brief_lists_every_toolset_with_counts(self):
        brief = self.registry.toolset_brief()
        self.assertIn("• files (2 tools): Local filesystem operations", brief)
        self.assertIn("• web (1 tools): Web search", brief)

    def test_brief_is_far_cheaper_than_full_schemas(self):
        brief = self.registry.toolset_brief()
        manifests = "".join(
            self.registry.toolset_manifest(name)
            for name in self.registry.get_toolset_names()
        )
        self.assertLess(len(brief), len(manifests))

    def test_manifest_documents_arguments(self):
        manifest = self.registry.toolset_manifest("files")
        self.assertIn("### read_file", manifest)
        self.assertIn("- path (string, required): Path to read", manifest)
        # Other toolsets must not leak into a scoped manifest.
        self.assertNotIn("search", manifest)

    def test_manifest_and_grammar_agree(self):
        names = self.registry.toolset_tool_names("files")
        manifest = self.registry.toolset_manifest("files")
        for name in names:
            self.assertIn(f"### {name}", manifest)

    def test_unknown_toolset_renders_empty(self):
        self.assertEqual(self.registry.toolset_manifest("nope"), "")


class GrammarTests(unittest.TestCase):
    def setUp(self):
        self.fsm = FSMLogitsProcessor(
            tokenizer_decode=lambda ids: "",
            tokenizer_vocab_size=32,
            allowed_tool_names=["read_file", "write_file"],
        )

    def test_partial_real_name_allowed(self):
        self.assertTrue(self.fsm._is_valid_prefix("read_f"))

    def test_partial_unknown_name_rejected(self):
        self.assertFalse(self.fsm._is_valid_prefix("delete_"))

    def test_paths_and_urls_survive(self):
        # A narrow charset used to reject every path, silently making the
        # whole files/web surface unreachable from local mode.
        self.assertTrue(
            self.fsm._is_valid_prefix('read_file(path="/home/a-b/c.txt")')
        )
        self.assertTrue(
            self.fsm._is_valid_prefix('read_file(path="https://x.io/a?b=1")')
        )

    def test_parens_inside_string_do_not_close_the_call(self):
        self.assertTrue(
            self.fsm._is_valid_prefix('write_file(content="a (b) c"')
        )

    def test_trailing_junk_after_close_rejected(self):
        self.assertFalse(self.fsm._is_valid_prefix('read_file(path="a") junk'))

    def test_parse_action_tags_extracts_kwargs(self):
        actions = parse_action_tags('thinking {[(( read_file(path="/tmp/a") ))]} done')
        self.assertEqual(actions, [("read_file", {"path": "/tmp/a"})])

    def test_parse_action_tags_drops_non_literal_arguments(self):
        actions = parse_action_tags('{[(( read_file(path=os.environ) ))]}')
        self.assertEqual(actions, [("read_file", {})])


class ToolPassTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()
        self.executor = RecordingExecutor({"read_file": "TODO: fix the parser"})

    def runner(self, script, **kwargs):
        self.pass_obj = ScriptedPass(script)
        return ToolTaskRunner(
            self.registry, self.executor, lambda _sys: self.pass_obj, **kwargs
        )

    def test_executes_then_reports(self):
        runner = self.runner([
            '{[(( read_file(path="/tmp/notes") ))]}',
            "I read /tmp/notes; it says TODO: fix the parser.",
        ])
        result = runner.run("files", "read my notes")
        self.assertTrue(result.complete)
        self.assertEqual([o.tool for o in result.observations], ["read_file"])
        self.assertIn("TODO", result.report)

    def test_grammar_is_scoped_to_the_toolset(self):
        runner = self.runner(["done"])
        runner.run("files", "nothing")
        self.assertEqual(self.pass_obj.scoped, ["read_file", "write_file"])

    def test_out_of_group_tool_never_dispatches(self):
        runner = self.runner([
            '{[(( search(query="x") ))]}',
            "I stopped.",
        ])
        runner.run("files", "search the web")
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(runner.stats["rejected"], 1)

    def test_near_miss_name_recovered_within_group(self):
        runner = self.runner([
            '{[(( readfile(path="/tmp/a") ))]}',
            "read it.",
        ])
        runner.run("files", "read a file")
        self.assertEqual([c[0] for c in self.executor.calls], ["read_file"])
        self.assertEqual(runner.stats["recovered"], 1)

    def test_step_budget_reports_incomplete_honestly(self):
        runner = self.runner(
            ['{[(( read_file(path="/tmp/a") ))]}'] * 10, max_steps=3,
        )
        result = runner.run("files", "loop")
        self.assertFalse(result.complete)
        self.assertIn(INCOMPLETE_MARKER, result.report)

    def test_json_form_works_without_a_grammar(self):
        runner = self.runner([
            '{"tool": "read_file", "args": {"path": "/tmp/b"}}',
            "read it.",
        ], grammar_constrained=False)
        runner.run("files", "read b")
        self.assertEqual([c[0] for c in self.executor.calls], ["read_file"])

    def test_pass_is_always_closed(self):
        runner = self.runner(["done"])
        runner.run("files", "nothing")
        self.assertTrue(self.pass_obj.closed)


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()
        self.executor = RecordingExecutor({
            "read_file": "TODO: fix the parser",
            "search": "docs at example.com",
        })
        scripts = {
            "files": ['{[(( read_file(path="/tmp/notes") ))]}', "Read the notes."],
            "web": ['{[(( search(query="parser docs") ))]}', "Found the docs."],
        }

        def factory(system_prompt):
            key = "files" if "'files'" in system_prompt else "web"
            return ScriptedPass(scripts[key])

        self.runner = ToolTaskRunner(self.registry, self.executor, factory)
        self.plan_prompts = []

    def orchestrator(self, plan_output, **kwargs):
        def plan_llm(prompt):
            self.plan_prompts.append(prompt)
            if "Split this request" in prompt:
                return plan_output
            return "I read my notes and found the docs."

        return ToolOrchestrator(self.runner, plan_llm, **kwargs)

    def test_multi_task_plan_runs_each_toolset(self):
        orch = self.orchestrator(
            '[{"toolset":"files","task":"read notes"},'
            '{"toolset":"web","task":"find docs"}]'
        )
        result = orch.handle("check my notes then find docs")
        self.assertEqual(len(result.plan), 2)
        self.assertEqual(
            [c[0] for c in self.executor.calls], ["read_file", "search"],
        )
        self.assertEqual(len(result.observations), 2)
        self.assertTrue(result.complete)

    def test_planner_receives_scoped_memory(self):
        orch = self.orchestrator(
            '[{"toolset":"files","task":"read notes"}]',
            context_provider=lambda request: "Josh is my creator.",
        )
        orch.handle("read my notes")
        self.assertIn("Josh is my creator.", self.plan_prompts[0])

    def test_unroutable_request_reports_rather_than_guessing(self):
        orch = self.orchestrator("not json at all")
        result = orch.handle("do something impossible")
        self.assertFalse(result.complete)
        self.assertEqual(self.executor.calls, [])


class SessionWrapperTests(unittest.TestCase):
    class Inner:
        def __init__(self, replies):
            self.replies = list(replies)
            self.received = []

        def send_message(self, message):
            self.received.append(message)
            return self.replies.pop(0) if self.replies else "ok"

        def get_history_size(self):
            return 11

    def setUp(self):
        self.registry = build_registry()
        self.executor = RecordingExecutor({"read_file": "TODO: fix the parser"})
        self.runner = ToolTaskRunner(
            self.registry,
            self.executor,
            lambda _s: ScriptedPass([
                '{[(( read_file(path="/tmp/notes") ))]}',
                "I read the notes.",
            ]),
        )
        self.orch = ToolOrchestrator(
            self.runner,
            lambda p: '[{"toolset":"files","task":"read notes"}]',
        )

    def test_tool_request_is_orchestrated_then_answered(self):
        inner = self.Inner([
            '{"tool_request": "read /tmp/notes"}',
            "Your notes say: TODO: fix the parser.",
        ])
        session = OrchestratedToolSession(inner, self.orch)
        reply = session.send_message("what is in my notes?")
        self.assertEqual(reply, "Your notes say: TODO: fix the parser.")
        self.assertEqual([c[0] for c in self.executor.calls], ["read_file"])

    def test_observations_are_offered_to_the_ingest(self):
        captured = {}
        inner = self.Inner([
            '{"tool_request": "read /tmp/notes"}',
            "Done.",
        ])
        session = OrchestratedToolSession(
            inner, self.orch, ingest=lambda r: captured.update(obs=r.observations),
        )
        session.send_message("read my notes")
        self.assertEqual([o.tool for o in captured["obs"]], ["read_file"])

    def test_plain_turn_passes_through_untouched(self):
        inner = self.Inner(["Just talking."])
        session = OrchestratedToolSession(inner, self.orch)
        self.assertEqual(session.send_message("hello"), "Just talking.")
        self.assertEqual(self.executor.calls, [])

    def test_unknown_methods_delegate_to_the_inner_session(self):
        session = OrchestratedToolSession(self.Inner([]), self.orch)
        self.assertEqual(session.get_history_size(), 11)


if __name__ == "__main__":
    unittest.main(verbosity=2)
