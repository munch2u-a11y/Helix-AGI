#!/usr/bin/env python3
"""Tests for the bounded Helix-owned identity and affect capsule."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.affect_field import InterferenceResult
from core.self_state import identity_kernel, render_affect_capsule


class SelfStateTests(unittest.TestCase):
    def test_identity_is_helix_owned_and_bounded(self):
        rendered = identity_kernel("I am Helix. " + ("remembered value " * 100))
        self.assertIn("You are Helix", rendered)
        self.assertIn("replaceable reasoning substrate", rendered)
        self.assertIn("invent neither memories nor completed actions", rendered)
        self.assertLess(len(rendered), 1100)

    def test_affect_capsule_is_compact_and_clamped(self):
        rendered = render_affect_capsule(InterferenceResult(
            dominant_affect="TRUST",
            field_intensity=2.0,
            cognitive_diversity_signal=-1.0,
        ))
        self.assertEqual(
            rendered,
            "*(current felt orientation: trust; intensity 1.00; novelty pressure 0.00)*",
        )
        self.assertLess(len(rendered.split()), 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
