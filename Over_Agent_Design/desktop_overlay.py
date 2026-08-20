#!/usr/bin/env /home/nemo/Helix/.venv/bin/python
"""
Helix Subconscious Over-Agent — Native Desktop Floating Overlay Launcher.

Renders the official 3D animated Helix logo video/GIF with 100% thread-safe PyQt6 signals
for instant, fluid click-and-drag desktop movement across all screens.
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
    from PyQt6.QtCore import Qt, QUrl, QPoint, QObject, pyqtSignal, pyqtSlot
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    import web_server

    class ThreadSafeDragBridge(QObject):
        """Thread-safe signal bridge allowing background HTTP server to move Qt GUI window."""
        move_signal = pyqtSignal(int, int)

    class NativeMascotWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self._drag_pos = QPoint()

            # Native OS Window Flags: Frameless, Always-On-Top, Translucent Background
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.resize(440, 680)
            self.move(1400, 320)

            self.web = QWebEngineView(self)
            self.web.page().setBackgroundColor(Qt.GlobalColor.transparent)
            self.web.load(QUrl(SERVER_URL))
            self.setCentralWidget(self.web)

            # Thread-safe drag signal bridge
            self.bridge = ThreadSafeDragBridge()
            self.bridge.move_signal.connect(self.on_move_requested)

            web_server.QT_DRAG_BRIDGE = self.bridge
            web_server.DESKTOP_WINDOW_REF = self

        @pyqtSlot(int, int)
        def on_move_requested(self, x, y):
            self.move(x, y)

    app = QApplication(sys.argv)
    window = NativeMascotWindow()
    window.show()
    print("  ✓ Native PyQt6 Mascot Overlay Active: Thread-Safe Drag Signal Bridge & Official 3D Render!")
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
