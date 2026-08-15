#!/usr/bin/env python3
"""Regression tests for one-switch Codex-backed Helix agent setup."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from setup import subscription_cli_config, upsert_env_values
from wizard.model_detector import codex_app_server_probe


class CodexAgentSetupTests(unittest.TestCase):
    def test_codex_subscription_enables_modular_agent_mode(self):
        config = subscription_cli_config("codex_cli", "")
        self.assertEqual(config["task_cognition_mode"], "active")
        self.assertTrue(config["cli_agent_mode"])
        self.assertEqual(config["tool_format"], "api")

    def test_claude_remains_observe_until_focus_transport_is_supported(self):
        config = subscription_cli_config("claude_cli", "")
        self.assertEqual(config["task_cognition_mode"], "observe")
        self.assertFalse(config["cli_agent_mode"])

    def test_env_upsert_preserves_unrelated_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.env"
            path.write_text(
                "# keep this\nGEMINI_API_KEY=secret-value\nHELIX_PROVIDER=gemini\n"
            )
            upsert_env_values(path, {
                "HELIX_PROVIDER": "codex_cli",
                "HELIX_MODEL": "",
            })
            rendered = path.read_text()
            self.assertIn("# keep this", rendered)
            self.assertIn("GEMINI_API_KEY=secret-value", rendered)
            self.assertIn("HELIX_PROVIDER=codex_cli", rendered)
            self.assertIn("HELIX_MODEL=", rendered)
            self.assertEqual(rendered.count("HELIX_PROVIDER="), 1)

    def test_readiness_probe_checks_app_server_not_login_alone(self):
        with patch(
            "wizard.model_detector.codex_login_status",
            return_value="Logged in using ChatGPT",
        ), patch(
            "llm.providers.codex_cli_provider.CodexCliSession",
        ) as session_class:
            ready, status = codex_app_server_probe()
        self.assertTrue(ready)
        self.assertIn("App Server handshake: ready", status)
        session_class.return_value.close.assert_called_once_with()

    def test_readiness_probe_surfaces_handshake_failure(self):
        with patch(
            "wizard.model_detector.codex_login_status",
            return_value="Logged in using ChatGPT",
        ), patch(
            "llm.providers.codex_cli_provider.CodexCliSession",
            side_effect=RuntimeError("unsupported app-server"),
        ):
            ready, status = codex_app_server_probe()
        self.assertFalse(ready)
        self.assertIn("unsupported app-server", status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
