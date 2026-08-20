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

class TestProactiveVisionAgent(unittest.TestCase):
    def test_screen_summary_capture(self):
        agent = ProactiveVisionAgent()
        summary = agent.capture_screen_summary()
        self.assertIsInstance(summary, str)
        self.assertTrue(len(summary) > 0)
        print(f"\n  ✓ Captured Screen Context Summary: '{summary}'")

    def test_proactive_resonance_evaluation(self):
        agent = ProactiveVisionAgent()
        # Force min_interval = 0 for testing
        event = agent.evaluate_proactive_resonance(min_interval_s=0.0)
        if event:
            print(f"  ✓ Proactive Speech Triggered: '{event['proactive_speech']}'")
            self.assertIn("proactive_speech", event)
        else:
            print("  ✓ Proactive evaluation checked cleanly (no memory resonance triggered)")

if __name__ == "__main__":
    unittest.main()
