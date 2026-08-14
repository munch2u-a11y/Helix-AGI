# Tool Execution System, Hermes Dynamic Registry & Lesson Learning Audit

**Status:** Current Runtime Audit · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

**Scope:** [`tools/tool_registry.py`](../../tools/tool_registry.py), [`tools/ui_canvas_tool.py`](../../tools/ui_canvas_tool.py), [`core/tool_lesson_tracker.py`](../../core/tool_lesson_tracker.py), [`tools/tool_executor.py`](../../tools/tool_executor.py)

---

## 1. Hermes Dynamic Tool Registry & Availability Gating

The central dynamic registry ([`tools/tool_registry.py`](../../tools/tool_registry.py#L30-L110)) manages tool declarations, handlers, and availability checks:

- **Hermes Dynamic Registration**: Tools register via `registry.register(name, toolset, schema, handler, check_fn)`.
- **TTL Availability Caching**: `check_fn` results are TTL-cached for 30 seconds to avoid repeated environment or API probes ([`tools/tool_registry.py`](../../tools/tool_registry.py#L44-L65)).
- **Toolset Gating**: `get_declarations(active_toolsets)` returns only tool declarations that pass availability checks for active toolsets.

---

## 2. Dynamic Agent-Controlled UI Canvas (`ui_canvas`)

The `ui_canvas` toolset ([`tools/ui_canvas_tool.py`](../../tools/ui_canvas_tool.py#L25-L95)) equips Helix with dynamic UI rendering capabilities:

- **`render_ui_canvas(view_type, content, title, media_url, auto_switch)`**:
  - `view_type`: `"markdown"`, `"image"`, `"browser"`, `"terminal"`, `"card"`.
  - Persists JSON state to `data/spatial/agent_canvas.json` and updates `data/spatial/agent_canvas_history.json`.
  - Broadcasts state updates to the Web Dashboard at `localhost:5050` ([`dashboard/dashboard.py`](../../dashboard/dashboard.py#L504-L550)).
  - Auto-switches the user's dashboard tab to **Agent Canvas 🎨** when `auto_switch=True`.

---

## 3. Real-Time Tool Failure Capture & Nightly Consolidation

The tool learning loop operates as follows ([`core/tool_lesson_tracker.py`](../../core/tool_lesson_tracker.py#L20-L90)):

1. **Failure Capture**: Every tool execution outcome is reported to `observe_tool_result()`. Failures matching error patterns are deduplicated and queued in `data/pending_beliefs.json`.
2. **Nightly Curator Consolidation ($G=2.5$)**: The Curator groups tool-bound beliefs, ranks them by mass, and saves top notes to `data/tool_learned_notes.json`.
3. **Learned Notes Injection**: `registry.apply_learned_notes()` appends learned operational notes directly to tool JSON descriptions for future conscious sessions ([`tools/tool_registry.py`](../../tools/tool_registry.py#L209-L259)).
4. **Validation & Reinforcement**: When a tool-bound lesson is injected (`note_lessons_injected()`) and the tool succeeds within a 10-minute TTL window, the lesson's verifications and stability index increase, preserving it against nightly attrition.
