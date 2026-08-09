#!/usr/bin/env python3
"""Credential-loading precedence tests for benchmark transports."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cli_benchmark_adapter import _load_helix_credentials


class CredentialPrecedenceTests(unittest.TestCase):
    def test_saved_defaults_do_not_override_explicit_runtime_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            credentials = Path(tmp) / "credentials.env"
            credentials.write_text(
                "HELIX_PROVIDER=gemini\nHELIX_MODEL=saved-model\nSAVED_ONLY=yes\n",
                encoding="utf-8",
            )
            target = {
                "HELIX_PROVIDER": "ollama",
                "HELIX_MODEL": "granite4.1:8b",
            }
            with patch(
                "scripts.cli_benchmark_adapter._helix_credentials_path",
                return_value=credentials,
            ):
                loaded = _load_helix_credentials(target)

        self.assertEqual(loaded, credentials)
        self.assertEqual(target["HELIX_PROVIDER"], "ollama")
        self.assertEqual(target["HELIX_MODEL"], "granite4.1:8b")
        self.assertEqual(target["SAVED_ONLY"], "yes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
