"""
Helix — llama-cpp-python Chat Session Provider

Direct GGUF model loading with Vulkan GPU offload.
Falls back to CPU if Vulkan isn't available.

Note: As of llama-cpp-python 0.3.21, it can't load qwen35 or gemma4
architectures. This provider exists for future compatibility when
the library catches up.

Extracted from pulse_loop.py into the provider abstraction layer.
"""

import logging
from typing import Optional, Dict, Any, List

from llm.providers.base import ChatSession

logger = logging.getLogger("helix.llm.providers.llama_cpp")


class LlamaCppSession(ChatSession):
    """Chat session backed by llama-cpp-python with Vulkan GPU offload.

    Loads the GGUF model directly. Auto-offloads layers to local GPU
    via Vulkan backend. No hardcoded timeout.
    """

    def __init__(
        self,
        model_path: str,
        system_instruction: str,
        n_ctx: int = 128_000,
        n_gpu_layers: int = -1,
        temperature: float = 0.8,
        max_output_tokens: int = 2048,
    ):
        from llama_cpp import Llama

        self.system_instruction = system_instruction
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.history: List[Dict[str, str]] = []

        logger.info(
            f"Loading model via llama.cpp "
            f"(n_ctx={n_ctx}, n_gpu_layers={n_gpu_layers})..."
        )

        self._llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )

        logger.info("llama.cpp model loaded successfully")

    def send_message(self, message: str) -> str:
        """Send a message and return the model's response."""
        self.history.append({"role": "user", "content": message})

        messages = [
            {"role": "system", "content": self.system_instruction},
        ] + self.history

        try:
            response = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=self.max_output_tokens,
                temperature=self.temperature,
                top_p=0.95,
            )

            thought = response["choices"][0]["message"]["content"] or ""

            # Log performance
            usage = response.get("usage", {})
            logger.debug(
                f"llama.cpp response: "
                f"{usage.get('completion_tokens', '?')} tokens generated, "
                f"{usage.get('prompt_tokens', '?')} prompt tokens"
            )

        except Exception as e:
            logger.error(f"llama.cpp call failed: {e}")
            thought = f"[internal error: LLM call failed — {str(e)[:100]}]"

        self.history.append({"role": "assistant", "content": thought})
        return thought

    def get_history_size(self) -> int:
        """Return approximate character count of the full session."""
        total = len(self.system_instruction)
        for msg in self.history:
            total += len(msg.get("content", ""))
        return total
