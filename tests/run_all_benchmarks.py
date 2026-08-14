#!/usr/bin/env python3
"""Helix Interactive & Automated Benchmark Suite Runner.

Provides a single unified interface for testers to run any or all of Helix's benchmark suites:
  1. Non-LLM 100-Question A/B Retrieval Ablation Benchmark
  2. Early Helix Memory Grounding & Tone Evaluation (Gemini 3.1 Flash-Lite)
  3. Agent Adaptation, Constraint Shift & Skill Acquisition Benchmark
  4. Multi-Pulse Live Agent Conversation & Skill Recall Simulation
  5. Autonomous Multi-Pulse Internal Monologue Stream & 8D Attractor Navigation
  6. Long-Form Agentic Memory, Proactive Initiative & Opinion Defense Benchmark
  7. Run ALL Benchmarks sequentially
"""

import os
import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PYTHON_EXEC = sys.executable if ("venv" in sys.executable or ".venv" in sys.executable) else str(REPO_ROOT / "venv" / "bin" / "python")

BENCHMARKS = [
    ("1", "Non-LLM 100-Question A/B Retrieval Ablation", "tests/test_mrag_ablation_bench.py"),
    ("2", "Early Helix Memory Grounding & Organic Tone", "tests/test_helix_early_memories.py"),
    ("3", "Agent Adaptation & Skill Acquisition", "tests/test_agent_adaptation_bench.py"),
    ("4", "Multi-Pulse Live Agent Simulation", "tests/test_live_agent_pulse_simulation.py"),
    ("5", "Autonomous Internal Monologue Stream", "tests/test_autonomous_pulse_chain.py"),
    ("6", "Long-Form Agentic Memory & Proactive Initiative", "tests/test_longform_agentic_memory_bench.py"),
]


def run_suite(index_choice: str):
    if index_choice.lower() in ("all", "7", "a"):
        print("\n" + "=" * 80)
        print("  RUNNING ALL HELIX BENCHMARK SUITES IN SEQUENCE")
        print("=" * 80)
        for num, title, script in BENCHMARKS:
            print(f"\n>>> Running Benchmark {num}: {title} ({script})...")
            subprocess.run([PYTHON_EXEC, script], check=False)
        print("\n" + "=" * 80)
        print("  ALL BENCHMARK SUITES COMPLETED")
        print("=" * 80)
        return

    selected = [b for b in BENCHMARKS if b[0] == index_choice]
    if selected:
        num, title, script = selected[0]
        print(f"\n>>> Running Benchmark {num}: {title} ({script})...")
        subprocess.run([PYTHON_EXEC, script], check=False)
    else:
        print(f"Invalid selection: '{index_choice}'")


def main():
    print("\n" + "=" * 80)
    print("  HELIX AGI BENCHMARK & TEST SUITE RUNNER")
    print("=" * 80)
    for num, title, script in BENCHMARKS:
        print(f"  [{num}] {title:<50} ({script})")
    print("  [7] Run ALL Benchmarks Sequentially")
    print("=" * 80)

    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        try:
            choice = input("Select a benchmark suite to run (1-7) [default: 7]: ").strip() or "7"
        except EOFError:
            choice = "7"

    run_suite(choice)


if __name__ == "__main__":
    main()
