#!/usr/bin/env /home/nemo/Helix/.venv/bin/python
"""
Helix Subconscious Over-Agent — Native Desktop Floating Overlay Launcher.

Creates a TRUE system-wide native OS floating window (frameless, transparent, always-on-top)
that floats over all open applications (VS Code, Chrome, Terminals, etc.).
"""

import os
import sys
import time
import urllib.request

try:
    import webview
except ImportError:
    print("[Error] pywebview not found. Run: /home/nemo/Helix/.venv/bin/pip install pywebview PyQt6 PyQt6-WebEngine")
    sys.exit(1)

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

def launch_native_overlay():
    print("=====================================================================")
    print(" 🚀 LAUNCHING NATIVE SYSTEM-WIDE DESKTOP FLOATING OVERLAY WINDOW")
    print("=====================================================================")
    
    if not wait_for_server(SERVER_URL):
        print(f"  ⚠️ Warning: Server at {SERVER_URL} is not responding. Starting overlay anyway...")

    # Create Frameless, Transparent, Always-On-Top OS Window
    window = webview.create_window(
        title="Helix Floating Mascot",
        url=SERVER_URL,
        width=460,
        height=660,
        x=1400,
        y=400,
        frameless=True,       # No OS titlebar / borders
        on_top=True,          # Sits on top of all open programs
        transparent=True,     # Transparent window background
        easy_drag=True,       # Click & drag anywhere on avatar
        min_size=(100, 100)
    )

    webview.start(debug=False)

if __name__ == "__main__":
    launch_native_overlay()
