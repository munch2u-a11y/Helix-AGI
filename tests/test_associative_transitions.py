#!/usr/bin/env python3
"""Tests for sequence-sensitive cluster association learning."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.associative_transitions import AssociativeTransitionMemory
from core.preconscious import Preconscious


def _pos(axis: int) -> np.ndarray:
    result = np.zeros(8, dtype=np.float32)
    result[axis] = 1.0
    return result


class TestAssociativeTransitions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="helix_association_test_")
        self.memory = AssociativeTransitionMemory(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _teach(self, source="guilt", destination="mother", repetitions=2):
        for _ in range(repetitions):
            self.memory.break_sequence()
            self.memory.observe(source, _pos(0))
            self.memory.observe(destination, _pos(1))

    def test_one_transition_does_not_become_a_habit(self):
        self._teach(repetitions=1)
        self.assertEqual(self.memory.recall("guilt"), [])

    def test_repeated_direct_transition_is_recalled(self):
        self._teach(repetitions=2)
        recalled = self.memory.recall("guilt")
        self.assertEqual(recalled[0]["cluster_id"], "mother")
        self.assertEqual(recalled[0]["hops"], 1)

    def test_transition_is_directed(self):
        self._teach(repetitions=3)
        self.assertEqual(self.memory.recall("mother"), [])

    def test_two_hop_chain_remains_faintly_available(self):
        self._teach("guilt", "mother", repetitions=3)
        self._teach("mother", "relationships", repetitions=3)

        recalled = self.memory.recall("guilt", limit=3)
        by_id = {item["cluster_id"]: item for item in recalled}
        self.assertIn("mother", by_id)
        self.assertIn("relationships", by_id)
        self.assertEqual(by_id["relationships"]["hops"], 2)
        self.assertGreater(by_id["mother"]["score"], by_id["relationships"]["score"])

    def test_only_cluster_overlay_moves(self):
        guilt = _pos(0)
        mother = _pos(1)
        guilt_before = guilt.copy()
        mother_before = mother.copy()

        self.memory.observe("guilt", guilt)
        self.memory.observe("mother", mother)

        # Caller-owned item positions remain canonical.
        np.testing.assert_array_equal(guilt, guilt_before)
        np.testing.assert_array_equal(mother, mother_before)
        # Separate cluster prototypes acquire the small Hebbian nudge.
        self.assertFalse(np.array_equal(self.memory.positions["guilt"], guilt_before))
        self.assertFalse(np.array_equal(self.memory.positions["mother"], mother_before))

    def test_same_cluster_is_not_a_transition(self):
        self.memory.observe("story", _pos(0))
        learned = self.memory.observe("story", _pos(0))
        self.assertFalse(learned)
        self.assertEqual(self.memory.edges, {})

    def test_state_round_trip(self):
        self._teach(repetitions=3)
        self.memory.save()

        restored = AssociativeTransitionMemory(self.tmp)
        recalled = restored.recall("guilt")
        self.assertEqual(recalled[0]["cluster_id"], "mother")


class TestRawSpatialLane(unittest.TestCase):
    def test_raw_lane_is_trajectory_relative_and_does_not_refresh_candidates(self):
        captured = {}

        class _Physics:
            def query_neighborhood(self, **kwargs):
                captured.update(kwargs)
                return [
                    {"point_id": "bel_1", "content": "lateral belief", "relevance": 2.0,
                     "mass": 1.0, "type": "belief"},
                    {"point_id": "mem_2", "content": "lateral memory", "relevance": 1.5,
                     "mass": 0.7, "type": "memory"},
                ]

        pre = Preconscious.__new__(Preconscious)
        pre.physics = _Physics()
        pre.RAW_SPATIAL_K = 12

        results = pre._raw_spatial_candidates("current topic")

        self.assertTrue(captured["attention_relative"])
        self.assertFalse(captured["refresh_access"])
        self.assertEqual([item["id"] for item in results], ["bel_1", "mem_2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
