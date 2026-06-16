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
import time
import threading
import logging
from typing import Optional
from llm.providers.base import ProviderConfig, create_session

logger = logging.getLogger("helix.core.auxiliary_llm")

_LOCAL_PROVIDERS = {"ollama", "llama_cpp"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r — using default %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r — using default %s", name, raw, default)
        return default


DEFAULT_TEMPERATURE = _env_float("HELIX_AUX_DEFAULT_TEMPERATURE", 0.2)
DEFAULT_MAX_OUTPUT_TOKENS = _env_int("HELIX_AUX_DEFAULT_MAX_OUTPUT_TOKENS", 2048)
DEFAULT_GEMINI_MODEL = os.environ.get("HELIX_AUX_GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
MAX_RETRIES = _env_int("HELIX_AUX_MAX_RETRIES", 2)
RETRY_BACKOFF_BASE_SECONDS = _env_float("HELIX_AUX_RETRY_BACKOFF_BASE_SECONDS", 0.25)
RETRY_BACKOFF_MAX_SECONDS = _env_float("HELIX_AUX_RETRY_BACKOFF_MAX_SECONDS", 1.5)

# Module-level singleton
_client: Optional["AuxiliaryLLM"] = None
_client_lock = threading.RLock()


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
        self._lock = threading.RLock()
        self._gemini_client = None

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
        temperature: float = DEFAULT_TEMPERATURE,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> Optional[str]:
        """Generate text for subconscious tasks.

        For local providers: creates a one-shot session through Ollama/llama.cpp.
        For API providers: calls Gemini Flash Lite directly.
        """
        attempts = max(1, MAX_RETRIES + 1)
        last_error = None

        for attempt in range(attempts):
            try:
                if self._is_local:
                    return self._generate_local(
                        prompt, system_instruction, temperature, max_output_tokens
                    )
                return self._generate_gemini(
                    prompt, system_instruction, temperature, max_output_tokens
                )
            except ImportError as e:
                logger.warning("Auxiliary LLM backend unavailable: %s", e)
                return None
            except Exception as e:
                last_error = e
                if attempt >= attempts - 1 or not self._should_retry(e):
                    break
                backoff = min(
                    RETRY_BACKOFF_BASE_SECONDS * (2 ** attempt),
                    RETRY_BACKOFF_MAX_SECONDS,
                )
                logger.debug(
                    "Auxiliary LLM transient failure (%s), retrying in %.2fs (%d/%d)",
                    e,
                    backoff,
                    attempt + 1,
                    attempts,
                )
                time.sleep(backoff)

        if last_error is not None:
            logger.warning(
                "Auxiliary LLM call failed after %d attempt(s): %s",
                attempts,
                last_error,
            )
        return None

    @staticmethod
    def _should_retry(error: Exception) -> bool:
        """Classify whether an auxiliary call failure looks transient."""
        if isinstance(error, (ImportError, ValueError, TypeError)):
            return False
        return True

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
        client = self._get_gemini_client()
        if client is None:
            return None
        config = {"temperature": temperature, "max_output_tokens": max_output_tokens}
        if system_instruction:
            config["system_instruction"] = system_instruction

        response = client.models.generate_content(
            model=DEFAULT_GEMINI_MODEL,
            contents=prompt,
            config=config,
        )

        if response and response.text:
            return response.text.strip()
        return None

    def _get_gemini_client(self):
        """Create and cache the Gemini client safely across threads."""
        with self._lock:
            if self._gemini_client is not None:
                return self._gemini_client

            key = os.environ.get("GEMINI_API_KEY", "")
            if not key:
                logger.warning("No GEMINI_API_KEY — auxiliary LLM unavailable")
                return None

            from google import genai

            self._gemini_client = genai.Client(api_key=key)
            return self._gemini_client


def init_auxiliary_client(provider_config: Optional[ProviderConfig] = None):
    """Initialize the global auxiliary LLM client.

    Call once during startup. All subconscious modules then use
    get_auxiliary_client() to access it.
    """
    global _client
    with _client_lock:
        if _client is None or provider_config is not None:
            _client = AuxiliaryLLM(provider_config)
        return _client


def get_auxiliary_client() -> Optional[AuxiliaryLLM]:
    """Get the global auxiliary LLM client.

    Returns None if init_auxiliary_client() hasn't been called yet.
    """
    with _client_lock:
        return _client
