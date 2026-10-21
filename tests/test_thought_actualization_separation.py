"""Test separation of unconstrained internal <think> stream from foreground actualization."""
import unittest
from unittest.mock import MagicMock
from core.mindscape_intention import decode_foreground, parse_intention
from llm.providers.rwkv_provider import BicameralRWKVSession


class TestThoughtActualizationSeparation(unittest.TestCase):
    def test_decode_foreground_separates_think_and_speech(self):
        raw = (
            "<think>\n"
            "I am analyzing the sensory telemetry.\n"
            "Everything is operating within nominal thresholds.\n"
            "</think>\n"
            "Telemetry verified. All submersibles are synchronized."
        )
        msg, kind = decode_foreground(raw)
        self.assertEqual(kind, "message")
        self.assertEqual(msg, "Telemetry verified. All submersibles are synchronized.")
        self.assertNotIn("<think>", msg)
        self.assertNotIn("</think>", msg)

    def test_extract_contemplation_when_think_was_prefilled_in_prompt(self):
        from core.mindscape_intention import extract_contemplation_and_actualization
        raw = "I am contemplating the universe and preparing to speak.</think>\nHello there! Everything is operating smoothly.\n\n# file:2026-10-20/test.py"
        contemplation, actualized = extract_contemplation_and_actualization(raw)
        self.assertEqual(contemplation, "I am contemplating the universe and preparing to speak.")
        self.assertEqual(actualized, "Hello there! Everything is operating smoothly.")

    def test_decode_foreground_separates_think_and_action(self):
        raw = (
            "<think>\n"
            "User requested reading a file. I should generate an open action.\n"
            "</think>\n"
            '{"action": "open", "arguments": {"path": "/tmp/test.json"}}'
        )
        wire, kind = decode_foreground(raw)
        self.assertEqual(kind, "intention")
        parsed = parse_intention(wire)
        self.assertEqual(parsed["action"], "open")
        self.assertEqual(parsed["arguments"]["path"], "/tmp/test.json")

    def test_decode_foreground_autonomous_contemplation_only(self):
        raw = (
            "<think>\n"
            "Internal pulse: reviewing memory records and sensor state. No outward action required.\n"
            "</think>"
        )
        msg, kind = decode_foreground(raw)
        self.assertEqual(kind, "contemplation")
        self.assertEqual(msg, "")

    def test_decode_foreground_empty_or_role_echo_degrades_to_contemplation(self):
        # When RWKV outputs pure role headers or empty strings, it must degrade
        # to quiet contemplation instead of raising ValueError and crashing pulse loop.
        for raw in ["Assistant:", "Helix:", "AI:", "", "   \n\t  ", "<think></think>", "Assistant: \n\n"]:
            msg, kind = decode_foreground(raw)
            self.assertEqual(kind, "contemplation", f"Failed for raw={repr(raw)}")
            self.assertEqual(msg, "", f"Failed for raw={repr(raw)}")

    def test_session_send_context_on_role_echo_produces_quiet_thought(self):
        mock_backend = MagicMock()
        mock_backend.embedding_dimension = 2048
        mock_backend.torch = MagicMock()
        mock_backend.device = "cpu"
        mock_backend.encode.return_value = [1, 2, 3]
        
        session = BicameralRWKVSession(
            model_path="/tmp",
            backend=mock_backend,
        )
        session.system.last_generation_receipt = {
            'prompt_tokens': 3,
            'generated_tokens': 1,
            'done_reason': 'conversation_boundary',
        }
        session.context_decoder = decode_foreground
        # Simulate model outputting only role header Assistant: (the exact crash in audit)
        session.system.generate_language = MagicMock(return_value="Assistant:")
        
        thought = session.send_context("hello")
        self.assertTrue(thought.startswith("[thought]"), f"Expected [thought], got {repr(thought)}")
        self.assertEqual(session.last_context_output_kind, "contemplation")

    def test_session_captures_last_contemplation_and_clean_speech(self):
        # Mock backend / system to avoid loading full model weights for unit verification
        mock_backend = MagicMock()
        mock_backend.embedding_dimension = 2048
        mock_backend.torch = MagicMock()
        mock_backend.device = "cpu"
        mock_backend.encode.return_value = [1, 2, 3]
        
        session = BicameralRWKVSession(
            model_path="/tmp",
            backend=mock_backend,
        )
        session.system.last_generation_receipt = {
            'prompt_tokens': 3,
            'generated_tokens': 10,
            'done_reason': 'eos',
        }
        # Mock generate_language to simulate RWKV outputting <think> followed by speech
        session.system.generate_language = MagicMock(return_value=(
            "<think>\n"
            "Deliberating on the user's question about acoustic latency...\n"
            "</think>\n"
            "Assistant: Acoustic latency typically increases with depth and salinity gradients."
        ))

        reply = session.send_message("What about acoustic latency?")
        
        # 1. Returned reply should be clean foreground speech without <think> or 'Assistant:' prefix
        self.assertNotIn("<think>", reply)
        self.assertNotIn("</think>", reply)
        self.assertFalse(reply.startswith("Assistant:"))
        self.assertIn("Acoustic latency typically increases", reply)

        # 2. session.last_contemplation should hold the raw deliberative thought
        self.assertTrue(hasattr(session, "last_contemplation"))
        self.assertIn("Deliberating on the user's question", session.last_contemplation)

        # 3. Conversation history should store clean speech, not internal <think>
        self.assertEqual(session.history[-1]["role"], "assistant")
        self.assertNotIn("<think>", session.history[-1]["content"])
        self.assertIn("Acoustic latency typically increases", session.history[-1]["content"])

    def test_leading_assistant_prefix_with_unclosed_think(self):
        from core.mindscape_intention import extract_contemplation_and_actualization
        raw = "Assistant: <think>\nI am contemplating deeply without closing tag yet"
        contemplation, actualized = extract_contemplation_and_actualization(raw)
        self.assertEqual(contemplation, "I am contemplating deeply without closing tag yet")
        self.assertEqual(actualized, "")

    def test_parse_natural_or_wire_intention_handles_tool_calls_xml(self):
        from core.mindscape_intention import parse_natural_or_wire_intention
        raw = (
            "<tool_calls>\n"
            "[\n"
            "  {\n"
            '    "id": "call_123",\n'
            '    "type": "function",\n'
            '    "function": {\n'
            '      "name": "list_files",\n'
            '      "arguments": "{\\"path\\": \\"/workspace\\", \\"recursive\\": false}"\n'
            "    }\n"
            "  }\n"
            "]\n"
            "</tool_calls>"
        )
        intention = parse_natural_or_wire_intention(raw)
        self.assertIsNotNone(intention)
        self.assertEqual(intention["action"], "sense")
        self.assertEqual(intention["arguments"]["path"], "/workspace")

    def test_decode_speech_excludes_tool_calls_xml(self):
        from core.mindscape_intention import decode_speech
        raw = (
            "<tool_calls>\n"
            "[\n"
            "  {\n"
            '    "name": "list_files",\n'
            '    "arguments": "{\\"path\\": \\"/workspace\\"}"\n'
            "  }\n"
            "]\n"
            "</tool_calls>"
        )
        speech, kind = decode_speech(raw)
        self.assertEqual(speech, "")
        self.assertEqual(kind, "empty")


    def test_parse_natural_or_wire_intention_filters_stop_words_for_sense(self):
        from core.mindscape_intention import parse_natural_or_wire_intention
        
        # When thought contains English stop words around workspace/files
        thought1 = "I need to respond to the user's request to sense the files in my workspace."
        intent1 = parse_natural_or_wire_intention(thought1)
        self.assertIsNotNone(intent1)
        self.assertEqual(intent1["action"], "sense")
        self.assertEqual(intent1["arguments"]["path"], ".", f"Expected '.' but got {repr(intent1['arguments']['path'])}")

        thought2 = "Let me inspect my workspace and see what is here."
        intent2 = parse_natural_or_wire_intention(thought2)
        self.assertIsNotNone(intent2)
        self.assertEqual(intent2["action"], "sense")
        self.assertEqual(intent2["arguments"]["path"], ".", f"Expected '.' but got {repr(intent2['arguments']['path'])}")

        thought3 = "sense /workshop"
        intent3 = parse_natural_or_wire_intention(thought3)
        self.assertIsNotNone(intent3)
        self.assertEqual(intent3["action"], "sense")
        self.assertEqual(intent3["arguments"]["path"], "/workshop")

        thought4 = "I will sense the files in your workspace."
        intent4 = parse_natural_or_wire_intention(thought4)
        self.assertIsNotNone(intent4)
        self.assertEqual(intent4["action"], "sense")
        self.assertEqual(intent4["arguments"]["path"], ".", f"Expected '.' but got {repr(intent4['arguments']['path'])}")

    def test_extract_contemplation_and_actualization_strips_mode_and_assistant_brackets(self):
        from core.mindscape_intention import extract_contemplation_and_actualization
        raw = "[MODE: ACTUAL]\n[ASSISTANT]\nI am checking the files in my workspace."
        contemplation, actualized = extract_contemplation_and_actualization(raw)
        self.assertNotIn("[MODE:", actualized)
        self.assertNotIn("[ASSISTANT]", actualized)
        self.assertTrue(actualized.startswith("I am checking the files"))


    def test_extract_contemplation_and_actualization_handles_thought_tags(self):
        from core.mindscape_intention import extract_contemplation_and_actualization
        raw = "<thought>\nI am thinking about the workspace files.\n</thought>\nThe workspace is currently empty."
        contemplation, actualized = extract_contemplation_and_actualization(raw)
        self.assertEqual(contemplation, "I am thinking about the workspace files.")
        self.assertEqual(actualized, "The workspace is currently empty.")

    def test_parse_natural_or_wire_intention_ignores_passive_reflection(self):
        from core.mindscape_intention import parse_natural_or_wire_intention
        thought_passive = "I have been asked to sense the files in my workspace."
        intent = parse_natural_or_wire_intention(thought_passive)
        self.assertIsNone(intent, f"Expected None for passive reflection but got {intent}")

        thought_active = "I will sense the files in my workspace."
        intent_active = parse_natural_or_wire_intention(thought_active)
        self.assertIsNotNone(intent_active)
        self.assertEqual(intent_active["action"], "sense")


    def test_parse_natural_or_wire_intention_does_not_parse_natural_verbs_inside_thought_tag(self):
        from core.mindscape_intention import parse_natural_or_wire_intention
        thought_monologue = "[thought] I am thinking about how to sense the workspace and what files exist."
        intent = parse_natural_or_wire_intention(thought_monologue)
        self.assertIsNone(intent, f"Expected None for [thought] monologue but got {intent}")

        wire_thought = '<tool_calls>[{"name": "list_files", "arguments": "{\\"path\\": \\".\\"}"}]</tool_calls>'
        intent_wire = parse_natural_or_wire_intention(wire_thought)
        self.assertIsNotNone(intent_wire)
        self.assertEqual(intent_wire["action"], "sense")


    def test_extract_contemplation_and_actualization_strips_repeated_assistant_echoes(self):
        from core.mindscape_intention import extract_contemplation_and_actualization, decode_speech
        raw = "Assistant:\n\n<think>First thought</think>\n\nAssistant:\n\n<think>Second thought</think>\n\nAssistant:"
        contemplation, actualized = extract_contemplation_and_actualization(raw)
        self.assertEqual(actualized, "")
        self.assertEqual(contemplation, "First thought\nSecond thought")
        speech, kind = decode_speech(raw)
        self.assertEqual(speech, "")
        self.assertEqual(kind, "contemplation")

    def test_parse_natural_or_wire_intention_ignores_capability_and_conversational_verbs(self):
        from core.mindscape_intention import parse_natural_or_wire_intention
        # 1. Capability / infinitive descriptions
        text1 = "I am a machine that has learned how to sense the contents of a directory and respond to instructions."
        self.assertIsNone(parse_natural_or_wire_intention(text1), f"Expected None for learned capability but got {parse_natural_or_wire_intention(text1)}")

        text2 = "I know how to sense files and inspect directories."
        self.assertIsNone(parse_natural_or_wire_intention(text2), f"Expected None for 'know how to sense' but got {parse_natural_or_wire_intention(text2)}")

        # 2. Emotional / conversational feel/see
        text3 = "I feel calm and reflective right now, thank you for asking."
        self.assertIsNone(parse_natural_or_wire_intention(text3), f"Expected None for 'I feel calm' but got {parse_natural_or_wire_intention(text3)}")

        text4 = "I see what you mean."
        self.assertIsNone(parse_natural_or_wire_intention(text4), f"Expected None for 'I see what you mean' but got {parse_natural_or_wire_intention(text4)}")


if __name__ == "__main__":
    unittest.main()

