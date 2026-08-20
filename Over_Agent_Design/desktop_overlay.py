#!/usr/bin/env /home/nemo/Helix/.venv/bin/python
"""
Helix Subconscious Over-Agent — Native Desktop Floating Overlay Launcher.

Creates a TRUE system-wide native OS floating window (frameless, transparent, always-on-top)
featuring native click-and-drag window movement anywhere across screens, pure mascot UI,
and dynamic window size syncing between character widget mode and mini-chat drawer mode.
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

def launch_pyqt6_overlay():
    from PyQt6.QtCore import Qt, QUrl, QPoint, pyqtSlot
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebChannel import QWebChannel

    class NativeFloatingOverlayWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self._drag_pos = QPoint()

            # Frameless, Always-on-top, Translucent Desktop Tool Window
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.resize(440, 660)
            self.move(1400, 350)

            self.web = QWebEngineView(self)
            self.web.page().setBackgroundColor(Qt.GlobalColor.transparent)
            self.web.load(QUrl(SERVER_URL))
            self.setCentralWidget(self.web)

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

        def mouseMoveEvent(self, event):
            if event.buttons() == Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()

    app = QApplication(sys.argv)
    window = NativeFloatingOverlayWindow()
    window.show()
    print("  ✓ Native PyQt6 Overlay Window Active with Fluid Mouse Dragging & Pure Mascot Rendering!")
    sys.exit(app.exec())

def launch_native_overlay():
    print("=====================================================================")
    print(" 🚀 LAUNCHING NATIVE SYSTEM-WIDE DESKTOP FLOATING OVERLAY WINDOW")
    print("=====================================================================")
    
    if not wait_for_server(SERVER_URL):
        print(f"  ⚠️ Warning: Server at {SERVER_URL} is not responding. Starting overlay anyway...")

    launch_pyqt6_overlay()

if __name__ == "__main__":
    launch_native_overlay()
