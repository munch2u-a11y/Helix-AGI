"""Unit tests for LoCoMo factual tracking and RWKV reader configuration."""
import unittest
from unittest.mock import patch


class TestLoCoMoFactualTracking(unittest.TestCase):
    """Verify factual tracking categorization and CLI contracts."""

    def test_cli_parser_supports_rwkv_and_ingest_mode(self):
        from tests.locomo_sandbox import build_argument_parser

        parser = build_argument_parser()
        args = parser.parse_args([
            "--backend", "rwkv",
            "--ingest-mode", "scripted",
            "--maintenance", "cases",
        ])
        self.assertEqual(args.backend, "rwkv")
        self.assertEqual(args.ingest_mode, "scripted")
        self.assertEqual(args.maintenance, "cases")

    def test_load_provider_config_rwkv(self):
        from tests.locomo_sandbox import load_provider_config

        config = load_provider_config(backend="rwkv")
        self.assertIsNotNone(config)
        self.assertEqual(config.provider_type, "rwkv")
        self.assertEqual(config.temperature, 0.2)
        self.assertGreaterEqual(config.context_window, 8192)
        self.assertEqual(config.max_output_tokens, 128)
        self.assertIsNotNone(config.options)
        self.assertEqual(config.options.get("on_boundary"), "truncate")
        self.assertIn("stop_sequences", config.options)

    def test_rwkv_on_boundary_truncate(self):
        import numpy as np
        from unittest.mock import MagicMock
        from core.bicameral_rwkv import BicameralRWKV

        rwkv = BicameralRWKV.__new__(BicameralRWKV)
        rwkv.cancel_event = MagicMock(is_set=MagicMock(return_value=False))
        rwkv.generation_progress = None
        rwkv.backend = MagicMock()
        rwkv.backend.encode.return_value = [10]
        rwkv.backend.decode.side_effect = lambda ids: f"Answer {len(ids)}"
        rwkv.backend.eos_token_id = 9999
        rwkv.step_language = MagicMock(return_value=np.zeros(100))
        rwkv.membrane = MagicMock()
        rwkv.feedback_language_to_sensory = MagicMock()
        rwkv.torch = MagicMock()
        rwkv.device = "cpu"
        rwkv.model = MagicMock()
        mock_result = MagicMock()
        mock_result.state = None
        mock_result.logits = MagicMock()
        mock_result.logits.__getitem__.return_value.detach.return_value.float.return_value.cpu.return_value.numpy.return_value = np.zeros(100)
        rwkv.model.return_value = mock_result

        # With on_boundary='truncate', reaching max_new_tokens returns text without raising
        text = rwkv.generate_language("prompt", max_new_tokens=2, on_boundary="truncate")
        self.assertEqual(text, "Answer 2")

        # With on_boundary='raise', reaching max_new_tokens raises RuntimeError
        with self.assertRaises(RuntimeError):
            rwkv.generate_language("prompt", max_new_tokens=2, on_boundary="raise")


    def test_classify_factual_fate(self):
        from tests.locomo_sandbox import classify_factual_fate

        # 1. Accurately recalled when F1 >= 0.5
        fate_hit = classify_factual_fate(
            category=1,
            answer_em=1.0,
            answer_f1=1.0,
            evidence=["D1:2", "D1:4"],
            retrieved_ids=["D1:2", "D1:5"],
        )
        self.assertEqual(fate_hit["fate"], "ACCURATELY_RECALLED")
        self.assertTrue(fate_hit["retrieval_hit"])
        self.assertEqual(fate_hit["retrieved_evidence"], ["D1:2"])
        self.assertEqual(fate_hit["missing_evidence"], ["D1:4"])

        # 2. Lost in reasoning when evidence in context but F1 < 0.5
        fate_reasoning = classify_factual_fate(
            category=2,
            answer_em=0.0,
            answer_f1=0.2,
            evidence=["D2:1"],
            retrieved_ids=["D2:1", "D3:4"],
        )
        self.assertEqual(fate_reasoning["fate"], "LOST_IN_REASONING")
        self.assertTrue(fate_reasoning["retrieval_hit"])

        # 3. Lost in retrieval when evidence never reached context
        fate_retrieval = classify_factual_fate(
            category=4,
            answer_em=0.0,
            answer_f1=0.0,
            evidence=["D4:8"],
            retrieved_ids=["D1:1", "D2:2"],
        )
        self.assertEqual(fate_retrieval["fate"], "LOST_IN_RETRIEVAL")
        self.assertFalse(fate_retrieval["retrieval_hit"])

        # 4. Correct abstention for Category 5 adversarial questions
        fate_abstain = classify_factual_fate(
            category=5,
            answer_em=1.0,
            answer_f1=1.0,
            evidence=[],
            retrieved_ids=["D1:1"],
        )
        self.assertEqual(fate_abstain["fate"], "CORRECT_ABSTENTION")

        # 5. Failed abstention (hallucination) for Category 5 adversarial questions
        fate_hallucinate = classify_factual_fate(
            category=5,
            answer_em=0.0,
            answer_f1=0.1,
            evidence=[],
            retrieved_ids=["D1:1"],
        )
        self.assertEqual(fate_hallucinate["fate"], "FAILED_ABSTENTION")


if __name__ == "__main__":
    unittest.main()
