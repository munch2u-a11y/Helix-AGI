#!/usr/bin/env python3
"""Start the existing Helix dashboard when needed, then open the widget."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from desktop_widget.overlay import DEFAULT_WIDGET_URL, launch_native_overlay


REPO_ROOT = Path(__file__).resolve().parents[1]


def wait_for_url(url: str, timeout_seconds: float = 12.0) -> bool:
    """Return True when a local HTTP endpoint responds before the timeout."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    return False


def start_dashboard() -> subprocess.Popen:
    """Start the restored main dashboard with the current interpreter."""
    return subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "dashboard" / "dashboard.py"),
            "--host",
            "127.0.0.1",
            "--port",
            "5050",
        ],
        cwd=str(REPO_ROOT),
    )


def main() -> int:
    widget_url = os.environ.get("HELIX_WIDGET_URL", DEFAULT_WIDGET_URL)
    dashboard_process = None

    if not wait_for_url(widget_url, timeout_seconds=0.5):
        print("Starting the local Helix dashboard for the desktop widget...")
        dashboard_process = start_dashboard()
        if not wait_for_url(widget_url):
            dashboard_process.terminate()
            dashboard_process.wait(timeout=5)
            print(f"Unable to reach the widget at {widget_url}", file=sys.stderr)
            return 1

    try:
        launch_native_overlay(widget_url)
    finally:
        if dashboard_process is not None and dashboard_process.poll() is None:
            dashboard_process.terminate()
            try:
                dashboard_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dashboard_process.kill()
                dashboard_process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
