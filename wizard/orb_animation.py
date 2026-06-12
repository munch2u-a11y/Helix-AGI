"""
Wizard Orb Animation System

Floating light orbs that fill progress circles as users complete each step.
On final creation, the orbs orbit and collapse into a singularity.
"""

import math
import random
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import (
    QPainter, QColor, QRadialGradient, QPen, QPainterPath,
)


# Distinct colors for each wizard step orb
ORB_COLORS = [
    QColor(74, 222, 128),    # Green — Welcome
    QColor(251, 191, 36),    # Gold — Credentials
    QColor(167, 139, 250),   # Purple — Identity
    QColor(59, 130, 246),    # Blue — Tools
    QColor(248, 113, 113),   # Red — Safety
    QColor(129, 140, 248),   # Indigo — Schedule
    QColor(244, 114, 182),   # Pink — Summary
]


class Orb:
    """A single animated light orb."""

    def __init__(self, color: QColor, start: QPointF, target: QPointF):
        self.color = color
        self.pos = QPointF(start)
        self.start = QPointF(start)
        self.target = QPointF(target)
        self.radius = 8.0
        self.alpha = 0.0  # Fade in
        self.progress = 0.0  # 0 → 1 travel
        self.settled = False
        self.glow_phase = random.uniform(0, math.pi * 2)

        # Orbit state (used during collapse animation)
        self.orbit_angle = random.uniform(0, math.pi * 2)
        self.orbit_radius = 0.0
        self.orbit_speed = random.uniform(2.0, 4.0)

    def update_travel(self, dt: float):
        """Animate toward target with easing."""
        if self.settled:
            return

        self.alpha = min(1.0, self.alpha + dt * 4)
        self.progress = min(1.0, self.progress + dt * 2.0)

        # Cubic ease-out
        t = 1 - (1 - self.progress) ** 3

        # Add a gentle arc (sine wave offset)
        arc = math.sin(self.progress * math.pi) * 40

        self.pos.setX(self.start.x() + (self.target.x() - self.start.x()) * t)
        self.pos.setY(self.start.y() + (self.target.y() - self.start.y()) * t - arc)

        if self.progress >= 1.0:
            self.pos = QPointF(self.target)
            self.settled = True

    def update_glow(self, time: float):
        """Pulsing glow effect."""
        self.glow_phase += 0.05
        self.radius = 7.0 + math.sin(self.glow_phase) * 2.0


class OrbOverlay(QWidget):
    """
    Transparent overlay that draws animated orbs over the wizard.
    Sits on top of the entire wizard widget.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        self.orbs: list[Orb] = []
        self._time = 0.0
        self._collapse_mode = False
        self._collapse_progress = 0.0
        self._collapse_center = QPointF(0, 0)
        self._collapse_done = False
        self._collapse_callback = None
        self._particle_trails = []  # sparkle trails

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # ~60fps

    def spawn_orb(self, step_index: int, start_pos: QPointF, target_pos: QPointF):
        """Spawn a new orb that travels from start to target (the progress circle)."""
        color = ORB_COLORS[step_index % len(ORB_COLORS)]
        orb = Orb(color, start_pos, target_pos)
        self.orbs.append(orb)

    def start_collapse(self, center: QPointF, callback=None):
        """
        Begin the collapse animation: all orbs orbit the center, then collapse.
        Calls callback() when the collapse animation completes.
        """
        self._collapse_mode = True
        self._collapse_progress = 0.0
        self._collapse_center = center
        self._collapse_done = False
        self._collapse_callback = callback

        # Set all orbs to orbit mode
        for i, orb in enumerate(self.orbs):
            orb.orbit_angle = (2 * math.pi / max(len(self.orbs), 1)) * i
            orb.orbit_radius = 120.0
            orb.orbit_speed = 1.5 + i * 0.3

    def _tick(self):
        """Animation frame update."""
        dt = 0.016
        self._time += dt

        if self._collapse_mode:
            self._update_collapse(dt)
        else:
            for orb in self.orbs:
                if not orb.settled:
                    orb.update_travel(dt)
                orb.update_glow(self._time)

        # Update particle trails
        self._particle_trails = [
            (p, a - dt * 2, r) for p, a, r in self._particle_trails if a > 0
        ]

        self.update()

    def _update_collapse(self, dt: float):
        """Update the orbital collapse animation."""
        self._collapse_progress += dt * 0.4  # ~2.5 second total animation

        cx = self._collapse_center.x()
        cy = self._collapse_center.y()

        # Phase 1 (0 → 0.6): Orbit and spin up
        # Phase 2 (0.6 → 1.0): Collapse inward
        for orb in self.orbs:
            if self._collapse_progress < 0.6:
                # Orbiting phase — speed increases
                speed_mult = 1 + self._collapse_progress * 8
                orb.orbit_angle += dt * orb.orbit_speed * speed_mult
                orb.orbit_radius = 120.0 - self._collapse_progress * 30
            else:
                # Collapse phase
                collapse_t = (self._collapse_progress - 0.6) / 0.4
                ease_t = collapse_t ** 2
                orb.orbit_angle += dt * orb.orbit_speed * 6
                orb.orbit_radius = max(0, 90 * (1 - ease_t))

            orb.pos.setX(cx + math.cos(orb.orbit_angle) * orb.orbit_radius)
            orb.pos.setY(cy + math.sin(orb.orbit_angle) * orb.orbit_radius)

            # Spawn sparkle trails
            if random.random() < 0.3:
                self._particle_trails.append(
                    (QPointF(orb.pos), 1.0, orb.radius * 0.5)
                )

            orb.update_glow(self._time)

        if self._collapse_progress >= 1.0 and not self._collapse_done:
            self._collapse_done = True
            # Final flash — all orbs converge
            for orb in self.orbs:
                orb.pos = QPointF(cx, cy)
                orb.radius = 3.0
            if self._collapse_callback:
                QTimer.singleShot(600, self._collapse_callback)

    def paintEvent(self, event):
        """Draw all orbs with glow effects."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw particle trails first (behind orbs)
        for pos, alpha, radius in self._particle_trails:
            color = QColor(167, 139, 250, int(alpha * 60))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(pos, radius, radius)

        # Draw orbs
        for orb in self.orbs:
            if orb.alpha <= 0:
                continue

            alpha = orb.alpha
            r = orb.radius

            # Outer glow (large, faint)
            glow_r = r * 4
            gradient = QRadialGradient(orb.pos, glow_r)
            glow_color = QColor(orb.color)
            glow_color.setAlpha(int(40 * alpha))
            gradient.setColorAt(0, glow_color)
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(orb.pos, glow_r, glow_r)

            # Inner glow
            inner_r = r * 2
            gradient2 = QRadialGradient(orb.pos, inner_r)
            mid_color = QColor(orb.color)
            mid_color.setAlpha(int(120 * alpha))
            gradient2.setColorAt(0, QColor(255, 255, 255, int(200 * alpha)))
            gradient2.setColorAt(0.3, mid_color)
            gradient2.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setBrush(gradient2)
            painter.drawEllipse(orb.pos, inner_r, inner_r)

            # Core (bright white center)
            core_r = r * 0.6
            core_gradient = QRadialGradient(orb.pos, core_r)
            core_gradient.setColorAt(0, QColor(255, 255, 255, int(240 * alpha)))
            core_gradient.setColorAt(1, QColor(orb.color.red(), orb.color.green(), orb.color.blue(), int(180 * alpha)))
            painter.setBrush(core_gradient)
            painter.drawEllipse(orb.pos, core_r, core_r)

        # Collapse flash effect
        if self._collapse_mode and self._collapse_done:
            flash_alpha = max(0, 1.0 - (self._time % 1.0) * 2)
            if flash_alpha > 0:
                cx = self._collapse_center.x()
                cy = self._collapse_center.y()
                center = QPointF(cx, cy)
                flash_r = 60 * flash_alpha
                gradient = QRadialGradient(center, flash_r)
                gradient.setColorAt(0, QColor(255, 255, 255, int(200 * flash_alpha)))
                gradient.setColorAt(0.5, QColor(167, 139, 250, int(100 * flash_alpha)))
                gradient.setColorAt(1, QColor(0, 0, 0, 0))
                painter.setBrush(gradient)
                painter.drawEllipse(center, flash_r, flash_r)

        painter.end()

    def clear(self):
        """Reset all orbs."""
        self.orbs.clear()
        self._particle_trails.clear()
        self._collapse_mode = False
        self._collapse_progress = 0.0
        self._collapse_done = False
        self.update()
