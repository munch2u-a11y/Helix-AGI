"""Tests for role grounding and eliminating arbitrary User: labelling of internal pulse state."""
import unittest
from llm.rwkv_tokens import RWKVTokenCounter
from llm.providers.rwkv_provider import BicameralRWKVSession


class TestRWKVRoleGrounding(unittest.TestCase):
    def test_render_messages_supports_context_role_without_user_label(self):
        """Context role must render internal pulse content directly without prepending User: label."""
        messages = [
            {"role": "system", "content": "You are Ada."},
            {"role": "context", "content": "[MODE: PULSE]\nMy current feeling: alert."},
        ]
        rendered = RWKVTokenCounter.render_messages(messages)
        self.assertNotIn("User:", rendered, "Internal pulse context must not be labeled as User:")
        self.assertIn("[MODE: PULSE]\nMy current feeling: alert.", rendered)
        self.assertTrue(rendered.endswith("\n\nAssistant:"), "Prompt must terminate on Assistant: boundary")

    def test_rwkv_provider_context_messages_uses_context_role(self):
        """BicameralRWKVSession.context_messages must use 'context' role for pulse context, not 'user'."""
        session = BicameralRWKVSession.__new__(BicameralRWKVSession)
        session.system_instruction = "You are Ada."
        session.history = []
        session.compiled_context_only = False
        msgs = session.context_messages("[MODE: PULSE]\nInternal state")
        self.assertEqual(msgs[-1]["role"], "context", "Pulse context role must be 'context', not 'user'")
        self.assertEqual(msgs[-1]["content"], "[MODE: PULSE]\nInternal state")


if __name__ == "__main__":
    unittest.main()
