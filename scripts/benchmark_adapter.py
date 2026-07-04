#!/usr/bin/env python3
"""
Benchmark Adapter — Abstract Interface for Cross-Agent Benchmark Compatibility

Defines the `BenchmarkAdapter` abstract base class that any autonomous agent
system must implement to run the Helix Tool-Use and Adaptive Reasoning
Benchmark.  By subclassing this adapter, agents like Hermes, OpenClaw,
Antigravity, or Codex can plug their own memory/belief/retrieval backends
into the same test scenario, mock tools, and grading criteria.

A `NullBenchmarkAdapter` is provided for agents with no persistent memory
or retrieval system — they run the benchmark using only their raw LLM
tool-use capability.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class BenchmarkAdapter(ABC):
    """Interface for plugging any autonomous agent into the benchmark.

    Implementors must provide:
    - Session management (LLM + tool dispatch)
    - Belief corpus seeding
    - Memory corpus seeding
    - Context injection / retrieval (the agent's "recall" step)
    - Context reset (for zero-shot stages)
    - Derived belief storage (benchmark stores beliefs mid-run)
    - Physics stepping (optional — no-op for agents without attention models)
    """

    # ── Session ──────────────────────────────────────────────────────

    @abstractmethod
    def create_session(
        self,
        system_instruction: str,
        tool_declarations: List[Dict],
        executor: Any,
    ) -> Any:
        """Create and return a chat session object.

        The returned session must implement:
            - send_message(msg: str) -> str
            - get_last_tool_calls() -> list[dict] | None
            - get_pending_tool_results() -> list[dict]
            - clear_pending_tool_results() -> None
        """

    # ── Seeding ──────────────────────────────────────────────────────

    @abstractmethod
    def seed_beliefs(self, beliefs_dict: Dict[str, list]) -> None:
        """Write the belief corpus into the agent's knowledge store.

        ``beliefs_dict`` maps category names (e.g. 'premises', 'skills')
        to lists of belief dicts.
        """

    @abstractmethod
    def seed_memories(self, memories_list: List[Dict]) -> None:
        """Store the memory corpus in the agent's memory system.

        Each memory dict has keys: content, memory_type, source,
        importance, tags, lagrangian_snapshot.
        """

    # ── Context Injection / Retrieval ────────────────────────────────

    @abstractmethod
    def inject_context(
        self,
        previous_thought: str,
        events: List[str],
        trigger_type: str,
    ) -> Tuple[str, list, Any]:
        """Run the agent's context injection / retrieval step.

        Returns:
            (context_string, surfaced_ids, extra)
            - context_string: text to prepend to the next pulse message
            - surfaced_ids: list of belief/memory IDs that were recalled
            - extra: adapter-specific metadata (may be None)
        """

    @abstractmethod
    def reset_context(self) -> None:
        """Reset short-term / attention state for zero-shot stages.

        Should clear any cached context, attention trails, and belief
        caches so the agent starts the next stage with no short-term
        memory of previous stages.
        """

    # ── Belief Management ────────────────────────────────────────────

    @abstractmethod
    def store_belief(
        self,
        content: str,
        category: str = "propositions",
        source: str = "benchmark_stage",
        mass: float = 1.5,
        confidence: float = 1.0,
    ) -> str:
        """Store a derived belief during the benchmark.

        Returns the belief ID assigned by the store.
        """

    # ── Physics / Attention (optional) ───────────────────────────────

    def step_physics(self, thought_text: str, incoming_text: str) -> None:
        """Advance any attention / physics model.

        Default is a no-op.  Override if your agent has a spatial or
        attention model that should be updated between stages.
        """

    # ── Bootstrap (optional) ─────────────────────────────────────────

    def bootstrap(self) -> None:
        """Run any one-time bootstrap after seeding beliefs and memories.

        Default is a no-op.  Override if your agent needs to build
        indexes, embed beliefs, or compute initial positions.
        """

    # ── Teardown (optional) ──────────────────────────────────────────

    def teardown(self) -> None:
        """Clean up any resources after the iteration completes.

        Default is a no-op.  Override to close temp directories, DB
        connections, etc.
        """


class NullBenchmarkAdapter(BenchmarkAdapter):
    """Minimal adapter for agents with no persistent memory or retrieval.

    Uses only the LLM's raw tool-use capability.  Context injection
    returns empty strings, belief storage is a no-op, and physics
    stepping does nothing.  This is useful for establishing a baseline
    comparison against agents that have full retrieval systems.

    To use, provide a ``session_factory`` callable that takes
    (system_instruction, tool_declarations, executor) and returns a
    session object.
    """

    def __init__(self, session_factory):
        """
        Args:
            session_factory: Callable(system_instruction, tool_declarations, executor) -> session
        """
        self._session_factory = session_factory
        self._belief_counter = 0

    def create_session(self, system_instruction, tool_declarations, executor):
        return self._session_factory(system_instruction, tool_declarations, executor)

    def seed_beliefs(self, beliefs_dict):
        pass  # No-op: raw LLM has no belief store

    def seed_memories(self, memories_list):
        pass  # No-op: raw LLM has no persistent memory

    def inject_context(self, previous_thought, events, trigger_type):
        return ("", [], None)  # No retrieval — agent gets only pulse events

    def reset_context(self):
        pass  # Nothing to reset

    def store_belief(self, content, category="propositions", source="benchmark_stage",
                     mass=1.5, confidence=1.0):
        self._belief_counter += 1
        return f"null_belief_{self._belief_counter}"
