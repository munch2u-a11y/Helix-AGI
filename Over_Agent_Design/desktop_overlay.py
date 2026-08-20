#!/usr/bin/env /home/nemo/Helix/.venv/bin/python
"""Native transparent desktop shell for the Helix WebGL widget.

The browser and window live in this process. A Qt WebChannel object therefore
moves the real OS window directly; drag events never make an HTTP round trip.
"""

import sys
import time
import urllib.request


SERVER_URL = "http://localhost:8080"
WIDGET_CLOSED_SIZE = (280, 320)
WIDGET_OPEN_SIZE = (480, 760)


def calculate_drag_position(
    window_origin: tuple[int, int],
    pointer_origin: tuple[int, int],
    pointer_current: tuple[int, int],
) -> tuple[int, int]:
    """Return the window position that preserves the pointer's grab offset."""
    return (
        window_origin[0] + pointer_current[0] - pointer_origin[0],
        window_origin[1] + pointer_current[1] - pointer_origin[1],
    )


def calculate_anchored_resize_position(
    bottom_right: tuple[int, int], target_size: tuple[int, int]
) -> tuple[int, int]:
    """Resize up/left while keeping the mascot's bottom-right point fixed."""
    return (
        bottom_right[0] - target_size[0] + 1,
        bottom_right[1] - target_size[1] + 1,
    )


def wait_for_server(url: str, timeout_s: float = 10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def launch_pyqt6_native_overlay() -> None:
    from PyQt6.QtCore import QObject, QPoint, QSize, Qt, QTimer, QUrl, pyqtSlot
    from PyQt6.QtGui import QColor, QCursor, QGuiApplication
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication, QMainWindow

    class DesktopBridge(QObject):
        """Small, synchronous JS-to-Qt API for window movement and sizing."""

        def __init__(self, window: "NativeMascotWindow") -> None:
            super().__init__(window)
            self.window = window
            self.drag_active = False
            self.pointer_origin = QPoint()
            self.window_origin = QPoint()

        @pyqtSlot()
        def beginWindowDrag(self) -> None:
            self.drag_active = True
            self.pointer_origin = QCursor.pos()
            self.window_origin = self.window.pos()

        @pyqtSlot()
        def moveWindowDrag(self) -> None:
            if not self.drag_active:
                return
            # Native coordinates avoid browser screenX inconsistencies under
            # Wayland, mixed-DPI monitors, and while the window itself moves.
            current = QCursor.pos()
            new_x, new_y = calculate_drag_position(
                (self.window_origin.x(), self.window_origin.y()),
                (self.pointer_origin.x(), self.pointer_origin.y()),
                (current.x(), current.y()),
            )
            self.window.move(new_x, new_y)

        @pyqtSlot()
        def endWindowDrag(self) -> None:
            self.drag_active = False

        @pyqtSlot(bool)
        def setDrawerOpen(self, is_open: bool) -> None:
            self.window.set_drawer_open(is_open)

    class NativeMascotWindow(QMainWindow):
        CLOSED_SIZE = QSize(*WIDGET_CLOSED_SIZE)
        OPEN_SIZE = QSize(*WIDGET_OPEN_SIZE)

        def __init__(self) -> None:
            super().__init__()
            self.drawer_open = False
            self.setWindowTitle("Helix Desktop Agent")
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.NoDropShadowWindowHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.resize(self.CLOSED_SIZE)

            self.web = QWebEngineView(self)
            self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.web.setStyleSheet("background: transparent;")
            self.web.page().setBackgroundColor(QColor(0, 0, 0, 0))
            self.setCentralWidget(self.web)

            self.bridge = DesktopBridge(self)
            self.channel = QWebChannel(self.web.page())
            self.channel.registerObject("helixDesktop", self.bridge)
            self.web.page().setWebChannel(self.channel)
            self.web.load(QUrl(SERVER_URL))

            QTimer.singleShot(0, self.move_to_initial_position)

        def move_to_initial_position(self) -> None:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()
            margin = 18
            self.move(
                area.right() - self.width() - margin + 1,
                area.bottom() - self.height() - margin + 1,
            )

        def set_drawer_open(self, is_open: bool) -> None:
            is_open = bool(is_open)
            if self.drawer_open == is_open:
                return
            self.drawer_open = is_open

            # Keep the mascot anchored to the same desktop point while the
            # transparent shell expands left/up to make room for the drawer.
            anchor = self.frameGeometry().bottomRight()
            target_size = self.OPEN_SIZE if is_open else self.CLOSED_SIZE
            self.resize(target_size)
            new_x, new_y = calculate_anchored_resize_position(
                (anchor.x(), anchor.y()),
                (target_size.width(), target_size.height()),
            )
            self.move(new_x, new_y)

    app = QApplication(sys.argv)
    app.setApplicationName("Helix Desktop Agent")
    window = NativeMascotWindow()
    window.show()
    print("  ✓ Native transparent Helix widget active (direct Qt dragging + real-time WebGL)")
    raise SystemExit(app.exec())


def launch_native_overlay() -> None:
    print("=====================================================================")
    print(" 🚀 LAUNCHING NATIVE SYSTEM-WIDE DESKTOP FLOATING OVERLAY WINDOW")
    print("=====================================================================")
    if not wait_for_server(SERVER_URL):
        print(f"  ⚠️ Warning: Server at {SERVER_URL} is not responding. Starting overlay anyway...")
    launch_pyqt6_native_overlay()


if __name__ == "__main__":
    launch_native_overlay()
