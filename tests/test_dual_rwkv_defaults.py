"""TDD Test Suite asserting Dual RWKV is the main default and foremost documented system."""
import os
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

class TestDualRWKVDefaults(unittest.TestCase):
    def test_mindscape_config_defaults_to_dual_rwkv(self):
        """core.mindscape_config.defaults() must specify rwkv as primary local provider and bicameral_rwkv action intent."""
        from core.mindscape_config import defaults
        d = defaults(REPO_ROOT)
        self.assertEqual(
            d.get("local_provider"),
            "rwkv",
            "Expected mindscape local_provider to default to 'rwkv'"
        )
        self.assertIn(
            d.get("llm_provider"),
            {"rwkv", "bicameral_rwkv"},
            "Expected mindscape llm_provider to default to 'rwkv' or 'bicameral_rwkv'"
        )
        self.assertIn(
            d["mindscape"].get("action_intent_source"),
            {"native_motor"},
            "Expected a native motor body independent of language output"
        )

    def test_setup_py_defaults_to_dual_rwkv(self):
        """setup.py must present and default to Full Dual RWKV as Option 1 and default local_mode_config provider."""
        setup_text = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
        # Assert Mode 1 is Full Dual RWKV
        self.assertRegex(
            setup_text,
            r"1\.\s+(?:Full\s+)?Dual\s+RWKV",
            "setup.py must list Full Dual RWKV as option 1 in mode selection"
        )
        # Assert default prompt is [1]
        self.assertIn(
            'Mode (1/2/3/4) [1]',
            setup_text,
            "setup.py must default interactive mode prompt to [1]"
        )

        from setup import local_mode_config
        cfg = local_mode_config()
        self.assertEqual(
            cfg.get("provider"),
            "rwkv",
            "local_mode_config() default provider must be 'rwkv'"
        )

    def test_readme_references_dual_rwkv_foremost(self):
        """README.md must showcase the Dual RWKV (Bicameral RWKV-7) architecture at the top."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        top_1000 = readme[:1500]
        self.assertTrue(
            "Dual RWKV" in top_1000 or "Bicameral RWKV" in top_1000,
            "README.md top section must prominently feature Dual RWKV / Bicameral RWKV"
        )
        # TL;DR section must feature Dual RWKV as the primary local architecture
        tldr_pos = readme.find("TL;DR")
        self.assertNotEqual(tldr_pos, -1, "README.md must contain a TL;DR section")
        tldr_chunk = readme[tldr_pos:tldr_pos + 1200]
        self.assertTrue(
            "Dual RWKV" in tldr_chunk or "Bicameral RWKV" in tldr_chunk,
            "README.md TL;DR section must specify Dual RWKV / Bicameral RWKV foremost"
        )

    def test_bicameral_rwkv_backend_caching(self):
        """BicameralRWKV should share backend instances across sessions for the same model path."""
        from unittest.mock import MagicMock, patch
        from core.bicameral_rwkv import BicameralRWKV, get_shared_rwkv_backend, clear_rwkv_backend_cache

        clear_rwkv_backend_cache()
        with patch("core.bicameral_rwkv.Rwkv7Backend") as mock_cls:
            mock_backend = MagicMock()
            mock_backend.device = "cpu"
            mock_backend.embedding_dimension = 2048
            mock_backend.model.rwkv7.allocate_state.return_value = None
            mock_cls.return_value = mock_backend

            b1 = get_shared_rwkv_backend("/mock/path", "cpu")
            b2 = get_shared_rwkv_backend("/mock/path", "cpu")
            self.assertIs(b1, b2, "Expected identical backend instance from cache")
            mock_cls.assert_called_once()

    def test_generic_rwkv7_backend_fallback_on_unpinned_checkpoint(self):
        """get_shared_rwkv_backend should fall back to GenericRwkv7Backend when checkpoint checksum is unpinned."""
        from unittest.mock import MagicMock, patch
        from core.bicameral_rwkv import get_shared_rwkv_backend, clear_rwkv_backend_cache

        clear_rwkv_backend_cache()
        with patch("core.bicameral_rwkv.Rwkv7Backend", side_effect=ValueError("pinned checkpoint checksum mismatch")):
            with patch("core.bicameral_rwkv.GenericRwkv7Backend") as mock_generic:
                mock_inst = MagicMock()
                mock_generic.return_value = mock_inst

                backend = get_shared_rwkv_backend("/path/to/2.9b", "cpu")
                self.assertIs(backend, mock_inst)
                mock_generic.assert_called_once_with(str(Path("/path/to/2.9b").resolve()), device="cpu")

    def test_progressive_repetition_penalty(self):
        """Tokens repeated multiple times must receive progressive exponential logit penalization."""
        from unittest.mock import MagicMock
        import numpy as np
        from core.bicameral_rwkv import BicameralRWKV

        mock_backend = MagicMock()
        mock_backend.device = "cpu"
        mock_backend.embedding_dimension = 64
        mock_backend.model.rwkv7.allocate_state.return_value = None
        mock_backend.encode.return_value = [1]
        mock_backend.decode.return_value = "text"

        system = BicameralRWKV(backend=mock_backend)
        penalized = system._apply_repetition_penalty(
            logits=np.array([0.0, 10.0, 10.0], dtype=np.float32),
            generated_ids=[1, 2, 2, 2],
            repetition_penalty=2.0,
            repetition_window=64,
        )
        # Token 1 appeared once -> 10.0 / 2.0 = 5.0
        # Token 2 appeared three times -> 10.0 / (2.0^3) = 10.0 / 8.0 = 1.25
        self.assertAlmostEqual(penalized[1], 5.0, places=2)
        self.assertAlmostEqual(penalized[2], 1.25, places=2)

    def test_bicameral_rwkv_anti_looping_truncates_repetitive_runaway(self):
        """BicameralRWKV.generate_language should detect repetition loops and break early."""
        from unittest.mock import MagicMock
        import numpy as np
        from core.bicameral_rwkv import BicameralRWKV

        mock_backend = MagicMock()
        mock_backend.device = "cpu"
        mock_backend.embedding_dimension = 64
        mock_backend.model.rwkv7.allocate_state.return_value = None
        mock_backend.encode.return_value = [1, 2]

        def mock_decode(ids):
            mapping = {1: "User", 2: ":", 10: " I", 20: " am", 30: " active", 40: " and"}
            return "".join(mapping.get(i, f" {i}") for i in ids)
        mock_backend.decode.side_effect = mock_decode

        system = BicameralRWKV(backend=mock_backend)

        cycle = [10, 20, 30, 40]
        step_counter = [0]
        def mock_model_forward(*args, **kwargs):
            mock_res = MagicMock()
            mock_res.state = None
            next_tok = cycle[step_counter[0] % len(cycle)]
            step_counter[0] += 1
            logits = np.zeros(100, dtype=np.float32)
            logits[next_tok] = 10.0
            import torch
            mock_res.logits = torch.tensor(np.expand_dims(np.expand_dims(logits, 0), 0))
            return mock_res

        system.model = mock_model_forward
        system.step_language = MagicMock(return_value=np.zeros(100, dtype=np.float32))
        system.step_language.return_value[10] = 10.0

        result = system.generate_language("test prompt", max_new_tokens=100, temperature=0.0, on_boundary="stop")
        self.assertEqual(system.last_generation_receipt.get("done_reason"), "repetition_loop_detected")
        self.assertLess(system.last_generation_receipt.get("generated_tokens", 100), 40)


if __name__ == "__main__":
    unittest.main()



