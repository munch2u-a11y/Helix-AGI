#!/usr/bin/env python3
"""Bounded local-provider recovery tests."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.providers.ollama_provider import OllamaSession
from memory.semantic_encoder import SemanticEncoder


class OllamaRetryTests(unittest.TestCase):
    def test_chat_retries_transient_disconnect_without_duplicate_history(self):
        calls = []

        def chat(**_kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise ConnectionError("daemon restarting")
            return SimpleNamespace(
                message=SimpleNamespace(content="recovered"),
                total_duration=1_000_000,
                eval_count=1,
                prompt_eval_count=2,
            )

        session = OllamaSession("local", "system", options={"num_ctx": 1024})
        session.max_attempts = 2
        with patch("ollama.chat", side_effect=chat), patch("time.sleep"):
            result = session.send_message("hello")

        self.assertEqual(result, "recovered")
        self.assertEqual(len(calls), 2)
        self.assertEqual([item["role"] for item in session.history], ["user", "assistant"])

    def test_auxiliary_keep_alive_is_not_sent_as_generation_option(self):
        response = SimpleNamespace(
            message=SimpleNamespace(content="done"),
            total_duration=1_000_000,
            eval_count=1,
            prompt_eval_count=1,
        )
        session = OllamaSession(
            "worker", "system",
            options={"num_ctx": 16_384, "keep_alive": "0"},
        )
        with patch("ollama.chat", return_value=response) as chat:
            session.send_message("work")

        self.assertEqual(chat.call_args.kwargs["keep_alive"], "0")
        self.assertNotIn("keep_alive", chat.call_args.kwargs["options"])

    def test_strict_semantic_encoder_raises_after_bounded_retries(self):
        encoder = SemanticEncoder(dim=2)
        encoder.max_attempts = 2
        encoder.strict = True
        with patch("ollama.embed", side_effect=ConnectionError("down")), \
                patch("time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "after 2 attempts"):
                encoder.encode_documents(["memory"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
