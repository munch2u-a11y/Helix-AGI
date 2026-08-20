"""Tests for the isolated dashboard canvas extension."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.tool_registry import ToolRegistry
from tools import ui_canvas_tool
from tools.tool_executor import ToolExecutor


class UiCanvasToolTests(unittest.TestCase):
    def test_registration_is_isolated_to_ui_canvas_toolset(self):
        registry = ToolRegistry()
        ui_canvas_tool.register_ui_canvas_tool(registry)
        self.assertEqual(registry.get_tool_names("ui_canvas"), ["render_ui_canvas"])
        self.assertEqual(registry.get_tool_names("core"), [])

    def test_tool_executor_discovers_ui_canvas_without_core_schema_changes(self):
        executor = ToolExecutor()
        entry = executor._registry.get_entry("render_ui_canvas")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.toolset, "ui_canvas")

    def test_render_writes_bounded_state_and_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = Path(temp_dir) / "agent_canvas.json"
            history = Path(temp_dir) / "agent_canvas_history.json"
            with patch.object(ui_canvas_tool, "CANVAS_STATE_PATH", state), patch.object(
                ui_canvas_tool, "CANVAS_HISTORY_PATH", history
            ):
                result = json.loads(ui_canvas_tool.render_ui_canvas(
                    view_type="markdown",
                    title="Local report",
                    content="# Verified\nNo runtime replacement.",
                ))
            self.assertEqual(result["status"], "rendered")
            payload = json.loads(state.read_text(encoding="utf-8"))
            saved_history = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual(payload["view_type"], "markdown")
            self.assertEqual(saved_history, [payload])

    def test_invalid_view_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = Path(temp_dir) / "agent_canvas.json"
            with patch.object(ui_canvas_tool, "CANVAS_STATE_PATH", state):
                result = json.loads(ui_canvas_tool.render_ui_canvas("executable", "payload"))
            self.assertEqual(result["status"], "error")
            self.assertFalse(state.exists())

    def test_dashboard_canvas_restricts_embedded_url_protocols(self):
        html = (Path(__file__).resolve().parents[1] / "dashboard" / "dashboard_ui.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("url.protocol === 'http:' || url.protocol === 'https:'", html)
        self.assertIn("frame.sandbox", html)


if __name__ == "__main__":
    unittest.main()
