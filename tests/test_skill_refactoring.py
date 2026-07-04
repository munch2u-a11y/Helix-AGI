"""
Unit tests for Helix AGI's gravity math, relevance floor, mark_surfaced, goal anchoring,
one-shot skill promotion, and permanent skill reliance features.
"""

import os
import sys
import math
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognitive_space import CognitiveSpace
from core.preconscious import Preconscious
from memory.belief_store import BeliefStore
from core.batch_service import _promote_to_skill, process_pending_beliefs


class TestSkillRefactoring(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.beliefs_dir = os.path.join(self.temp_dir, "beliefs")
        os.makedirs(self.beliefs_dir, exist_ok=True)

        # Seed categories with empty arrays
        for category in ["premises", "propositions", "preferences", "skills", "desires", "people", "concepts"]:
            path = os.path.join(self.beliefs_dir, f"{category}.json")
            with open(path, "w") as f:
                f.write("[]")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch.dict(os.environ, {"HELIX_GRAVITY_MASS_EXPONENT": "0.6"})
    def test_sublinear_mass_exponent(self):
        """Verify that gravity scoring and force calculation use the sub-linear mass exponent (alpha)."""
        space = CognitiveSpace()
        space._current_pulse = 1
        
        # Test query_nearest_by_gravity with alpha=0.6
        point_data = {
            "id": "p1",
            "position": np.zeros(8, dtype=np.float32),
            "type": "belief",
            "confidence": 0.8,
            "importance": 2.0,
            "relations_count": 0,
            "access_count": 0,
            "stability_index": 0.5,
            "creation_pulse": 0,
            "last_accessed_pulse": 0,
            "volatile_mass": 0.0,
            "metadata": {}
        }
        space._points["p1"] = point_data
        
        # Mock tree search
        space.query_nearby = MagicMock(return_value=[("p1", 1.0)])
        space._compute_structural_mass = MagicMock(return_value=2.0)
        space._compute_temperature = MagicMock(return_value=1.0)

        # Query nearest
        results = space.gravity_ranked_query(position=np.ones(8, dtype=np.float32), k=1)
        self.assertEqual(len(results), 1)
        p_id, gravity, dist = results[0]
        
        # gravity = T * mass^alpha / d^2
        # d = max(1.0, 0.05) = 1.0
        expected_gravity = 1.0 * (2.0 ** 0.6) / 1.0
        self.assertAlmostEqual(gravity, expected_gravity, places=4)

    @patch.dict(os.environ, {"HELIX_BELIEF_RELEVANCE_FLOOR": "0.28"})
    def test_absolute_relevance_floor(self):
        """Verify that preconscious filter drops beliefs below the relevance floor."""
        physics = MagicMock()
        physics.embed_and_project = MagicMock(return_value=np.zeros(8))
        # Mock semantic search embeddings and similarities
        query_emb = np.array([1.0, 0.0, 0.0])
        physics.embed_text = MagicMock(return_value=query_emb)
        
        precon = Preconscious(
            memory_manager=MagicMock(),
            belief_store=MagicMock(),
            physics_engine=physics
        )
        
        # Set up a mock 384D matrix with 2 entries:
        # Index 0: similarity = 0.50 (above floor 0.28)
        # Index 1: similarity = 0.20 (below floor 0.28)
        precon._belief_emb_matrix = np.array([
            [0.5, 0.0, 0.0],
            [0.2, 0.0, 0.0]
        ])
        precon._belief_emb_reverse_map = {0: 0, 1: 1}
        precon._belief_cache = [
            {"id": "b1", "content": "belief 1", "category": "premises", "position_8d": np.zeros(8)},
            {"id": "b2", "content": "belief 2", "category": "premises", "position_8d": np.zeros(8)}
        ]
        
        # Run gravity query
        candidates = precon._gravity_query(seed_text="test", exclude=set(), max_results=2)
        # Candidate b2 (index 1) should be filtered out
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "b1")

    def test_mark_surfaced_no_increment(self):
        """Verify that mark_surfaced does not increment access_count or update last_accessed_pulse."""
        space = CognitiveSpace()
        space._current_pulse = 10
        
        point_data = {
            "position": np.zeros(8),
            "type": "belief",
            "confidence": 0.5,
            "importance": 1.0,
            "relations_count": 0,
            "access_count": 2,
            "stability_index": 0.5,
            "last_accessed_pulse": 5,
            "volatile_mass": 0.0,
            "metadata": {}
        }
        space._points["b1"] = point_data
        
        space.mark_surfaced("b1")
        
        # Verify that access_count and last_accessed_pulse are unchanged
        self.assertEqual(point_data["access_count"], 2)
        self.assertEqual(point_data["last_accessed_pulse"], 5)
        # Verify that last_surfaced_pulse is updated
        self.assertEqual(point_data["last_surfaced_pulse"], 10)
        self.assertTrue("last_surfaced" in point_data)

    @patch.dict(os.environ, {"HELIX_GOAL_ANCHOR_WEIGHT": "3.0"})
    def test_goal_anchoring_pull(self):
        """Verify that active goals in the scratchpad act as retrieval anchors with higher weight."""
        physics = MagicMock()
        physics.embed_and_project = MagicMock(return_value=np.zeros(8))
        
        scratchpad = MagicMock()
        scratchpad.get_active_notes = MagicMock(return_value=[{"content": "complete the task"}])
        
        precon = Preconscious(
            memory_manager=MagicMock(),
            belief_store=MagicMock(),
            physics_engine=physics,
            scratchpad=scratchpad
        )
        
        # Mock _gravity_query to return a dummy belief
        precon._gravity_query = MagicMock(side_effect=[
            # First call is for the goal seed "complete the task"
            [{"id": "b_goal", "content": "goal belief", "category": "propositions", "gravity": 1.0}],
            # Second call is for the concept seed "concept"
            [{"id": "b_concept", "content": "concept belief", "category": "propositions", "gravity": 1.0}]
        ])
        
        precon._ensure_belief_cache = MagicMock()
        precon._belief_cache = [1]
        
        # Run pull relevant beliefs
        precon._concept_extractor = MagicMock()
        precon._concept_extractor.extract = MagicMock(return_value={"concepts": ["concept"], "budget": 2})
        
        precon._deduplicate_beliefs = lambda x: x
        precon._compute_focus_budget = MagicMock(return_value=(10, 2))
        precon._galaxy_map = MagicMock()
        precon._galaxy_map.is_built = False
        
        block, ids = precon._pull_relevant_beliefs("last thought", [])
        
        # Verify that _gravity_query was called for both goal and concept
        self.assertEqual(precon._gravity_query.call_count, 2)
        precon._gravity_query.assert_any_call(
            seed_text="complete the task", exclude=unittest.mock.ANY, max_results=unittest.mock.ANY, min_results=unittest.mock.ANY
        )
        precon._gravity_query.assert_any_call(
            seed_text="concept", exclude=unittest.mock.ANY, max_results=unittest.mock.ANY, min_results=unittest.mock.ANY
        )

    def test_permanent_skill_reliance(self):
        """Verify that skill reliance increments stability and verifications permanently, updating mass."""
        store = BeliefStore(self.beliefs_dir)
        
        # Create a skill belief
        store.add_belief(
            category="skills",
            belief_id="skl_test",
            content="To code: write it",
            mass=1.0,
            confidence=0.6,
            source="test",
            stability_index=0.5,
            verifications=1.0
        )
        
        # Register reliance
        store.register_reliance("skl_test", current_pulse=10)
        
        # Retrieve the updated belief
        b = store.get_belief("skl_test")
        self.assertIsNotNone(b)
        
        # stability_index should increase from 0.5 to 0.55
        self.assertAlmostEqual(b["stability_index"], 0.55, places=3)
        # verifications should increase from 1.0 to 2.0
        self.assertEqual(b["verifications"], 2.0)
        # volatile_mass should remain 0.0
        self.assertEqual(b.get("volatile_mass", 0.0), 0.0)
        # Mass should be recomputed permanently
        self.assertTrue(b["mass"] > 1.0)

    @patch("core.batch_service._call_llm")
    def test_one_shot_skill_promotion(self, mock_call_llm):
        """Verify that one-shot contingency realization is formatted and promoted to skills."""
        # Mock LLM to return valid skill extraction
        mock_call_llm.return_value = (
            "SKILL: To debug issues: check the log files\n"
            "TRIGGER: debugging issues\n"
            "ALIASES: debug, errors, stack trace, logs"
        )
        
        content = "If I need to debug issues, I should check the log files."
        result = _promote_to_skill(content)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["content"], "To debug issues: check the log files")
        self.assertEqual(result["term"], "debugging issues")
        self.assertEqual(result["aliases"], ["debug", "errors", "stack trace", "logs"])


if __name__ == "__main__":
    unittest.main()
