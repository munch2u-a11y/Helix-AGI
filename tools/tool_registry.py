"""
Helix — Tool Registry (Hermes-Style Dynamic Registration)

Central registry that collects tool schemas, handlers, and availability
checks. Replaces the static _FC_DISPATCH dict and TOOL_DECLARATIONS list.

Features (adapted from Hermes):
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

    Adapted from Hermes's ToolRegistry. Provides:
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
        self._toolset_last_used_turn: Dict[str, int] = {}
        # Original schema descriptions, saved before learned notes are
        # appended (ToolEntry has __slots__, so this lives registry-side).
        self._base_schema_desc: Dict[str, str] = {}

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
            # Fresh schema — any saved base description is stale
            self._base_schema_desc.pop(name, None)
            # Store the first check_fn we see for a toolset as the
            # toolset-level availability check
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn
            self._generation += 1

    def register_toolset_description(self, toolset: str, description: str):
        """Set a human-readable description for a toolset."""
        with self._lock:
            self._toolset_descriptions[toolset] = description

    # ── Learned Notes (Lane 1 of dynamic tool learning) ───────────────
    #
    # Tool descriptions are the one injection point guaranteed to be in
    # the model's view at the moment it chooses a tool. The nightly
    # Curator compiles the heaviest tool-bound beliefs into short notes;
    # this applies them to the live schemas. The base description is
    # preserved so notes REPLACE previous notes rather than stacking.

    def apply_learned_notes(self, notes_by_tool: Dict[str, List[str]]) -> int:
        """Append learned notes to tool schema descriptions.

        Args:
            notes_by_tool: tool name → list of short note strings.

        Returns:
            Number of tools whose descriptions were updated.
        """
        updated = 0
        with self._lock:
            for name, entry in self._tools.items():
                base = self._base_schema_desc.get(name)
                if base is None:
                    base = entry.schema.get("description", "") or ""
                    self._base_schema_desc[name] = base

                notes = [
                    n.strip() for n in notes_by_tool.get(name, []) if n.strip()
                ]
                if notes:
                    entry.schema["description"] = (
                        base + "\nLearned: " + " | ".join(notes)
                    )
                    updated += 1
                else:
                    # No notes (or notes removed by attrition) — restore base
                    if entry.schema.get("description", "") != base:
                        entry.schema["description"] = base
            if updated:
                self._generation += 1
        if updated:
            logger.info("Learned notes applied to %d tool descriptions", updated)
        return updated

    def load_learned_notes(self, path="data/tool_learned_notes.json") -> int:
        """Load compiled notes from disk and apply them. Called at boot
        and on morning wake after the nightly compile."""
        import json
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            return 0
        try:
            data = json.loads(p.read_text())
            notes = data.get("notes", {})
            if isinstance(notes, dict) and notes:
                return self.apply_learned_notes(notes)
        except Exception as e:
            logger.warning("Failed to load learned tool notes: %s", e)
        return 0

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

    # ── Two-Layer Schema Rendering (orchestrated local tool use) ──────
    #
    # An API provider is handed every active declaration and selects from
    # them natively. A 3-4B local model at an 8K window cannot hold 80+
    # schemas, so the same registry is rendered at two depths:
    #
    #   Layer A — one line per toolset: what exists at all. Tens of tokens.
    #   Layer B — the full schemas for ONE toolset, given to a directed
    #             tool pass working inside that toolset. Hundreds.
    #
    # Learned notes need no special handling: apply_learned_notes folds them
    # into entry.schema["description"], so Layer B carries them already.

    def _available_toolsets(
        self, include_unavailable: bool = False,
    ) -> Dict[str, List[ToolEntry]]:
        """Group entries by toolset, dropping ones whose check_fn fails."""
        with self._lock:
            entries = list(self._tools.values())
            checks = dict(self._toolset_checks)

        grouped: Dict[str, List[ToolEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.toolset, []).append(entry)

        if include_unavailable:
            return grouped

        return {
            name: members
            for name, members in grouped.items()
            if name not in checks or _check_fn_cached(checks[name])
        }

    def toolset_brief(
        self,
        call_format: str = "",
        include_unavailable: bool = False,
    ) -> str:
        """Layer A: the slim toolset list a model keeps in its main window.

        Args:
            call_format: Optional instruction describing how to request a
                toolset. Supplied by the caller because it is provider
                specific — a grammar-constrained local model and a
                JSON-parsed one are told different things.
            include_unavailable: Advertise toolsets whose check_fn fails
                (missing API key, service down). Off by default so the
                model is never offered something that cannot run.
        """
        grouped = self._available_toolsets(include_unavailable)
        if not grouped:
            return ""

        with self._lock:
            descriptions = dict(self._toolset_descriptions)

        lines: List[str] = []
        if call_format:
            lines.append(call_format)
        for name in sorted(grouped):
            count = len(grouped[name])
            summary = descriptions.get(name, "")
            suffix = f": {summary}" if summary else ""
            lines.append(f"• {name} ({count} tools){suffix}")
        return "\n".join(lines)

    @staticmethod
    def _render_parameters(schema: dict) -> List[str]:
        """Render a JSON-Schema parameter block as readable bullet lines.

        Dumping raw JSON costs roughly twice the tokens and reads worse to a
        small model than a plain list of named arguments.
        """
        params = schema.get("parameters") or {}
        properties = params.get("properties") or {}
        if not properties:
            return []

        required = set(params.get("required") or [])
        lines = ["Arguments:"]
        for pname, pspec in properties.items():
            if not isinstance(pspec, dict):
                pspec = {}
            ptype = pspec.get("type", "any")
            marker = ", required" if pname in required else ""
            line = f"  - {pname} ({ptype}{marker})"
            desc = str(pspec.get("description", "") or "").strip()
            if desc:
                line += f": {desc}"
            enum = pspec.get("enum")
            if enum:
                line += f" [one of: {', '.join(str(v) for v in enum)}]"
            lines.append(line)
        return lines

    def toolset_manifest(
        self,
        toolset: str,
        include_unavailable: bool = False,
    ) -> str:
        """Layer B: full schemas for one toolset, for a directed tool pass."""
        grouped = self._available_toolsets(include_unavailable)
        members = grouped.get(toolset)
        if not members:
            return ""

        with self._lock:
            summary = self._toolset_descriptions.get(toolset, "")

        header = f"TOOLSET '{toolset}'"
        if summary:
            header += f": {summary}"
        lines: List[str] = [header, ""]

        check_results: Dict[Callable, bool] = {}
        for entry in sorted(members, key=lambda e: e.name):
            if entry.check_fn and not include_unavailable:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = _check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    continue
            lines.append(f"### {entry.name}")
            description = str(
                entry.schema.get("description", "") or entry.description or ""
            ).strip()
            if description:
                lines.append(description)
            lines.extend(self._render_parameters(entry.schema))
            lines.append("")

        return "\n".join(lines).strip()

    def toolset_tool_names(
        self,
        toolset: str,
        include_unavailable: bool = False,
    ) -> List[str]:
        """Names in one toolset, filtered the same way the manifest is.

        The grammar handed to a constrained local model must match the
        manifest it was shown, or the model can be masked away from a tool
        it was just told about.
        """
        grouped = self._available_toolsets(include_unavailable)
        members = grouped.get(toolset) or []

        names: List[str] = []
        check_results: Dict[Callable, bool] = {}
        for entry in members:
            if entry.check_fn and not include_unavailable:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = _check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    continue
            names.append(entry.name)
        return sorted(names)

    # ── Turn-based Usage Tracking (for auto-disengage) ────────────────

    def record_tool_use(self, name: str, turn: int):
        """Record that a tool was used in the current turn."""
        with self._lock:
            entry = self._tools.get(name)
            if entry:
                self._toolset_last_used_turn[entry.toolset] = turn

    def record_toolset_active(self, toolset: str, turn: int):
        """Record that a toolset is active/enabled in the current turn."""
        with self._lock:
            self._toolset_last_used_turn[toolset] = turn

    def deactivate_toolset_tracking(self, toolset: str):
        """Remove a toolset from usage tracking when it is disabled."""
        with self._lock:
            self._toolset_last_used_turn.pop(toolset, None)

    def get_idle_toolsets(self, current_turn: int, idle_threshold: int = 2) -> Set[str]:
        """Return a set of active toolsets that have been idle for > idle_threshold turns."""
        with self._lock:
            idle = set()
            for toolset, last_turn in list(self._toolset_last_used_turn.items()):
                if toolset == "core":
                    continue
                if current_turn - last_turn > idle_threshold:
                    idle.add(toolset)
            return idle


# ── Module-level singleton ───────────────────────────────────────────

registry = ToolRegistry()
