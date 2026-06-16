import os
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.auxiliary_llm as aux_module
from core.auxiliary_llm import AuxiliaryLLM
from core.batch_service import _confidence_blend_weights
from core.cognitive_space import CognitiveSpace
from llm.providers.base import ProviderConfig


class CognitiveScalingTests(unittest.TestCase):
    def test_memory_temperature_scales_with_manifold_growth(self):
        small = CognitiveSpace()
        small.GROWTH_TARGET_POINTS = 10.0
        small._current_pulse = 50

        large = CognitiveSpace()
        large.GROWTH_TARGET_POINTS = 10.0
        large._current_pulse = 50
        for i in range(10):
            large._points[f"mem_{i}"] = {
                "position": np.zeros(8, dtype=np.float32),
                "type": "memory",
            }

        point = {
            "type": "memory",
            "importance": 0.8,
            "creation_pulse": 0,
            "last_accessed_pulse": 0,
        }

        self.assertGreater(
            large._compute_temperature(point),
            small._compute_temperature(point),
        )

    def test_memory_recency_mass_scales_with_manifold_growth(self):
        small = CognitiveSpace()
        small.GROWTH_TARGET_POINTS = 10.0
        small._current_pulse = 30

        large = CognitiveSpace()
        large.GROWTH_TARGET_POINTS = 10.0
        large._current_pulse = 30
        for i in range(10):
            large._points[f"mem_{i}"] = {
                "position": np.zeros(8, dtype=np.float32),
                "type": "memory",
            }

        point = {
            "type": "memory",
            "importance": 0.7,
            "access_count": 0,
            "relations_count": 0,
            "encoding_omega": 0.5,
            "creation_pulse": 0,
            "last_accessed_pulse": 0,
        }

        self.assertGreater(
            large._compute_structural_mass(point),
            small._compute_structural_mass(point),
        )


class ConfidenceTuningTests(unittest.TestCase):
    def test_confidence_blend_weights_shift_toward_support_with_maturity(self):
        support_small, source_small = _confidence_blend_weights(0)
        support_large, source_large = _confidence_blend_weights(1000)

        self.assertGreater(support_large, support_small)
        self.assertLess(source_large, source_small)
        self.assertAlmostEqual(support_small + source_small, 1.0, places=6)
        self.assertAlmostEqual(support_large + source_large, 1.0, places=6)


class AuxiliaryLLMTests(unittest.TestCase):
    def tearDown(self):
        aux_module._client = None

    def test_generate_retries_transient_failures(self):
        client = AuxiliaryLLM()

        with patch.object(client, "_generate_gemini", side_effect=[
            RuntimeError("transient one"),
            RuntimeError("transient two"),
            "ok",
        ]) as mocked_generate, patch.object(aux_module.time, "sleep", return_value=None):
            result = client.generate("prompt")

        self.assertEqual(result, "ok")
        self.assertEqual(mocked_generate.call_count, 3)

    def test_generate_does_not_retry_import_error(self):
        client = AuxiliaryLLM()

        with patch.object(client, "_generate_gemini", side_effect=ImportError("missing backend")) as mocked_generate:
            result = client.generate("prompt")

        self.assertIsNone(result)
        self.assertEqual(mocked_generate.call_count, 1)

    def test_gemini_client_is_cached(self):
        client = AuxiliaryLLM()
        fake_google = types.ModuleType("google")

        class FakeGenAI:
            created = 0

            class Client:
                def __init__(self, api_key):
                    FakeGenAI.created += 1
                    self.api_key = api_key

        fake_google.genai = FakeGenAI

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False), patch.dict(sys.modules, {"google": fake_google}):
            first = client._get_gemini_client()
            second = client._get_gemini_client()

        self.assertIs(first, second)
        self.assertEqual(FakeGenAI.created, 1)

    def test_init_auxiliary_client_reuses_existing_instance_without_new_config(self):
        provider = ProviderConfig(provider_type="gemini", model="test-model")

        first = aux_module.init_auxiliary_client(provider)
        second = aux_module.init_auxiliary_client()

        self.assertIs(first, second)
        self.assertIs(aux_module.get_auxiliary_client(), first)


if __name__ == "__main__":
    unittest.main()
