import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.curator import Curator
from core.physics_engine import PhysicsEngine
from core.preconscious import Preconscious
from memory.belief_store import BeliefStore
from memory.memory_manager import MemoryManager


class _NoopLLM:
    def generate(self, *args, **kwargs):
        raise RuntimeError("LLM not needed for this test")


class RuntimeIntegrityTests(unittest.TestCase):
    def test_memory_counter_resumes_from_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(os.path.join(tmp, "memory"))
            self.assertEqual(memory.store("first"), 1)
            self.assertEqual(memory.store("second"), 2)

            restarted = MemoryManager(os.path.join(tmp, "memory"))
            self.assertEqual(restarted.store("third"), 3)

    def test_belief_add_syncs_runtime_and_journal_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(os.path.join(tmp, "memory"))
            beliefs = BeliefStore(os.path.join(tmp, "beliefs"))
            physics = PhysicsEngine(data_dir=os.path.join(tmp, "spatial"))

            memory.set_physics(physics)
            beliefs.set_runtime(physics_engine=physics, memory_manager=memory)

            stored = beliefs.add_belief(
                category="premises",
                belief_id="pre_test_001",
                content="I reliably preserve canonical spatial state.",
                confidence=0.92,
                position_8d=[1.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                encoding_lagrangian={"omega": 0.8, "s_total": 0.1, "H": 0.15, "D_KL": 0.0},
            )

            self.assertTrue(stored)
            self.assertEqual(physics.spatial_mind.belief_space.point_count, 1)

            belief = beliefs.get_belief("pre_test_001")
            self.assertIsNotNone(belief)
            self.assertEqual(len(belief.get("position_8d", [])), 8)

            entries = memory.journal.latest_by_id()
            self.assertIn("pre_test_001", entries)
            self.assertEqual(entries["pre_test_001"]["type"], "belief")

    def test_bootstrap_identity_center_uses_belief_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            beliefs = BeliefStore(os.path.join(tmp, "beliefs"))
            memory = MemoryManager(os.path.join(tmp, "memory"))

            beliefs.add_belief(
                category="premises",
                belief_id="pre_core_001",
                content="I maintain a stable internal reference frame.",
                confidence=0.95,
                position_8d=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            beliefs.add_belief(
                category="premises",
                belief_id="pre_core_002",
                content="My core self is anchored in durable beliefs.",
                confidence=0.9,
                position_8d=[3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )

            physics = PhysicsEngine(data_dir=os.path.join(tmp, "spatial"))
            memory.set_physics(physics)
            beliefs.set_runtime(physics_engine=physics, memory_manager=memory)
            physics.bootstrap_from_stores(beliefs, memory)

            identity_center = physics.spatial_mind._identity_center
            self.assertAlmostEqual(float(identity_center[0]), 2.0, places=4)
            self.assertGreater(float(np.linalg.norm(identity_center)), 0.0)

    def test_curator_collects_thoughts_from_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(os.path.join(tmp, "memory"))
            memory.store(
                content="[thought] I should reconcile tax rules before filing.",
                memory_type="thought",
                source="pulse_output",
                belief_ids=["pre_tax_001"],
                pulse_id=7,
            )
            memory.store(
                content="An unrelated external event.",
                memory_type="event",
                source="pulse_input",
                pulse_id=8,
            )

            curator = Curator(
                physics_engine=None,
                belief_store=None,
                memory_manager=memory,
                llm_client=_NoopLLM(),
                data_dir=tmp,
            )

            raw = curator._collect_raw_memories()
            self.assertEqual(len(raw), 1)
            self.assertEqual(raw[0]["memory_id"], "1")
            self.assertEqual(raw[0]["belief_ids"], ["pre_tax_001"])
            self.assertIn("reconcile tax rules", raw[0]["text"])

    def test_semantic_memory_search_returns_journal_id_and_point_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(os.path.join(tmp, "memory"))
            memory.store(
                content="A tax planning memory with durable task context.",
                memory_type="thought",
                source="pulse_output",
                pulse_id=11,
            )

            class _Physics:
                def semantic_search(self, query, k=10, filter_fn=None, return_embeddings=False):
                    candidate = {
                        "id": "mem_1",
                        "similarity": 0.91,
                        "metadata": {
                            "type": "memory",
                            "journal_id": "1",
                            "content": "A tax planning memory with durable task context.",
                            "memory_type": "thought",
                            "source": "pulse_output",
                            "importance": 0.5,
                            "encoding_omega": 0.5,
                            "pulse_id": 11,
                        },
                    }
                    if filter_fn and not filter_fn(candidate["id"], candidate["metadata"]):
                        return []
                    return [candidate]

            memory.set_physics(_Physics())
            results = memory.search_semantic("tax planning", limit=1)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], "1")
            self.assertEqual(results[0]["point_id"], "mem_1")
            self.assertEqual(results[0]["pulse_id"], 11)

    def test_preconscious_returns_only_selected_belief_ids(self):
        pre = Preconscious.__new__(Preconscious)
        pre._belief_cache = [{"id": "seed"}]
        pre._ensure_belief_cache = lambda: None
        pre._concept_extractor = type(
            "Extractor",
            (),
            {"extract": lambda self, text, max_concepts=None: {"concepts": ["tax policy"], "budget": 2}},
        )()
        pre._prev_pulse_beliefs = []
        pre._gravity_query = lambda **kwargs: [
            {
                "id": "pre_selected",
                "content": "I understand tax policy through durable abstractions.",
                "category": "propositions",
                "gravity": 10.0,
                "mass": 3.0,
                "position_8d": [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            },
            {
                "id": "pre_rejected",
                "content": "A weaker candidate belief should stay out of awareness.",
                "category": "propositions",
                "gravity": 1.0,
                "mass": 1.0,
                "position_8d": [9.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            },
        ]
        pre._deduplicate_beliefs = lambda beliefs: beliefs
        pre._compute_focus_budget = lambda: (1, 0)
        pre._galaxy_map = type("GalaxyMap", (), {"is_built": False})()
        pre._last_selected_beliefs = []
        pre._last_cluster_centroid = None
        pre._last_concepts = []

        class _BeliefSpace:
            def __init__(self):
                self.updated = []

            def update_access(self, belief_id):
                self.updated.append(belief_id)

        belief_space = _BeliefSpace()
        pre.physics = type(
            "Physics",
            (),
            {"spatial_mind": type("SpatialMind", (), {"belief_space": belief_space})()},
        )()

        text, surfaced_ids = pre._pull_relevant_beliefs(previous_thought="tax policy")

        self.assertIn("I understand", text)
        self.assertEqual(surfaced_ids, ["pre_selected"])
        self.assertEqual(belief_space.updated, ["pre_selected"])
        self.assertTrue(np.allclose(pre._last_cluster_centroid, np.array([2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)))


if __name__ == "__main__":
    unittest.main()
