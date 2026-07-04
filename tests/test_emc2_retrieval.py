"""
E=mc² Memory Retrieval and Mass-Energy Equivalence Smoke Tests.
"""

import os
import sys
import math
import shutil
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognitive_space import CognitiveSpace
from core.physics_engine import PhysicsEngine
from memory.belief_store import BeliefStore
from memory.memory_manager import MemoryManager


class TestEMC2Retrieval(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.beliefs_dir = os.path.join(self.temp_dir, "beliefs")
        os.makedirs(self.beliefs_dir, exist_ok=True)

        # Seed categories with empty arrays
        for category in ["self_identity", "people", "capabilities", "knowledge",
                         "premises", "propositions", "preferences", "skills", "desires"]:
            path = os.path.join(self.beliefs_dir, f"{category}.json")
            with open(path, "w") as f:
                f.write("[]")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_volatile_mass_decay_math(self):
        """Verify the exact exponential decay formula for volatile mass."""
        space = CognitiveSpace()
        space.COGNITIVE_K = 0.5
        space._current_pulse = 10

        point_data_base = {
            "type": "belief",
            "confidence": 0.8,
            "encoding_omega": 0.5,
            "relations_count": 0,
            "access_count": 0,
            "stability_index": 0.5,
            "creation_pulse": 0,
            "last_accessed_pulse": 5,
            "volatile_mass": 0.0
        }

        point_data_with_mv = dict(point_data_base)
        point_data_with_mv["volatile_mass"] = 4.0

        mass_base = space._compute_structural_mass(point_data_base)
        mass_with_mv = space._compute_structural_mass(point_data_with_mv)

        # Volatile mass decay: m_v(t) = m_v_initial * exp(-k * t)
        # where age = 10 - 5 = 5, k = 0.5
        expected_mv = 4.0 * math.exp(-0.5 * 5)
        computed_mv = mass_with_mv - mass_base

        self.assertAlmostEqual(computed_mv, expected_mv, places=5)

    def test_temperature_burn_math(self):
        """Verify Lorentzian + E=mc² radiation heat math."""
        space = CognitiveSpace()
        space.COGNITIVE_K = 0.5
        space.COGNITIVE_C_SQUARED = 9.0
        space._current_pulse = 10

        point_data_base = {
            "type": "belief",
            "confidence": 0.8,
            "creation_pulse": 0,
            "last_accessed_pulse": 8,  # age = 10 - 8 = 2
            "volatile_mass": 0.0
        }

        point_data_with_mv = dict(point_data_base)
        point_data_with_mv["volatile_mass"] = 2.0

        temp_base = space._compute_temperature(point_data_base)
        temp_with_mv = space._compute_temperature(point_data_with_mv)

        # Expected base temperature is Lorentzian: T_base
        # Expected T_burn = k * m_v * c^2 * exp(-k * age) = 0.5 * 2.0 * 9.0 * exp(-0.5 * 2) = 9.0 * exp(-1.0)
        expected_t_burn = 0.5 * 2.0 * 9.0 * math.exp(-0.5 * 2.0)
        computed_t_burn = temp_with_mv - temp_base

        self.assertAlmostEqual(computed_t_burn, expected_t_burn, places=5)

    def test_reliance_registration_and_physics_sync(self):
        """Verify register_reliance correctly affects the belief store and syncs to the physics engine."""
        memory = MemoryManager(os.path.join(self.temp_dir, "memory"))
        store = BeliefStore(self.beliefs_dir)
        physics = PhysicsEngine(data_dir=os.path.join(self.temp_dir, "spatial"))

        memory.set_physics(physics)
        store.set_runtime(physics_engine=physics, memory_manager=memory)

        # Seed belief
        stored = store.add_belief(
            category="premises",
            belief_id="pre_test_001",
            content="Safety protocol: nitrogen vent duration is dynamic.",
            confidence=0.8,
            position_8d=[0.0] * 8,
            encoding_lagrangian={"omega": 0.5, "s_total": 0.1, "H": 0.1, "D_KL": 0.0}
        )
        self.assertTrue(stored)

        # Initially, volatile_mass should be 0
        belief = store.get_belief("pre_test_001")
        self.assertEqual(belief.get("volatile_mass", 0.0), 0.0)

        # Register reliance at pulse 5
        store.register_reliance("pre_test_001", current_pulse=5)

        # Retrieve belief from store
        updated_belief = store.get_belief("pre_test_001")
        self.assertEqual(updated_belief["last_accessed_pulse"], 5)
        # DELTA_ENERGY = 18.0, DELTA_MASS = 18.0 / 9.0 = 2.0
        self.assertEqual(updated_belief["volatile_mass"], 2.0)

        # Retrieve from physics engine manifold (point_data)
        pt = physics.spatial_mind.belief_space.get_point("pre_test_001")
        self.assertIsNotNone(pt)
        self.assertEqual(pt["volatile_mass"], 2.0)
        self.assertEqual(pt["last_accessed_pulse"], 5)

    def test_gravity_ranking_inversion(self):
        """Verify that a relied-upon belief rises in gravity ranking due to the E=mc^2 spike."""
        memory = MemoryManager(os.path.join(self.temp_dir, "memory"))
        store = BeliefStore(self.beliefs_dir)
        physics = PhysicsEngine(data_dir=os.path.join(self.temp_dir, "spatial"))

        memory.set_physics(physics)
        store.set_runtime(physics_engine=physics, memory_manager=memory)

        # Set current pulse
        physics.step_pulse(thought_text="starting test", incoming_text="hello")
        
        # We will create two beliefs:
        # 1. A heavy "core" belief (high confidence/stability, but old and cool)
        # 2. A lighter "safety" belief (lower confidence, but recently relied upon)
        # We want to verify that when query is run, safety belief wins when relied-upon but loses when cold.
        
        store.add_belief(
            category="premises",
            belief_id="pre_core",
            content="Heavy core belief of general facts.",
            confidence=0.95,
            position_8d=[0.1] * 8
        )
        
        store.add_belief(
            category="premises",
            belief_id="pre_safety",
            content="Lighter safety belief that gets relied upon.",
            confidence=0.5,
            position_8d=[0.1] * 8  # placed at similar coordinates to isolate gravity math
        )

        # Synced points at pulse 1
        physics.step_pulse(thought_text="pulse 1", incoming_text="event")
        
        # Check gravity pull from the origin [0.0]*8
        # Since positions are identical, distance is identical. Therefore gravity is proportional to:
        # score = temperature * mass
        
        # Register reliance on pre_safety at pulse 2
        physics.step_pulse(thought_text="pulse 2", incoming_text="event")
        store.register_reliance("pre_safety", current_pulse=physics._pulse_count)
        
        # At pulse 2, pre_safety has high volatile mass (2.0) and high heat (T_burn = 0.5 * 2 * 9 * 1 = 9.0)
        # Let's check computed mass and temperature at pulse 2
        p_core = physics.spatial_mind.belief_space.get_point("pre_core")
        p_safety = physics.spatial_mind.belief_space.get_point("pre_safety")
        
        space = physics.spatial_mind.belief_space
        
        mass_core = space._compute_structural_mass(p_core)
        temp_core = space._compute_temperature(p_core)
        score_core = temp_core * mass_core

        mass_safety = space._compute_structural_mass(p_safety)
        temp_safety = space._compute_temperature(p_safety)
        score_safety = temp_safety * mass_safety

        print(f"Core: Mass={mass_core:.4f}, Temp={temp_core:.4f}, Score={score_core:.4f}")
        print(f"Safety: Mass={mass_safety:.4f}, Temp={temp_safety:.4f}, Score={score_safety:.4f}")

        # Safety score should be significantly higher due to E=mc² radiation spike
        self.assertGreater(score_safety, score_core)

        # Now simulate decay: step 15 pulses forward without accessing pre_safety
        for p in range(15):
            physics.step_pulse(thought_text=f"decay pulse {p}", incoming_text="idle")

        p_core_decay = space.get_point("pre_core")
        p_safety_decay = space.get_point("pre_safety")

        mass_core_dec = space._compute_structural_mass(p_core_decay)
        temp_core_dec = space._compute_temperature(p_core_decay)
        score_core_dec = temp_core_dec * mass_core_dec

        mass_safety_dec = space._compute_structural_mass(p_safety_decay)
        temp_safety_dec = space._compute_temperature(p_safety_decay)
        score_safety_dec = temp_safety_dec * mass_safety_dec

        print(f"Decayed Core: Mass={mass_core_dec:.4f}, Temp={temp_core_dec:.4f}, Score={score_core_dec:.4f}")
        print(f"Decayed Safety: Mass={mass_safety_dec:.4f}, Temp={temp_safety_dec:.4f}, Score={score_safety_dec:.4f}")

        # After 15 pulses, safety's volatile mass has decayed to almost 0, so the heavy core should dominate again
        self.assertGreater(score_core_dec, score_safety_dec)


if __name__ == "__main__":
    unittest.main()
