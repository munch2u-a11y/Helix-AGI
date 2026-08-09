#!/usr/bin/env python3
"""Tests for bounded affect bids in the shared Context Office budget."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.affect_field import InterferenceResult
from core.affect_office import AffectOffice


class AffectOfficeTests(unittest.TestCase):
    def test_neutral_unrelated_turn_submits_no_bid(self):
        result = InterferenceResult()
        with patch("core.affect_hook.get_last_result", return_value=result):
            proposed = AffectOffice().propose("What is the launch date?", {}, [])
        self.assertEqual(proposed, [])

    def test_explicit_affect_turn_submits_compact_state(self):
        result = InterferenceResult(
            field_intensity=0.61,
            dominant_affect="trust",
            contributing_packets=3,
        )
        with patch("core.affect_hook.get_last_result", return_value=result):
            proposed = AffectOffice().propose("How do you feel about this?", {}, [])
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["office_role"], "affect_state")
        self.assertIn("trust", proposed[0]["content"])

    def test_resonant_memories_are_bounded_and_not_factual_proof(self):
        result = InterferenceResult(
            field_intensity=0.7,
            dominant_affect="sadness",
            reactivation_strength=0.8,
            surfaced_memories=["mem_1", "mem_2", "mem_3"],
        )
        corpus = {
            f"mem_{index}": {
                "id": f"mem_{index}", "content": f"memory {index}", "tier": 0,
            }
            for index in range(1, 4)
        }
        with patch("core.affect_hook.get_last_result", return_value=result):
            proposed = AffectOffice().propose("I feel sad about Mom.", corpus, [])
        resonant = [item for item in proposed if item["office_role"] == "affective_resonance"]
        self.assertEqual(len(resonant), 2)
        self.assertTrue(all(not item["office_verified"] for item in resonant))


if __name__ == "__main__":
    unittest.main(verbosity=2)
