#!/usr/bin/env python3
"""Helix — Agent Canvas UI Interfacing Tool.

Allows Helix to dynamically change and render custom UI components,
markdown documents, images, web embeds, and terminal logs on the
user's Agent Canvas tab in the Web Dashboard.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from core.agent_home import write_home_json
from core.canvas_state import normalize_canvas_payload
from core.runtime_paths import RuntimePaths
from tools.tool_registry import registry

logger = logging.getLogger("helix.tools.ui_canvas")

BASE_DIR = Path(__file__).parent.parent.resolve()
SPATIAL_DIR = BASE_DIR / "data" / "spatial"
CANVAS_STATE_PATH = SPATIAL_DIR / "agent_canvas.json"
CANVAS_HISTORY_PATH = SPATIAL_DIR / "agent_canvas_history.json"


def render_ui_canvas(
    view_type: str,
    content: str,
    title: str = "Agent Canvas",
    media_url: Optional[str] = None,
    auto_switch: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Dynamically render or update the user's Agent Canvas tab in the Web Dashboard UI.

    Args:
        view_type: Render target type. Supported values:
                   - 'markdown' or 'text': Render rich formatted markdown documents or reports.
                   - 'image' or 'media': Display generated images, diagrams, or visual assets.
                   - 'browser' or 'iframe': Embed an external URL or web page.
                   - 'terminal' or 'sandbox': Display program execution logs or code outputs.
                   - 'card' or 'alert': Present big emphasis status cards or hero banners.
        content: The text content, markdown payload, code log, or description.
        title: Header title to display at the top of the Canvas tab.
        media_url: Optional image URL, video URL, or web link.
        auto_switch: Whether the UI should automatically switch the user's focus tab to Canvas.
        metadata: Optional dictionary of additional UI parameters (e.g. status, theme, layout).

    Returns:
        JSON string status confirmation.
    """
    try:
        payload = normalize_canvas_payload({
            "view_type": view_type, "title": title, "content": content,
            "media_url": media_url, "auto_switch": auto_switch,
            "metadata": {} if metadata is None else metadata,
        })
        from core.mindscape_config import configuration_path
        config_path = configuration_path(BASE_DIR)
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        spatial_dir = RuntimePaths.from_config(config, root=BASE_DIR).data / "spatial"
        spatial_dir.mkdir(parents=True, exist_ok=True)
        state_path = spatial_dir / "agent_canvas.json"
        history_path = spatial_dir / "agent_canvas_history.json"
        write_home_json(state_path, payload)

        history = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text(encoding="utf-8"))
                if not isinstance(history, list):
                    history = []
            except (OSError, ValueError):
                history = []
        history.append(payload)
        write_home_json(history_path, history[-50:])

        logger.info("Rendered Agent Canvas UI view '%s' [%s]", title, view_type)
        return json.dumps({"status": "rendered", "view_type": view_type, "title": title})
    except Exception as e:
        logger.error("Failed to render Agent Canvas UI: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


# ── Tool Registration ──────────────────────────────────────────────────

UI_CANVAS_SCHEMA = {
    "name": "render_ui_canvas",
    "description": (
        "Dynamically render or update the user's Agent Canvas tab in the Web Dashboard UI. "
        "Use this to show rich markdown docs, images, web pages, terminal logs, or status cards to the user."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "view_type": {
                "type": "STRING",
                "enum": ["markdown", "text", "image", "media", "browser", "iframe", "terminal", "sandbox", "card", "alert"],
                "description": "Target UI view type: 'markdown' (docs), 'image' (pictures), 'browser' (web pages), 'terminal' (logs), 'card' (status hero).",
            },
            "content": {
                "type": "STRING",
                "description": "Main text content, markdown payload, code log, or description.",
            },
            "title": {
                "type": "STRING",
                "description": "Header title for the canvas view.",
            },
            "media_url": {
                "type": "STRING",
                "description": "Optional image URL, video URL, or web link to embed.",
            },
            "auto_switch": {
                "type": "BOOLEAN",
                "description": "Set true to automatically switch the user's dashboard tab to the Agent Canvas.",
            },
        },
        "required": ["view_type", "content"],
    },
}


def register_ui_canvas_tool(tool_registry):
    """Register in the executor's selected registry, including after reload."""
    tool_registry.register(
        name="render_ui_canvas", toolset="ui_canvas", schema=UI_CANVAS_SCHEMA,
        handler=lambda args: render_ui_canvas(**args),
    )


register_ui_canvas_tool(registry)
