"""
Helix — Reliance Evaluator (Local Model Auditor)

Evaluates whether injected beliefs were actually relied upon by the conscious
API model. Uses a local Ollama model to assess the reasoning inside the
API model's output.
"""

import threading
import logging
import json
import requests
from typing import List, Optional

logger = logging.getLogger("helix.core.reliance_evaluator")


class RelianceEvaluator:
    """Asynchronously audits the conscious model's output for belief reliance."""

    def __init__(self, belief_store, ollama_url: str = "http://localhost:11434", ollama_model: str = "gemma3:4b"):
        self.beliefs = belief_store
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model

    def evaluate(self, trigger_text: str, injected_beliefs: List[dict], model_output: str, current_pulse: int):
        """Spawns a background thread to evaluate reliance without blocking the pulse loop."""
        if not injected_beliefs:
            return  # Nothing to evaluate

        thread = threading.Thread(
            target=self._run_evaluation,
            args=(trigger_text, injected_beliefs, model_output, current_pulse),
            daemon=True,
            name="reliance_evaluator"
        )
        thread.start()

    def _run_evaluation(self, trigger_text: str, injected_beliefs: List[dict], model_output: str, current_pulse: int):
        """The actual evaluation logic running in the background thread."""
        try:
            # Format beliefs for the prompt
            belief_context = ""
            valid_ids = set()
            for b in injected_beliefs:
                b_id = b.get("id", "unknown")
                b_content = b.get("content", "")
                belief_context += f"- [{b_id}] {b_content}\n"
                valid_ids.add(b_id)

            prompt = f"""You are a cognitive auditor evaluating an AI agent's reasoning.
The agent received the following trigger event:
{trigger_text}

The agent was injected with the following context beliefs:
{belief_context}

The agent produced the following thought/action:
{model_output}

Which of the injected context beliefs did the agent *definitively rely upon* to produce its thought/action?
Output ONLY a valid JSON object with a single key "relied_belief_ids" mapping to an array of belief IDs. Do not include any other text or explanation. Example format:
{{
  "relied_belief_ids": ["id1", "id2"]
}}
"""

            payload = {
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }

            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=15.0
            )
            response.raise_for_status()
            
            result = response.json().get("response", "{}").strip()
            
            try:
                data = json.loads(result)
                if not isinstance(data, dict) or "relied_belief_ids" not in data:
                    logger.warning(f"Reliance Evaluator returned invalid JSON structure: {data}")
                    return
                
                relied_ids = data["relied_belief_ids"]
                if not isinstance(relied_ids, list):
                    logger.warning(f"Reliance Evaluator relied_belief_ids is not a list: {relied_ids}")
                    return
                
                # Filter out invalid or hallucinated IDs
                relied_ids = [str(r_id) for r_id in relied_ids if str(r_id) in valid_ids]
                
                if relied_ids:
                    logger.info(f"Reliance Evaluator found relied-upon beliefs: {relied_ids}")
                    for r_id in relied_ids:
                        self.beliefs.register_reliance(r_id, current_pulse)
                        
            except json.JSONDecodeError:
                logger.warning(f"Reliance Evaluator returned invalid JSON: {result}")
                
        except Exception as e:
            logger.debug(f"Reliance Evaluator failed: {e}")
