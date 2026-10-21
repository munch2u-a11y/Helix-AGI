"""Context/persistence diagnostics with controlled output, not product evaluation."""
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.mindscape import Mindscape
from core.mindscape_intention import decode_speech
from core.pulse_context import build_pulse_context, carry_private_thought
from core.pulse_loop import PulseLoop
from llm.providers.rwkv_provider import BicameralRWKVSession
from memory.memory_manager import MemoryManager
from habitus_ai.store import MindStore


class PrivateStreamContinuityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.memory = MemoryManager(str(self.directory / "canonical"))

    def loop(self, contemplation=""):
        loop = PulseLoop.__new__(PulseLoop)
        loop.memory = self.memory
        loop._memory_session_id = "continuity-diagnostic"
        loop._pulse_count = 1
        loop._private_continuation = None
        loop._chat = SimpleNamespace(last_contemplation=contemplation)
        return loop

    def test_mixed_private_thought_and_speech_have_distinct_canonical_sources(self):
        private = "I need to compare the café notes.\nKeep the negation: do not overwrite them."
        loop = self.loop(private)
        speech_id = self.memory.store("[response] I will inspect the notes.", memory_type="conversation",
                                      source="mindscape_speaker")
        carried = loop._capture_private_continuation(
            "I will inspect the notes.", speech_id, action_attempted=False, external_response=True)
        records = self.memory.get_recent()
        stored = next(item for item in records if f"mem_{item['id']}" in carried.source_ids)
        self.assertEqual(stored["content"], "[thought] " + private)
        self.assertEqual(stored["memory_type"], "thought")
        self.assertNotEqual(carried.source_ids, (f"mem_{speech_id}",))
        self.assertEqual(carried.text, private)
        loop._private_continuation = carried
        loop._chat.last_contemplation = ""
        following = loop._capture_private_continuation(
            "A later spoken reply.", speech_id, action_attempted=False, external_response=True)
        self.assertIs(following, carried)
        self.assertEqual(len(self.memory.get_recent()), len(records))

    def test_private_only_pulse_reuses_its_actual_journal_source(self):
        private = "I should read the actual observation before choosing my next step."
        loop = self.loop(private)
        memory_id = self.memory.store("[thought] " + private, memory_type="thought", source="pulse_output")
        carried = loop._capture_private_continuation(
            "[thought] " + private, memory_id, action_attempted=True, external_response=False)
        self.assertEqual(carried.source_ids, (f"mem_{memory_id}",))
        self.assertEqual(len(self.memory.get_recent()), 1)
        loop._private_continuation = carried
        self.assertIs(loop._capture_private_continuation(
            "[internal error: failed generation]", memory_id, action_attempted=False,
            external_response=False), carried)

    def test_private_continuity_outlives_completed_interaction_in_native_metadata(self):
        private = carry_private_thought("I have learned where the notes are.", "source-1",
                                        action_attempted=False, external_response=False)
        path = self.directory / "native.sqlite"
        with closing(MindStore(path, space_id="context-diagnostic", dimension=8)) as store:
            adapter = Mindscape.__new__(Mindscape)
            adapter.native = SimpleNamespace(mind=SimpleNamespace(store=store))
            adapter.continuation = {
                "pending": {"messages": ["read the notes"], "thoughts": ["[thought] older thought"]},
                "motor_returns": [{"id": "seen", "consumed": False}, {"id": "arrived-later", "consumed": False}],
            }
            adapter.session_id = "diagnostic"
            adapter._observed_return_id = None
            adapter.needs_native_observation = False
            adapter.last_sensed_feeling = {"is_external": True}
            adapter._receipt = Mock()
            adapter._checkpoint = Mock()
            adapter._admit_foreground = Mock()
            adapter._finish("The notes are in the workshop.", 1, delivered_external=True,
                            observed_motor_ids={"seen"}, private_continuation=private)
            self.assertNotIn("pending", adapter.continuation)
            self.assertTrue(adapter.continuation["motor_returns"][0]["consumed"])
            self.assertFalse(adapter.continuation["motor_returns"][1]["consumed"])
        with closing(MindStore(path, space_id="context-diagnostic", dimension=8)) as store:
            resumed = Mindscape.__new__(Mindscape)
            resumed.continuation = json.loads(store.get_metadata("helix_pulse_continuation"))
            restored = resumed._load_private_continuation()
            self.assertEqual(restored, private)
            frame = build_pulse_context(pulse=2, timestamp="now", events=[], private_continuation=restored)
            self.assertTrue(frame.render().endswith(private.text))

    def test_legacy_pending_thoughts_restore_only_the_latest_as_current(self):
        adapter = Mindscape.__new__(Mindscape)
        adapter.continuation = {"pending": {"thoughts": ["[thought] older", "[thought] newest"]}}
        self.assertEqual(adapter._load_private_continuation().text, "newest")

    def test_provider_history_cannot_bypass_compiled_item_admission_or_leak_private_text(self):
        system = SimpleNamespace(backend=SimpleNamespace(encode=lambda text: list(text.encode())), device="cpu")
        def generate(prompt, **options):
            system.last_generation_receipt = {"prompt_tokens": len(prompt.encode()), "generated_tokens": 1,
                                              "done_reason": "eos"}
            return "<think>My private intention.</think>A public reply."
        system.generate_language = generate
        with patch("llm.providers.rwkv_provider.BicameralRWKV", return_value=system):
            session = BicameralRWKVSession(str(self.directory), system_instruction="stable identity")
        session.compiled_context_only = True
        session.context_decoder = decode_speech
        session.history = [{"role": "user", "content": f"old unrelated topic {i}"} for i in range(30)]
        response = session.send_context("one admitted pulse")
        session.finish_context(["current request"], response, delivered=True)
        loop = self.loop()
        loop._chat = session
        carried = loop._capture_private_continuation(response, "public-source", action_attempted=False,
                                                    external_response=True)
        following = session.context_messages(build_pulse_context(
            pulse=2, timestamp="now", events=[], private_continuation=carried).render())
        self.assertEqual(len(following), 2)
        self.assertNotIn("old unrelated topic", str(following))
        self.assertIn("My private intention.", following[-1]["content"])
        self.assertNotIn("My private intention.", str(session.history))
        self.assertEqual(session.covered_source_hashes(), set())
        self.assertEqual(len(session.history), 32)

    def test_fixed_native_identity_does_not_inject_an_unbudgeted_belief_list(self):
        loop = self.loop()
        loop.beliefs = SimpleNamespace(get_category=lambda *args, **kwargs: [
            {"content": "Ada was created by Josh."}, {"content": "A separate belief must use admission."}])
        loop.config = {"agent_name": "Ada", "creator_name": "Josh"}
        loop.mindscape = SimpleNamespace(config={"mindscape": {"context_item_limit": 8}})
        loop._task_cognition = None
        instruction = loop._build_system_instruction()
        self.assertIn("Ada was created by Josh.", instruction)
        self.assertNotIn("A separate belief", instruction)
        self.assertNotIn("Core Premises", instruction)

