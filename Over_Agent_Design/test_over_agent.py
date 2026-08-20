"""
Automated Test Suite for Subconscious Over-Agent System.
Tests stream continuity, surgical subagent dispatches, and log compaction.
"""

import sys
from subconscious_conductor import SubconsciousConductor
from llm_backend import LLMBackend

def run_tests():
    print("===============================================================")
    print("      Subconscious Over-Agent Automated Test Suite             ")
    print("===============================================================")
    
    backend = LLMBackend()
    if not backend.check_health():
        print("❌ FAILED: Ollama server is not running on http://localhost:11434.")
        sys.exit(1)
        
    print("✓ Ollama backend connection confirmed.")
    
    conductor = SubconsciousConductor(backend=backend, max_history_chars=500)
    
    # Test 1: Basic Conversational Turn
    print("\n--- Test 1: Basic Conversational Turn ---")
    resp1 = conductor.process_user_event("Hello! Introduce yourself briefly.", debug=True)
    print(f"Result 1: {resp1[:150]}...")
    assert len(resp1) > 0, "Response 1 should not be empty"
    print("✓ Test 1 Passed.")
    
    # Test 2: Research Action Dispatch
    print("\n--- Test 2: Research Action Turn ---")
    resp2 = conductor.process_user_event("What files exist in the Over_Agent_Design workspace directory?", debug=True)
    print(f"Result 2: {resp2[:150]}...")
    assert len(resp2) > 0, "Response 2 should not be empty"
    print("✓ Test 2 Passed.")

    # Test 3: Log Compaction Check
    print("\n--- Test 3: Stream Log Compaction Check ---")
    # Send a long turn to trigger compaction threshold (max_history_chars=500)
    long_prompt = "Can you summarize the architecture plan again? " + ("Provide detailed analysis. " * 15)
    resp3 = conductor.process_user_event(long_prompt, debug=True)
    print(f"Result 3: {resp3[:150]}...")
    print(f"Compacted Memories Count: {len(conductor.compacted_memories)}")
    assert len(conductor.compacted_memories) >= 1, "Should have triggered log compaction"
    print("✓ Test 3 Passed (Log Compactor Verified).")

    print("\n===============================================================")
    print("🎉 ALL TESTS COMPLETED SUCCESSFULLY!")
    print("===============================================================")

if __name__ == "__main__":
    run_tests()
