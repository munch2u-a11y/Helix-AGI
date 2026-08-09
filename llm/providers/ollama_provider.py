"""
Helix — Ollama Chat Session Provider

Wraps Ollama's /api/chat with persistent message history.
Supports BOTH the Python package and direct REST API.
Vulkan auto-offload on AMD 780m iGPU. No hardcoded timeout.
Thinking mode disabled for faster pulse responses.

Extracted from pulse_loop.py into the provider abstraction layer.
"""

import json
import logging
import os
import time
from typing import Optional, Dict, Any, List

from llm.providers.base import ChatSession

logger = logging.getLogger("helix.llm.providers.ollama")


def _has_ollama_package() -> bool:
    """Check if the ollama Python package is installed."""
    try:
        import ollama
        return True
    except ImportError:
        return False


class OllamaSession(ChatSession):
    """Chat session backed by Ollama's /api/chat endpoint.

    Uses the ollama Python package if available, falls back to
    direct REST API calls otherwise.

    Maintains message history locally (same as start_chat()).
    Each send_message() sends the full history.
    No hardcoded timeout — waits as long as the model needs.
    Thinking mode disabled for faster responses.
    """

    def __init__(
        self,
        model: str,
        system_instruction: str,
        temperature: float = 0.8,
        max_output_tokens: int = 2048,
        options: Optional[Dict[str, Any]] = None,
    ):
        self.model = model
        self.system_instruction = system_instruction
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.options = dict(options or {})
        # keep_alive is an Ollama request parameter, not a model-generation
        # option. A short-lived auxiliary worker can set it to zero so its
        # model is unloaded before the foreground and embedding models resume.
        self.keep_alive = self.options.pop("keep_alive", None)
        self.history: List[Dict[str, str]] = []
        self._last_token_count = 0
        try:
            self.max_attempts = max(
                1, int(os.environ.get("HELIX_OLLAMA_MAX_ATTEMPTS", "4"))
            )
        except (TypeError, ValueError):
            self.max_attempts = 4

        # Ensure options include context window
        if "num_ctx" not in self.options:
            self.options["num_ctx"] = 128_000

        # Detect which interface to use
        self._use_package = _has_ollama_package()
        mode = "package" if self._use_package else "REST API"

        logger.info(
            f"OllamaSession created ({mode}): model={model}, "
            f"temp={temperature}, ctx={self.options.get('num_ctx')}"
        )

    def send_message(self, message: str) -> str:
        """Send a message and return the model's response text."""
        self.history.append({"role": "user", "content": message})

        # Build messages array with system instruction
        messages = [
            {"role": "system", "content": self.system_instruction},
        ] + self.history

        if self._use_package:
            thought = self._send_via_package(messages)
        else:
            thought = self._send_via_rest(messages)

        self.history.append({"role": "assistant", "content": thought})
        return thought

    def _send_via_package(self, messages: List[Dict[str, str]]) -> str:
        """Send using the ollama Python package."""
        import ollama

        try:
            response = None
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = ollama.chat(
                        model=self.model,
                        messages=messages,
                        options=self.options,
                        keep_alive=self.keep_alive,
                        think=False,  # Disable thinking for fast pulses
                    )
                    break
                except Exception as exc:
                    if attempt >= self.max_attempts:
                        raise
                    delay = 2 ** attempt
                    logger.warning(
                        "Ollama package call failed (%d/%d): %s; retrying in %ds",
                        attempt, self.max_attempts, exc, delay,
                    )
                    time.sleep(delay)
            if response is None:
                raise RuntimeError("Ollama returned no response")

            thought = response.message.content or ""

            # Log performance
            total_s = response.total_duration / 1e9 if response.total_duration else 0
            eval_count = response.eval_count or 0
            prompt_eval_count = getattr(response, "prompt_eval_count", 0) or 0
            self._last_token_count = eval_count + prompt_eval_count
            logger.debug(
                f"Ollama response: {eval_count} tokens in {total_s:.1f}s"
            )
            return thought

        except Exception as e:
            logger.error(f"Ollama package call failed: {e}")
            self._last_token_count = self.get_history_size() // 4
            return f"[internal error: LLM call failed — {str(e)[:100]}]"

    def _send_via_rest(self, messages: List[Dict[str, str]]) -> str:
        """Send using the Ollama REST API directly."""
        import requests

        try:
            response = None
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = requests.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": self.model,
                            "messages": messages,
                            "options": self.options,
                            "stream": False,
                            "think": False,
                            "keep_alive": self.keep_alive,
                        },
                        timeout=None,  # No timeout — wait as long as needed
                    )
                    response.raise_for_status()
                    break
                except Exception as exc:
                    if attempt >= self.max_attempts:
                        raise
                    delay = 2 ** attempt
                    logger.warning(
                        "Ollama REST call failed (%d/%d): %s; retrying in %ds",
                        attempt, self.max_attempts, exc, delay,
                    )
                    time.sleep(delay)
            if response is None:
                raise RuntimeError("Ollama returned no response")
            data = response.json()

            thought = data.get("message", {}).get("content", "")

            # Log performance
            total_s = data.get("total_duration", 0) / 1e9
            eval_count = data.get("eval_count", 0)
            prompt_eval_count = data.get("prompt_eval_count", 0)
            self._last_token_count = eval_count + prompt_eval_count
            if eval_count:
                logger.debug(
                    f"Ollama REST response: {eval_count} tokens in {total_s:.1f}s"
                )
            return thought

        except Exception as e:
            logger.error(f"Ollama REST call failed: {e}")
            self._last_token_count = self.get_history_size() // 4
            return f"[internal error: LLM call failed — {str(e)[:100]}]"

    def get_history_size(self) -> int:
        """Return approximate character count of the full session."""
        total = len(self.system_instruction)
        for msg in self.history:
            total += len(msg.get("content", ""))
        return total

    def get_history(self) -> List[Dict[str, Any]]:
        """Return conversation history converted to Gemini format for the compressor."""
        gemini_history = []
        for msg in self.history:
            role = msg.get("role")
            gemini_role = "model" if role == "assistant" else "user"
            gemini_history.append({
                "role": gemini_role,
                "parts": [{"text": msg.get("content", "")}]
            })
        return gemini_history

    def replace_history(self, compressed_history: List[Dict[str, Any]]):
        """Replace history with compressed history mapped from Gemini format."""
        new_history = []
        for msg in compressed_history:
            role = msg.get("role")
            cpp_role = "assistant" if role == "model" else "user"
            text_parts = []
            for part in msg.get("parts", []):
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts)
            new_history.append({
                "role": cpp_role,
                "content": content
            })
        self.history = new_history
        self._last_token_count = 0

    def get_last_token_count(self) -> int:
        """Return token count of the last chat completion, or estimate it."""
        if hasattr(self, '_last_token_count') and self._last_token_count > 0:
            return self._last_token_count
        return self.get_history_size() // 4
