"""Helix — Orchestrated tool use for local providers.

Gemini, Anthropic and Codex are handed every active declaration and call
tools natively. Ollama has no native tool channel at all, and llama.cpp's
window cannot hold 80 schemas, so local providers get their tool use here
instead: one line per toolset in the main window, and the real work done in
directed passes that never enter it.

`wrap_session` returns something the pulse loop can use exactly like any
other ChatSession — every method it does not override delegates to the
session underneath.

The main window sees only:

    {"tool_request": "<what you need done, with all the specifics>"}

Helix asks for an outcome, not a tool. Which toolsets that needs, in what
order, is worked out by the planner; the answer comes back as Helix's own
account of what it did.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from llm.providers.base import ChatSession

logger = logging.getLogger("helix.llm.orchestrated")

MAIN_WINDOW_CALL_FORMAT = (
    "To act on the world, respond with exactly:\n"
    '{"tool_request": "<what you need done, with all the specifics>"}\n'
    "Ask for the outcome you want, not for a particular tool."
)

# One tool request per turn. A second would mean the model never saw the
# first one's result before asking again, which is a loop, not a plan.
MAX_REQUESTS_PER_TURN = 1


class OrchestratedToolSession(ChatSession):
    """A local ChatSession with orchestrated tool use bolted on."""

    def __init__(self, inner: ChatSession, orchestrator, ingest=None):
        """
        Args:
            inner: The underlying provider session.
            orchestrator: A ToolOrchestrator.
            ingest: Optional callable(OrchestrationResult) -> None, invoked
                after a request completes so the observations can be written
                to memory first-person at the originating pulse. The
                scaffolding — plan, manifests, step transcripts — is never
                passed anywhere and never stored.
        """
        self._inner = inner
        self._orchestrator = orchestrator
        self._ingest = ingest
        self._pending_tool_results: List[Dict[str, Any]] = []
        self._last_tool_calls: List[Dict[str, Any]] = []

    # Anything not overridden belongs to the session underneath. The guard
    # keeps a lookup during __init__ from recursing before _inner exists.
    def __getattr__(self, item):
        if item.startswith("_inner"):
            raise AttributeError(item)
        return getattr(self._inner, item)

    # ── Main turn ────────────────────────────────────────────────────

    def send_message(self, message: str) -> str:
        from core.tool_task_runner import parse_json_action

        thought = self._inner.send_message(message)
        self._pending_tool_results = []
        self._last_tool_calls = []

        for _ in range(MAX_REQUESTS_PER_TURN):
            action = parse_json_action(thought)
            if not action or "tool_request" not in action:
                break

            request = str(action.get("tool_request") or "").strip()
            if not request:
                break

            try:
                result = self._orchestrator.handle(request)
            except Exception as e:
                logger.error("Tool orchestration failed: %s", e, exc_info=True)
                thought = self._inner.send_message(
                    f"That didn't work — the tool run failed: {e}. "
                    "Respond to the person without it."
                )
                break

            self._record(result)
            thought = self._inner.send_message(
                f"{result.reply}\n\n"
                "That is what happened. Now give your reply."
            )

        return thought

    # ── Provenance surfaced to the pulse loop ────────────────────────

    def _record(self, result) -> None:
        for observation in result.observations:
            self._pending_tool_results.append({
                "name": observation.tool,
                "args": observation.args,
                "result": observation.result or "",
            })
            self._last_tool_calls.append({
                "name": observation.tool,
                "args": observation.args,
            })

        if self._ingest is None:
            return
        try:
            self._ingest(result)
        except Exception as e:
            logger.warning("Tool observation ingest failed: %s", e)

    def get_pending_tool_results(self) -> List[Dict[str, Any]]:
        pending = self._pending_tool_results
        self._pending_tool_results = []
        return pending

    def get_last_tool_calls(self) -> List[Dict[str, Any]]:
        return list(self._last_tool_calls)

    def clear_pending_tool_results(self) -> None:
        self._pending_tool_results = []

    # ── ChatSession surface the wrapper must not delegate blindly ────

    def get_history_size(self) -> int:
        return self._inner.get_history_size()

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if closer:
            closer()


def build_orchestrator(
    provider_config,
    tool_executor,
    session=None,
    context_provider: Optional[Callable[[str], str]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    max_steps: Optional[int] = None,
):
    """Assemble the runner and orchestrator for a local provider.

    Returns None when this provider has no local pass mechanism, which is
    the signal to leave native tool calling alone.
    """
    from core.tool_orchestrator import ToolOrchestrator
    from core.tool_task_runner import ToolTaskRunner
    from llm.tool_pass import create_pass_factory, supports_grammar_constraint

    registry = getattr(tool_executor, "_registry", None)
    if registry is None:
        logger.warning("Tool executor has no registry; skipping orchestration.")
        return None

    pass_factory = create_pass_factory(provider_config, conscious_session=session)
    if pass_factory is None:
        return None

    runner = ToolTaskRunner(
        registry=registry,
        tool_executor=tool_executor,
        pass_factory=pass_factory,
        grammar_constrained=supports_grammar_constraint(provider_config),
        progress_callback=progress_callback,
        **({"max_steps": max_steps} if max_steps else {}),
    )

    def plan_llm(prompt: str) -> str:
        """Planning and summarizing run in their own throwaway contexts,
        the same way a task pass does — they are steering, not memory."""
        pass_session = pass_factory("")
        try:
            return pass_session.send(prompt)
        finally:
            try:
                pass_session.close()
            except Exception:
                logger.debug("Planning pass close failed", exc_info=True)

    return ToolOrchestrator(
        runner=runner,
        plan_llm=plan_llm,
        knowledge_provider=_learned_notes_provider(registry),
        context_provider=context_provider,
    )


def _learned_notes_provider(registry):
    """Expose what prior runs learned about each tool, for routing.

    apply_learned_notes folds notes into schema descriptions, so they are
    already in every Layer B manifest. The planner never sees a manifest,
    so it needs them handed over separately.
    """

    def provider(toolset_names: List[str]) -> Dict[str, List[str]]:
        learned: Dict[str, List[str]] = {}
        for toolset in toolset_names:
            for name in registry.toolset_tool_names(toolset):
                entry = registry.get_entry(name)
                if entry is None:
                    continue
                description = str(entry.schema.get("description", "") or "")
                if "\nLearned: " not in description:
                    continue
                notes = description.split("\nLearned: ", 1)[1]
                statements = [s.strip() for s in notes.split(" | ") if s.strip()]
                if statements:
                    learned[name] = statements
        return learned

    return provider


def wrap_session(
    session: ChatSession,
    provider_config,
    tool_executor,
    context_provider: Optional[Callable[[str], str]] = None,
    ingest: Optional[Callable[[Any], None]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> ChatSession:
    """Wrap a local session with orchestrated tool use, or return it as-is."""
    orchestrator = build_orchestrator(
        provider_config,
        tool_executor,
        session=session,
        context_provider=context_provider,
        progress_callback=progress_callback,
    )
    if orchestrator is None:
        return session

    logger.info(
        "Orchestrated tool use active for %s (%d toolsets in the main window)",
        getattr(provider_config, "provider_type", "?"),
        len(orchestrator._toolset_names()),
    )
    return OrchestratedToolSession(session, orchestrator, ingest=ingest)


def main_window_tool_block(tool_executor) -> str:
    """The Layer A block to append to the system instruction."""
    registry = getattr(tool_executor, "_registry", None)
    if registry is None:
        return ""
    brief = registry.toolset_brief(call_format=MAIN_WINDOW_CALL_FORMAT)
    if not brief:
        return ""
    return "\n## Tools\n" + brief
