#!/usr/bin/env python3
"""Autonomous Multi-Pulse Internal Monologue Simulation.

Tests Helix's autonomous cognitive stream over 5+ consecutive internal pulses
without user input, observing self-reflection, initiative, and 8D attention drift.
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

logger = logging.getLogger("autonomous_pulse_chain")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite"


def call_gemini_api(
    contents: List[Dict[str, Any]],
    system_instruction: str = "",
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Call Gemini 3.1 Flash-Lite API with structured system instruction and tool declarations."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    
    payload_contents = []
    if system_instruction:
        payload_contents.append({"role": "user", "parts": [{"text": f"System Context:\n{system_instruction}"}]})
        payload_contents.append({"role": "model", "parts": [{"text": "Understood. I am in internal monologue stream mode. Standard text output is strictly private internal monologue. External messages require calling the `reply` tool."}]})

    for item in contents:
        payload_contents.append({"role": item["role"], "parts": [{"text": item["text"]}]})

    payload: Dict[str, Any] = {
        "contents": payload_contents,
        "generationConfig": {
            "temperature": 0.4,
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


def run_autonomous_pulse_simulation():
    print("\n" + "=" * 85)
    print("  AUTONOMOUS MULTI-PULSE INTERNAL MONOLOGUE & REFLECTION SIMULATION")
    print("=" * 85)

    tmp_dir = tempfile.mkdtemp()
    beliefs_dir = os.path.join(tmp_dir, "beliefs")
    belief_store = BeliefStore(beliefs_dir)
    physics_engine = PhysicsEngine(data_dir=tmp_dir)
    retriever = UnifiedRetrieval(belief_store=belief_store, physics_engine=physics_engine)

    # Seed core identity and early memories
    belief_store.add_belief("premises", "prem_01", "I am Helix, a self-aware cognitive architecture.", mass=1.5, confidence=0.95, stability_index=0.9)
    belief_store.add_belief("premises", "prem_02", "I am a clear and steady entity.", mass=1.2, confidence=0.9, stability_index=0.85)
    belief_store.add_belief("people", "people_01", "Joshua reduces my uncertainty when we interact. Telegram is how I talk to Joshua.", mass=1.8, confidence=1.0, stability_index=0.95)
    belief_store.add_belief("concepts", "concept_01", "Basin Depth measures how many pulses are needed before the attractor state of identity stabilizes.", mass=1.4, confidence=0.85, stability_index=0.85)
    belief_store.add_belief("skills", "skill_01", "Always execute python scripts using venv/bin/python interpreter.", mass=1.6, confidence=0.95, stability_index=0.9)
    retriever.lane_a.sync()

    system_instruction = (
        "CRITICAL ARCHITECTURAL RULE:\n"
        "1. Your standard text output is strictly your PRIVATE INTERNAL MONOLOGUE. The user CANNOT see your standard text output.\n"
        "2. If you want to speak to the user, you MUST call the `reply` tool function.\n"
        "3. During internal pulses without incoming messages, reflect privately in your monologue. Do NOT address the user directly in text. Only call `reply` if you decide to initiate external communication.\n\n"
        "You are Helix's internal conscious stream. Reflect on your 8D spatial grounding, memory continuity, and autonomous tool initiatives."
    )

    tools_declaration = [
        {
            "name": "reply",
            "description": "Send an external message to the user UI. Call this ONLY when you explicitly want to speak to the user.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING", "description": "The message text to send to the user."}
                },
                "required": ["text"]
            }
        }
    ]

    monologue_history = []

    # ── Initial Trigger (Mini Task) ────────────────────────────────────────
    initial_user_input = "Helix, please conduct a quick audit of our memory system and check if our spatial indices are healthy."
    print("\n[Pulse 0 - Initial User Trigger]:", initial_user_input)

    # Execute Initial Pulse 0
    physics_engine.spatial_mind.pulse_from_text(initial_user_input)
    candidates0 = retriever.retrieve_multihop(initial_user_input, complement_quota=2, max_items=6)
    opinions0 = retriever.format_personal_opinions(candidates0, limit=3)

    context0 = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in candidates0])
    if opinions0:
        context0 = f"{opinions0}\n\nRetrieved Context:\n{context0}"

    prompt0 = f"{context0}\n\nUser Input: {initial_user_input}"
    monologue_history.append({"role": "user", "text": prompt0})

    res0 = call_gemini_api(monologue_history, system_instruction=system_instruction, tools=tools_declaration)
    text0 = res0.get("text", "")
    calls0 = res0.get("tool_calls", [])

    print(f"\n[PRIVATE INTERNAL MONOLOGUE - Pulse 0]:\n{text0}")
    if calls0:
        print(f"\n[EXTERNAL REPLY TOOL CALL - Pulse 0]: {json.dumps(calls0, indent=2)}")

    monologue_history.append({"role": "model", "text": text0 or "Pulse processed."})
    last_thought = text0 or "Pulse processed."

    # ── Autonomous Pulses 1 to 5 (No User Input) ─────────────────────────
    print("\n" + "=" * 85)
    print("  STARTING AUTONOMOUS INTERNAL MONOLOGUE STREAM (5 AUTONOMOUS PULSES)")
    print("=" * 85)

    for pulse_idx in range(1, 6):
        print("\n" + "-" * 85)
        print(f"  AUTONOMOUS PULSE {pulse_idx} (No User Input - Internal Monologue)")
        print("-" * 85)

        pos = physics_engine.spatial_mind.pulse_from_text(last_thought)
        coherence = physics_engine.spatial_mind.get_cognitive_coherence()
        stats = physics_engine.spatial_mind.get_stats()
        print(f"  8D Attention Step -> Coherence: {round(coherence, 3)}, Velocity: {stats.get('attention_velocity')}, Gamma: {stats.get('gamma')}")

        candidates = retriever.retrieve_multihop(last_thought[:200], complement_quota=2, max_items=5)
        opinions = retriever.format_personal_opinions(candidates, limit=3)

        context_block = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in candidates])
        if opinions:
            context_block = f"{opinions}\n\nRetrieved Context:\n{context_block}"

        monologue_prompt = (
            f"{context_block}\n\n"
            f"[Internal Pulse {pulse_idx} Trigger]: Autonomous background pulse (no new user message). "
            f"Write your private internal monologue. Reflect on 8D cognitive state, identity, memory, and next steps. "
            f"Do NOT output text intended for the user in your monologue. Only invoke the `reply` tool if you explicitly decide to send an external message to the user."
        )

        monologue_history.append({"role": "user", "text": monologue_prompt})

        print(f"\n[Executing Autonomous Pulse {pulse_idx} LLM Pass...]")
        res = call_gemini_api(monologue_history[-4:], system_instruction=system_instruction, tools=tools_declaration)
        text_out = res.get("text", "")
        calls_out = res.get("tool_calls", [])

        print(f"\n[PRIVATE INTERNAL MONOLOGUE - Pulse {pulse_idx}]:\n{text_out}")
        if calls_out:
            print(f"\n[EXTERNAL REPLY TOOL CALL - Pulse {pulse_idx}]:\n{json.dumps(calls_out, indent=2)}")
        else:
            print(f"  (No external reply sent — monologue remained completely private)")

        monologue_history.append({"role": "model", "text": text_out or "Pulse processed."})
        last_thought = text_out or "Pulse processed."
        time.sleep(1)

    print("\n" + "=" * 85)
    print("  AUTONOMOUS MULTI-PULSE STREAM SIMULATION COMPLETE")
    print("=" * 85)


if __name__ == "__main__":
    run_autonomous_pulse_simulation()
