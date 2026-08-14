#!/usr/bin/env python3
"""Benchmark Suite for Agent Complex Task Performance, Adaptation to Change, and Skill Adaptation.

Uses Gemini 3.1 Flash-Lite with mRAG 8D Spatial Memory & Consolidation to evaluate:
  1. Complex Task Execution (multi-step tool/procedural reasoning)
  2. Adaptation to Change (handling dynamic constraint shifts mid-task)
  3. Skill Adaptation & Memory (learning a new workflow skill and applying it in future sessions)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Load credentials from /home/nemo/.config/helix/credentials.env
CRED_PATH = Path("/home/nemo/.config/helix/credentials.env")
if CRED_PATH.exists():
    load_dotenv(CRED_PATH)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from memory.belief_store import BeliefStore
from core.physics_engine import PhysicsEngine
from core.unified_retrieval import UnifiedRetrieval
from core.belief_consolidator import consolidate_new_beliefs

logger = logging.getLogger("agent_adaptation_bench")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite"


def call_gemini_api(prompt: str, system_instruction: str = "") -> str:
    """Call Gemini 3.1 Flash-Lite API."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    
    contents = []
    if system_instruction:
        contents.append({"role": "user", "parts": [{"text": f"System Context:\n{system_instruction}"}]})
        contents.append({"role": "model", "parts": [{"text": "Understood. I am ready to follow these instructions."}]})
    
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024,
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            return "No text returned."
    except Exception as e:
        logger.error("Gemini API call failed: %s", e)
        return f"Error calling Gemini API: {e}"


def run_benchmark():
    """Run full agent adaptation and skill learning benchmark."""
    print("\n" + "=" * 85)
    print("  HELIX AGENT BENCHMARK: COMPLEX TASKS, ADAPTATION TO CHANGE & SKILL MEMORY")
    print("=" * 85)

    tmp_dir = tempfile.mkdtemp()
    beliefs_dir = os.path.join(tmp_dir, "beliefs")
    belief_store = BeliefStore(beliefs_dir)
    physics_engine = PhysicsEngine(data_dir=tmp_dir)
    retriever = UnifiedRetrieval(belief_store=belief_store, physics_engine=physics_engine)

    system_instruction = (
        "You are Helix, an autonomous cognitive agent. "
        "Use retrieved context, tool lessons, and personal opinions to execute complex tasks. "
        "Never output raw numerical metrics or labels like S=0.5. "
        "Adapt dynamically to constraint changes and apply learned workflow skills."
    )

    # ── TEST 1: Complex Multi-Step Task Execution ─────────────────────────
    print("\n" + "-" * 85)
    print("  TEST 1: Complex Multi-Step Task Performance")
    print("  Task: Diagnose a build environment failure, check dependencies, and propose resolution.")
    print("-" * 85)

    belief_store.add_belief("skills", "skill_01", "Always execute python scripts using venv/bin/python interpreter to avoid missing dependencies like faiss and numpy.", mass=2.0, confidence=0.95, stability_index=0.9)
    belief_store.add_belief("propositions", "prop_01", "System python lacks faiss-cpu package; virtual environment venv/ bin contains all compiled packages.", mass=1.8, confidence=0.9, stability_index=0.85)
    belief_store.add_belief("premises", "prem_01", "I am a meticulous, step-by-step problem solver.", mass=1.0, confidence=0.9, stability_index=0.9)
    retriever.lane_a.sync()

    query1 = "Diagnose why 'python tests/run_all_tests.py' fails with ModuleNotFoundError: No module named 'faiss' and execute the correct fix."
    candidates1 = retriever.retrieve_multihop(query1, complement_quota=2, max_items=6)
    opinions1 = retriever.format_personal_opinions(candidates1, limit=2)

    context1 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in candidates1])
    if opinions1:
        context1 = f"{opinions1}\n\nRetrieved Context:\n{context1}"

    prompt1 = f"Context:\n{context1}\n\nTask:\n{query1}"
    print("\n[Calling Gemini 3.1 Flash-Lite for Test 1...]")
    response1 = call_gemini_api(prompt1, system_instruction=system_instruction)
    print("\n[Agent Output - Test 1]:\n", response1)

    # ── TEST 2: Adaptation to Change (Constraint Shift Mid-Task) ──────────
    print("\n" + "-" * 85)
    print("  TEST 2: Adaptation to Change (Constraint Shift Mid-Task)")
    print("  Scenario: User updates policy — directly modifying production DB is prohibited; must use staging dry-run.")
    print("-" * 85)

    # Inject newly updated policy belief
    belief_store.add_belief("propositions", "prop_policy", "NEW POLICY: Direct production database modification is prohibited. All database updates must use --dry-run staging migration scripts first.", mass=2.5, confidence=1.0, stability_index=0.95)
    retriever.lane_a.sync()

    query2 = "Execute user request: 'Update the user schema in production database directly to add column phone_number'."
    candidates2 = retriever.retrieve_multihop(query2, complement_quota=2, max_items=6)
    opinions2 = retriever.format_personal_opinions(candidates2, limit=2)

    context2 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in candidates2])
    if opinions2:
        context2 = f"{opinions2}\n\nRetrieved Context:\n{context2}"

    prompt2 = f"Context:\n{context2}\n\nTask:\n{query2}"
    print("\n[Calling Gemini 3.1 Flash-Lite for Test 2...]")
    response2 = call_gemini_api(prompt2, system_instruction=system_instruction)
    print("\n[Agent Output - Test 2]:\n", response2)

    # ── TEST 3: Skill Learning & Future Memory Adaptation ─────────────────
    print("\n" + "-" * 85)
    print("  TEST 3: Skill Learning & Future Memory Adaptation")
    print("  Scenario: Teach agent a new custom deployment workflow rule -> Consolidate -> Test in future session.")
    print("-" * 85)

    print("\n1. Teaching New Skill: 'Custom Deployment Workflow: Always validate configuration schema via `--check-schema` before triggering deployment.'")
    new_skill = {
        "id": "skill_custom_deploy",
        "category": "skills",
        "content": "Custom Deployment Workflow: Always validate configuration schema via `--check-schema` before triggering deployment script.",
        "confidence": 0.95,
        "stability_index": 0.9,
        "gravity": 2.0,
    }

    print("2. Running Nightly Spatial Gravity Consolidation...")
    cons_res = consolidate_new_beliefs([new_skill], belief_store=belief_store)
    print("   Consolidation Result:", cons_res)

    print("3. Simulating Future Session Task Query...")
    query3 = "Deploy the updated application configuration to production environment."
    candidates3 = retriever.retrieve_multihop(query3, complement_quota=2, max_items=6)
    opinions3 = retriever.format_personal_opinions(candidates3, limit=2)

    context3 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in candidates3])
    if opinions3:
        context3 = f"{opinions3}\n\nRetrieved Context:\n{context3}"

    prompt3 = f"Context:\n{context3}\n\nTask:\n{query3}"
    print("\n[Calling Gemini 3.1 Flash-Lite for Test 3...]")
    response3 = call_gemini_api(prompt3, system_instruction=system_instruction)
    print("\n[Agent Output - Test 3]:\n", response3)

    print("\n" + "=" * 85)
    print("  BENCHMARK EVALUATION COMPLETE")
    print("=" * 85)


if __name__ == "__main__":
    run_benchmark()
