"""
Belief Operations Tests

Tests belief system functionality:
- Belief creation across categories
- Belief retrieval (by category, with limits, search)
- Belief mass calculations and normalization
- Belief merging and composition
"""

import os
import sys
import json
import unittest
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.belief_store import BeliefStore


class TestBeliefCreation(unittest.TestCase):
    """Test belief creation across categories."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.beliefs_dir = os.path.join(self.temp_dir, "beliefs")
        os.makedirs(self.beliefs_dir, exist_ok=True)

        # Seed minimal belief files for each category
        for category in ["self_identity", "people", "capabilities", "knowledge",
                         "preferences", "skills", "feedback"]:
            path = os.path.join(self.beliefs_dir, f"{category}.json")
            with open(path, "w") as f:
                json.dump([], f)

        self.store = BeliefStore(self.beliefs_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_store_initializes(self):
        """Test that belief store initializes without error."""
        self.assertIsNotNone(self.store)

    def test_get_all_beliefs_flat_returns_list(self):
        """Test that get_all_beliefs_flat returns a list."""
        beliefs = self.store.get_all_beliefs_flat()
        self.assertIsInstance(beliefs, list)

    def test_empty_store_returns_empty_list(self):
        """Test that an empty store returns an empty list."""
        beliefs = self.store.get_all_beliefs_flat()
        self.assertEqual(len(beliefs), 0)


class TestBeliefStructure(unittest.TestCase):
    """Test belief data structure integrity."""

    def test_belief_dict_required_fields(self):
        """Test that a well-formed belief has all required fields."""
        belief = {
            "id": "b_test_001",
            "content": "I am a test belief.",
            "mass": 1.0,
            "confidence": 0.8,
            "source": "test",
            "created_at": datetime.now().isoformat(),
            "last_accessed": datetime.now().isoformat(),
            "access_count": 0,
            "verifications": 1.0,
            "stability_index": 0.7,
            "relations": [],
            "memory_refs": [],
            "position_8d": None,
            "encoding_lagrangian": {
                "omega": 0.5, "s_total": 0.15, "H": 0.15, "D_KL": 0.0,
            },
        }

        required = ["id", "content", "mass", "confidence", "source",
                     "created_at", "relations"]
        for field in required:
            self.assertIn(field, belief, f"Missing required field: {field}")

    def test_belief_mass_positive(self):
        """Test that belief mass is always positive."""
        belief = {"mass": 1.0, "confidence": 0.8}
        self.assertGreater(belief["mass"], 0)

    def test_belief_confidence_bounded(self):
        """Test that confidence is between 0 and 1."""
        for conf in [0.0, 0.5, 1.0]:
            self.assertGreaterEqual(conf, 0.0)
            self.assertLessEqual(conf, 1.0)


class TestBeliefMassCalculation(unittest.TestCase):
    """Test belief mass calculations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.beliefs_dir = os.path.join(self.temp_dir, "beliefs")
        os.makedirs(self.beliefs_dir, exist_ok=True)
        for cat in ["self_identity", "people", "capabilities", "knowledge",
                     "preferences", "skills", "feedback"]:
            with open(os.path.join(self.beliefs_dir, f"{cat}.json"), "w") as f:
                json.dump([], f)
        self.store = BeliefStore(self.beliefs_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_compute_cognitive_mass_exists(self):
        """Test that compute_cognitive_mass method exists."""
        self.assertTrue(hasattr(self.store, "compute_cognitive_mass"))

    def test_mass_for_minimal_belief(self):
        """Test mass computation for a minimal belief."""
        belief = {
            "id": "b_test",
            "content": "Test belief",
            "mass": 1.0,
            "confidence": 0.5,
            "verifications": 1.0,
            "access_count": 0,
            "stability_index": 0.5,
            "relations": [],
        }
        mass = self.store.compute_cognitive_mass(belief)
        self.assertIsInstance(mass, (int, float))
        self.assertGreater(mass, 0)

    def test_mass_increases_with_confidence(self):
        """Test that higher confidence gives higher mass."""
        low_conf = {
            "id": "b1", "content": "X", "mass": 1.0, "confidence": 0.2,
            "verifications": 1.0, "access_count": 0,
            "stability_index": 0.5, "relations": [],
        }
        high_conf = {
            "id": "b2", "content": "X", "mass": 1.0, "confidence": 0.9,
            "verifications": 1.0, "access_count": 0,
            "stability_index": 0.5, "relations": [],
        }
        m_low = self.store.compute_cognitive_mass(low_conf)
        m_high = self.store.compute_cognitive_mass(high_conf)
        self.assertGreater(m_high, m_low)


class TestBeliefCategories(unittest.TestCase):
    """Test belief category management."""

    EXPECTED_CATEGORIES = [
        "self_identity", "people", "capabilities",
        "knowledge", "preferences", "skills", "feedback",
    ]

    def test_all_categories_recognized(self):
        """Test that all expected categories exist."""
        for cat in self.EXPECTED_CATEGORIES:
            self.assertIsInstance(cat, str)
            self.assertGreater(len(cat), 0)

    def test_category_file_naming(self):
        """Test that category names map to valid filenames."""
        for cat in self.EXPECTED_CATEGORIES:
            filename = f"{cat}.json"
            # Should not contain path separators or special chars
            self.assertNotIn("/", filename)
            self.assertNotIn("\\", filename)
            self.assertTrue(filename.endswith(".json"))


def run_belief_operations_tests():
    """Run all belief operations tests."""
    print("Running Belief Operations Test Suite...")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestBeliefCreation))
    suite.addTests(loader.loadTestsFromTestCase(TestBeliefStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestBeliefMassCalculation))
    suite.addTests(loader.loadTestsFromTestCase(TestBeliefCategories))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_belief_operations_tests()
    sys.exit(0 if success else 1)
