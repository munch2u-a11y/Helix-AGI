"""
Helix — Auxiliary LLM Client (Subconscious Session)

Provides a shared, lightweight LLM client for all subconscious tasks:
  - Context compression (summarization)
  - Belief extraction and formatting (batch_service)
  - Belief consolidation (merge/pass decisions)
  - Dream engine (curator)

When using a LOCAL provider (Ollama/llama.cpp), this runs as a SEPARATE
session from the main consciousness, so the main agent's context window
is never interrupted for subconscious work.

When using an API provider, this defaults to Gemini Flash Lite for
cost-efficiency (subconscious work doesn't need the full model).

Usage:
    from core.auxiliary_llm import get_auxiliary_client, init_auxiliary_client

    # During startup (main.py or pulse_loop init):
    init_auxiliary_client(provider_config)

    # From any subconscious module:
    client = get_auxiliary_client()
    result = client.generate("summarize this...")
"""

import os
import logging
from typing import Optional
from llm.providers.base import ProviderConfig, create_session

logger = logging.getLogger("helix.core.auxiliary_llm")

_LOCAL_PROVIDERS = {"ollama", "llama_cpp"}

# Module-level singleton
_client: Optional["AuxiliaryLLM"] = None


class AuxiliaryLLM:
    """Lightweight LLM client for subconscious tasks.

    Keeps a separate session from the main consciousness so the primary
    context window is never polluted with summarization/formatting work.
    """

    def __init__(self, provider_config: Optional[ProviderConfig] = None):
        self._provider_config = provider_config
        self._is_local = (
            provider_config is not None
            and provider_config.provider_type in _LOCAL_PROVIDERS
        )

        if self._is_local:
            logger.info(
                "Auxiliary LLM: local (%s/%s) — separate session from main",
                provider_config.provider_type,
                provider_config.model,
            )
        else:
            logger.info("Auxiliary LLM: Gemini Flash Lite (API)")

    def generate(
        self,
        prompt: str,
        system_instruction: str = "",
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> Optional[str]:
        """Generate text for subconscious tasks.

        For local providers: creates a one-shot session through Ollama/llama.cpp.
        For API providers: calls Gemini Flash Lite directly.
        """
        try:
            if self._is_local:
                return self._generate_local(
                    prompt, system_instruction, temperature, max_output_tokens
                )
            else:
                return self._generate_gemini(
                    prompt, system_instruction, temperature, max_output_tokens
                )
        except Exception as e:
            logger.warning("Auxiliary LLM call failed: %s", e)
            return None

    def _generate_local(
        self,
        prompt: str,
        system_instruction: str,
        temperature: float,
        max_output_tokens: int,
    ) -> Optional[str]:
        """Route through the local Ollama/llama.cpp provider."""
        config = ProviderConfig(
            provider_type=self._provider_config.provider_type,
            model=self._provider_config.model,
            context_window=self._provider_config.context_window,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            options=self._provider_config.options,
        )
        session = create_session(
            config=config,
            system_instruction=system_instruction or "You are a helpful assistant.",
        )
        result = session.send_message(prompt)
        if result:
            return result.strip() if isinstance(result, str) else str(result).strip()
        return None

    def _generate_gemini(
        self,
        prompt: str,
        system_instruction: str,
        temperature: float,
        max_output_tokens: int,
    ) -> Optional[str]:
        """Route through Gemini Flash Lite API."""
        from google import genai

        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            logger.warning("No GEMINI_API_KEY — auxiliary LLM unavailable")
            return None

        client = genai.Client(api_key=key)
        config = {"temperature": temperature, "max_output_tokens": max_output_tokens}
        if system_instruction:
            config["system_instruction"] = system_instruction

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
            config=config,
        )

        if response and response.text:
            return response.text.strip()
        return None


def init_auxiliary_client(provider_config: Optional[ProviderConfig] = None):
    """Initialize the global auxiliary LLM client.

    Call once during startup. All subconscious modules then use
    get_auxiliary_client() to access it.
    """
    global _client
    _client = AuxiliaryLLM(provider_config)
    return _client


def get_auxiliary_client() -> Optional[AuxiliaryLLM]:
    """Get the global auxiliary LLM client.

    Returns None if init_auxiliary_client() hasn't been called yet.
    """
    return _client
