#!/usr/bin/env /home/nemo/Helix/.venv/bin/python
"""
Helix Subconscious Over-Agent — Native Desktop Floating Mascot Launcher.

Creates a TRUE system-wide native OS floating character window (frameless, transparent, always-on-top)
that displays the exact transparent PNG Helix Guy character cutout (no circles/boxes)
with 100% fluid Qt native click-and-drag window movement across all desktop screens.
"""

import os
import sys
import time
import urllib.request

SERVER_URL = "http://localhost:8080"

def wait_for_server(url: str, timeout_s: float = 10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False

def launch_pyqt6_native_overlay():
    from PyQt6.QtCore import Qt, QUrl, QPoint
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    import web_server

    class NativeMascotWindow(QWidget):
        def __init__(self):
            super().__init__()
            self._drag_pos = QPoint()
            self._is_dragging = False

            # Native OS Window Flags: Frameless, Always-On-Top, Translucent Background
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.resize(440, 680)
            self.move(1400, 320)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            self.web = QWebEngineView(self)
            self.web.page().setBackgroundColor(Qt.GlobalColor.transparent)
            self.web.load(QUrl(SERVER_URL))
            layout.addWidget(self.web)

            web_server.DESKTOP_WINDOW_REF = self

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self._is_dragging = True
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

        def mouseMoveEvent(self, event):
            if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()

        def mouseReleaseEvent(self, event):
            self._is_dragging = False
            event.accept()

    app = QApplication(sys.argv)
    window = NativeMascotWindow()
    window.show()
    print("  ✓ Native PyQt6 Mascot Window Active: 100% Fluid Mouse Dragging & Transparent Character Cutout!")
    sys.exit(app.exec())

def launch_native_overlay():
    print("=====================================================================")
    print(" 🚀 LAUNCHING NATIVE SYSTEM-WIDE DESKTOP FLOATING OVERLAY WINDOW")
    print("=====================================================================")
    
    if not wait_for_server(SERVER_URL):
        print(f"  ⚠️ Warning: Server at {SERVER_URL} is not responding. Starting overlay anyway...")

    launch_pyqt6_native_overlay()

if __name__ == "__main__":
    launch_native_overlay()
