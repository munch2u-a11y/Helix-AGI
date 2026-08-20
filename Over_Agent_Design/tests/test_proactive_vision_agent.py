"""
Unit Test Suite for Proactive Vision & Screen Resonance Agent.
Verifies:
1. ProactiveVisionAgent screen summary capture.
2. mRAG memory resonance evaluation.
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from proactive_vision_agent import ProactiveVisionAgent

class FakeMRAG:
    def recall_context(self, query, top_k=3):
        return "--- HELIX mRAG RECALLED CONTEXT ---\n- Relevant local memory"


class FakeBackend:
    def generate(self, **_kwargs):
        return "That workspace connects nicely to your local-memory project."


class TestProactiveVisionAgent(unittest.TestCase):
    def test_screen_summary_capture(self):
        agent = ProactiveVisionAgent(backend=FakeBackend(), mrag_runtime=FakeMRAG())
        summary = agent.capture_screen_summary()
        self.assertIsInstance(summary, str)
        self.assertTrue(len(summary) > 0)
        print(f"\n  ✓ Captured Screen Context Summary: '{summary}'")

    def test_proactive_resonance_evaluation(self):
        agent = ProactiveVisionAgent(backend=FakeBackend(), mrag_runtime=FakeMRAG())
        # Force min_interval = 0 for testing
        event = agent.evaluate_proactive_resonance(min_interval_s=0.0)
        self.assertIsNotNone(event)
        print(f"  ✓ Proactive Speech Triggered: '{event['proactive_speech']}'")
        self.assertIn("proactive_speech", event)

if __name__ == "__main__":
    unittest.main()
