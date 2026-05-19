"""
Helix — Post-Pulse Hook System

Lightweight hooks that run after each pulse completes, without blocking
the next pulse. These are the "subconscious" background processes that
observe patterns, update state, and maintain cognitive hygiene.

Inspired by Claude Code's post-sampling hooks (backgroundHousekeeping.ts,
skillImprovement.ts) — but simpler, because Helix is single-threaded
with background tasks, not event-driven.

Each hook receives a PostPulseHookContext containing:
  - thought: the model's output from this pulse
  - events: incoming events that triggered the pulse
  - pulse_count: monotonic pulse counter
  - tool_calls: list of tool call dicts from this pulse
  - spatial_state: current 8D spatial state snapshot
  - active_toolsets: set of currently enabled toolset names
  - memory_id: short-term memory ID of the stored thought (provenance)
  - lagrangian_before: sentinel snapshot BEFORE the pulse
  - lagrangian_after: sentinel snapshot AFTER the pulse

The lagrangian_before/after pair enables hooks to compute stability
deltas — measuring the perturbation a pulse caused, not just the
absolute atmospheric state.

Hooks MUST be non-blocking. If a hook needs to do LLM work, it should
queue it for the next idle period (similar to the dream engine).

Usage:
    from core.post_pulse_hooks import register_hook, run_hooks

    # Registration (at startup in main.py):
    def my_hook(ctx: PostPulseHookContext):
        if ctx.tool_calls:
            logger.info("Tools used: %s", [tc['name'] for tc in ctx.tool_calls])

    register_hook(my_hook, name="tool_logger")

    # Execution (at end of _pulse() in pulse_loop.py):
    run_hooks(hook_context)
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("helix.core.post_pulse_hooks")


class PostPulseHookContext:
    """Read-only context snapshot passed to each hook.

    Contains everything a background hook needs to observe the
    current pulse's results without modifying the main loop state.

    The lagrangian_before/after pair captures the sentinel state
    delta across the pulse, enabling hooks to measure the stability
    perturbation a pulse caused (not the noisy absolute state).
    """

    __slots__ = (
        "thought", "events", "pulse_count", "tool_calls",
        "spatial_state", "active_toolsets",
        "memory_id", "lagrangian_before", "lagrangian_after",
        "injected_belief_ids",
    )

    def __init__(
        self,
        thought: str = "",
        events: Optional[List[str]] = None,
        pulse_count: int = 0,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        spatial_state: Optional[Dict[str, Any]] = None,
        active_toolsets: Optional[Set[str]] = None,
        memory_id: int = -1,
        lagrangian_before: Optional[Dict[str, Any]] = None,
        lagrangian_after: Optional[Dict[str, Any]] = None,
        injected_belief_ids: Optional[List[str]] = None,
    ):
        self.thought = thought
        self.events = events or []
        self.pulse_count = pulse_count
        self.tool_calls = tool_calls or []
        self.spatial_state = spatial_state or {}
        self.active_toolsets = active_toolsets or {"core"}
        self.memory_id = memory_id
        self.lagrangian_before = lagrangian_before or {}
        self.lagrangian_after = lagrangian_after or {}
        self.injected_belief_ids = injected_belief_ids or []


# Type alias for hook functions
PostPulseHook = Callable[[PostPulseHookContext], None]

# Registry — hooks run in registration order
_hooks: List[PostPulseHook] = []
_hook_names: List[str] = []
_lock = threading.Lock()


def register_hook(hook: PostPulseHook, name: str = ""):
    """Register a post-pulse hook. Hooks run in registration order.

    Args:
        hook: Callable that receives a PostPulseHookContext.
              Must be non-blocking.
        name: Human-readable name for logging. Defaults to the
              function's __name__.
    """
    display_name = name or getattr(hook, "__name__", "anonymous")
    with _lock:
        _hooks.append(hook)
        _hook_names.append(display_name)
    logger.info("Post-pulse hook registered: %s", display_name)


def run_hooks(context: PostPulseHookContext):
    """Run all registered hooks. Exceptions are logged, never propagated.

    Each hook failure is isolated — a crash in one hook does not prevent
    subsequent hooks from running. This is critical for system stability:
    the pulse loop must never crash due to a hook error.
    """
    with _lock:
        hooks = list(zip(_hooks, _hook_names))

    for hook, name in hooks:
        try:
            hook(context)
        except Exception as e:
            logger.warning(
                "Post-pulse hook '%s' failed: %s", name, e,
                exc_info=True,
            )


def get_registered_hooks() -> List[str]:
    """Return names of all registered hooks (for diagnostics)."""
    with _lock:
        return list(_hook_names)
