#!/usr/bin/env /home/nemo/Helix/.venv/bin/python
"""
Helix Subconscious Over-Agent — Native Desktop Floating Mascot Launcher.

Creates a TRUE system-wide native OS floating window (frameless, transparent, always-on-top)
featuring QWebEngineView focusProxy event filtering for 100% fluid click-and-drag desktop movement,
real-time 3D WebGL Helix Mascot Character rendering, and dynamic window sizing.
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
    from PyQt6.QtCore import Qt, QUrl, QPoint, QObject, QEvent
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    import web_server

    class NativeWindowDragFilter(QObject):
        """Intercepts mouse press/move events directly from Chromium focusProxy."""
        def __init__(self, main_window):
            super().__init__()
            self.window = main_window
            self.dragging = False
            self.offset = QPoint()

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.dragging = True
                    self.offset = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            elif event.type() == QEvent.Type.MouseMove:
                if self.dragging and (event.buttons() & Qt.MouseButton.LeftButton):
                    self.window.move(event.globalPosition().toPoint() - self.offset)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.dragging = False
            return False

    app = QApplication(sys.argv)
    window = QMainWindow()

    # Native OS Window Flags: Frameless, Always-On-Top, Translucent Background
    window.setWindowFlags(
        Qt.WindowType.FramelessWindowHint |
        Qt.WindowType.WindowStaysOnTopHint |
        Qt.WindowType.Tool
    )
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.resize(440, 680)
    window.move(1400, 320)

    web = QWebEngineView(window)
    web.page().setBackgroundColor(Qt.GlobalColor.transparent)
    web.load(QUrl(SERVER_URL))
    window.setCentralWidget(web)

    drag_filter = NativeWindowDragFilter(window)

    # Attach event filter to web view and focusProxy upon load
    def attach_filter():
        if web.focusProxy():
            web.focusProxy().installEventFilter(drag_filter)
        web.installEventFilter(drag_filter)
        app.installEventFilter(drag_filter)

    web.loadFinished.connect(attach_filter)

    web_server.DESKTOP_WINDOW_REF = window

    window.show()
    print("  ✓ Native PyQt6 Overlay Window Active: focusProxy Drag Filter Attached & Real-Time 3D Mascot!")
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
