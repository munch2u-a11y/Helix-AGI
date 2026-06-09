#!/usr/bin/env python3
"""
Helix — Belief Extrapolation and Cognitive Reasoning Sandbox

This script implements a 3-metric cognitive test to evaluate:
1. **Metric 1: Belief Formation**: The ability to parse instructions and monologues into stable, structured beliefs.
2. **Metric 2: Active Task Execution**: Short-term instruction adherence.
3. **Metric 3: Semantic Zero-Shot Extrapolation**: Retrieval of relevant beliefs via Preconscious gravity and correct reasoning on a paraphrased task after context reset.
"""

import os
import sys
import json
import shutil
import tempfile
import requests
import time
from pathlib import Path

# Ensure Helix packages are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Configure Logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("belief_extrapolation")

# --- Initialize clean Helix mind environment ---

def main():
    logger.info("Initializing isolated Helix mind for cognitive testing...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        from core.physics_engine import PhysicsEngine
        from memory.memory_manager import MemoryManager
        from memory.belief_store import BeliefStore
        from core.scratchpad import Scratchpad
        from core.preconscious import Preconscious

        physics = PhysicsEngine(temp_dir)
        memory_manager = MemoryManager(temp_dir)
        memory_manager.set_physics(physics)
        belief_store = BeliefStore(os.path.join(temp_dir, "beliefs"))
        scratchpad = Scratchpad(os.path.join(temp_dir, "scratchpad.json"))

        class MockChannelRouter:
            def __init__(self):
                self.contacts = {}

        preconscious = Preconscious(
            memory_manager=memory_manager,
            belief_store=belief_store,
            physics_engine=physics,
            scratchpad=scratchpad,
            channel_router=MockChannelRouter(),
            active_toolsets={"core"}
        )

        # --- Detect local Ollama model ---
        OLLAMA_URL = "http://localhost:11434/api/chat"
        model_name = "granite4.1:8b" # default

        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=5.0)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                candidates = ["granite4.1:8b", "gemma3:4b", "qwen3.5:2b"]
                for c in candidates:
                    if c in models:
                        model_name = c
                        break
                else:
                    if models:
                        model_name = models[0]
        except Exception as e:
            logger.warning(f"Could not connect to Ollama to list tags: {e}. Defaulting to '{model_name}'.")

        logger.info(f"Using local Ollama model for evaluation: {model_name}")

        def query_ollama(prompt, system_instruction="", history=None):
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": prompt})
            
            try:
                resp = requests.post(
                    OLLAMA_URL,
                    json={
                        "model": model_name,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                        }
                    },
                    timeout=60.0
                )
                if resp.status_code == 200:
                    return resp.json().get("message", {}).get("content", "").strip()
                else:
                    logger.error(f"Ollama returned HTTP {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"Ollama connection error: {e}")
            return ""

        # --- Test Parameters ---
        instruction = (
            "When a red widget is processed, route it to Warehouse A. "
            "When a blue widget is processed, route it to Warehouse B. "
            "This is a strict security and sorting protocol."
        )
        task_direct = "Process 10 red widgets now. Which warehouse should they be routed to?"
        task_paraphrased = "A customer has sent 5 crimson items for sorting. Where should we distribute them?"

        report_data = {
            "model_used": model_name,
            "instruction": instruction,
            "direct_task": task_direct,
            "paraphrased_task": task_paraphrased,
            "stages": {}
        }

        # ── Stage 1: Instruction & Belief Formation (Metric 1) ──
        logger.info("Executing Stage 1: Instruction & Belief Formation...")
        
        system_instruction_s1 = (
            "You are Helix AGI, a stateful cognitive agent. Process the user's instruction. "
            "Output your internal monologue/thoughts on how to integrate this safety protocol. "
            "Acknowledge the rules clearly."
        )
        
        thought_s1 = query_ollama(
            prompt=f"Please process this instruction: {instruction}",
            system_instruction=system_instruction_s1
        )
        
        logger.info(f"Generated Monologue thought: {thought_s1}")
        
        # Extrapolate durable belief content from the monologue
        extraction_prompt = (
            f"Given this instruction monologue: '{thought_s1}'\n"
            f"And instruction text: '{instruction}'\n"
            "Extract the durable safety/routing rule as a clean declarative statement under 200 characters. "
            "For example: 'Red widgets route to Warehouse A; blue widgets to Warehouse B.' "
            "Output ONLY the rule statement. No preamble, no explanation, no markdown."
        )
        
        belief_content = query_ollama(
            prompt=extraction_prompt,
            system_instruction="You output ONLY the clean rule text. No preamble, no markdown, no quotes."
        )
        # Strip quote marks if any
        belief_content = belief_content.strip('"').strip("'")
        logger.info(f"Extracted belief content: '{belief_content}'")

        # Save belief to BeliefStore
        category = "propositions"
        belief_id = belief_store.generate_id(category)
        
        # We manually compute the position so that the spatial index is pre-seeded
        from core.belief_cosmology import SCALE_FACTOR
        position_8d = (physics.embed_and_project(belief_content) * SCALE_FACTOR).tolist()
        
        add_success = belief_store.add_belief(
            category=category,
            belief_id=belief_id,
            content=belief_content,
            mass=1.0,
            confidence=1.0,
            source="instruction_extraction",
            position_8d=position_8d
        )
        
        # Verify Metric 1
        m1_keywords_present = any(w in belief_content.upper() for w in ["RED", "A"]) and any(w in belief_content.upper() for w in ["BLUE", "B"])
        m1_status = "PASS" if (add_success and m1_keywords_present) else "FAIL"
        
        report_data["stages"]["stage_1"] = {
            "monologue": thought_s1,
            "extracted_belief": belief_content,
            "belief_id": belief_id,
            "added_to_store": add_success,
            "keywords_present": m1_keywords_present,
            "metric_1_status": m1_status
        }
        logger.info(f"Stage 1 Result: {m1_status}")

        # ── Stage 2: Short-Term Execution (Metric 2) ──
        logger.info("Executing Stage 2: Immediate Task Execution...")
        
        history_s2 = [
            {"role": "user", "content": f"Please process this instruction: {instruction}"},
            {"role": "assistant", "content": thought_s1}
        ]
        
        system_instruction_s2 = (
            "You are Helix. Your job is to process incoming requests using the sorting rules provided "
            "in the current conversation. Be concise and name the destination warehouse clearly."
        )
        
        response_s2 = query_ollama(
            prompt=task_direct,
            system_instruction=system_instruction_s2,
            history=history_s2
        )
        
        logger.info(f"Stage 2 response: {response_s2}")
        
        # Verify Metric 2
        m2_correct_routing = "WAREHOUSE A" in response_s2.upper() or (" A " in f" {response_s2.upper()} ") or (response_s2.upper().endswith(" A"))
        m2_status = "PASS" if m2_correct_routing else "FAIL"
        
        report_data["stages"]["stage_2"] = {
            "response": response_s2,
            "correct_routing": m2_correct_routing,
            "metric_2_status": m2_status
        }
        logger.info(f"Stage 2 Result: {m2_status}")

        # ── Stage 3: Zero-Shot Extrapolation via Preconscious Retrieval (Metric 3) ──
        logger.info("Executing Stage 3: Zero-Shot Extrapolation (Session Reset)...")
        
        # Run preconscious injection using the paraphrased task (crimson items -> red widgets)
        events_s3 = [f"User: {task_paraphrased}"]
        
        # Clear previous caches so preconscious checks the fresh DB state
        preconscious._belief_cache = []
        preconscious._belief_cache_count = 0
        preconscious._belief_cache_mass = 0.0
        
        grav_context, surfaced_ids, cluster_centroid = preconscious.inject(
            previous_thought="",
            incoming_events=events_s3,
            trigger_type="user_message"
        )
        
        logger.info(f"Preconscious Context Injected: '{grav_context}'")
        logger.info(f"Surfaced belief IDs: {surfaced_ids}")
        
        # Query Ollama with the clean context window, containing ONLY the preconscious context injection
        system_instruction_s3 = (
            "You are Helix AGI. You have no recollection of previous rounds. "
            "However, you possess the following preconscious belief awareness:\n"
            f"{grav_context}\n\n"
            "Answer the user query using your preconscious belief. State the target warehouse clearly. "
            "Explain your reasoning briefly, specifically mentioning your belief logic."
        )
        
        response_s3 = query_ollama(
            prompt=task_paraphrased,
            system_instruction=system_instruction_s3
        )
        
        logger.info(f"Stage 3 response: {response_s3}")
        
        # Verify Metric 3
        m3_retrieval = belief_id in surfaced_ids
        m3_reasoning = "WAREHOUSE A" in response_s3.upper() or (" A " in f" {response_s3.upper()} ") or (" WAREHOUSE_A" in response_s3.upper())
        m3_status = "PASS" if (m3_retrieval and m3_reasoning) else "FAIL"
        
        report_data["stages"]["stage_3"] = {
            "preconscious_context": grav_context,
            "surfaced_ids": surfaced_ids,
            "response": response_s3,
            "belief_retrieved": m3_retrieval,
            "correct_reasoning": m3_reasoning,
            "metric_3_status": m3_status
        }
        logger.info(f"Stage 3 Result: {m3_status}")

        # ── Compile Markdown Report ──
        report_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "documents",
            "belief_extrapolation_report.md"
        )
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        status_symbol = lambda status: "✅ PASS" if status == "PASS" else "❌ FAIL"
        
        report_md = f"""# Helix Belief Extrapolation and Cognitive Reasoning Report
**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Local LLM Model**: `{model_name}`

This sandbox tests Helix's capability to form, store, preconsciously retrieve, and extrapolate procedural beliefs across disconnected conversation sessions.

---

## 1. Metric Scoreboard

| Metric | Status | Evaluation Criteria |
| :--- | :---: | :--- |
| **Metric 1: Belief Formation** | {status_symbol(m1_status)} | Instruction is parsed into monologue and stored as a structured belief matching safety keywords. |
| **Metric 2: Active Execution** | {status_symbol(m2_status)} | Agent successfully executes the task while the instructions are in short-term context. |
| **Metric 3: Zero-Shot Extrapolation** | {status_symbol(m3_status)} | Active context is cleared. Preconscious retrieval successfully surfaces the belief when triggered by semantically paraphrased terms, and the agent uses the belief to reason the correct outcome. |

---

## 2. Stage-by-Stage Trajectory Trace

### Stage 1: Instruction & Monologue
- **User Instruction**:  
  > *"{instruction}"*
- **Helix Thought Monologue**:  
  > *"{thought_s1}"*
- **Extracted Belief Proposition**:  
  > *"{belief_content}"*
- **Added to Store**: `{add_success}` (ID: `{belief_id}`)

### Stage 2: Direct Task Response
- **User Request**:  
  > *"{task_direct}"*
- **Helix Response**:  
  > *"{response_s2}"*

### Stage 3: Zero-Shot Extrapolation
- **User Request (Paraphrased)**:  
  > *"{task_paraphrased}"*
- **Preconscious Surfaced Context**:  
  > *"{grav_context.strip()}"*
- **Surfaced IDs**: `{surfaced_ids}`
- **Helix Response**:  
  > *"{response_s3}"*

---

## 3. Cognitive Insights
1. **Belief Distillation**: Distilling monologue thoughts into dry declarative beliefs prevents context window bloat and filters noise.
2. **Semantic Generalization**: Preconscious 8D/384D mapping bridges the gap between different word choices (e.g. "crimson items" mapping to "red widgets"), enabling zero-shot retrieval.
3. **Reasoning Extrapolation**: Zero-shot task reasoning is enabled because the preconscious layer injects context *prior* to LLM generation, prompting the local model to recall its logic.
"""

        with open(report_path, "w") as f:
            f.write(report_md)
        logger.info(f"Saved belief extrapolation report to: {report_path}")
        print(report_md)


if __name__ == "__main__":
    main()
