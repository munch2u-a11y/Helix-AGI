"""Focused tests for the presentation-only floating desktop widget."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard.dashboard_comms as dashboard_comms
import dashboard.dashboard as dashboard_module
from desktop_widget.overlay import (
    WIDGET_CLOSED_SIZE,
    WIDGET_OPEN_SIZE,
    calculate_anchored_resize_position,
    calculate_drag_position,
)


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "desktop_widget" / "web"


class DesktopWidgetTests(unittest.TestCase):
    def test_drag_position_preserves_grab_offset(self):
        self.assertEqual(
            calculate_drag_position((1400, 320), (1700, 500), (1815, 565)),
            (1515, 385),
        )

    def test_drawer_resize_keeps_bottom_right_anchor(self):
        anchor = (1919, 1079)
        closed = calculate_anchored_resize_position(anchor, WIDGET_CLOSED_SIZE)
        opened = calculate_anchored_resize_position(anchor, WIDGET_OPEN_SIZE)
        self.assertEqual(closed[0] + WIDGET_CLOSED_SIZE[0], opened[0] + WIDGET_OPEN_SIZE[0])
        self.assertEqual(closed[1] + WIDGET_CLOSED_SIZE[1], opened[1] + WIDGET_OPEN_SIZE[1])

    def test_widget_is_local_webgl_and_uses_existing_dashboard_bridge(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        app_js = (WEB / "app.js").read_text(encoding="utf-8")
        mascot_js = (WEB / "mascot.js").read_text(encoding="utf-8")
        overlay = (ROOT / "desktop_widget" / "overlay.py").read_text(encoding="utf-8")

        self.assertIn('id="helix-3d-canvas"', html)
        self.assertNotIn("https://", html)
        self.assertIn('getContext("webgl"', mascot_js)
        self.assertIn("gl_FragColor", mascot_js)
        self.assertIn("setPointerCapture", app_js)
        self.assertIn("moveWindowDrag", app_js)
        self.assertIn('fetch("/api/messages"', app_js)
        self.assertIn('registerObject("helixDesktop"', overlay)
        combined = "\n".join((app_js, mascot_js, overlay)).lower()
        for forbidden in ("mrag", "context office", "subconsciousconductor", "documentingester"):
            self.assertNotIn(forbidden, combined)

    def test_dashboard_serves_widget_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = dashboard_comms._instance
            dashboard_comms._instance = dashboard_comms.DashboardComms(
                Path(temp_dir) / "messages.json"
            )
            try:
                app = dashboard_module.create_app()
                app.config.update(TESTING=True)
                client = app.test_client()
                page = client.get("/widget/")
                script = client.get("/widget/mascot.js")
                self.assertEqual(page.status_code, 200)
                self.assertEqual(script.status_code, 200)
                self.assertIn(b"Helix Desktop Widget", page.data)
                self.assertIn(b"WebGL", script.data)
                page.close()
                script.close()
            finally:
                dashboard_comms._instance = previous

    def test_canvas_endpoint_rejects_unbounded_or_invalid_payloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            previous = dashboard_comms._instance
            dashboard_comms._instance = dashboard_comms.DashboardComms(temp_path / "messages.json")
            try:
                with patch.object(dashboard_module, "SPATIAL_DIR", temp_path / "spatial"):
                    app = dashboard_module.create_app()
                    app.config.update(TESTING=True)
                    client = app.test_client()
                    self.assertEqual(client.post("/api/canvas", json={"view_type": "executable"}).status_code, 400)
                    self.assertEqual(client.post(
                        "/api/canvas",
                        json={"view_type": "card", "content": "ok", "timestamp": "not-a-number"},
                    ).status_code, 400)
                    valid = client.post(
                        "/api/canvas",
                        json={"view_type": "card", "title": "Ready", "content": "Local UI"},
                    )
                    self.assertEqual(valid.status_code, 200)
                    self.assertTrue((temp_path / "spatial" / "agent_canvas.json").is_file())
            finally:
                dashboard_comms._instance = previous


if __name__ == "__main__":
    unittest.main()
