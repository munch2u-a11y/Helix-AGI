#!/usr/bin/env /home/nemo/Helix/.venv/bin/python
"""
Helix Subconscious Over-Agent — Native Desktop Floating Overlay Launcher.

Creates a TRUE system-wide native OS floating window (frameless, transparent, always-on-top)
registered to web_server.DESKTOP_WINDOW_REF for 100% fluid click-and-drag desktop movement.
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
    from PyQt6.QtCore import Qt, QUrl, QPoint
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    import web_server

    app = QApplication(sys.argv)
    window = QMainWindow()

    # Frameless, Translucent, Always-On-Top OS Window
    window.setWindowFlags(
        Qt.WindowType.FramelessWindowHint |
        Qt.WindowType.WindowStaysOnTopHint |
        Qt.WindowType.Tool
    )
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.resize(440, 660)
    window.move(1400, 350)

    web = QWebEngineView(window)
    web.page().setBackgroundColor(Qt.GlobalColor.transparent)
    web.load(QUrl(SERVER_URL))
    window.setCentralWidget(web)

    # Register global window reference for web-to-python dragging
    web_server.DESKTOP_WINDOW_REF = window

    window.show()
    print("  ✓ Native PyQt6 Overlay Window Active & Drag-Bridge Connected!")
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
