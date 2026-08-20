"""
Full System Integration Test Suite for Subconscious Over-Agent System.
Tests:
1. LLM Backend health & model availability.
2. Dynamic Identity Compiler & Synthetic Affect Pipeline.
3. mRAG Adapter memory retrieval over /home/nemo/Helix/data.
4. Sub-Orchestrator routing (Speaker, Researcher, Executor).
5. Thread-safe Subconscious Conductor execution.
6. DORMANT state nightly consolidation pass.
"""

import unittest
import os
import sys

# Ensure parent directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from llm_backend import LLMBackend
from affect_simulation import SyntheticAffectPipeline
from dynamic_identity_compiler import DynamicIdentityCompiler
from mrag_adapter import HelixMRAGAdapter
from subagents import SpeakerFocus, ResearcherSubOrchestrator, ExecutorSubOrchestrator
from subconscious_conductor import SubconsciousConductor


class TestOverAgentSystem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.backend = LLMBackend()
        cls.backend_online = cls.backend.check_health()

    def test_01_backend_health(self):
        """Test local Ollama backend connectivity."""
        self.assertTrue(self.backend_online, "Ollama local backend should be ONLINE at http://localhost:11434")

    def test_02_affect_simulation_pipeline(self):
        """Test synthetic affect state vector updates and prompt injections."""
        pipeline = SyntheticAffectPipeline()
        initial_label = pipeline.label
        pipeline.update_affect(user_sentiment="positive", task_complexity="complex_research")
        
        self.assertIsNotNone(pipeline.label)
        injection = pipeline.get_affect_injection()
        self.assertIn("Synthetic Affect Vector", injection)
        self.assertIn("Valence", injection)
        self.assertIn("Arousal", injection)

    def test_03_dynamic_identity_compiler(self):
        """Test compiling dynamic identity with self-opinion statement."""
        compiler = DynamicIdentityCompiler()
        dynamic_identity = compiler.compile_dynamic_identity()
        self.assertIn("Helix", dynamic_identity)
        self.assertIn("DYNAMIC SELF-OPINION STATEMENT", dynamic_identity)
        self.assertIn("CURRENT AFFECT SIMULATION STATE", dynamic_identity)

    def test_04_mrag_adapter_memory_retrieval(self):
        """Test mRAG preconscious retrieval over /home/nemo/Helix/data belief stores."""
        adapter = HelixMRAGAdapter()
        self.assertGreater(len(adapter.beliefs_data), 0, "mRAG adapter should load belief files from /home/nemo/Helix/data")
        
        query = "joshua"
        retrieved = adapter.retrieve_mrag_context(query)
        self.assertIn("mRAG", retrieved)

    def test_05_sub_orchestrators(self):
        """Test SpeakerFocus, ResearcherSubOrchestrator, and ExecutorSubOrchestrator."""
        if not self.backend_online:
            self.skipTest("Backend offline")

        speaker = SpeakerFocus(self.backend)
        speaker_res = speaker.run(task_instruction="Say hello to Nemo", user_context="Testing speaker sub-pass")
        self.assertIsNotNone(speaker_res)
        self.assertGreater(len(speaker_res), 0)

        researcher = ResearcherSubOrchestrator(self.backend)
        res_res = researcher.run(query="workspace files")
        self.assertIsNotNone(res_res)

        executor = ExecutorSubOrchestrator(self.backend)
        exec_res = executor.run(task_description="echo 'Testing Executor'")
        self.assertIn("Testing Executor", exec_res)

    def test_06_subconscious_conductor_and_dormant_pass(self):
        """Test thread-safe conductor execution and DORMANT consolidation pass."""
        if not self.backend_online:
            self.skipTest("Backend offline")

        conductor = SubconsciousConductor(backend=self.backend)
        self.assertEqual(conductor.state, "RESTING")
        
        user_reply = conductor.process_user_event("Hello Helix, test turn.", debug=False)
        self.assertIsNotNone(user_reply)
        
        dormant_result = conductor.run_dormant_consolidation_pass(debug=False)
        self.assertIn("DORMANT Consolidation Pass complete", dormant_result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
