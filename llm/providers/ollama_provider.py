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
        self.compiled_context_only = False
        # keep_alive is an Ollama request parameter, not a model-generation
        # option. A short-lived auxiliary worker can set it to zero so its
        # model is unloaded before the foreground and embedding models resume.
        self.keep_alive = self.options.pop("keep_alive", None)
        self.history: List[Dict[str, str]] = []
        self.context_counter = None
        self.context_format = None
        self.context_decoder = None
        self.last_context_output_kind = None
        self.last_context_receipt = None
        self._pending_context_response = None
        self._context_in_flight = False
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

    def context_messages(self, message):
        """Render durable dialogue plus one replaceable pulse presentation."""
        messages = [{"role": "system", "content": self.system_instruction}]
        history = [] if self.compiled_context_only else self.history
        for item in history + [{"role": "user", "content": message}]:
            item = dict(item)
            if item["role"] == "assistant" and self.context_format and self.context_decoder:
                # The native foreground emits message envelopes. Present its
                # delivered history in the same protocol without changing the
                # actual dialogue or admitting private actions as public speech.
                item["content"] = json.dumps({"message": item["content"]}, ensure_ascii=False)
            # Match adjacent-role collation explicitly so the tokenizer and
            # provider receive the same conversation, including unanswered input.
            if len(messages) > 1 and messages[-1]["role"] == item["role"]:
                messages[-1] = {"role": item["role"],
                                "content": messages[-1]["content"] + "\n\n" + item["content"]}
            else:
                messages.append(dict(item))
        return messages

    def pulse_input_allowance(self):
        if self.context_counter is None:
            raise RuntimeError("Mindscape requires the installed model's exact token counter")
        overhead = self.context_counter.count_messages(self.context_messages(""))
        headroom = 1 if self.max_output_tokens is None else int(self.max_output_tokens)
        remaining = int(self.options["num_ctx"]) - overhead - headroom
        if remaining <= 0:
            from llm.ollama_tokens import ProviderContextExceeded
            raise ProviderContextExceeded("Durable dialogue fills the selected context; explicit continuation is required")
        return remaining

    def covered_source_hashes(self):
        """Canonical dialogue already present in the provider request."""
        import hashlib
        if self.compiled_context_only:
            return set()
        values = set()
        for item in self.history:
            text = item["content"]
            values.add(hashlib.sha256(text.encode()).hexdigest())
            if item["role"] == "assistant":
                values.add(hashlib.sha256(("[response] " + text).encode()).hexdigest())
        return values

    def send_context(self, message):
        """Generate from a pulse without retaining its temporary retrieval view."""
        if self.context_counter is None:
            raise RuntimeError("No exact provider context accounting configured")
        messages = self.context_messages(message)
        self.last_context_receipt = self.context_counter.check_request(messages, int(self.options["num_ctx"]))
        self._pending_context_response = None
        self._context_in_flight = True
        try:
            thought = self._send_via_package(messages) if self._use_package else self._send_via_rest(messages)
        finally:
            self._context_in_flight = False
        self.last_context_output_kind = None
        if not thought.startswith("[internal error:") and self.context_decoder is not None:
            raw = thought
            try:
                thought, self.last_context_output_kind = self.context_decoder(raw)
                self.last_context_receipt.update(raw_foreground=raw, output_kind=self.last_context_output_kind)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid private foreground envelope; no action or message delivered: {exc}") from exc
        if not thought.startswith("[internal error:"):
            self._pending_context_response = thought
        return thought

    def finish_context(self, current_messages, response, *, delivered):
        """Retain received dialogue and only actually delivered assistant prose.

        Private continuation has its own pulse slot. Retrieved text, transient
        telemetry and undelivered drafts do not become earlier user utterances.
        """
        if self._pending_context_response != response:
            raise ValueError("No matching generated pulse to commit")
        self.history.extend({"role": "user", "content": message} for message in current_messages)
        if delivered:
            self.history.append({"role": "assistant", "content": response})
        self._pending_context_response = None

    def _check_context_response(self, prompt_tokens, output_tokens, done_reason):
        if not self._context_in_flight:
            return
        from llm.ollama_tokens import ProviderContextExceeded
        self.last_context_receipt.update(
            evaluated_prompt_tokens=prompt_tokens, generated_tokens=output_tokens, done_reason=done_reason)
        if prompt_tokens != self.last_context_receipt["prompt_tokens"]:
            raise ProviderContextExceeded(
                f"Provider evaluated {prompt_tokens} input tokens, but the complete request "
                f"contains {self.last_context_receipt['prompt_tokens']}; response withheld")
        if done_reason == "length":
            raise ProviderContextExceeded("Generation reached the provider context/output boundary; incomplete response withheld")

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
                        format=self.context_format if self._context_in_flight else None,
                        think=False,  # Disable thinking for fast pulses
                    )
                    break
                except Exception as exc:
                    if self._context_in_flight:
                        raise
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
            self._check_context_response(prompt_eval_count, eval_count, getattr(response, "done_reason", None))
            self._last_token_count = eval_count + prompt_eval_count
            logger.debug(
                f"Ollama response: {eval_count} tokens in {total_s:.1f}s"
            )
            return thought

        except Exception as e:
            if self._context_in_flight:
                raise
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
                            **({"format": self.context_format} if self._context_in_flight and self.context_format else {}),
                            "think": False,
                            "keep_alive": self.keep_alive,
                        },
                        timeout=None,  # No timeout — wait as long as needed
                    )
                    response.raise_for_status()
                    break
                except Exception as exc:
                    if self._context_in_flight:
                        raise
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
            self._check_context_response(prompt_eval_count, eval_count, data.get("done_reason"))
            self._last_token_count = eval_count + prompt_eval_count
            if eval_count:
                logger.debug(
                    f"Ollama REST response: {eval_count} tokens in {total_s:.1f}s"
                )
            return thought

        except Exception as e:
            if self._context_in_flight:
                raise
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
