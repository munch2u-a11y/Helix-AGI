"""Narrow boundary/continuity regressions, not agent competence tests."""
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.context_compressor import ContextCompressor, SUMMARY_PREFIX
from llm.ollama_tokens import ProviderContextExceeded
from llm.providers.ollama_provider import OllamaSession


class ContinuityTests(unittest.TestCase):
    def test_compiled_item_policy_does_not_replay_the_dialogue_archive(self):
        session = self.session()
        session.history = [{"role": "user", "content": "older received request"},
                           {"role": "assistant", "content": "older delivered reply"}]
        session.compiled_context_only = True
        messages = session.context_messages("admitted current pulse")
        self.assertEqual(messages, [{"role": "system", "content": "identity"},
                                    {"role": "user", "content": "admitted current pulse"}])
        self.assertEqual(len(session.history), 2)
        self.assertEqual(session.covered_source_hashes(), set())

    def session(self):
        session = OllamaSession("local-test", "identity", options={"num_ctx": 1000})
        session.context_counter = SimpleNamespace(
            count_messages=lambda messages: sum(len(m["content"]) for m in messages),
            check_request=lambda messages, limit: {"prompt_tokens": 42, "context_tokens": limit},
        )
        session._use_package = True
        return session

    def test_retrieval_snapshot_is_transient_but_actual_dialogue_persists(self):
        session = self.session()
        with patch.object(session, "_send_via_package", return_value="Use distinct filenames."):
            response = session.send_context("OLD RECALLED CAT\nMira: suggest filenames")
        self.assertEqual(session.history, [])
        session.finish_context(["Mira: suggest filenames"], response, delivered=True)
        following = session.context_messages("Mira: now read this file")
        self.assertNotIn("OLD RECALLED CAT", str(following))
        self.assertIn("Use distinct filenames.", str(following))
        self.assertIn("Mira: suggest filenames", str(following))
        self.assertIn(hashlib.sha256(b"[response] Use distinct filenames.").hexdigest(), session.covered_source_hashes())
        self.assertNotIn(hashlib.sha256(b"OLD RECALLED CAT").hexdigest(), session.covered_source_hashes())

    def test_private_and_undelivered_prose_never_becomes_delivered_dialogue(self):
        session = self.session()
        with patch.object(session, "_send_via_package", return_value="private draft"):
            response = session.send_context("idle recalled context")
        session.finish_context([], response, delivered=False)
        self.assertEqual(session.history, [])
        with patch.object(session, "_send_via_package", return_value="unsent reply"):
            response = session.send_context("fresh question")
        session.finish_context(["fresh question"], response, delivered=False)
        self.assertEqual(session.history, [{"role": "user", "content": "fresh question"}])
        self.assertEqual(session.context_messages("follow-up")[-1]["content"], "fresh question\n\nfollow-up")

    def test_duplicate_or_wrong_response_cannot_commit(self):
        session = self.session()
        with patch.object(session, "_send_via_package", return_value="actual response"):
            session.send_context("current")
        with self.assertRaises(ValueError):
            session.finish_context(["current"], "invented response", delivered=True)
        session.finish_context(["current"], "actual response", delivered=True)
        with self.assertRaises(ValueError):
            session.finish_context(["current"], "actual response", delivered=True)

    def test_native_envelope_decodes_without_inventing_an_execution(self):
        from core.mindscape_intention import foreground_schema, decode_foreground
        session = self.session()
        session.context_format = foreground_schema()
        session.context_decoder = decode_foreground
        with patch.object(session, "_send_via_package", return_value='{"message":"Hello."}'):
            response = session.send_context("greeting")
        self.assertEqual(response, "Hello.")
        self.assertEqual(session.last_context_output_kind, "message")
        self.assertEqual(session.last_context_receipt["raw_foreground"], '{"message":"Hello."}')
        session.finish_context(["greeting"], response, delivered=True)
        rendered = session.context_messages("next question")
        self.assertEqual(json.loads(rendered[-2]["content"]), {"message": "Hello."})
        self.assertEqual(session.history[-1]["content"], "Hello.")
        self.assertIn(hashlib.sha256(b"Hello.").hexdigest(), session.covered_source_hashes())
        with patch.object(session, "_send_via_package", return_value='{"action":"sense","arguments":{"path":"."}}'):
            response = session.send_context("sense current folder")
        self.assertEqual(session.last_context_output_kind, "intention")
        self.assertTrue(response.startswith("<intention>"))
        session.finish_context(["sense current folder"], response, delivered=False)
        self.assertNotIn("<intention>", str(session.history))

    def test_provider_pruning_or_incomplete_generation_is_an_explicit_failure(self):
        session = self.session()
        session._context_in_flight = True
        session.last_context_receipt = {"prompt_tokens": 42}
        with self.assertRaises(ProviderContextExceeded):
            session._check_context_response(30, 10, "stop")
        with self.assertRaises(ProviderContextExceeded):
            session._check_context_response(42, 958, "length")
        session._check_context_response(42, 20, "stop")

    def test_actual_live_requests_survive_summary_serialization(self):
        root = Path(__file__).resolve().parents[1]
        run = root / "documents/audits/2026-10-10-operational-recheck/cases"
        compressor = ContextCompressor(context_length=8192)
        for case in ("conversation", "sense"):
            provider = json.loads((run / case / "provider.json").read_text())[0]
            context = json.loads((run / case / "context.json").read_text())
            text = provider["locals"]["messages"][-1]["content"]
            serialized = compressor._serialize_for_summary([{"role": "user", "parts": [{"text": text}]}])
            self.assertIn(context["events"][0], serialized)
            self.assertIn(text, serialized)
            self.assertNotIn("...[truncated]...", serialized)
        self.assertNotIn("already experienced everything", SUMMARY_PREFIX)


if __name__ == "__main__":
    unittest.main()
