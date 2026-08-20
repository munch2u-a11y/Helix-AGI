"""
LLM Backend Adapter for Local Ollama / REST Models.
Provides fast, reliable text generation for the Subconscious Conductor and Surgical Subagents.
"""

import json
import os
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "granite4.1:8b"

class LLMBackend:
    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        default_model: str = DEFAULT_MODEL,
        fallback_model: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        configured_fallback = (
            fallback_model
            if fallback_model is not None
            else os.environ.get("HELIX_LLM_FALLBACK_MODEL", "")
        )
        self.fallback_model = configured_fallback.strip() or None
        self.last_model_used: Optional[str] = None
        self.last_response_metadata: Dict[str, Any] = {}

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        stop: Optional[List[str]] = None
    ) -> str:
        model_to_use = model or self.default_model
        
        payload: Dict[str, Any] = {
            "model": model_to_use,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        
        if system_prompt:
            payload["system"] = system_prompt
            
        if stop:
            payload["options"]["stop"] = stop

        try:
            return self._call_ollama(payload)
        except Exception as e:
            if self.fallback_model and model_to_use != self.fallback_model:
                print(f"[LLMBackend Warning] Primary model '{model_to_use}' failed: {e}. Trying configured fallback '{self.fallback_model}'...")
                payload["model"] = self.fallback_model
                try:
                    return self._call_ollama(payload)
                except Exception as fallback_err:
                    raise RuntimeError(f"Both primary and fallback models failed: {fallback_err}")
            raise

    def _call_ollama(self, payload: Dict[str, Any]) -> str:
        url = f"{self.base_url}/api/generate"
        json_data = json.dumps(payload).encode("utf-8")
        
        req = urllib.request.Request(
            url,
            data=json_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        # 300 second timeout for large local model generation
        with urllib.request.urlopen(req, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
            self.last_model_used = str(result.get("model") or payload["model"])
            self.last_response_metadata = {
                key: result.get(key)
                for key in (
                    "model", "created_at", "done", "done_reason",
                    "total_duration", "load_duration", "prompt_eval_count",
                    "prompt_eval_duration", "eval_count", "eval_duration",
                )
                if key in result
            }
            return result.get("response", "").strip()

    def check_health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False
