"""
Wizard Page 6: Schedule

Configure active hours (sleep/wake) using a dual-handle slider with
live readout. Tick labels are properly edge-aligned to match the slider.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QGroupBox, QSpacerItem, QSizePolicy,
)
from PyQt6.QtCore import Qt
from wizard.ai_helper import AiHelperBanner


def _minutes_to_time(minutes: int) -> str:
    """Convert minutes since midnight to HH:MM string."""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _time_to_minutes(time_str: str) -> int:
    """Convert HH:MM string to minutes since midnight."""
    parts = time_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _make_tick_row() -> QHBoxLayout:
    """Create a tick label row where labels align with slider edges."""
    ticks = ["00:00", "06:00", "12:00", "18:00", "24:00"]
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)

    for i, t in enumerate(ticks):
        lbl = QLabel(t)
        lbl.setStyleSheet("font-size: 10px; color: #666688;")

        # First label: left-aligned, last label: right-aligned, middle: centered
        if i == 0:
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        elif i == len(ticks) - 1:
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row.addWidget(lbl, stretch=1)

    return row


class SchedulePage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 24, 60, 24)
        layout.setSpacing(16)

        heading = QLabel("Active Schedule")
        heading.setProperty("class", "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        sub = QLabel(
            "Set when your agent is active. During sleep hours, the dream engine\n"
            "consolidates memories and crystallizes beliefs. At least 3–4 hours of\n"
            "sleep is recommended for healthy cognitive development."
        )
        sub.setProperty("class", "subheading")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # AI Helper
        self.ai_banner = AiHelperBanner("schedule", self.wizard)
        layout.addWidget(self.ai_banner)

        layout.addSpacing(8)

        # ── Schedule Group ────────────────────────────────────────────
        schedule_group = QGroupBox("Daily Active Window")
        schedule_layout = QVBoxLayout(schedule_group)
        schedule_layout.setSpacing(20)

        # Load current config
        active_hours = self.wizard.config.get("active_hours", {"start": "08:00", "end": "23:00"})
        wake_minutes = _time_to_minutes(active_hours.get("start", "08:00"))
        sleep_minutes = _time_to_minutes(active_hours.get("end", "23:00"))

        # ── Wake Time Slider ──────────────────────────────────────────
        wake_container = QVBoxLayout()
        wake_container.setSpacing(4)
        wake_header = QHBoxLayout()
        wake_header.addWidget(QLabel("☀️  Wake Time"))
        self.wake_label = QLabel(_minutes_to_time(wake_minutes))
        self.wake_label.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 18px; color: #4ade80; font-weight: 700;")
        wake_header.addStretch()
        wake_header.addWidget(self.wake_label)
        wake_container.addLayout(wake_header)

        self.wake_slider = QSlider(Qt.Orientation.Horizontal)
        self.wake_slider.setMinimum(0)
        self.wake_slider.setMaximum(1440)
        self.wake_slider.setValue(wake_minutes)
        self.wake_slider.setSingleStep(15)
        self.wake_slider.setPageStep(60)
        self.wake_slider.valueChanged.connect(self._on_wake_changed)
        wake_container.addWidget(self.wake_slider)

        wake_container.addLayout(_make_tick_row())
        schedule_layout.addLayout(wake_container)

        # ── Sleep Time Slider ─────────────────────────────────────────
        sleep_container = QVBoxLayout()
        sleep_container.setSpacing(4)
        sleep_header = QHBoxLayout()
        sleep_header.addWidget(QLabel("🌙  Sleep Time"))
        self.sleep_label = QLabel(_minutes_to_time(sleep_minutes))
        self.sleep_label.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 18px; color: #818cf8; font-weight: 700;")
        sleep_header.addStretch()
        sleep_header.addWidget(self.sleep_label)
        sleep_container.addLayout(sleep_header)

        self.sleep_slider = QSlider(Qt.Orientation.Horizontal)
        self.sleep_slider.setMinimum(0)
        self.sleep_slider.setMaximum(1440)
        self.sleep_slider.setValue(sleep_minutes)
        self.sleep_slider.setSingleStep(15)
        self.sleep_slider.setPageStep(60)
        self.sleep_slider.valueChanged.connect(self._on_sleep_changed)
        sleep_container.addWidget(self.sleep_slider)

        sleep_container.addLayout(_make_tick_row())
        schedule_layout.addLayout(sleep_container)

        # ── Resting Pulse Rate Slider ─────────────────────────────────
        pulse_container = QVBoxLayout()
        pulse_container.setSpacing(4)
        pulse_header = QHBoxLayout()
        pulse_header.addWidget(QLabel("💓  Resting Pulse Rate"))
        resting_min = self.wizard.config.get("resting_pulse_minutes", 15)
        self.pulse_label = QLabel(f"{resting_min} min")
        self.pulse_label.setStyleSheet(
            "font-family: 'JetBrains Mono', monospace; font-size: 18px; "
            "color: #f59e0b; font-weight: 700;"
        )
        pulse_header.addStretch()
        pulse_header.addWidget(self.pulse_label)
        pulse_container.addLayout(pulse_header)

        self.pulse_slider = QSlider(Qt.Orientation.Horizontal)
        self.pulse_slider.setMinimum(5)
        self.pulse_slider.setMaximum(60)
        self.pulse_slider.setValue(resting_min)
        self.pulse_slider.setSingleStep(1)
        self.pulse_slider.setPageStep(5)
        self.pulse_slider.valueChanged.connect(self._on_pulse_changed)
        pulse_container.addWidget(self.pulse_slider)

        pulse_ticks = QHBoxLayout()
        pulse_ticks.setContentsMargins(0, 0, 0, 0)
        for t in ["5 min", "15 min", "30 min", "60 min"]:
            lbl = QLabel(t)
            lbl.setStyleSheet("font-size: 10px; color: #666688;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pulse_ticks.addWidget(lbl, stretch=1)
        pulse_container.addLayout(pulse_ticks)

        self.pulse_desc = QLabel(
            "How often your agent thinks autonomously when idle. "
            "Lower = more active (costs more API tokens). "
            "Higher = more energy-efficient."
        )
        self.pulse_desc.setStyleSheet("font-size: 11px; color: #8888aa;")
        self.pulse_desc.setWordWrap(True)
        pulse_container.addWidget(self.pulse_desc)

        # Flow mode notice for local providers
        self.flow_mode_label = QLabel(
            "🔄  Local provider detected — Flow Mode active!\n"
            "Your agent will maintain a continuous 30-second pulse with no long "
            "resting intervals. No API costs to worry about."
        )
        self.flow_mode_label.setStyleSheet(
            "font-size: 11px; color: #4ade80; padding: 8px; "
            "background: rgba(74, 222, 128, 0.08); "
            "border: 1px solid rgba(74, 222, 128, 0.25); "
            "border-radius: 8px;"
        )
        self.flow_mode_label.setWordWrap(True)
        self.flow_mode_label.setVisible(False)
        pulse_container.addWidget(self.flow_mode_label)

        schedule_layout.addLayout(pulse_container)

        # ── Summary Readout ───────────────────────────────────────────
        self.summary_label = QLabel()
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_label.setStyleSheet("""
            font-size: 14px; color: #e8e8f0;
            background: rgba(15, 22, 41, 0.7);
            border: 1px solid rgba(42, 42, 94, 0.6);
            border-radius: 10px;
            padding: 16px;
        """)
        schedule_layout.addWidget(self.summary_label)

        # Check if current provider is local and update summary
        self._update_pulse_mode()

        layout.addWidget(schedule_group)

        # Cost info
        cost_note = QLabel(
            "💡 Tip: If you're using paid API providers, shorter active windows and longer pulse\n"
            "intervals reduce costs. Each pulse consumes API tokens."
        )
        cost_note.setStyleSheet("color: #8888aa; font-size: 11px; padding: 8px;")
        cost_note.setWordWrap(True)
        cost_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(cost_note)

        layout.addStretch()

        # Navigation
        nav = QHBoxLayout()
        back_btn = QPushButton("←  Back")
        back_btn.setProperty("class", "secondary")
        back_btn.setFixedWidth(140)
        back_btn.clicked.connect(self.wizard.prev_page)
        nav.addWidget(back_btn)
        nav.addStretch()
        next_btn = QPushButton("Next  →")
        next_btn.setFixedWidth(140)
        next_btn.clicked.connect(self._save_and_next)
        nav.addWidget(next_btn)
        layout.addLayout(nav)

    def _on_wake_changed(self, value):
        # Snap to 15-minute intervals
        snapped = round(value / 15) * 15
        if snapped != value:
            self.wake_slider.blockSignals(True)
            self.wake_slider.setValue(snapped)
            self.wake_slider.blockSignals(False)
        self.wake_label.setText(_minutes_to_time(snapped))
        self._update_summary()

    def _on_sleep_changed(self, value):
        snapped = round(value / 15) * 15
        if snapped != value:
            self.sleep_slider.blockSignals(True)
            self.sleep_slider.setValue(snapped)
            self.sleep_slider.blockSignals(False)
        self.sleep_label.setText(_minutes_to_time(snapped))
        self._update_summary()

    def _on_pulse_changed(self, value):
        self.pulse_label.setText(f"{value} min")
        self._update_summary()

    def _update_summary(self):
        wake = self.wake_slider.value()
        sleep = self.sleep_slider.value()
        pulse = self.pulse_slider.value()
        if sleep > wake:
            active_hours = (sleep - wake) / 60
            sleep_hours = 24 - active_hours
        else:
            active_hours = (1440 - wake + sleep) / 60
            sleep_hours = 24 - active_hours

        is_local = self.wizard.config.get("llm_provider", "gemini") in ("ollama", "llama_cpp")

        if is_local:
            pulse_text = "Resting pulse: continuous flow (30s)"
            daily_text = ""
        else:
            daily_pulses = int(active_hours * 60 / pulse)
            pulse_text = f"Resting pulse: every {pulse} min (~{daily_pulses} autonomous pulses/day)"
            daily_text = ""

        status = ""
        if sleep_hours < 3:
            status = "⚠️  Less than 3 hours of sleep — dream consolidation may be limited"
        elif sleep_hours < 4:
            status = "⚠️  Minimum recommended sleep — consider allowing more rest"
        else:
            status = "✅  Good balance of active and rest time"

        self.summary_label.setText(
            f"Active: {active_hours:.1f} hours  ·  Sleep: {sleep_hours:.1f} hours\n"
            f"Wake {_minutes_to_time(wake)} → Sleep {_minutes_to_time(sleep)}\n"
            f"{pulse_text}\n\n"
            f"{status}"
        )

    def _update_pulse_mode(self):
        """Show/hide pulse slider based on whether provider is local."""
        provider = self.wizard.config.get("llm_provider", "gemini")
        is_local = provider in ("ollama", "llama_cpp")

        self.pulse_slider.setEnabled(not is_local)
        self.pulse_desc.setVisible(not is_local)
        self.flow_mode_label.setVisible(is_local)

        if is_local:
            self.pulse_label.setText("30s")
            self.pulse_label.setStyleSheet(
                "font-family: 'JetBrains Mono', monospace; font-size: 18px; "
                "color: #4ade80; font-weight: 700;"
            )
        else:
            pulse_val = self.pulse_slider.value()
            self.pulse_label.setText(f"{pulse_val} min")
            self.pulse_label.setStyleSheet(
                "font-family: 'JetBrains Mono', monospace; font-size: 18px; "
                "color: #f59e0b; font-weight: 700;"
            )

        self._update_summary()

    def on_enter(self):
        """Called when user navigates to this page — refresh pulse mode."""
        self._update_pulse_mode()

    def _save_and_next(self):
        wake = self.wake_slider.value()
        sleep = self.sleep_slider.value()
        self.wizard.config["active_hours"] = {
            "start": _minutes_to_time(wake),
            "end": _minutes_to_time(sleep),
        }
        self.wizard.config["resting_pulse_minutes"] = self.pulse_slider.value()
        self.wizard.next_page()
