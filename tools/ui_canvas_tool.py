#!/usr/bin/env python3
"""Bounded tool for rendering content in the existing dashboard canvas."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
SPATIAL_DIR = BASE_DIR / "data" / "spatial"
CANVAS_STATE_PATH = SPATIAL_DIR / "agent_canvas.json"
CANVAS_HISTORY_PATH = SPATIAL_DIR / "agent_canvas_history.json"
ALLOWED_VIEW_TYPES = {
    "markdown", "text", "image", "media", "browser", "iframe",
    "terminal", "sandbox", "card", "alert",
}
_WRITE_LOCK = threading.Lock()


def _atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def render_ui_canvas(
    view_type: str,
    content: str,
    title: str = "Agent Canvas",
    media_url: Optional[str] = None,
    auto_switch: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Persist a presentation payload for the local dashboard canvas."""
    normalized_type = str(view_type or "").strip().lower()
    if normalized_type not in ALLOWED_VIEW_TYPES:
        return json.dumps({"status": "error", "message": f"Unsupported view type: {normalized_type}"})

    normalized_content = str(content or "")
    normalized_title = str(title or "Agent Canvas").strip()
    normalized_url = str(media_url).strip() if media_url else None
    if len(normalized_content) > 500_000 or len(normalized_title) > 200:
        return json.dumps({"status": "error", "message": "Canvas payload exceeds the local UI limit"})
    if normalized_url and len(normalized_url) > 2_048:
        return json.dumps({"status": "error", "message": "Canvas media URL is too long"})

    payload = {
        "view_type": normalized_type,
        "title": normalized_title,
        "content": normalized_content,
        "media_url": normalized_url,
        "auto_switch": bool(auto_switch),
        "timestamp": time.time(),
        "metadata": metadata if isinstance(metadata, dict) else {},
    }

    try:
        with _WRITE_LOCK:
            history = []
            if CANVAS_HISTORY_PATH.exists():
                try:
                    loaded = json.loads(CANVAS_HISTORY_PATH.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        history = loaded
                except (OSError, json.JSONDecodeError):
                    history = []
            history.append(payload)
            _atomic_json_write(CANVAS_STATE_PATH, payload)
            _atomic_json_write(CANVAS_HISTORY_PATH, history[-50:])
    except (OSError, TypeError, ValueError) as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    return json.dumps({"status": "rendered", "view_type": normalized_type, "title": normalized_title})


UI_CANVAS_SCHEMA = {
    "name": "render_ui_canvas",
    "description": (
        "Render a bounded text, media, browser, terminal, or status view in "
        "the user's local Helix dashboard canvas."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "view_type": {
                "type": "STRING",
                "enum": sorted(ALLOWED_VIEW_TYPES),
                "description": "Presentation type for the dashboard canvas.",
            },
            "content": {
                "type": "STRING",
                "description": "Text, description, or terminal output to display.",
            },
            "title": {"type": "STRING", "description": "Short canvas heading."},
            "media_url": {"type": "STRING", "description": "Optional HTTP or HTTPS media URL."},
            "auto_switch": {
                "type": "BOOLEAN",
                "description": "Whether the dashboard should switch to the canvas when updated.",
            },
        },
        "required": ["view_type", "content"],
    },
}


def register_ui_canvas_tool(registry_instance) -> None:
    """Register the isolated UI tool with Helix's existing tool registry."""
    registry_instance.register(
        name="render_ui_canvas",
        toolset="ui_canvas",
        schema=UI_CANVAS_SCHEMA,
        handler=lambda args: render_ui_canvas(**args),
        description="Local dashboard presentation canvas",
    )
