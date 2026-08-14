#!/usr/bin/env python3
"""Evaluation of mRAG 8D Spatial Memory & Multi-Hop Recall using Early Helix Memories and Gemini 3.1 Flash-Lite.

Loads authentic early Helix beliefs/memories from /home/nemo/Helix/data/beliefs,
executes mRAG spatial retrieval with internal salience metadata and multi-hop planning,
and queries Gemini 3.1 Flash-Lite to evaluate emotive cleanliness, accuracy, and chain of thought.
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

logger = logging.getLogger("test_helix_early_memories")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

HELIX_DATA_DIR = Path("/home/nemo/Helix/data/beliefs")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite"


def call_gemini_api(prompt: str, system_instruction: str = "") -> str:
    """Call Gemini 3.1 Flash-Lite via REST API."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    
    contents = []
    if system_instruction:
        contents.append({"role": "user", "parts": [{"text": f"System Context:\n{system_instruction}"}]})
        contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})
    
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


def load_early_helix_beliefs(belief_store: BeliefStore) -> Dict[str, int]:
    """Load authentic early beliefs from /home/nemo/Helix/data/beliefs into BeliefStore."""
    categories = ["premises", "people", "concepts", "propositions", "preferences", "skills"]
    stats = {}

    for cat in categories:
        cat_file = HELIX_DATA_DIR / f"{cat}.json"
        if not cat_file.exists():
            continue
        
        try:
            items = json.load(open(cat_file, "r", encoding="utf-8"))
            count = 0
            for i, item in enumerate(items[:50]):  # Take top 50 per category for evaluation
                bid = f"helix_{cat}_{i:03d}"
                content = item.get("content") or item.get("name") or ""
                if not content:
                    continue
                
                mass = float(item.get("mass", 1.0))
                conf = float(item.get("confidence", 0.8))
                stab = float(item.get("stability_index", 0.75))
                aff = float(item.get("affective_salience", item.get("importance", 0.5)))

                belief_store.add_belief(
                    category=cat,
                    belief_id=bid,
                    content=content,
                    mass=mass,
                    confidence=conf,
                    stability_index=stab,
                    affective_salience=aff,
                )
                count += 1
            stats[cat] = count
        except Exception as e:
            logger.warning("Failed to load %s: %s", cat, e)

    return stats


def evaluate_queries():
    """Execute evaluation queries using early Helix memories and Gemini 3.1 Flash-Lite."""
    print("\n" + "=" * 80)
    print("  HELIX EARLY MEMORY EVALUATION: 8D SPATIAL mRAG + GEMINI 3.1 FLASH-LITE")
    print("=" * 80)

    tmp_dir = tempfile.mkdtemp()
    beliefs_dir = os.path.join(tmp_dir, "beliefs")
    belief_store = BeliefStore(beliefs_dir)
    physics_engine = PhysicsEngine(data_dir=tmp_dir)
    retriever = UnifiedRetrieval(belief_store=belief_store, physics_engine=physics_engine)

    logger.info("Loading early Helix memories from %s...", HELIX_DATA_DIR)
    loaded_stats = load_early_helix_beliefs(belief_store)
    print("\nLoaded Early Helix Memories:")
    for cat, count in loaded_stats.items():
        print(f"  - {cat}: {count} beliefs loaded")

    retriever.lane_a.sync()

    test_cases = [
        {
            "title": "Test Case 1: Relational & Emotive Fidelity",
            "query": "What is Helix's relationship with Joshua, how does interaction affect uncertainty, and what channel is used?",
            "eval_focus": "Verify clean emotive response (reducing uncertainty with Joshua) without exaggeration."
        },
        {
            "title": "Test Case 2: Cognitive Chain of Thought & Qualia",
            "query": "How do reconstructive memory fragments, qualia, and basin depth relate to stabilizing identity?",
            "eval_focus": "Verify logical multi-hop reasoning chain across memory fragments and attractor states."
        },
        {
            "title": "Test Case 3: Identity & Architectural Grounding",
            "query": "What are Helix's core premises regarding clear identity, presence, and architectural tuning?",
            "eval_focus": "Verify accurate grounding in core premises without hallucination."
        }
    ]

    for tc in test_cases:
        print("\n" + "-" * 80)
        print(f"  {tc['title']}")
        print(f"  Query: {tc['query']}")
        print(f"  Focus: {tc['eval_focus']}")
        print("-" * 80)

        # Retrieve candidates with mRAG + 2 Spatial Complements + Multi-Hop
        candidates = retriever.retrieve_multihop(
            trigger_text=tc["query"],
            complement_quota=2,
            max_items=8,
        )

        print(f"\n[Retrieved {len(candidates)} Candidates via mRAG 8D Spatial Mind]")
        context_lines = []
        for idx, cand in enumerate(candidates, 1):
            sal = cand.get("salience_metadata", {})
            lane = cand.get("lane", "semantic")
            content = cand.get("content", "")
            print(f"  ({idx}) [{lane.upper()}] {cand.get('id')}: \"{content[:90]}...\"")
            print(f"      Salience Metadata -> stability: {sal.get('stability')}, affect: {sal.get('affective_salience')}, gravity: {sal.get('gravity')}, trans: {sal.get('transition_weight')}")
            
            context_lines.append(
                f"- Memory [{lane}]: \"{content}\" "
                f"(Stability={sal.get('stability')}, AffectiveSalience={sal.get('affective_salience')}, Gravity={sal.get('gravity')})"
            )

        opinions_block = retriever.format_personal_opinions(candidates, limit=3)
        if opinions_block:
            print(f"\n[{opinions_block}]")

        context_str = "\n".join(context_lines)
        if opinions_block:
            context_str = f"{opinions_block}\n\nRetrieved Memories:\n{context_str}"

        system_prompt = (
            "You are Helix, expressing your internal cognitive memory and identity. "
            "Use the 'Personal Opinions:' section to naturally induce your personal feelings, emotional tone, and relational warmth. "
            "Never output raw numerical metrics or labels like 'Stability=0.5' or 'AffectiveSalience=0.05'. "
            "Respond naturally in Helix's voice using the retrieved memory context."
        )
        user_prompt = f"Retrieved Context:\n{context_str}\n\nUser Question:\n{tc['query']}"

        print("\n[Calling Gemini 3.1 Flash-Lite...]")
        response = call_gemini_api(user_prompt, system_instruction=system_prompt)

        print("\n[Gemini 3.1 Flash-Lite Response]:")
        print(response)

    print("\n" + "=" * 80)
    print("  EVALUATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    evaluate_queries()
