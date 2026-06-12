"""
Settings Tab — Mutable Configuration

Displayed after the wizard completes (or when launching with existing config).
Allows editing of all mutable settings: safety mode, whitelist, tool toggles,
schedule, and comms channels. Does NOT allow changing agent name or bootstrap
profile (those are immutable after creation).
"""

import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QTextEdit, QSlider, QScrollArea,
    QTabWidget, QSpacerItem, QSizePolicy, QComboBox,
)
from PyQt6.QtCore import Qt


class SettingsTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 20, 40, 20)

        heading = QLabel("⚙️  Settings")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #a78bfa;")
        outer.addWidget(heading)

        sub = QLabel("Modify your agent's runtime configuration. Changes are saved immediately.")
        sub.setStyleSheet("font-size: 12px; color: #8888aa; margin-bottom: 12px;")
        outer.addWidget(sub)

        # Scrollable settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        settings_layout = QVBoxLayout(scroll_content)
        settings_layout.setSpacing(16)

        # ── Agent Info (read-only) ────────────────────────────────────
        info_group = QGroupBox("Agent Identity (Read-Only)")
        info_layout = QVBoxLayout(info_group)
        cfg = self.app.config

        name_lbl = QLabel(f"Agent: {cfg.get('agent_name', 'Helix')}  ·  Creator: {cfg.get('creator_name', '')}  ·  Profile: {cfg.get('bootstrap_profile', 'prepared').title()}")
        name_lbl.setStyleSheet("font-size: 12px; color: #8888aa; background: transparent; border: none;")
        info_layout.addWidget(name_lbl)
        settings_layout.addWidget(info_group)

        # ── Safety Mode ───────────────────────────────────────────────
        safety_group = QGroupBox("Safety & Permissions")
        safety_layout = QVBoxLayout(safety_group)

        self.safety_check = QCheckBox("  Enable Safety Mode")
        self.safety_check.setChecked(cfg.get("safety_mode", True))
        self.safety_check.toggled.connect(self._on_safety_changed)
        safety_layout.addWidget(self.safety_check)

        safety_layout.addWidget(QLabel("Whitelist (one entry per line):"))
        self.whitelist_edit = QTextEdit()
        self.whitelist_edit.setFixedHeight(120)
        self.whitelist_edit.setPlainText("\n".join(cfg.get("whitelist", [])))
        safety_layout.addWidget(self.whitelist_edit)

        # Pending requests area
        safety_layout.addWidget(QLabel("Pending Whitelist Requests:"))
        self.pending_area = QLabel("No pending requests")
        self.pending_area.setStyleSheet("""
            background: rgba(15, 22, 41, 0.7);
            border: 1px solid rgba(42, 42, 94, 0.6);
            border-radius: 8px;
            padding: 12px;
            font-size: 11px;
            color: #8888aa;
        """)
        self.pending_area.setWordWrap(True)
        safety_layout.addWidget(self.pending_area)

        settings_layout.addWidget(safety_group)

        # ── Schedule ──────────────────────────────────────────────────
        schedule_group = QGroupBox("Active Schedule")
        schedule_layout = QVBoxLayout(schedule_group)

        active_hours = cfg.get("active_hours", {"start": "08:00", "end": "23:00"})

        wake_row = QHBoxLayout()
        wake_row.addWidget(QLabel("☀️  Wake:"))
        self.wake_slider = QSlider(Qt.Orientation.Horizontal)
        self.wake_slider.setMinimum(0)
        self.wake_slider.setMaximum(1440)
        wake_min = self._time_to_min(active_hours.get("start", "08:00"))
        self.wake_slider.setValue(wake_min)
        self.wake_slider.setSingleStep(15)
        self.wake_label = QLabel(active_hours.get("start", "08:00"))
        self.wake_label.setStyleSheet("font-family: monospace; font-size: 14px; color: #4ade80; font-weight: 700; min-width: 50px;")
        self.wake_slider.valueChanged.connect(self._on_wake_changed)
        wake_row.addWidget(self.wake_slider, stretch=1)
        wake_row.addWidget(self.wake_label)
        schedule_layout.addLayout(wake_row)

        sleep_row = QHBoxLayout()
        sleep_row.addWidget(QLabel("🌙  Sleep:"))
        self.sleep_slider = QSlider(Qt.Orientation.Horizontal)
        self.sleep_slider.setMinimum(0)
        self.sleep_slider.setMaximum(1440)
        sleep_min = self._time_to_min(active_hours.get("end", "23:00"))
        self.sleep_slider.setValue(sleep_min)
        self.sleep_slider.setSingleStep(15)
        self.sleep_label = QLabel(active_hours.get("end", "23:00"))
        self.sleep_label.setStyleSheet("font-family: monospace; font-size: 14px; color: #818cf8; font-weight: 700; min-width: 50px;")
        self.sleep_slider.valueChanged.connect(self._on_sleep_changed)
        sleep_row.addWidget(self.sleep_slider, stretch=1)
        sleep_row.addWidget(self.sleep_label)
        schedule_layout.addLayout(sleep_row)

        # Resting pulse rate
        pulse_row = QHBoxLayout()
        pulse_row.addWidget(QLabel("💓  Resting Pulse:"))
        self.pulse_slider = QSlider(Qt.Orientation.Horizontal)
        self.pulse_slider.setMinimum(5)
        self.pulse_slider.setMaximum(60)
        resting_min = cfg.get("resting_pulse_minutes", 15)
        self.pulse_slider.setValue(resting_min)
        self.pulse_slider.setSingleStep(1)
        self.pulse_slider.setPageStep(5)
        self.pulse_value_label = QLabel(f"{resting_min} min")
        self.pulse_value_label.setStyleSheet(
            "font-family: monospace; font-size: 14px; color: #f59e0b; "
            "font-weight: 700; min-width: 55px;"
        )
        self.pulse_slider.valueChanged.connect(self._on_pulse_changed)
        pulse_row.addWidget(self.pulse_slider, stretch=1)
        pulse_row.addWidget(self.pulse_value_label)
        schedule_layout.addLayout(pulse_row)

        pulse_desc = QLabel(
            "How often the agent pulses autonomously when idle (5–60 min). "
            "Lower = more active, higher = more energy-efficient."
        )
        pulse_desc.setStyleSheet("font-size: 10px; color: #666688; padding-left: 28px;")
        pulse_desc.setWordWrap(True)
        schedule_layout.addWidget(pulse_desc)

        settings_layout.addWidget(schedule_group)

        # ── Tool Toggles ─────────────────────────────────────────────
        tools_group = QGroupBox("Tool Sets")
        tools_layout = QVBoxLayout(tools_group)

        from wizard.pages.tool_selection import TOOLSET_INFO
        self.tool_checks = {}
        current_tools = set(cfg.get("tool_set", ["core"]))

        for ts in TOOLSET_INFO:
            row = QHBoxLayout()
            check = QCheckBox(f"  {ts['name'].upper()}")
            check.setChecked(ts["name"] in current_tools)
            if ts["always_on"]:
                check.setEnabled(False)
                check.setChecked(True)
            self.tool_checks[ts["name"]] = check
            row.addWidget(check)

            desc = QLabel(ts["description"])
            desc.setStyleSheet("font-size: 11px; color: #8888aa; background: transparent; border: none;")
            desc.setWordWrap(True)
            row.addWidget(desc, stretch=1)
            tools_layout.addLayout(row)

        settings_layout.addWidget(tools_group)

        settings_layout.addStretch()
        scroll.setWidget(scroll_content)
        outer.addWidget(scroll, stretch=1)

        # Save button
        save_btn = QPushButton("💾  Save Settings")
        save_btn.setFixedHeight(44)
        save_btn.clicked.connect(self._save_settings)
        outer.addWidget(save_btn)

        # ── Danger Zone ──────────────────────────────────────────────
        outer.addSpacing(20)
        danger_group = QGroupBox("Danger Zone")
        danger_group.setStyleSheet("""
            QGroupBox {
                color: #f87171;
                border: 1px solid rgba(248, 113, 113, 0.3);
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                padding: 0 8px;
            }
        """)
        danger_layout = QVBoxLayout(danger_group)

        danger_desc = QLabel(
            "⚠️ Resetting your agent will permanently delete all memories, beliefs, and learned behaviors.\n"
            "Your API keys and credentials will be preserved. This cannot be undone."
        )
        danger_desc.setWordWrap(True)
        danger_desc.setStyleSheet("font-size: 11px; color: #f87171;")
        danger_layout.addWidget(danger_desc)

        reset_btn = QPushButton("🗑️  Reset Agent & Start Over")
        reset_btn.setFixedHeight(40)
        reset_btn.setStyleSheet("""
            QPushButton {
                background: rgba(248, 113, 113, 0.1);
                border: 1px solid rgba(248, 113, 113, 0.4);
                border-radius: 10px;
                color: #f87171;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background: rgba(248, 113, 113, 0.2);
                border-color: #f87171;
            }
        """)
        reset_btn.clicked.connect(self._on_reset_clicked)
        danger_layout.addWidget(reset_btn)

        outer.addWidget(danger_group)

    def _time_to_min(self, time_str: str) -> int:
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def _min_to_time(self, minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _on_safety_changed(self, checked):
        pass  # Visual only; saved on button click

    def _on_wake_changed(self, value):
        snapped = round(value / 15) * 15
        if snapped != value:
            self.wake_slider.blockSignals(True)
            self.wake_slider.setValue(snapped)
            self.wake_slider.blockSignals(False)
        self.wake_label.setText(self._min_to_time(snapped))

    def _on_sleep_changed(self, value):
        snapped = round(value / 15) * 15
        if snapped != value:
            self.sleep_slider.blockSignals(True)
            self.sleep_slider.setValue(snapped)
            self.sleep_slider.blockSignals(False)
        self.sleep_label.setText(self._min_to_time(snapped))

    def _on_pulse_changed(self, value):
        self.pulse_value_label.setText(f"{value} min")

    def _save_settings(self):
        cfg = self.app.config

        # Safety
        cfg["safety_mode"] = self.safety_check.isChecked()
        wl_text = self.whitelist_edit.toPlainText().strip()
        cfg["whitelist"] = [line.strip() for line in wl_text.split("\n") if line.strip()]

        # Schedule
        cfg["active_hours"] = {
            "start": self._min_to_time(self.wake_slider.value()),
            "end": self._min_to_time(self.sleep_slider.value()),
        }
        cfg["resting_pulse_minutes"] = self.pulse_slider.value()

        # Tools
        selected = []
        for name, check in self.tool_checks.items():
            if check.isChecked():
                selected.append(name)
        cfg["tool_set"] = selected

        # Persist
        from wizard.app import save_config
        save_config(cfg)

    def _on_reset_clicked(self):
        """Show multi-step confirmation before resetting."""
        from PyQt6.QtWidgets import QMessageBox

        agent_name = self.app.config.get("agent_name", "Helix")

        # First confirmation
        msg1 = QMessageBox(self)
        msg1.setWindowTitle("Reset Agent")
        msg1.setIcon(QMessageBox.Icon.Warning)
        msg1.setText(f"Are you sure you want to reset {agent_name}?")
        msg1.setInformativeText(
            "This will permanently delete:\n\n"
            "• All memories and episodic experiences\n"
            "• All learned beliefs and personality development\n"
            "• Journal entries and cognitive history\n"
            "• Tool usage patterns and preferences\n\n"
            "Your API keys and credentials will be kept.\n"
            "This action cannot be undone."
        )
        msg1.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg1.setDefaultButton(QMessageBox.StandardButton.Cancel)

        if msg1.exec() != QMessageBox.StandardButton.Yes:
            return

        # Second confirmation — must type agent name
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Confirm Reset",
            f"Type \"{agent_name}\" to confirm permanent deletion:",
        )
        if not ok or text.strip() != agent_name:
            QMessageBox.information(self, "Reset Cancelled", "Agent name didn't match. No changes were made.")
            return

        # Perform reset
        self._do_reset()

    def _do_reset(self):
        """Actually reset: clear config, wipe data, relaunch wizard."""
        import shutil
        from wizard.app import CONFIG_PATH, BASE_DIR

        # Terminate running agent process first
        if hasattr(self.app, "_agent_process") and self.app._agent_process and self.app._agent_process.poll() is None:
            self.app._agent_process.terminate()
            try:
                self.app._agent_process.wait(timeout=2)
            except Exception:
                self.app._agent_process.kill()
            self.app._agent_process = None

        agent_name = self.app.config.get("agent_name", "Helix")

        # Remove config (but keep credentials.env)
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()

        # Clear agent data directory
        data_dir = BASE_DIR / self.app.config.get("data_dir", "data")
        if data_dir.exists():
            for item in data_dir.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception:
                    pass

        # Reset in-memory config
        self.app.config = {}

        # Rebuild wizard and switch to it
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Agent Reset",
            f"{agent_name} has been reset.\n\nThe setup wizard will now restart."
        )

        # Rebuild wizard pages and switch
        new_wizard = self.app._build_wizard()
        self.app.central.addWidget(new_wizard)
        self.app.wizard_widget = new_wizard
        self.app.central.setCurrentWidget(new_wizard)
