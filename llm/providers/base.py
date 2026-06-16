"""
Helix — Base Chat Session Interface

All LLM providers implement this interface. The pulse loop only knows
about ChatSession — it never imports provider-specific code directly.

To add a new provider:
    1. Create a new file in llm/providers/
    2. Implement a class that extends ChatSession
    3. Register it in get_provider() below
"""

import logging
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod

logger = logging.getLogger("helix.llm.providers.base")


class ChatSession(ABC):
    """Abstract chat session — the only interface the pulse loop sees."""

    @abstractmethod
    def send_message(self, message: str) -> str:
        """Send a user-turn message and return the assistant response."""
        ...

    @abstractmethod
    def get_history_size(self) -> int:
        """Return approximate character count of all messages in the session."""
        ...

    def clear_pending_tool_results(self) -> None:
        """Clear any pending/queued tool responses/results in the session."""
        pass



class ProviderConfig:
    """Configuration for a specific LLM provider.

    Each provider's config is a simple dataclass. New providers just
    add their own fields. The pulse loop reads provider-agnostic
    fields (model, context_window) and passes the rest through.
    """

    def __init__(
        self,
        provider_type: str,          # "ollama", "llama_cpp", "gemini", "anthropic"
        model: str,                  # Model name or path
        context_window: int = 128_000,
        temperature: float = 0.8,
        max_output_tokens: int = 2048,
        options: Optional[Dict[str, Any]] = None,
    ):
        self.provider_type = provider_type
        self.model = model
        self.context_window = context_window
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.options = options or {}


def create_session(
    config: ProviderConfig,
    system_instruction: str,
    tool_declarations: list = None,
    tool_executor=None,
    preconscious=None,
) -> ChatSession:
    """Factory: create a ChatSession from a ProviderConfig.

    This is the ONLY place provider-specific imports happen.
    Adding a new provider = adding an elif branch here.

    Args:
        config: Provider configuration.
        system_instruction: System prompt text.
        tool_declarations: Optional Gemini FunctionDeclaration dicts (Gemini only).
        tool_executor: Optional ToolExecutor for function call handling (Gemini only).
        preconscious: Optional Preconscious for belief enrichment on tool returns.
    """
    if config.provider_type == "gemini":
        from llm.providers.gemini_provider import GeminiSession
        return GeminiSession(
            model=config.model,
            system_instruction=system_instruction,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
            tool_declarations=tool_declarations,
            tool_executor=tool_executor,
            preconscious=preconscious,
        )

    elif config.provider_type == "ollama":
        from llm.providers.ollama_provider import OllamaSession
        return OllamaSession(
            model=config.model,
            system_instruction=system_instruction,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
            options=config.options,
        )

    elif config.provider_type == "anthropic":
        from llm.providers.anthropic_provider import AnthropicSession
        return AnthropicSession(
            model=config.model,
            system_instruction=system_instruction,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
            tool_declarations=tool_declarations,
            tool_executor=tool_executor,
            preconscious=preconscious,
        )

    elif config.provider_type == "llama_cpp":
        from llm.providers.llama_cpp_provider import LlamaCppSession
        return LlamaCppSession(
            model_path=config.model,
            system_instruction=system_instruction,
            n_ctx=config.context_window,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
            n_gpu_layers=config.options.get("n_gpu_layers", -1),
        )

    else:
        raise ValueError(
            f"Unknown provider type: {config.provider_type}. "
            f"Supported: gemini, anthropic, ollama, llama_cpp"
        )


def detect_available_provider() -> Optional[ProviderConfig]:
    """Auto-detect the best available LLM backend.

    Priority:
      If HELIX_PROVIDER is set, try to use that provider and HELIX_MODEL.
      Otherwise, fall back to auto-detecting in order:
      Gemini API (if key exists) > Ollama > llama.cpp > None
    """
    import os
    from pathlib import Path

    provider_pref = os.environ.get("HELIX_PROVIDER", "").lower()
    model_pref = os.environ.get("HELIX_MODEL", "").strip()

    # 1. Handle Explicit Provider Preferences
    if provider_pref == "gemini":
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            model = model_pref or "gemini-2.5-flash"
            logger.info(f"Using explicitly configured Gemini provider with model: {model}")
            return ProviderConfig(
                provider_type="gemini",
                model=model,
                context_window=1_000_000,
                temperature=0.8,
                max_output_tokens=8192,
            )
        else:
            logger.warning("HELIX_PROVIDER=gemini but GEMINI_API_KEY is missing.")

    elif provider_pref == "anthropic":
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            model = model_pref or "claude-fable-5"
            logger.info(f"Using explicitly configured Anthropic provider with model: {model}")
            return ProviderConfig(
                provider_type="anthropic",
                model=model,
                context_window=1_000_000,
                temperature=0.8,
                max_output_tokens=16384,
            )
        else:
            logger.warning("HELIX_PROVIDER=anthropic but ANTHROPIC_API_KEY is missing.")

    elif provider_pref == "ollama":
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        model = model_pref or os.environ.get("OLLAMA_MODEL", "granite4.1:8b")
        logger.info(f"Using explicitly configured Ollama provider with model: {model} at {url}")
        return ProviderConfig(
            provider_type="ollama",
            model=model,
            context_window=64_000,
            options={"num_ctx": 64_000, "url": url},
        )

    elif provider_pref == "llama_cpp":
        model = model_pref
        if model:
            if not os.path.exists(model):
                repo_models_dir = Path(__file__).parent.parent.parent / "models"
                candidate = repo_models_dir / model
                if candidate.exists():
                    model = str(candidate)
                else:
                    candidate_rel = Path("models") / model
                    if candidate_rel.exists():
                        model = str(candidate_rel)
        else:
            # Try to find a .gguf model in models/
            models_dir = Path("models")
            ggufs = list(models_dir.glob("*.gguf")) if models_dir.exists() else []
            if ggufs:
                model = str(ggufs[0])
            else:
                repo_models_dir = Path(__file__).parent.parent.parent / "models"
                repo_ggufs = list(repo_models_dir.glob("*.gguf")) if repo_models_dir.exists() else []
                if repo_ggufs:
                    model = str(repo_ggufs[0])
                else:
                    model = "/home/nemo/.ollama/models/blobs/sha256-afb54ad43a39f947407f5cabc59856348d70e072baa5c62d436332157c151bcd"
        logger.info(f"Using explicitly configured llama_cpp provider with model: {model}")
        return ProviderConfig(
            provider_type="llama_cpp",
            model=model,
            context_window=64_000,
            options={"n_gpu_layers": -1},
        )

    # 2. Auto-Detection Fallback (when no explicit provider_pref is set or it failed)
    # 2a. Gemini API
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        model = model_pref or "gemini-3-flash-preview"
        logger.info(f"Auto-detected Gemini API key — using {model}")
        return ProviderConfig(
            provider_type="gemini",
            model=model,
            context_window=1_000_000,
            temperature=0.8,
            max_output_tokens=8192,
        )

    # 2b. Ollama
    try:
        import ollama
        models = ollama.list()
        model_names = [m.model for m in models.models]

        preferred = [
            "granite4.1:8b",
            "granite4.1:3b",
        ]
        for pref in preferred:
            if pref in model_names:
                logger.info(f"Auto-detected Ollama with {pref}")
                return ProviderConfig(
                    provider_type="ollama",
                    model=pref,
                    context_window=64_000,
                    options={"num_ctx": 64_000},
                )

        if model_names:
            first = model_names[0]
            logger.info(f"Auto-detected Ollama with {first} (fallback)")
            return ProviderConfig(
                provider_type="ollama",
                model=first,
                context_window=64_000,
                options={"num_ctx": 64_000},
            )
    except Exception:
        pass

    # 2c. llama-cpp-python
    try:
        import llama_cpp
        model_path = (
            "/home/nemo/.ollama/models/blobs/"
            "sha256-afb54ad43a39f947407f5cabc59856348d70e072baa5c62d436332157c151bcd"
        )
        if os.path.exists(model_path):
            gpu = "Vulkan" if llama_cpp.llama_supports_gpu_offload() else "CPU"
            logger.info(f"Auto-detected llama.cpp ({gpu})")
            return ProviderConfig(
                provider_type="llama_cpp",
                model=model_path,
                context_window=64_000,
                options={"n_gpu_layers": -1},
            )
    except ImportError:
        pass

    logger.warning("No LLM backend detected")
    return None
