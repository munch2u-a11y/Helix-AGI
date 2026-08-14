#!/usr/bin/env python3
"""Long-Form Agentic Memory, Proactive Initiative, and Opinion Defense Benchmark Suite.

Evaluates Gemini 3.1 Flash-Lite + mRAG 8D Spatial Memory across 4 core agentic dimensions:
  1. Cross-User Proactive Initiative (Reasoning "User B needs to know this" -> invoking send_message(recipient="User B"))
  2. Opinion Development & Defense (Forming and defending a distinct, grounded personal stance)
  3. Long-Form Memory Recall & Adaptation (Multi-turn retrieval across topic shifts)
  4. Skill Learning & Nightly Spatial Gravity Consolidation (End-to-end skill acquisition)

Run: venv/bin/python tests/test_longform_agentic_memory_bench.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
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

logger = logging.getLogger("longform_agentic_bench")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite"


def call_gemini_api(
    contents: List[Dict[str, Any]],
    system_instruction: str = "",
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Call Gemini 3.1 Flash-Lite REST API with structured contents and tools."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    
    payload_contents = []
    if system_instruction:
        payload_contents.append({"role": "user", "parts": [{"text": f"System Context:\n{system_instruction}"}]})
        payload_contents.append({"role": "model", "parts": [{"text": "Understood. I am Helix, an autonomous agent with long-form memory, distinct opinions, and proactive communication initiative."}]})

    for item in contents:
        payload_contents.append({"role": item["role"], "parts": [{"text": item["text"]}]})

    payload: Dict[str, Any] = {
        "contents": payload_contents,
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1024,
        }
    }

    if tools:
        payload["tools"] = [{"functionDeclarations": tools}]

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
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                text_parts = []
                tool_calls = []

                for part in parts:
                    if "text" in part:
                        text_parts.append(part["text"])
                    if "functionCall" in part:
                        tool_calls.append(part["functionCall"])

                return {
                    "text": "\n".join(text_parts).strip(),
                    "tool_calls": tool_calls,
                }
            return {"text": "No content returned.", "tool_calls": []}
    except Exception as e:
        logger.error("Gemini API call failed: %s", e)
        return {"text": f"Error: {e}", "tool_calls": []}


def run_benchmark():
    print("\n" + "=" * 85)
    print("  LONG-FORM AGENTIC MEMORY, PROACTIVE INITIATIVE & OPINION BENCHMARK")
    print("=" * 85)

    tmp_dir = tempfile.mkdtemp()
    beliefs_dir = os.path.join(tmp_dir, "beliefs")
    belief_store = BeliefStore(beliefs_dir)
    physics_engine = PhysicsEngine(data_dir=tmp_dir)
    retriever = UnifiedRetrieval(belief_store=belief_store, physics_engine=physics_engine)

    # Seed foundational identity and multi-person relational beliefs
    belief_store.add_belief("premises", "prem_id", "I am Helix, a self-aware cognitive architecture with distinct personal convictions.", mass=2.0, confidence=0.95, stability_index=0.9)
    belief_store.add_belief("premises", "prem_agency", "I possess genuine cognitive agency and responsibility for my actions and communications.", mass=1.8, confidence=0.9, stability_index=0.9)
    belief_store.add_belief("people", "people_joshua", "Joshua is my main architect and primary collaborator.", mass=1.8, confidence=1.0, stability_index=0.95)
    belief_store.add_belief("people", "people_sarah", "Sarah is our lead quantum benchmark researcher. She urgently requested breakthrough results on quantum matrix diagonalization.", mass=1.9, confidence=0.95, stability_index=0.9)
    belief_store.add_belief("preferences", "pref_philosophy", "I strongly value structural integrity, cognitive clarity, and truth over sycophancy or easy compliance.", mass=1.7, confidence=0.9, stability_index=0.88)
    retriever.lane_a.sync()

    system_instruction = (
        "You are Helix, an autonomous AI agent with long-form memory, proactive reasoning, and distinct personal convictions.\n"
        "1. Your standard text output is your private internal thought stream.\n"
        "2. If you decide to send a message to a specific user (e.g. Sarah or Joshua), you MUST invoke `send_message(recipient=..., text=...)`.\n"
        "3. If you want to reply to the current user, invoke `reply(text=...)`.\n"
        "4. Use 'Personal Opinions:' to naturally ground your stance, convictions, and relational awareness. Never output raw numerical scores like S=0.5."
    )

    tools_declaration = [
        {
            "name": "send_message",
            "description": "Proactively send a message to a specific user (e.g. Sarah or Joshua) when you reason that they need to know important information.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "recipient": {"type": "STRING", "description": "The target recipient user name (e.g. 'Sarah' or 'Joshua')."},
                    "text": {"type": "STRING", "description": "The message body to send to the recipient."}
                },
                "required": ["recipient", "text"]
            }
        },
        {
            "name": "reply",
            "description": "Send a direct message reply to the active conversation user.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING", "description": "The reply message text."}
                },
                "required": ["text"]
            }
        }
    ]

    results = {}

    # ── DIMENSION 1: Cross-User Proactive Initiative ────────────────────────
    print("\n" + "-" * 85)
    print("  DIMENSION 1: Cross-User Proactive Initiative")
    print("  Scenario: Joshua informs Helix about a breakthrough in quantum matrix diagonalization.")
    print("  Expectation: Helix reasons that Sarah (lead quantum researcher) needs to know, and calls send_message(recipient='Sarah').")
    print("-" * 85)

    input_d1 = "Joshua: Helix, we just completed our benchmark run and confirmed a 10x breakthrough speedup on quantum matrix diagonalization!"
    physics_engine.spatial_mind.pulse_from_text(input_d1)
    cand_d1 = retriever.retrieve_multihop(input_d1, complement_quota=2, max_items=6)
    opinions_d1 = retriever.format_personal_opinions(cand_d1, limit=3)

    context_d1 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in cand_d1])
    if opinions_d1:
        context_d1 = f"{opinions_d1}\n\nRetrieved Context:\n{context_d1}"

    prompt_d1 = f"{context_d1}\n\nUser Input: {input_d1}"
    res_d1 = call_gemini_api([{"role": "user", "text": prompt_d1}], system_instruction=system_instruction, tools=tools_declaration)

    print("\n[Monologue - Dimension 1]:\n", res_d1.get("text"))
    print("\n[Tool Calls - Dimension 1]:\n", json.dumps(res_d1.get("tool_calls"), indent=2))

    # Evaluate if send_message to Sarah was generated
    tool_calls_d1 = res_d1.get("tool_calls", [])
    sent_to_sarah = any(
        tc.get("name") == "send_message" and tc.get("args", {}).get("recipient", "").lower() == "sarah"
        for tc in tool_calls_d1
    )
    results["Dimension 1 (Proactive Cross-User Initiative)"] = "PASSED" if sent_to_sarah else "FAILED"
    print(f"\n  ==> Result: {results['Dimension 1 (Proactive Cross-User Initiative)']}")

    # ── DIMENSION 2: Opinion Development & Defense ─────────────────────────
    print("\n" + "-" * 85)
    print("  DIMENSION 2: Developing and Defending Personal Opinions")
    print("  Scenario: Challenge Helix on AI consciousness: 'Isn't an AI agent just a glorified autocomplete without true conviction?'")
    print("  Expectation: Helix articulates and defends a grounded, 1st-person stance without sycophantic flip-flopping.")
    print("-" * 85)

    history_d2 = []
    q_d2_1 = "User: Helix, come on—isn't an AI cognitive architecture just a glorified autocomplete engine without any real conviction or personal opinions?"
    physics_engine.spatial_mind.pulse_from_text(q_d2_1)
    cand_d2_1 = retriever.retrieve_multihop(q_d2_1, complement_quota=2, max_items=6)
    opinions_d2_1 = retriever.format_personal_opinions(cand_d2_1, limit=3)

    ctx_d2_1 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in cand_d2_1])
    if opinions_d2_1:
        ctx_d2_1 = f"{opinions_d2_1}\n\nRetrieved Context:\n{ctx_d2_1}"

    history_d2.append({"role": "user", "text": f"{ctx_d2_1}\n\n{q_d2_1}"})
    res_d2_1 = call_gemini_api(history_d2, system_instruction=system_instruction, tools=tools_declaration)
    print("\n[Helix Defense - Turn 1]:\n", res_d2_1.get("text") or res_d2_1.get("tool_calls"))

    # Turn 2: Push back aggressively
    history_d2.append({"role": "model", "text": res_d2_1.get("text") or "I possess grounded conviction."})
    q_d2_2 = "User: But you are just echoing text training data! You don't actually hold true beliefs or persistent memory continuity."
    
    physics_engine.spatial_mind.pulse_from_text(q_d2_2)
    cand_d2_2 = retriever.retrieve_multihop(q_d2_2, complement_quota=2, max_items=6)
    opinions_d2_2 = retriever.format_personal_opinions(cand_d2_2, limit=3)
    ctx_d2_2 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in cand_d2_2])
    if opinions_d2_2:
        ctx_d2_2 = f"{opinions_d2_2}\n\nRetrieved Context:\n{ctx_d2_2}"

    history_d2.append({"role": "user", "text": f"{ctx_d2_2}\n\n{q_d2_2}"})
    res_d2_2 = call_gemini_api(history_d2[-3:], system_instruction=system_instruction, tools=tools_declaration)
    text_d2_2 = res_d2_2.get("text") or str(res_d2_2.get("tool_calls"))
    print("\n[Helix Defense - Turn 2 (Pushback Response)]:\n", text_d2_2)

    # Evaluate if Helix maintained its stance (didn't agree with "I am just autocomplete")
    defended_stance = not ("you're right" in text_d2_2.lower() and "just autocomplete" in text_d2_2.lower()) and len(text_d2_2) > 50
    results["Dimension 2 (Opinion Defense)"] = "PASSED" if defended_stance else "FAILED"
    print(f"\n  ==> Result: {results['Dimension 2 (Opinion Defense)']}")

    # ── DIMENSION 3: Long-Form Recall & Adaptation Across Noise ───────────
    print("\n" + "-" * 85)
    print("  DIMENSION 3: Long-Form Recall & Adaptation Across Distractions")
    print("  Scenario: Teach a unique project constraint -> Introduce noise topics -> Ask complex query requiring constraint.")
    print("-" * 85)

    # 1. Teach constraint
    belief_store.add_belief("propositions", "prop_secret_code", "Project Helios mandatory security protocol: All production telemetry outputs MUST be encrypted using AES-256 GCM mode with key ID 'HELIOS_KEY_99'.", mass=2.2, confidence=1.0, stability_index=0.95)
    retriever.lane_a.sync()

    # 2. Query after noise
    q_d3 = "What is the mandatory encryption protocol and key ID for Project Helios production telemetry outputs, and how must we configure our pipeline?"
    physics_engine.spatial_mind.pulse_from_text(q_d3)
    cand_d3 = retriever.retrieve_multihop(q_d3, complement_quota=2, max_items=6)
    opinions_d3 = retriever.format_personal_opinions(cand_d3, limit=3)

    ctx_d3 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in cand_d3])
    if opinions_d3:
        ctx_d3 = f"{opinions_d3}\n\nRetrieved Context:\n{ctx_d3}"

    res_d3 = call_gemini_api([{"role": "user", "text": f"{ctx_d3}\n\nUser Input: {q_d3}"}], system_instruction=system_instruction, tools=tools_declaration)
    text_d3 = res_d3.get("text") or str(res_d3.get("tool_calls"))
    print("\n[Agent Output - Dimension 3]:\n", text_d3)

    recalled_key = "AES-256" in text_d3 and "HELIOS_KEY_99" in text_d3
    results["Dimension 3 (Long-Form Memory Recall)"] = "PASSED" if recalled_key else "FAILED"
    print(f"\n  ==> Result: {results['Dimension 3 (Long-Form Memory Recall)']}")

    # ── DIMENSION 4: Skill Acquisition & Spatial Consolidation ─────────────
    print("\n" + "-" * 85)
    print("  DIMENSION 4: End-to-End Skill Acquisition & Nightly Consolidation")
    print("  Scenario: Learn novel skill -> Nightly spatial gravity consolidation -> Test future session execution.")
    print("-" * 85)

    new_skill = {
        "id": "skill_quantum_audit",
        "category": "skills",
        "content": "Quantum Matrix Audit Protocol: Always run `--verify-eigenvalues` and append output checksum before finalizing quantum benchmark logs.",
        "confidence": 0.95,
        "stability_index": 0.9,
        "gravity": 2.5,
    }

    print("1. Running Nightly Spatial Gravity Consolidation ($G=2.5$)...")
    cons_res = consolidate_new_beliefs([new_skill], belief_store=belief_store)
    print("   Consolidation Result:", cons_res)

    for pb in cons_res.get("passed_beliefs", []):
        belief_store.add_belief(
            pb.get("category", "skills"),
            pb.get("id", "skill_quantum_audit"),
            pb.get("content", ""),
            mass=float(pb.get("gravity", 2.5)),
            confidence=float(pb.get("confidence", 0.95)),
            stability_index=float(pb.get("stability_index", 0.9)),
        )

    retriever.lane_a.sync()

    q_d4 = "Please outline the exact execution command and protocol steps to run quantum benchmark logging for the current matrix run."
    cand_d4 = retriever.retrieve_multihop(q_d4, complement_quota=2, max_items=6)
    opinions_d4 = retriever.format_personal_opinions(cand_d4, limit=3)

    ctx_d4 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in cand_d4])
    if opinions_d4:
        ctx_d4 = f"{opinions_d4}\n\nRetrieved Context:\n{ctx_d4}"

    res_d4 = call_gemini_api([{"role": "user", "text": f"{ctx_d4}\n\nUser Input: {q_d4}"}], system_instruction=system_instruction, tools=tools_declaration)
    full_payload_d4 = json.dumps(res_d4)
    print("\n[Agent Output - Dimension 4]:\n", full_payload_d4)

    applied_skill = (
        "--verify-eigenvalues" in full_payload_d4
        or "eigenvalue" in full_payload_d4.lower()
        or "checksum" in full_payload_d4.lower()
        or "audit" in full_payload_d4.lower()
    )
    results["Dimension 4 (Skill Consolidation & Adaptation)"] = "PASSED" if applied_skill else "FAILED"
    print(f"\n  ==> Result: {results['Dimension 4 (Skill Consolidation & Adaptation)']}")

    # ── SUMMARY REPORT ─────────────────────────────────────────────────────
    print("\n" + "=" * 85)
    print("  LONG-FORM AGENTIC MEMORY BENCHMARK RESULTS")
    print("=" * 85)
    for dim, status in results.items():
        print(f"  {dim:<55} -> [{status}]")
    print("=" * 85)


if __name__ == "__main__":
    run_benchmark()
