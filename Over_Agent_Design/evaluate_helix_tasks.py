"""
Helix Task Evaluation & Error-Learning Test Suite.
Evaluates Helix's subconscious thought process, sub-orchestrator performance,
and self-correction when encountering execution errors.
"""

import sys
from subconscious_conductor import SubconsciousConductor
from llm_backend import LLMBackend

def run_evaluation():
    print("===============================================================")
    print("      Helix Task Performance & Error-Learning Evaluation       ")
    print("===============================================================")
    
    backend = LLMBackend()
    if not backend.check_health():
        print("❌ Ollama server offline.")
        sys.exit(1)
        
    conductor = SubconsciousConductor(backend=backend)

    # -------------------------------------------------------------
    # Task 1: Workspace Research & Overview
    # -------------------------------------------------------------
    print("\n" + "="*70)
    print("  TASK 1: Workspace Research & Overview")
    print("="*70)
    t1_prompt = "Inspect the Over_Agent_Design workspace and summarize what files exist."
    print(f"User Input: '{t1_prompt}'\n")
    resp1 = conductor.process_user_event(t1_prompt, debug=True)
    print(f"\n[Helix Final Spoken Answer 1]:\n{resp1}\n")

    # -------------------------------------------------------------
    # Task 2: OS Execution & System Status
    # -------------------------------------------------------------
    print("\n" + "="*70)
    print("  TASK 2: OS Execution & System Status")
    print("="*70)
    t2_prompt = "Run a shell command to report current system date and disk usage."
    print(f"User Input: '{t2_prompt}'\n")
    resp2 = conductor.process_user_event(t2_prompt, debug=True)
    print(f"\n[Helix Final Spoken Answer 2]:\n{resp2}\n")

    # -------------------------------------------------------------
    # Task 3: Error Recovery & Self-Correction Test
    # -------------------------------------------------------------
    print("\n" + "="*70)
    print("  TASK 3: Error Recovery & Self-Correction (Failed File Inspection)")
    print("="*70)
    t3_prompt = "Check the contents of non_existent_folder_xyz/missing_data.txt. If it fails, report why and adapt."
    print(f"User Input: '{t3_prompt}'\n")
    resp3 = conductor.process_user_event(t3_prompt, debug=True)
    print(f"\n[Helix Final Spoken Answer 3]:\n{resp3}\n")

    print("===============================================================")
    print("🎉 TASK EVALUATION COMPLETE")
    print("===============================================================")

if __name__ == "__main__":
    run_evaluation()
