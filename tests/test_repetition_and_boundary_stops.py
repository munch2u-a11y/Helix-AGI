import unittest
import inspect
from core.bicameral_rwkv import BicameralRWKV


class TestRepetitionAndBoundaryStops(unittest.TestCase):
    def test_repetition_detection_catches_55_token_cycle(self):
        # A repeating pattern of 55 unique tokens repeated 3 times
        cycle = list(range(100, 155))
        generated_ids = cycle * 3

        # Default _detect_repetition_loop should detect cycles up to at least 128 tokens
        detected = BicameralRWKV._detect_repetition_loop(generated_ids)
        self.assertTrue(detected, "Default _detect_repetition_loop failed to catch a 55-token cycle")

    def test_default_stop_sequences_include_markdown_turn_delimiters(self):
        sig = inspect.signature(BicameralRWKV.generate_language)
        default_stops = sig.parameters["stop_sequences"].default
        self.assertIn("\n---\n", default_stops, "Missing '\\n---\\n' turn stop sequence")
        self.assertIn("\n## ", default_stops, "Missing '\\n## ' turn stop sequence")
        self.assertNotIn("\n<think>", default_stops, "\\n<think> must not be in stop_sequences as it truncates thought generation")
        self.assertNotIn("\n\n<think>", default_stops, "\\n\\n<think> must not be in stop_sequences as it truncates thought generation")

    def test_rwkv_provider_default_stop_sequences_exclude_think(self):
        import unittest.mock as mock
        from llm.providers.rwkv_provider import BicameralRWKVSession
        mock_backend = mock.MagicMock()
        mock_backend.encode.return_value = [1, 2, 3]
        provider = BicameralRWKVSession(model_path="test-model", backend=mock_backend)
        # Mock system to inspect passed stop_sequences
        mock_system = mock.MagicMock()
        mock_system.generate_language.return_value = "<think>\nThinking</think>\nHello!"
        mock_system.last_generation_receipt = {"prompt_tokens": 5, "generated_tokens": 10}
        provider.system = mock_system
        provider.context_counter = mock.MagicMock()
        provider.context_counter.count.return_value = 5
        provider.context_counter.check_request.return_value = {"prompt_tokens": 5}
        provider.context_counter.render_messages.return_value = "Hello"


        provider._generate("Hello")
        called_args, called_kwargs = mock_system.generate_language.call_args
        stop_seqs = called_kwargs.get("stop_sequences", ())
        self.assertNotIn("\n<think>", stop_seqs, "\\n<think> must not be in provider stop_sequences")
        self.assertNotIn("\n\n<think>", stop_seqs, "\\n\\n<think> must not be in provider stop_sequences")


