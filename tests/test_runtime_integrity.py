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

    def test_recent_memory_defaults_to_journal_order_not_wall_clock_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(os.path.join(tmp, "memory"))
            memory.journal.append(
                id="1",
                type="memory",
                content="A continuity memory should not vanish after idle time.",
                position_8d=[],
                pulse_id=4,
                metadata={"memory_type": "thought", "created_at": "2001-01-01T00:00:00"},
                timestamp="2001-01-01T00:00:00",
            )

            recent = memory.get_recent(limit=1)

            self.assertEqual(len(recent), 1)
            self.assertEqual(
                recent[0]["content"],
                "A continuity memory should not vanish after idle time.",
            )

    def test_recent_memory_pulse_window_uses_cognitive_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(os.path.join(tmp, "memory"))
            memory.store("pulse 2", pulse_id=2)
            memory.store("pulse 8", pulse_id=8)
            memory.store("pulse 9", pulse_id=9)
            memory.set_physics(type("Physics", (), {"_pulse_count": 9})())

            recent = memory.get_recent(limit=10, pulses_back=1)

            self.assertEqual([entry["content"] for entry in recent], ["pulse 9", "pulse 8"])

    def test_contextual_search_reranks_semantic_hits_and_refreshes_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(os.path.join(tmp, "memory"))

            class _MemorySpace:
                def __init__(self):
                    self.updated = []
                    self.points = {
                        "mem_1": {"position": [4.0, 0.0], "mass": 1.0, "temperature": 1.0},
                        "mem_2": {"position": [0.2, 0.0], "mass": 2.0, "temperature": 1.5},
                    }

                def get_point(self, point_id):
                    return self.points.get(point_id)

                def _compute_structural_mass(self, point):
                    return point["mass"]

                def _compute_temperature(self, point):
                    return point["temperature"]

                def update_access(self, point_id):
                    self.updated.append(point_id)

            memory_space = _MemorySpace()
            memory.set_physics(type(
                "Physics",
                (),
                {
                    "derive_query_center": lambda self, focus_text=None, attention_relative=False: [0.0, 0.0],
                    "spatial_mind": type("SpatialMind", (), {"memory_space": memory_space})(),
                },
            )())

            memory.search_semantic = lambda *args, **kwargs: [
                {"id": "1", "point_id": "mem_1", "content": "far semantic hit", "similarity": 0.99},
                {"id": "2", "point_id": "mem_2", "content": "near gravity hit", "similarity": 0.95},
            ]

            results = memory.search_contextual("repeat notification", limit=2)

            self.assertEqual([entry["id"] for entry in results], ["2", "1"])
            self.assertEqual(memory_space.updated, ["mem_2", "mem_1"])

    def test_store_reinforces_prior_input_echo_without_merging_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(os.path.join(tmp, "memory"))

            class _MemorySpace:
                def __init__(self):
                    self.updated = []
                    self.points = {
                        "mem_7": {"position": [10.0, 0.0]},
                    }

                def get_point(self, point_id):
                    return self.points.get(point_id)

                def update_access(self, point_id):
                    self.updated.append(point_id)

            memory_space = _MemorySpace()
            captured = {}

            class _Physics:
                _pulse_count = 12

                def __init__(self):
                    self.spatial_mind = type("SpatialMind", (), {"memory_space": memory_space})()

                def semantic_search(self, query_text, k=10, filter_fn=None, return_embeddings=False):
                    candidate = {
                        "id": "mem_7",
                        "similarity": 0.97,
                        "metadata": {
                            "type": "memory",
                            "source": "pulse_input",
                            "memory_type": "tool_intake",
                            "journal_id": "7",
                        },
                    }
                    if filter_fn and not filter_fn(candidate["id"], candidate["metadata"]):
                        return []
                    return [candidate]

                def register_memory_entry(self, **kwargs):
                    captured["position_8d"] = kwargs.get("position_8d")
                    return "mem_8", kwargs.get("position_8d") or [], kwargs.get("embedding_384d") or []

            memory.set_physics(_Physics())
            stored_id = memory.store(
                content="The same notification arrives again.",
                memory_type="tool_intake",
                source="pulse_input",
                importance=0.84,
                tags=["pulse_event", "tool_result"],
                position_8d=[0.0, 0.0],
                pulse_id=12,
            )

            self.assertEqual(stored_id, 1)
            self.assertEqual(memory_space.updated, ["mem_7"])
            self.assertEqual(captured["position_8d"], [7.0, 0.0])

            entry = memory.journal.latest_by_id()["1"]
            self.assertEqual(entry["metadata"]["echo_of"], "7")
            self.assertIn("repeat_echo", entry["metadata"]["tags"])

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

    def test_preconscious_recent_memory_requests_pulse_window(self):
        captured = {}

        class _Memory:
            def get_recent(self, **kwargs):
                captured.update(kwargs)
                return []

        pre = Preconscious.__new__(Preconscious)
        pre.memory = _Memory()
        pre.CHAIN_WINDOW = 3

        result = pre._pull_recent_memory()

        self.assertEqual(result, "")
        self.assertEqual(captured, {"limit": 3, "pulses_back": 3})

    def test_preconscious_trigger_keeps_informative_tool_results_but_suppresses_acks(self):
        pre = Preconscious.__new__(Preconscious)

        trigger_text, using_fallback = pre._build_trigger_text(
            previous_thought="Continue tracing the issue.",
            incoming_events=[
                "[10:00:00] Tool [moltbook_notifications] returned: Alert one\\nAlert two",
                "[10:00:01] Tool [moltbook_notifications_read] returned: Notification 42 marked as read.",
            ],
        )

        self.assertFalse(using_fallback)
        self.assertIn("moltbook_notifications:", trigger_text)
        self.assertIn("Alert one", trigger_text)
        self.assertNotIn("marked as read", trigger_text)


if __name__ == "__main__":
    unittest.main()
