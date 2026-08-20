#!/usr/bin/env python3
"""Native transparent desktop shell for the Helix widget.

The browser and native window live in one process.  A Qt WebChannel bridge
moves the real operating-system window directly, so dragging does not depend
on HTTP requests or browser screen-coordinate quirks.
"""

from __future__ import annotations

import os
import sys
from typing import Tuple


DEFAULT_WIDGET_URL = "http://127.0.0.1:5050/widget/"
WIDGET_CLOSED_SIZE = (300, 350)
WIDGET_OPEN_SIZE = (500, 760)


def calculate_drag_position(
    window_origin: Tuple[int, int],
    pointer_origin: Tuple[int, int],
    pointer_current: Tuple[int, int],
) -> Tuple[int, int]:
    """Return the window position that preserves the pointer grab offset."""
    return (
        window_origin[0] + pointer_current[0] - pointer_origin[0],
        window_origin[1] + pointer_current[1] - pointer_origin[1],
    )


def calculate_anchored_resize_position(
    bottom_right: Tuple[int, int], target_size: Tuple[int, int]
) -> Tuple[int, int]:
    """Resize up and left while keeping the bottom-right anchor fixed."""
    return (
        bottom_right[0] - target_size[0] + 1,
        bottom_right[1] - target_size[1] + 1,
    )


def launch_native_overlay(widget_url: str | None = None) -> None:
    """Launch the always-on-top transparent widget window."""
    from PyQt6.QtCore import QObject, QPoint, QSize, Qt, QTimer, QUrl, pyqtSlot
    from PyQt6.QtGui import QColor, QCursor, QGuiApplication
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication, QMainWindow

    target_url = widget_url or os.environ.get("HELIX_WIDGET_URL", DEFAULT_WIDGET_URL)

    class DesktopBridge(QObject):
        """Synchronous JavaScript-to-Qt window movement and sizing API."""

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
            self.window.set_drawer_open(bool(is_open))

        @pyqtSlot()
        def closeWidget(self) -> None:
            self.window.close()

    class NativeMascotWindow(QMainWindow):
        CLOSED_SIZE = QSize(*WIDGET_CLOSED_SIZE)
        OPEN_SIZE = QSize(*WIDGET_OPEN_SIZE)

        def __init__(self) -> None:
            super().__init__()
            self.drawer_open = False
            self.setWindowTitle("Helix Desktop Widget")
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
            self.web.load(QUrl(target_url))

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
            if self.drawer_open == is_open:
                return
            self.drawer_open = is_open
            anchor = self.frameGeometry().bottomRight()
            target_size = self.OPEN_SIZE if is_open else self.CLOSED_SIZE
            self.resize(target_size)
            new_x, new_y = calculate_anchored_resize_position(
                (anchor.x(), anchor.y()),
                (target_size.width(), target_size.height()),
            )
            self.move(new_x, new_y)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Helix Desktop Widget")
    window = NativeMascotWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    launch_native_overlay()
