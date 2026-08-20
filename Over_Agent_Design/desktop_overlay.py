#!/usr/bin/env /home/nemo/Helix/.venv/bin/python
"""
Helix Subconscious Over-Agent — Native Desktop Floating Overlay Launcher.

Creates a TRUE system-wide native OS floating window (frameless, transparent, always-on-top)
that floats over all open applications (VS Code, Chrome, Terminals, etc.).
Uses PyQt6 QtWebEngineWidgets or PyWebView for fail-proof native desktop rendering.
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
    from PyQt6.QtCore import Qt, QUrl
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    window = QMainWindow()
    
    # Frameless, Always-on-top, Tool window (hidden from taskbar)
    window.setWindowFlags(
        Qt.WindowType.FramelessWindowHint |
        Qt.WindowType.WindowStaysOnTopHint |
        Qt.WindowType.Tool
    )
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.resize(460, 660)
    window.move(1400, 400)

    web = QWebEngineView(window)
    web.page().setBackgroundColor(Qt.GlobalColor.transparent)
    web.load(QUrl(SERVER_URL))
    window.setCentralWidget(web)
    
    window.show()
    print("  ✓ Native PyQt6 Overlay Window Active & Floating On Top!")
    sys.exit(app.exec())

def launch_pywebview_overlay():
    import webview
    window = webview.create_window(
        title="Helix Floating Mascot",
        url=SERVER_URL,
        width=460,
        height=660,
        x=1400,
        y=400,
        frameless=True,
        on_top=True,
        transparent=True,
        easy_drag=True
    )
    webview.start(debug=False)

def launch_native_overlay():
    print("=====================================================================")
    print(" 🚀 LAUNCHING NATIVE SYSTEM-WIDE DESKTOP FLOATING OVERLAY WINDOW")
    print("=====================================================================")
    
    if not wait_for_server(SERVER_URL):
        print(f"  ⚠️ Warning: Server at {SERVER_URL} is not responding. Starting overlay anyway...")

    try:
        launch_pyqt6_overlay()
    except Exception as e:
        print(f"  ℹ️ PyQt6 direct launcher note ({e}); falling back to pywebview...")
        launch_pywebview_overlay()

if __name__ == "__main__":
    launch_native_overlay()
