"""
Helix — Desktop Control Tools

Provides desktop automation via action tags:
  [DESKTOP_TYPE:] text
  [DESKTOP_KEY:] key_combo
  [DESKTOP_CLICK:] x,y
  [DESKTOP_MOUSE:] x,y
  [DESKTOP_SCROLL:] direction,amount
  [DESKTOP_WINDOW:]
  [DESKTOP_FOCUS:] window_name
  [DESKTOP_OPEN:] application
  [DESKTOP_SCREENSHOT:]

Uses xdotool for input simulation and gnome-screenshot/grim for captures.
Requires DISPLAY and XAUTHORITY environment for Wayland/X11 access.
"""

import os
import glob
import logging
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("helix.tools.desktop_control")

# Screenshot storage
_SCREENSHOT_DIR = Path("/home/nemo/Helix/data/screenshots")


def _get_gui_env() -> dict:
    """Dynamically build the environment required to access Wayland/X11 displays."""
    env = os.environ.copy()
    env['DISPLAY'] = os.environ.get('DISPLAY', ':1')
    env['DBUS_SESSION_BUS_ADDRESS'] = os.environ.get(
        'DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus'
    )

    if 'XAUTHORITY' not in env:
        wayland_auths = glob.glob('/run/user/1000/.mutter-Xwaylandauth.*')
        if wayland_auths:
            env['XAUTHORITY'] = wayland_auths[0]
        else:
            env['XAUTHORITY'] = os.path.expanduser('~/.Xauthority')
    return env


def _run_xdotool(*xdotool_args) -> str:
    """Run an xdotool command and return output."""
    try:
        result = subprocess.run(
            ["xdotool"] + list(xdotool_args),
            capture_output=True, text=True, timeout=5, env=_get_gui_env()
        )
        if result.returncode != 0:
            return f"xdotool error: {result.stderr.strip()}"
        return result.stdout.strip()
    except FileNotFoundError:
        return "xdotool not installed. Run: sudo apt install xdotool"
    except Exception as e:
        return f"xdotool failed: {e}"


# ── Tool Functions ────────────────────────────────────────────────────


def desktop_type(text: str, delay_ms: int = 12) -> str:
    """Type text at current cursor position."""
    if not text:
        return "Text required."

    result = _run_xdotool("type", "--delay", str(delay_ms), text)
    return result or f"Typed: '{text[:50]}{'...' if len(text) > 50 else ''}'"


def desktop_key(key: str) -> str:
    """Press a key or key combo."""
    if not key:
        return "Key required."

    result = _run_xdotool("key", key)
    return result or f"Pressed: {key}"


def desktop_click(x: int, y: int, button: str = "left", double: bool = False) -> str:
    """Click at screen coordinates."""
    button_map = {"left": "1", "right": "3", "middle": "2"}
    btn = button_map.get(button, "1")

    _run_xdotool("mousemove", str(x), str(y))
    if double:
        _run_xdotool("click", "--repeat", "2", btn)
    else:
        _run_xdotool("click", btn)

    return f"Clicked at ({x}, {y}) button={button}{' (double)' if double else ''}"


def desktop_mouse(x: int, y: int) -> str:
    """Move mouse to coordinates."""
    result = _run_xdotool("mousemove", str(x), str(y))
    return result or f"Mouse moved to ({x}, {y})"


def desktop_scroll(direction: str = "down", clicks: int = 3) -> str:
    """Scroll up or down."""
    # xdotool: button 4 = scroll up, button 5 = scroll down
    button = "4" if direction == "up" else "5"
    _run_xdotool("click", "--repeat", str(clicks), button)
    return f"Scrolled {direction} {clicks} clicks"


def desktop_window() -> str:
    """Get the active window title."""
    window_id = _run_xdotool("getactivewindow")
    if "error" in window_id.lower() or "not installed" in window_id.lower():
        return window_id

    name = _run_xdotool("getactivewindow", "getwindowname")
    pid = _run_xdotool("getactivewindow", "getwindowpid")

    return f"Active window: {name}\n  Window ID: {window_id}\n  PID: {pid}"


def desktop_focus(title: str) -> str:
    """Focus a window by title search."""
    if not title:
        return "Window title required."

    window_id = _run_xdotool("search", "--name", title)
    if not window_id or "error" in window_id.lower():
        return f"No window found matching '{title}'."

    first_id = window_id.split("\n")[0].strip()
    _run_xdotool("windowactivate", first_id)
    name = _run_xdotool("getwindowname", first_id)

    return f"Focused window: {name} (ID: {first_id})"


def desktop_open(app: str) -> str:
    """Launch a desktop application."""
    if not app:
        return "Application name required."

    # Security: block dangerous commands
    blocked = ["rm ", "dd ", "mkfs", "shutdown", "reboot", "kill"]
    if any(b in app.lower() for b in blocked):
        return f"Blocked: '{app}' is not allowed."

    try:
        subprocess.Popen(
            app.split(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Launched: {app}"
    except FileNotFoundError:
        return f"Application '{app}' not found."
    except Exception as e:
        return f"Failed to launch '{app}': {e}"


def desktop_screenshot() -> str:
    """Take a screenshot of the desktop.

    Captures using gnome-screenshot, grim, or scrot (whatever's available).
    Returns the file path and a description prompt for the vision system.
    """
    import shutil

    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    filepath = _SCREENSHOT_DIR / filename

    gui_env = _get_gui_env()

    try:
        if shutil.which("gnome-screenshot"):
            cmd = ["gnome-screenshot", "-f", str(filepath)]
        elif shutil.which("grim"):
            cmd = ["grim", str(filepath)]
        else:
            cmd = ["scrot", str(filepath)]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, env=gui_env
        )

        if result.returncode == 0 and filepath.exists():
            return (
                f"Screenshot saved to {filepath}\n"
                f"(Screenshot captured — use LOOK to analyze it visually)"
            )
        return f"Screenshot failed (used {' '.join(cmd)}): {result.stderr.strip()}"
    except Exception as e:
        return f"Screenshot completely failed: {e}"
