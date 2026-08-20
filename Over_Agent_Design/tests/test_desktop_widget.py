"""Focused regression tests for the local 3D desktop widget."""

from pathlib import Path

from desktop_overlay import (
    WIDGET_CLOSED_SIZE,
    WIDGET_OPEN_SIZE,
    calculate_anchored_resize_position,
    calculate_drag_position,
)


ROOT = Path(__file__).resolve().parents[1]
WEB_UI = ROOT / "web_ui"


def test_drag_position_preserves_grab_offset() -> None:
    assert calculate_drag_position((1400, 320), (1700, 500), (1815, 565)) == (1515, 385)


def test_drawer_resize_keeps_bottom_right_anchor() -> None:
    anchor = (1919, 1079)
    closed_position = calculate_anchored_resize_position(anchor, WIDGET_CLOSED_SIZE)
    open_position = calculate_anchored_resize_position(anchor, WIDGET_OPEN_SIZE)

    assert closed_position == (1640, 760)
    assert open_position == (1440, 320)
    assert closed_position[0] + WIDGET_CLOSED_SIZE[0] == open_position[0] + WIDGET_OPEN_SIZE[0]
    assert closed_position[1] + WIDGET_CLOSED_SIZE[1] == open_position[1] + WIDGET_OPEN_SIZE[1]


def test_page_loads_local_realtime_webgl_mascot() -> None:
    html = (WEB_UI / "index.html").read_text(encoding="utf-8")
    assert '<canvas id="helix-3d-canvas"' in html
    assert '<script src="three.min.js"></script>' in html
    assert '<script src="helix_3d_mascot.js"></script>' in html
    assert "helix_mascot_3d_transparent.gif" not in html
    assert "https://" not in html


def test_dragging_uses_pointer_capture_and_direct_qt_channel() -> None:
    app_js = (WEB_UI / "app.js").read_text(encoding="utf-8")
    overlay_py = (ROOT / "desktop_overlay.py").read_text(encoding="utf-8")

    assert 'registerObject("helixDesktop"' in overlay_py
    assert 'script.src = "qrc:///qtwebchannel/qwebchannel.js"' in app_js
    assert "setPointerCapture" in app_js
    assert "moveWindowDrag" in app_js
    assert "QCursor.pos()" in overlay_py
    assert "/api/drag_move" not in app_js
