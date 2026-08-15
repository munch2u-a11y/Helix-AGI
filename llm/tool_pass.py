"""Helix — Fresh-context sessions for directed tool passes.

A directed tool pass is Helix working under a task frame: the same model,
the same weights, a context window containing one toolset's manifest and
one objective. It is not another agent, and nothing about the frame is
remembered afterwards — only what was done and what came back.

Two providers need different mechanics for "fresh context":

  Ollama     — a session is an HTTP client with local history, so a pass
               gets its own session. The model stays resident in Ollama's
               server (keep_alive), so this costs nothing but a dict.

  llama.cpp  — a session owns a loaded GGUF. Reinstantiating one would
               reload gigabytes from disk, so a pass borrows the live
               session, swaps its system prompt and history, and restores
               both on close. Passes are strictly sequential — one
               generation in flight at a time — so borrowing is safe.

The llama.cpp path additionally narrows the decoding grammar to the pass's
toolset, which is the one guarantee no prompt can make: the model cannot
emit a call to a tool outside the group it was given.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("helix.llm.tool_pass")


class ToolPass:
    """One directed pass. Subclasses supply the provider mechanics."""

    def send(self, message: str) -> str:
        raise NotImplementedError

    def scope_tools(self, names: List[str]) -> None:
        """Restrict generation to `names` where the provider supports it."""
        return None

    def close(self) -> None:
        return None

    def get_last_token_count(self) -> int:
        """Provider-reported tokens for the most recent generation, if known."""
        return 0

    def __enter__(self) -> "ToolPass":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class OllamaToolPass(ToolPass):
    """A pass with its own Ollama session.

    Ollama exposes no logit hook, so the toolset restriction is carried by
    the manifest in the prompt and enforced after the fact by the runner,
    which refuses to dispatch a name outside the group.
    """

    def __init__(self, config, system_prompt: str):
        from llm.providers.ollama_provider import OllamaSession

        options = dict(getattr(config, "options", None) or {})
        self._session = OllamaSession(
            model=config.model,
            system_instruction=system_prompt,
            temperature=getattr(config, "temperature", 0.6),
            max_output_tokens=getattr(config, "max_output_tokens", 1024),
            options=options,
        )

    def send(self, message: str) -> str:
        return self._session.send_message(message)

    def get_last_token_count(self) -> int:
        getter = getattr(self._session, "get_last_token_count", None)
        return int(getter() or 0) if getter else 0

    def close(self) -> None:
        self._session = None


class LlamaCppToolPass(ToolPass):
    """A pass that borrows an already-loaded llama.cpp session."""

    def __init__(self, session, system_prompt: str):
        self._session = session
        self._saved_system = getattr(session, "system_instruction", "")
        self._saved_history = list(getattr(session, "history", []) or [])
        self._saved_auto = getattr(session, "auto_execute_tools", None)

        session.system_instruction = system_prompt
        session.history = []
        # The runner drives the tool loop one call at a time; the session
        # must not also execute what it parses.
        if self._saved_auto is not None:
            session.auto_execute_tools = False

    def send(self, message: str) -> str:
        return self._session.send_message(message)

    def get_last_token_count(self) -> int:
        getter = getattr(self._session, "get_last_token_count", None)
        return int(getter() or 0) if getter else 0

    def scope_tools(self, names: List[str]) -> None:
        setter = getattr(self._session, "set_allowed_tools", None)
        if setter is None:
            return
        try:
            setter(names)
        except Exception as e:
            logger.warning("Could not scope decoding grammar: %s", e)

    def close(self) -> None:
        session = self._session
        if session is None:
            return
        session.system_instruction = self._saved_system
        session.history = self._saved_history
        if self._saved_auto is not None:
            session.auto_execute_tools = self._saved_auto
        # Restore the full grammar so the main window is not left narrowed
        # to whichever toolset the last pass happened to use.
        restore = getattr(session, "scope_to_toolset", None)
        if restore is not None:
            try:
                restore(None)
            except Exception as e:
                logger.warning("Could not restore decoding grammar: %s", e)
        self._session = None


def create_pass_factory(
    provider_config,
    conscious_session=None,
) -> Optional[Callable[[str], ToolPass]]:
    """Build a factory that opens a fresh-context pass for this provider.

    Returns None when the provider has no local pass mechanism — API
    providers use their own native tool calling and never take this route.
    """
    provider_type = getattr(provider_config, "provider_type", "")

    if provider_type == "ollama":
        return lambda system_prompt: OllamaToolPass(provider_config, system_prompt)

    if provider_type == "llama_cpp":
        if conscious_session is None:
            logger.warning(
                "llama_cpp tool passes need the live session to borrow; "
                "none was supplied."
            )
            return None
        return lambda system_prompt: LlamaCppToolPass(
            conscious_session, system_prompt,
        )

    return None


def supports_grammar_constraint(provider_config) -> bool:
    """True when this provider can enforce the tool grammar at the logits."""
    return getattr(provider_config, "provider_type", "") == "llama_cpp"
