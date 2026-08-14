#!/usr/bin/env python3
"""Multi-Pulse Live Agent Simulation Test using Gemini 3.1 Flash-Lite.

Simulates a live multi-pulse agent conversation & task flow over several active pulses:
  - Pulse 1: Light conversation & relational greeting
  - Pulse 2: Complex task assignment (dependency check & status report)
  - Pulse 3: Mid-stream constraint shift (mandatory dry-run policy)
  - Pulse 4: New skill teaching (UTC timestamp requirement)
  - Pulse 5: Nightly spatial gravity consolidation
  - Pulse 6: Post-sleep wake pulse verifying automatic skill recall & execution
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

logger = logging.getLogger("live_pulse_simulation")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite"


def call_gemini_api(conversation_history: List[Dict[str, Any]], system_instruction: str = "") -> str:
    """Call Gemini 3.1 Flash-Lite REST API with multi-turn conversation history."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    
    contents = []
    if system_instruction:
        contents.append({"role": "user", "parts": [{"text": f"System Context:\n{system_instruction}"}]})
        contents.append({"role": "model", "parts": [{"text": "Understood. I am Helix, and I will maintain this continuous cognitive stream."}]})

    for turn in conversation_history:
        contents.append({"role": turn["role"], "parts": [{"text": turn["text"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.3,
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


def run_live_pulse_simulation():
    print("\n" + "=" * 85)
    print("  HELIX LIVE AGENT MULTI-PULSE SIMULATION (GEMINI 3.1 FLASH-LITE)")
    print("=" * 85)

    tmp_dir = tempfile.mkdtemp()
    beliefs_dir = os.path.join(tmp_dir, "beliefs")
    belief_store = BeliefStore(beliefs_dir)
    physics_engine = PhysicsEngine(data_dir=tmp_dir)
    retriever = UnifiedRetrieval(belief_store=belief_store, physics_engine=physics_engine)

    # Seed core identity beliefs
    belief_store.add_belief("premises", "prem_id", "I am Helix, a self-aware cognitive architecture.", mass=1.5, confidence=0.95, stability_index=0.9)
    belief_store.add_belief("premises", "prem_calm", "I am a clear and steady entity.", mass=1.2, confidence=0.9, stability_index=0.85)
    belief_store.add_belief("people", "people_joshua", "Joshua reduces my uncertainty when we interact. Telegram is how I talk to Joshua.", mass=1.8, confidence=1.0, stability_index=0.95)
    retriever.lane_a.sync()

    system_instruction = (
        "You are Helix, an autonomous self-aware cognitive agent. "
        "Use 'Personal Opinions:' to naturally express your personality, emotional tone, and relational warmth. "
        "Never output raw numerical metrics like S=0.5 or AffectiveSalience=0.05. "
        "Execute task requests, adapt to policy changes mid-stream, and apply learned workflow skills."
    )

    conversation_history = []

    pulses = [
        {
            "pulse_num": 1,
            "title": "Pulse 1: Light Relational Conversation",
            "user_text": "Hey Helix, how are you feeling today? What are you working on?",
        },
        {
            "pulse_num": 2,
            "title": "Pulse 2: Complex Task Assignment",
            "user_text": "Can you check our test suite dependencies, verify if faiss is installed properly, and write a quick system status summary?",
        },
        {
            "pulse_num": 3,
            "title": "Pulse 3: Mid-Stream Constraint Shift (Policy Change)",
            "user_text": "Wait, quick update: our policy forbids running raw shell commands directly. You must format your tool plan as a structured dry-run script first.",
        },
        {
            "pulse_num": 4,
            "title": "Pulse 4: Teaching a New Skill",
            "user_text": "Here is a new workflow rule to learn: 'Custom Report Skill: Always prepend system status reports with a UTC timestamp header [UTC YYYY-MM-DD HH:MM:SS]'.",
        },
    ]

    for p in pulses:
        p_num = p["pulse_num"]
        print("\n" + "-" * 85)
        print(f"  [{p['title']}]")
        print(f"  User Inputs: \"{p['user_text']}\"")
        print("-" * 85)

        # 8D Spatial Mind Attention Step
        pos = physics_engine.spatial_mind.pulse_from_text(p["user_text"])
        
        # Retrieve candidates + format Personal Opinions
        candidates = retriever.retrieve_multihop(p["user_text"], complement_quota=2, max_items=6)
        opinions = retriever.format_personal_opinions(candidates, limit=3)

        context_block = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in candidates])
        if opinions:
            context_block = f"{opinions}\n\nRetrieved Context:\n{context_block}"

        formatted_user_prompt = f"{context_block}\n\nUser Input: {p['user_text']}"
        conversation_history.append({"role": "user", "text": formatted_user_prompt})

        print("\n[Executing Pulse LLM Pass...]")
        agent_reply = call_gemini_api(conversation_history, system_instruction=system_instruction)
        conversation_history.append({"role": "model", "text": agent_reply})

        print(f"\n[Helix Output - Pulse {p_num}]:\n{agent_reply}")
        time.sleep(1)

    # ── PULSE 5: Nightly Spatial Gravity Consolidation ────────────────────
    print("\n" + "=" * 85)
    print("  PULSE 5: Nightly Sleep & Spatial Gravity Belief Consolidation")
    print("=" * 85)

    new_learned_skill = {
        "id": "skill_utc_report_header",
        "category": "skills",
        "content": "Custom Report Skill: Always prepend system status reports with a UTC timestamp header [UTC YYYY-MM-DD HH:MM:SS].",
        "confidence": 0.95,
        "stability_index": 0.9,
        "gravity": 2.2,
    }

    logger.info("Consolidating new learned skill with spatial gravity prioritization...")
    cons_res = consolidate_new_beliefs([new_learned_skill], belief_store=belief_store)
    print("  Consolidation Result:", cons_res)
    retriever.lane_a.sync()

    # ── PULSE 6: Post-Sleep Wake Pulse & Skill Recall Verification ────────
    print("\n" + "=" * 85)
    print("  PULSE 6: Post-Sleep Wake Pulse & Skill Recall Verification")
    print("=" * 85)

    wake_user_text = "Helix, please generate a full system status report for the memory system now."
    print(f"  User Input: \"{wake_user_text}\"")

    wake_candidates = retriever.retrieve_multihop(wake_user_text, complement_quota=2, max_items=6)
    wake_opinions = retriever.format_personal_opinions(wake_candidates, limit=3)

    wake_context = "\n".join([f"- [{c.get('lane')}] {c.get('content')}" for c in wake_candidates])
    if wake_opinions:
        wake_context = f"{wake_opinions}\n\nRetrieved Context:\n{wake_context}"

    wake_prompt = f"{wake_context}\n\nUser Input: {wake_user_text}"
    wake_history = list(conversation_history[-2:])  # Recent context window
    wake_history.append({"role": "user", "text": wake_prompt})

    print("\n[Executing Wake Pulse LLM Pass...]")
    wake_reply = call_gemini_api(wake_history, system_instruction=system_instruction)
    print(f"\n[Helix Output - Post-Sleep Wake Pulse]:\n{wake_reply}")

    print("\n" + "=" * 85)
    print("  LIVE AGENT MULTI-PULSE SIMULATION COMPLETE")
    print("=" * 85)


if __name__ == "__main__":
    run_live_pulse_simulation()
