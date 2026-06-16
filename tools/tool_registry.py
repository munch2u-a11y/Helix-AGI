"""
Helix — Tool Registry (Dynamic Registration)

Central registry that collects tool schemas, handlers, and availability
checks. Replaces the static _FC_DISPATCH dict and TOOL_DECLARATIONS list.

Features:
  - register() with check_fn for runtime availability gating
  - TTL-cached check_fn results (30s) to avoid re-probing external state
  - Thread-safe with generation counter for cache invalidation
  - dispatch() for centralized tool execution
  - get_declarations() returns only available tools for the active toolsets

Usage:
    from tools.tool_registry import registry

    # Registration (at module level in each tool file):
    registry.register(
        name="github_search",
        toolset="github",
        schema={...},
        handler=my_handler_fn,
        check_fn=lambda: bool(os.environ.get("GITHUB_TOKEN")),
        requires_env=["GITHUB_TOKEN"],
    )

    # Retrieval (from pulse_loop):
    declarations = registry.get_declarations(active_toolsets={"core", "github"})

    # Dispatch (from tool_executor):
    result = registry.dispatch("github_search", {"query": "helix"})
"""

import json
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("helix.tools.registry")


# ── TTL Cache for check_fn ───────────────────────────────────────────

_CHECK_FN_TTL_SECONDS = 30.0
_check_fn_cache: Dict[Callable, tuple] = {}  # fn -> (timestamp, result)
_check_fn_lock = threading.Lock()


def _check_fn_cached(fn: Callable) -> bool:
    """Return bool(fn()), TTL-cached. Swallows exceptions as False."""
    now = time.monotonic()
    with _check_fn_lock:
        cached = _check_fn_cache.get(fn)
        if cached is not None:
            ts, value = cached
            if now - ts < _CHECK_FN_TTL_SECONDS:
                return value
    try:
        value = bool(fn())
    except Exception:
        value = False
    with _check_fn_lock:
        _check_fn_cache[fn] = (now, value)
    return value


def invalidate_check_cache():
    """Drop all cached check_fn results. Call after config changes."""
    with _check_fn_lock:
        _check_fn_cache.clear()


# ── Tool Entry ───────────────────────────────────────────────────────

# Focus type constants for preconscious injection budget
FOCUS_TYPE_FOCUS = "focus"      # Narrowing tools (terminal, write_file, search)
FOCUS_TYPE_INTAKE = "intake"    # Info-reading tools (email_read, drive_read)
FOCUS_TYPE_NEUTRAL = "neutral"  # Default — no effect on focus budget


class ToolEntry:
    """Metadata for a single registered tool."""

    __slots__ = (
        "name", "toolset", "schema", "handler", "check_fn",
        "requires_env", "description", "focus_type",
    )

    def __init__(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
        requires_env: Optional[List[str]] = None,
        description: str = "",
        focus_type: str = FOCUS_TYPE_NEUTRAL,
    ):
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.check_fn = check_fn
        self.requires_env = requires_env or []
        self.description = description or schema.get("description", "")
        self.focus_type = focus_type


# ── Tool Registry ────────────────────────────────────────────────────

class ToolRegistry:
    """Thread-safe registry for tool schemas, handlers, and availability checks.

    Provides:
      - register()/deregister() for dynamic tool management
      - check_fn with TTL caching for availability gating
      - get_declarations() that filters by active toolsets + check_fn
      - dispatch() for centralized tool execution
      - Generation counter for cache invalidation
    """

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._toolset_checks: Dict[str, Callable] = {}
        self._toolset_descriptions: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._generation: int = 0

    @property
    def generation(self) -> int:
        """Monotonic counter bumped on every mutation."""
        return self._generation

    # ── Registration ─────────────────────────────────────────────────

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
        requires_env: Optional[List[str]] = None,
        description: str = "",
        focus_type: str = FOCUS_TYPE_NEUTRAL,
    ):
        """Register a tool with its schema, handler, and optional check.

        Args:
            name: Tool name (must match the function_call name).
            toolset: Toolset this tool belongs to (e.g., "core", "github").
            schema: Gemini FunctionDeclaration dict with name, description,
                    parameters.
            handler: Callable(args: dict) -> str that executes the tool.
            check_fn: Optional callable that returns True if the tool's
                      requirements are met (e.g., API key exists, service
                      is running). Results are TTL-cached for 30s.
            requires_env: List of env var names required (informational).
            description: Human-readable description for list_toolsets.
            focus_type: One of 'focus', 'intake', or 'neutral'. Controls
                        how this tool affects the preconscious injection
                        budget (focus narrows it, intake keeps it wide).
        """
        with self._lock:
            existing = self._tools.get(name)
            if existing and existing.toolset != toolset:
                logger.warning(
                    "Tool '%s' (toolset '%s') shadowing existing from '%s'",
                    name, toolset, existing.toolset,
                )
            self._tools[name] = ToolEntry(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env,
                description=description,
                focus_type=focus_type,
            )
            # Store the first check_fn we see for a toolset as the
            # toolset-level availability check
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn
            self._generation += 1

    def register_toolset_description(self, toolset: str, description: str):
        """Set a human-readable description for a toolset."""
        with self._lock:
            self._toolset_descriptions[toolset] = description

    def deregister(self, name: str):
        """Remove a tool from the registry."""
        with self._lock:
            entry = self._tools.pop(name, None)
            if entry is None:
                return
            # Clean up toolset check if this was the last tool in that toolset
            toolset_still_exists = any(
                e.toolset == entry.toolset for e in self._tools.values()
            )
            if not toolset_still_exists:
                self._toolset_checks.pop(entry.toolset, None)
            self._generation += 1
        logger.debug("Deregistered tool: %s", name)

    def register_batch(
        self,
        toolset: str,
        tools: List[dict],
        handlers: Dict[str, Callable],
        check_fn: Optional[Callable] = None,
        requires_env: Optional[List[str]] = None,
        description: str = "",
        focus_types: Optional[Dict[str, str]] = None,
    ):
        """Register a batch of tools for a toolset at once.

        Convenience method for migrating existing TOOL_DECLARATIONS + _FC_DISPATCH.

        Args:
            toolset: Toolset name.
            tools: List of FunctionDeclaration schema dicts.
            handlers: Dict mapping tool name -> handler callable.
            check_fn: Shared availability check for all tools in this batch.
            requires_env: Shared env var requirements.
            description: Toolset description.
            focus_types: Optional dict mapping tool name -> focus_type.
                        Tools not in this dict default to 'neutral'.
        """
        if description:
            self.register_toolset_description(toolset, description)
        _ft = focus_types or {}
        for schema in tools:
            name = schema["name"]
            handler = handlers.get(name)
            if handler is None:
                logger.warning(
                    "No handler for tool '%s' in toolset '%s' — skipping",
                    name, toolset,
                )
                continue
            self.register(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env,
                focus_type=_ft.get(name, FOCUS_TYPE_NEUTRAL),
            )

    # ── Query ────────────────────────────────────────────────────────

    def get_entry(self, name: str) -> Optional[ToolEntry]:
        """Return a registered tool entry by name, or None."""
        with self._lock:
            return self._tools.get(name)

    def get_focus_type(self, name: str) -> str:
        """Return the focus_type for a tool ('focus', 'intake', or 'neutral')."""
        with self._lock:
            entry = self._tools.get(name)
        return entry.focus_type if entry else FOCUS_TYPE_NEUTRAL

    def get_toolset_names(self) -> List[str]:
        """Return sorted unique toolset names in the registry."""
        with self._lock:
            return sorted({e.toolset for e in self._tools.values()})

    def get_tool_names(self, toolset: str = None) -> List[str]:
        """Return tool names, optionally filtered by toolset."""
        with self._lock:
            if toolset:
                return sorted(
                    e.name for e in self._tools.values()
                    if e.toolset == toolset
                )
            return sorted(self._tools.keys())

    def is_toolset_available(self, toolset: str) -> bool:
        """Check if a toolset's requirements are met (via check_fn)."""
        with self._lock:
            check = self._toolset_checks.get(toolset)
        if not check:
            return True  # No check = always available
        return _check_fn_cached(check)

    def check_all_toolsets(self) -> Dict[str, bool]:
        """Return {toolset: available} for every registered toolset."""
        with self._lock:
            toolsets = {e.toolset for e in self._tools.values()}
            checks = dict(self._toolset_checks)
        return {
            ts: (
                _check_fn_cached(checks[ts]) if ts in checks else True
            )
            for ts in sorted(toolsets)
        }

    # ── Schema Retrieval (for Gemini session creation) ───────────────

    def get_declarations(
        self,
        active_toolsets: Optional[Set[str]] = None,
    ) -> List[dict]:
        """Return Gemini FunctionDeclaration dicts for active, available tools.

        Filters by:
          1. Toolset membership (only tools in active_toolsets)
          2. check_fn availability (TTL-cached)

        Args:
            active_toolsets: Set of toolset names to include.
                            If None, includes only "core".

        Returns:
            List of FunctionDeclaration schema dicts.
        """
        if active_toolsets is None:
            active_toolsets = {"core"}

        with self._lock:
            entries = list(self._tools.values())

        result = []
        check_results: Dict[Callable, bool] = {}

        for entry in entries:
            # Filter by toolset
            if entry.toolset not in active_toolsets:
                continue

            # Filter by check_fn
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = _check_fn_cached(
                        entry.check_fn
                    )
                if not check_results[entry.check_fn]:
                    logger.debug(
                        "Tool %s unavailable (check failed)", entry.name,
                    )
                    continue

            result.append(entry.schema)

        return result

    # ── Dispatch ─────────────────────────────────────────────────────

    def dispatch(self, name: str, args: dict) -> str:
        """Execute a tool handler by name.

        All exceptions are caught and returned as JSON error strings.

        Args:
            name: Tool name to execute.
            args: Dict of arguments to pass to the handler.

        Returns:
            Result string from the handler, or JSON error.
        """
        entry = self.get_entry(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            return entry.handler(args)
        except Exception as e:
            logger.exception("Tool %s dispatch error: %s", name, e)
            return json.dumps({
                "error": f"Tool execution failed: {type(e).__name__}: {e}",
            })

    # ── Toolset Info (for list_toolsets tool) ─────────────────────────

    def get_toolset_info(
        self, active_toolsets: Optional[Set[str]] = None,
    ) -> List[dict]:
        """Return rich toolset metadata for the list_toolsets tool.

        Args:
            active_toolsets: Currently enabled toolsets (for status display).

        Returns:
            List of dicts with toolset metadata.
        """
        if active_toolsets is None:
            active_toolsets = {"core"}

        with self._lock:
            entries = list(self._tools.values())
            checks = dict(self._toolset_checks)
            descriptions = dict(self._toolset_descriptions)

        # Group tools by toolset
        toolsets: Dict[str, List[str]] = {}
        for entry in entries:
            ts = entry.toolset
            if ts not in toolsets:
                toolsets[ts] = []
            toolsets[ts].append(entry.name)

        result = []
        for ts_name in sorted(toolsets.keys()):
            check = checks.get(ts_name)
            available = (
                _check_fn_cached(check) if check else True
            )
            result.append({
                "name": ts_name,
                "enabled": ts_name in active_toolsets,
                "available": available,
                "description": descriptions.get(ts_name, ""),
                "tool_count": len(toolsets[ts_name]),
                "tools": sorted(toolsets[ts_name]),
                "requires_env": sorted({
                    env
                    for entry in entries
                    if entry.toolset == ts_name
                    for env in entry.requires_env
                }),
            })

        return result


# ── Module-level singleton ───────────────────────────────────────────

registry = ToolRegistry()
