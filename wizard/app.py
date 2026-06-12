"""
Helix‑AGI — Setup Wizard & Dashboard (PyQt6)

Standalone desktop application that provides:
  1. A multi-step setup wizard for first-time configuration
  2. An embedded dashboard (QWebEngineView) for monitoring the running agent
  3. A settings tab for editing mutable configuration after launch

Usage:
    python -m wizard.app            # Launch the wizard/dashboard
    python -m wizard.app --wizard   # Force wizard mode even if config exists
"""

import sys
import os
import json
import subprocess
import threading
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QMessageBox, QTabWidget,
    QSizePolicy, QFrame, QGraphicsDropShadowEffect, QDialog,
    QTextEdit, QProgressBar,
)
from PyQt6.QtCore import Qt, QSize, QUrl, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QIcon, QPalette, QLinearGradient, QBrush

logger = logging.getLogger("helix.wizard")

# ── Path Constants ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"
CRED_DIR = Path(os.path.expanduser("~/.config/helix"))
CRED_PATH = CRED_DIR / "credentials.env"


# ── Default Config Schema ─────────────────────────────────────────────
DEFAULT_CONFIG = {
    "agent_name": "Helix",
    "creator_name": "",
    "data_dir": "data",
    "llm_provider": "gemini",
    "model_name": "",
    "telegram_enabled": False,
    "telegram_token": "",
    "telegram_owner_id": "",
    "discord_enabled": False,
    "discord_token": "",
    "tool_set": ["core"],
    "safety_mode": True,
    "whitelist": [],
    "active_hours": {"start": "08:00", "end": "23:00"},
    "resting_pulse_minutes": 15,
    "bootstrap_profile": "prepared",
    "personality": "curious",
    "vision_provider": "local",
    "ai_assist": False,
}


def load_config() -> dict:
    """Load config.json, falling back to defaults."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            # Merge with defaults for any missing keys
            merged = dict(DEFAULT_CONFIG)
            merged.update(cfg)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    """Save config to config/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def config_exists() -> bool:
    """Check if a completed wizard config exists (not just a template)."""
    if not CONFIG_PATH.exists():
        return False
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        return cfg.get("setup_complete", False)
    except Exception:
        return False


# ── Color Theme ───────────────────────────────────────────────────────
class Theme:
    """Bubbly purple/grey design tokens."""
    BG_DARK = "#1a1a2e"
    BG_PANEL = "#16213e"
    BG_CARD = "#1e2a4a"
    BG_INPUT = "#0f1629"
    BORDER = "#2a2a5e"
    TEXT = "#e8e8f0"
    TEXT_DIM = "#8888aa"
    TEXT_MUTED = "#666688"
    ACCENT = "#7c3aed"       # Vivid purple
    ACCENT_HOVER = "#6d28d9"
    ACCENT_LIGHT = "#a78bfa"
    ACCENT_GLOW = "#c4b5fd"
    SUCCESS = "#4ade80"
    WARNING = "#fbbf24"
    DANGER = "#f87171"
    BUBBLE_1 = "#7c3aed"
    BUBBLE_2 = "#6366f1"
    BUBBLE_3 = "#818cf8"

    @staticmethod
    def stylesheet() -> str:
        """Return the global application stylesheet."""
        return f"""
            QMainWindow {{
                background-color: {Theme.BG_DARK};
            }}
            QWidget {{
                color: {Theme.TEXT};
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 13px;
            }}
            QLabel {{
                color: {Theme.TEXT};
            }}
            QLabel[class="heading"] {{
                font-size: 28px;
                font-weight: 700;
                color: {Theme.ACCENT_LIGHT};
            }}
            QLabel[class="subheading"] {{
                font-size: 15px;
                color: {Theme.TEXT_DIM};
                font-weight: 400;
            }}
            QLabel[class="section"] {{
                font-size: 14px;
                font-weight: 600;
                color: {Theme.ACCENT_GLOW};
                letter-spacing: 1px;
                margin-top: 12px;
            }}
            QLabel[class="description"] {{
                font-size: 12px;
                color: {Theme.TEXT_DIM};
                line-height: 1.5;
            }}
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {Theme.ACCENT}, stop:1 {Theme.BUBBLE_2});
                border: none;
                border-radius: 10px;
                padding: 10px 28px;
                color: white;
                font-size: 14px;
                font-weight: 600;
                min-height: 36px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {Theme.ACCENT_HOVER}, stop:1 {Theme.ACCENT});
            }}
            QPushButton:pressed {{
                background: {Theme.ACCENT_HOVER};
            }}
            QPushButton[class="secondary"] {{
                background: transparent;
                border: 1px solid {Theme.BORDER};
                color: {Theme.ACCENT_LIGHT};
            }}
            QPushButton[class="secondary"]:hover {{
                background: rgba(124, 58, 237, 0.15);
                border-color: {Theme.ACCENT};
            }}
            QLineEdit, QTextEdit {{
                background: #2a2f4a;
                border: 1px solid {Theme.BORDER};
                border-radius: 8px;
                padding: 8px 12px;
                color: {Theme.TEXT};
                font-size: 13px;
                selection-background-color: {Theme.ACCENT};
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border-color: {Theme.ACCENT};
                background: #303558;
            }}
            QComboBox {{
                background: {Theme.BG_INPUT};
                border: 1px solid {Theme.BORDER};
                border-radius: 8px;
                padding: 8px 12px;
                color: {Theme.TEXT};
                font-size: 13px;
                min-height: 32px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 30px;
            }}
            QComboBox QAbstractItemView {{
                background: {Theme.BG_PANEL};
                border: 1px solid {Theme.BORDER};
                selection-background-color: {Theme.ACCENT};
                color: {Theme.TEXT};
            }}
            QCheckBox {{
                spacing: 8px;
                font-size: 13px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {Theme.BORDER};
                background: {Theme.BG_INPUT};
            }}
            QCheckBox::indicator:checked {{
                background: {Theme.ACCENT};
                border-color: {Theme.ACCENT};
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {Theme.BORDER};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 18px;
                height: 18px;
                margin: -6px 0;
                background: {Theme.ACCENT};
                border-radius: 9px;
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Theme.ACCENT}, stop:1 {Theme.BUBBLE_3});
                border-radius: 3px;
            }}
            QGroupBox {{
                background: {Theme.BG_CARD};
                border: 1px solid {Theme.BORDER};
                border-radius: 12px;
                padding: 16px;
                margin-top: 12px;
                font-weight: 600;
                font-size: 13px;
            }}
            QGroupBox::title {{
                color: {Theme.ACCENT_LIGHT};
                subcontrol-origin: margin;
                padding: 0 8px;
            }}
            QTabWidget::pane {{
                background: {Theme.BG_DARK};
                border: 1px solid {Theme.BORDER};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background: {Theme.BG_PANEL};
                border: 1px solid {Theme.BORDER};
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 20px;
                color: {Theme.TEXT_DIM};
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background: {Theme.BG_DARK};
                color: {Theme.ACCENT_LIGHT};
                border-bottom: 2px solid {Theme.ACCENT};
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {Theme.BG_DARK};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {Theme.BORDER};
                border-radius: 4px;
                min-height: 30px;
            }}
        """


# ── Progress Indicator ────────────────────────────────────────────────
class WizardProgressBar(QWidget):
    """Visual step indicator at the top of the wizard."""

    def __init__(self, steps: list, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.current = 0
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(40, 16, 40, 16)
        self.dots = []
        self.labels = []

        for i, name in enumerate(self.steps):
            step_w = QWidget()
            step_layout = QVBoxLayout(step_w)
            step_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step_layout.setSpacing(6)

            dot = QLabel()
            dot.setFixedSize(32, 32)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setText(str(i + 1))
            dot.setStyleSheet(self._dot_style(i))
            step_layout.addWidget(dot, alignment=Qt.AlignmentFlag.AlignCenter)

            lbl = QLabel(name)
            lbl.setStyleSheet(f"font-size: 10px; color: {Theme.TEXT_DIM};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step_layout.addWidget(lbl)

            self.dots.append(dot)
            self.labels.append(lbl)
            layout.addWidget(step_w)

            if i < len(self.steps) - 1:
                line = QFrame()
                line.setFixedHeight(2)
                line.setStyleSheet(f"background: {Theme.BORDER};")
                line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                layout.addWidget(line, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _dot_style(self, index: int) -> str:
        if index < self.current:
            # Completed — subtle bg so the orb glow dominates
            color = self._orb_color(index)
            return f"""
                background: rgba({color}, 0.2); border-radius: 16px;
                color: white; font-weight: 700; font-size: 13px;
                border: 2px solid rgba({color}, 0.6);
            """
        elif index == self.current:
            return f"""
                background: {Theme.ACCENT}; border-radius: 16px;
                color: white; font-weight: 700; font-size: 13px;
                border: 2px solid {Theme.ACCENT_GLOW};
            """
        else:
            return f"""
                background: {Theme.BG_CARD}; border-radius: 16px;
                color: {Theme.TEXT_DIM}; font-weight: 500; font-size: 13px;
                border: 1px solid {Theme.BORDER};
            """

    @staticmethod
    def _orb_color(index: int) -> str:
        """RGB string for orb color matching the animation."""
        colors = [
            "74, 222, 128",   # Green
            "251, 191, 36",   # Gold
            "167, 139, 250",  # Purple
            "59, 130, 246",   # Blue
            "248, 113, 113",  # Red
            "129, 140, 248",  # Indigo
            "244, 114, 182",  # Pink
        ]
        return colors[index % len(colors)]

    def set_step(self, index: int):
        self.current = index
        for i in range(len(self.steps)):
            self.dots[i].setStyleSheet(self._dot_style(i))
            if i <= index:
                self.labels[i].setStyleSheet(f"font-size: 10px; color: {Theme.TEXT};")
            else:
                self.labels[i].setStyleSheet(f"font-size: 10px; color: {Theme.TEXT_DIM};")


# ── Main Window ───────────────────────────────────────────────────────
class HelixApp(QMainWindow):
    """Main application window combining wizard and dashboard."""

    launch_signal = pyqtSignal()

    def __init__(self, force_wizard: bool = False):
        super().__init__()
        self.setWindowTitle("Helix‑AGI")
        self.setWindowIcon(QIcon(str(BASE_DIR / "wizard" / "assets" / "helix_logo.png")))
        self.setMinimumSize(960, 680)
        self.resize(1100, 750)

        self.config = load_config()
        self._flask_thread = None
        self._agent_process = None

        # Central widget
        self.central = QStackedWidget()
        self.setCentralWidget(self.central)

        # Wizard mode
        self.wizard_widget = self._build_wizard()
        self.central.addWidget(self.wizard_widget)

        # Dashboard mode (lazy‑loaded on launch)
        self.dashboard_widget = None

        self.launch_signal.connect(self._on_launch_complete)

        if config_exists() and not force_wizard:
            self._switch_to_dashboard()

    def _on_launch_complete(self):
        """Signal handler for when background launch finishes."""
        self._switch_to_dashboard()

    def _build_wizard(self) -> QWidget:
        """Build the multi-step wizard UI."""
        from wizard.pages.welcome import WelcomePage
        from wizard.pages.credentials import CredentialsPage
        from wizard.pages.agent_info import AgentInfoPage
        from wizard.pages.tool_selection import ToolSelectionPage
        from wizard.pages.safety import SafetyPage
        from wizard.pages.schedule import SchedulePage
        from wizard.pages.summary import SummaryPage
        from wizard.orb_animation import OrbOverlay

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        container.setStyleSheet(f"background: {Theme.BG_DARK};")

        # Step names
        step_names = ["Welcome", "Credentials", "Identity", "Tools", "Safety", "Schedule", "Review"]
        self.progress_bar = WizardProgressBar(step_names)
        layout.addWidget(self.progress_bar)

        # Page stack
        self.page_stack = QStackedWidget()
        self.pages = [
            WelcomePage(self),
            CredentialsPage(self),
            AgentInfoPage(self),
            ToolSelectionPage(self),
            SafetyPage(self),
            SchedulePage(self),
            SummaryPage(self),
        ]
        for page in self.pages:
            self.page_stack.addWidget(page)

        layout.addWidget(self.page_stack, stretch=1)

        # Orb animation overlay — sits on top of everything
        self.orb_overlay = OrbOverlay(container)
        self.orb_overlay.raise_()

        # Resize overlay when container resizes
        container.resizeEvent = lambda e: self.orb_overlay.setGeometry(container.rect())

        return container

    def _get_dot_center(self, step_index: int) -> 'QPointF':
        """Get the center position of a progress circle in overlay coordinates."""
        from PyQt6.QtCore import QPointF
        dot = self.progress_bar.dots[step_index]
        # Map dot center to the wizard container's coordinate space
        pos = dot.mapTo(self.wizard_widget, dot.rect().center())
        return QPointF(pos.x(), pos.y())

    def next_page(self):
        idx = self.page_stack.currentIndex()
        if idx < len(self.pages) - 1:
            # Spawn an orb from center of current page up to the completed step circle
            if hasattr(self, 'orb_overlay'):
                from PyQt6.QtCore import QPointF
                # Start from center-bottom of the current page
                page_rect = self.page_stack.mapTo(self.wizard_widget, self.page_stack.rect().center())
                start = QPointF(page_rect.x(), page_rect.y() + 60)
                target = self._get_dot_center(idx)
                self.orb_overlay.spawn_orb(idx, start, target)

            self.page_stack.setCurrentIndex(idx + 1)
            self.progress_bar.set_step(idx + 1)
            # Let pages update when they become visible
            next_page = self.pages[idx + 1]
            if hasattr(next_page, "on_enter"):
                next_page.on_enter()
            # Refresh AI helper visibility
            if hasattr(next_page, "ai_banner"):
                next_page.ai_banner.refresh()

    def prev_page(self):
        idx = self.page_stack.currentIndex()
        if idx > 0:
            self.page_stack.setCurrentIndex(idx - 1)
            self.progress_bar.set_step(idx - 1)
            prev_widget = self.page_stack.currentWidget()
            if hasattr(prev_widget, "on_enter"):
                prev_widget.on_enter()

    def finish_wizard(self):
        """Called when user clicks 'Create <Agent Name>' on summary page."""
        self.config["setup_complete"] = True
        save_config(self.config)
        self._write_credentials()

        # Create desktop shortcuts if checked on the summary page
        try:
            summary_page = self.pages[-1]
            create_wizard = summary_page.shortcut_wizard_chk.isChecked()
            create_agent = summary_page.shortcut_agent_chk.isChecked()
            if create_wizard or create_agent:
                self._create_desktop_shortcuts(create_wizard, create_agent)
        except Exception as e:
            logger.warning(f"Failed to create desktop shortcuts: {e}")

        # Spawn the final orb for the Review step
        if hasattr(self, 'orb_overlay') and self.orb_overlay.orbs:
            from PyQt6.QtCore import QPointF
            page_rect = self.page_stack.mapTo(self.wizard_widget, self.page_stack.rect().center())
            start = QPointF(page_rect.x(), page_rect.y() + 60)
            target = self._get_dot_center(len(self.pages) - 1)
            self.orb_overlay.spawn_orb(len(self.pages) - 1, start, target)

            # Wait for it to settle, then start collapse
            QTimer.singleShot(800, self._start_orb_collapse)
        else:
            # No orbs (skipped wizard), proceed directly
            self._install_dependencies()

    def _start_orb_collapse(self):
        """Trigger the orbital collapse animation."""
        from PyQt6.QtCore import QPointF
        # Collapse center = center of the page stack area
        center_pt = self.page_stack.mapTo(
            self.wizard_widget, self.page_stack.rect().center()
        )
        center = QPointF(center_pt.x(), center_pt.y())

        # Dim the wizard content during animation
        for page in self.pages:
            page.setEnabled(False)

        self.orb_overlay.start_collapse(center, callback=self._on_collapse_done)

    def _on_collapse_done(self):
        """Called when the orb collapse animation finishes."""
        # Clean up overlay
        if hasattr(self, 'orb_overlay'):
            self.orb_overlay.clear()
        self._install_dependencies()

    def _install_dependencies(self):
        """Install requirements.txt in a progress dialog, then bootstrap."""
        req_file = BASE_DIR / "requirements.txt"
        if not req_file.exists():
            self._run_bootstrap()
            self._switch_to_dashboard()
            return

        # Build the progress dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Installing Dependencies")
        dlg.setMinimumSize(620, 420)
        dlg.setStyleSheet(f"background: {Theme.BG_DARK}; color: {Theme.TEXT};")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        heading = QLabel("📦  Installing Dependencies...")
        heading.setStyleSheet("font-size: 18px; font-weight: 700; color: #a78bfa;")
        layout.addWidget(heading)

        sub = QLabel("This may take a minute. Helix needs these packages to run.")
        sub.setStyleSheet("font-size: 12px; color: #8888aa;")
        layout.addWidget(sub)

        progress = QProgressBar()
        progress.setRange(0, 0)  # Indeterminate
        progress.setFixedHeight(6)
        progress.setStyleSheet(f"""
            QProgressBar {{
                background: {Theme.BORDER}; border: none; border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {Theme.ACCENT}, stop:1 {Theme.BUBBLE_3});
                border-radius: 3px;
            }}
        """)
        layout.addWidget(progress)

        log_output = QTextEdit()
        log_output.setReadOnly(True)
        log_output.setStyleSheet(f"""
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 11px;
            background: {Theme.BG_INPUT};
            color: #88cc88;
            border: 1px solid {Theme.BORDER};
            border-radius: 8px;
            padding: 8px;
        """)
        layout.addWidget(log_output, stretch=1)

        status_label = QLabel("")
        status_label.setStyleSheet("font-size: 12px; color: #8888aa;")
        layout.addWidget(status_label)

        dlg.show()
        QApplication.processEvents()

        # Thread-safe output buffer (QTimer polling — signals can't be added at runtime)
        self._install_lines = []
        self._install_rc = None

        def _install_thread():
            try:
                cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=str(BASE_DIR)
                )
                for line in proc.stdout:
                    self._install_lines.append(line.rstrip())
                proc.wait()
                self._install_rc = proc.returncode
            except Exception as e:
                self._install_lines.append(f"❌ Error: {e}")
                self._install_rc = 1

        thread = threading.Thread(target=_install_thread, daemon=True)
        thread.start()

        # Poll for output
        def _poll():
            while self._install_lines:
                line = self._install_lines.pop(0)
                log_output.append(line)
                # Auto-scroll
                log_output.verticalScrollBar().setValue(
                    log_output.verticalScrollBar().maximum()
                )

            if self._install_rc is not None:
                poll_timer.stop()
                progress.setRange(0, 1)
                progress.setValue(1)

                if self._install_rc == 0:
                    status_label.setText("✅  All dependencies installed successfully!")
                    status_label.setStyleSheet("font-size: 13px; color: #4ade80; font-weight: 600;")
                    log_output.append("\n✅ Done!")
                else:
                    status_label.setText("⚠️  Some packages may have failed — the dashboard may not work fully.")
                    status_label.setStyleSheet("font-size: 13px; color: #fbbf24; font-weight: 600;")
                    log_output.append("\n⚠️ Completed with warnings.")

                # Auto-close after a moment and proceed
                QTimer.singleShot(1500, lambda: self._finish_after_install(dlg))

        poll_timer = QTimer()
        poll_timer.timeout.connect(_poll)
        poll_timer.start(200)

    def _finish_after_install(self, dlg):
        """Close install dialog and proceed with bootstrap + dashboard."""
        dlg.close()
        self._run_bootstrap()
        self._switch_to_dashboard()

    def _write_credentials(self):
        """Write credentials.env from wizard config."""
        CRED_DIR.mkdir(parents=True, exist_ok=True)

        # Read existing credentials to preserve keys we don't manage
        existing = {}
        if CRED_PATH.exists():
            with open(CRED_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        existing[k.strip()] = v.strip().strip('"')

        # Merge wizard values
        creds = existing.copy()
        creds["GEMINI_API_KEY"] = self.config.get("gemini_api_key", creds.get("GEMINI_API_KEY", ""))
        creds["ANTHROPIC_API_KEY"] = self.config.get("anthropic_api_key", creds.get("ANTHROPIC_API_KEY", ""))
        creds["OPENAI_API_KEY"] = self.config.get("openai_api_key", creds.get("OPENAI_API_KEY", ""))
        creds["ALIBABA_API_KEY"] = self.config.get("alibaba_api_key", creds.get("ALIBABA_API_KEY", ""))
        creds["OLLAMA_URL"] = self.config.get("ollama_url", creds.get("OLLAMA_URL", "http://localhost:11434"))
        creds["OLLAMA_MODEL"] = self.config.get("ollama_model", creds.get("OLLAMA_MODEL", ""))
        creds["HELIX_TELEGRAM_TOKEN"] = self.config.get("telegram_token", creds.get("HELIX_TELEGRAM_TOKEN", ""))
        creds["TELEGRAM_OWNER_ID"] = self.config.get("telegram_owner_id", creds.get("TELEGRAM_OWNER_ID", ""))
        creds["HELIX_DISCORD_TOKEN"] = self.config.get("discord_token", creds.get("HELIX_DISCORD_TOKEN", ""))
        creds["HELIX_PROVIDER"] = self.config.get("llm_provider", "gemini")
        creds["HELIX_MODEL"] = self.config.get("llm_model", creds.get("HELIX_MODEL", ""))
        creds["HELIX_VISION_PROVIDER"] = self.config.get("vision_provider", "local")

        # Comms channels
        channels = ["dashboard"]
        if self.config.get("telegram_enabled") and creds.get("HELIX_TELEGRAM_TOKEN"):
            channels.append("telegram")
        if self.config.get("discord_enabled") and creds.get("HELIX_DISCORD_TOKEN"):
            channels.append("discord")
        creds["HELIX_COMMS_CHANNELS"] = ",".join(channels)

        with open(CRED_PATH, "w") as f:
            for k, v in sorted(creds.items()):
                f.write(f"{k}={v}\n")

    def _run_bootstrap(self):
        """Run the belief bootstrap from setup.py logic."""
        import subprocess
        profile = self.config.get("bootstrap_profile", "prepared")
        personality = self.config.get("personality", "curious")
        agent_name = self.config.get("agent_name", "Helix")
        creator_name = self.config.get("creator_name", "User")

        cmd = [
            sys.executable, str(BASE_DIR / "setup.py"),
            "--non-interactive",
            f"--agent-name={agent_name}",
            f"--creator-name={creator_name}",
            f"--profile={profile}",
            f"--personality={personality}",
        ]
        try:
            subprocess.run(cmd, cwd=str(BASE_DIR), check=True, capture_output=True, timeout=60)
        except Exception as e:
            logger.warning(f"Bootstrap subprocess error: {e}")

    def _switch_to_dashboard(self):
        """Switch from wizard to the dashboard + settings tabs."""
        if self.dashboard_widget is None:
            self.dashboard_widget = self._build_dashboard()
            self.central.addWidget(self.dashboard_widget)
        self.central.setCurrentWidget(self.dashboard_widget)
        self._start_flask_server()
        self._start_agent_process()

    def _build_dashboard(self) -> QWidget:
        """Build the tabbed dashboard/settings view."""
        tabs = QTabWidget()

        # Dashboard tab (embedded web view)
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            web = QWebEngineView()
            # Show a styled loading page first
            web.setHtml(self._dashboard_status_html("loading"))
            tabs.addTab(web, "🧠  Dashboard")
            self._web_view = web
        except Exception as e:
            logger.warning(f"WebEngine load failed: {e}")
            fallback = QLabel(f"Dashboard requires PyQt6-WebEngine.\nInstall with: pip install PyQt6-WebEngine\n\nError: {e}")
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tabs.addTab(fallback, "🧠  Dashboard")
            self._web_view = None

        # Models tab
        from wizard.models_tab import ModelsTab
        models = ModelsTab(self)
        tabs.addTab(models, "🤖  Models")

        # Settings tab
        from wizard.settings_tab import SettingsTab
        settings = SettingsTab(self)
        tabs.addTab(settings, "⚙️  Settings")

        return tabs

    def _dashboard_status_html(self, status: str) -> str:
        """Generate a styled status page for the embedded dashboard."""
        agent_name = self.config.get("agent_name", "Helix")
        if status == "loading":
            icon = "⏳"
            title = "Starting Dashboard..."
            body = f"Launching {agent_name}'s cognitive dashboard.<br>This may take a moment while dependencies load."
            extra = '<div class="spinner"></div>'
        else:
            icon = "⚠️"
            title = "Dashboard Unavailable"
            body = (
                "The Flask dashboard could not start. This usually means<br>"
                "project dependencies aren't installed in this environment.<br><br>"
                "Run the following to install all dependencies:<br>"
                '<code>pip install -r requirements.txt</code><br><br>'
                "Then restart the application."
            )
            extra = ""

        return f"""<!DOCTYPE html>
<html><head><style>
    body {{
        margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center;
        background: #1a1a2e; color: #e8e8f0; font-family: 'Inter', 'Segoe UI', sans-serif;
    }}
    .card {{
        text-align: center; padding: 48px; border-radius: 16px;
        background: rgba(30,42,74,0.6); border: 1px solid rgba(42,42,94,0.6);
        max-width: 500px;
    }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    h1 {{ font-size: 22px; color: #a78bfa; margin: 0 0 12px; font-weight: 600; }}
    p {{ font-size: 14px; color: #8888aa; line-height: 1.6; margin: 0; }}
    code {{
        background: rgba(124,58,237,0.15); color: #c4b5fd; padding: 4px 10px;
        border-radius: 6px; font-size: 13px; display: inline-block; margin-top: 4px;
    }}
    .spinner {{
        width: 32px; height: 32px; margin: 20px auto 0;
        border: 3px solid rgba(167,139,250,0.2); border-top-color: #a78bfa;
        border-radius: 50%; animation: spin 1s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style></head><body>
    <div class="card">
        <div class="icon">{icon}</div>
        <h1>{title}</h1>
        <p>{body}</p>
        {extra}
    </div>
</body></html>"""

    def _start_flask_server(self):
        """Start the Flask dashboard server in a background thread."""
        if self._flask_thread and self._flask_thread.is_alive():
            return

        self._flask_started = False

        def _run():
            try:
                sys.path.insert(0, str(BASE_DIR))
                from dashboard.dashboard import create_app
                app = create_app()
                self._flask_started = True
                app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)
            except Exception as e:
                logger.error(f"Flask server error: {e}")
                # Show error in web view from main thread
                self.launch_signal.emit()

        self._flask_thread = threading.Thread(target=_run, daemon=True, name="flask-dashboard")
        self._flask_thread.start()

        # Check periodically if Flask started, then load the dashboard
        self._flask_check_count = 0
        self._check_flask_timer = QTimer()
        self._check_flask_timer.timeout.connect(self._check_flask_ready)
        self._check_flask_timer.start(1000)

    def _check_flask_ready(self):
        """Poll until Flask is ready or timeout."""
        self._flask_check_count += 1

        if self._flask_started and self._web_view:
            self._check_flask_timer.stop()
            self._web_view.setUrl(QUrl("http://127.0.0.1:5050"))
        elif self._flask_check_count > 10:
            # Timeout — show error page
            self._check_flask_timer.stop()
            if self._web_view:
                self._web_view.setHtml(self._dashboard_status_html("error"))

    def _start_agent_process(self):
        """Start main.py in a background process if not already running."""
        if self._agent_process and self._agent_process.poll() is None:
            return

        import subprocess
        cmd = [sys.executable, str(BASE_DIR / "main.py")]
        try:
            self._agent_process = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info("Agent process (main.py) started successfully.")
        except Exception as e:
            logger.error(f"Failed to start agent process: {e}")

    def restart_agent_process(self):
        """Terminate the running agent process and start a new one to apply configuration changes."""
        logger.info("Restarting agent process...")
        if self._agent_process and self._agent_process.poll() is None:
            self._agent_process.terminate()
            try:
                self._agent_process.wait(timeout=2)
            except Exception:
                self._agent_process.kill()
            self._agent_process = None
        self._start_agent_process()

    def _create_desktop_shortcuts(self, wizard_shortcut: bool, agent_shortcut: bool):
        """Create Linux desktop shortcuts for Setup Wizard and Agent Launcher."""
        apps_dir = Path(os.path.expanduser("~/.local/share/applications"))
        apps_dir.mkdir(parents=True, exist_ok=True)
        
        desktop_dir = Path(os.path.expanduser("~/Desktop"))
        
        logo_icon_path = str(BASE_DIR / "wizard" / "assets" / "helix_logo.png")

        if wizard_shortcut:
            wizard_sh = BASE_DIR / "Helix Setup Wizard.sh"
            content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=Helix Setup Wizard
Comment=Configure Helix AGI settings
Exec=bash "{wizard_sh}"
Icon={logo_icon_path}
Terminal=false
Categories=Utility;Settings;
"""
            # Write to applications menu
            try:
                app_file = apps_dir / "helix_setup_wizard.desktop"
                app_file.write_text(content)
                app_file.chmod(0o755)
                logger.info(f"Created applications shortcut: {app_file}")
            except Exception as e:
                logger.error(f"Failed to create setup wizard application shortcut: {e}")

            # Write to Desktop if it exists
            if desktop_dir.exists():
                try:
                    desk_file = desktop_dir / "helix_setup_wizard.desktop"
                    desk_file.write_text(content)
                    desk_file.chmod(0o755)
                    logger.info(f"Created desktop shortcut: {desk_file}")
                except Exception as e:
                    logger.error(f"Failed to create setup wizard desktop shortcut: {e}")

        if agent_shortcut:
            agent_sh = BASE_DIR / "Launch Helix Agent.sh"
            content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=Launch Helix Agent & Dashboard
Comment=Start the Helix AGI agent and open dashboard
Exec=bash "{agent_sh}"
Icon={logo_icon_path}
Terminal=true
Categories=Utility;
"""
            # Write to applications menu
            try:
                app_file = apps_dir / "launch_helix_agent.desktop"
                app_file.write_text(content)
                app_file.chmod(0o755)
                logger.info(f"Created applications shortcut: {app_file}")
            except Exception as e:
                logger.error(f"Failed to create agent launcher application shortcut: {e}")

            # Write to Desktop if it exists
            if desktop_dir.exists():
                try:
                    desk_file = desktop_dir / "launch_helix_agent.desktop"
                    desk_file.write_text(content)
                    desk_file.chmod(0o755)
                    logger.info(f"Created desktop shortcut: {desk_file}")
                except Exception as e:
                    logger.error(f"Failed to create agent launcher desktop shortcut: {e}")

    def closeEvent(self, event):
        """Clean up background processes on close."""
        if self._agent_process and self._agent_process.poll() is None:
            self._agent_process.terminate()
            try:
                self._agent_process.wait(timeout=2)
            except Exception:
                self._agent_process.kill()
        event.accept()


# ── Entry Point ───────────────────────────────────────────────────────
def main():
    import argparse
    import subprocess
    import os
    parser = argparse.ArgumentParser(description="Helix‑AGI Setup Wizard & Dashboard")
    parser.add_argument("--wizard", action="store_true", help="Force wizard mode")
    args = parser.parse_args()

    # Headless detection on non-Windows systems
    is_headless = False
    if sys.platform != "win32":
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            is_headless = True

    if is_headless:
        print("\n⚠ No graphical display detected. Falling back to CLI Setup...")
        setup_path = BASE_DIR / "setup.py"
        try:
            subprocess.run([sys.executable, str(setup_path)], check=True)
        except Exception as e:
            print(f"❌ Error running CLI setup: {e}")
        return

    # WebEngine requires this BEFORE QApplication is created
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except ImportError:
        pass

    try:
        app = QApplication(sys.argv)
    except Exception as e:
        print(f"\n⚠ Failed to initialize PyQt6 GUI: {e}")
        print("Falling back to CLI Setup...")
        setup_path = BASE_DIR / "setup.py"
        try:
            subprocess.run([sys.executable, str(setup_path)], check=True)
        except Exception as e2:
            print(f"❌ Error running CLI setup: {e2}")
        return

    # Set app user model ID for taskbar grouping and icons (Windows & Linux)
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("munch2u.helix.agi.wizard")
        except Exception:
            pass
    elif sys.platform == "linux":
        try:
            app.setDesktopFileName("helix_setup_wizard.desktop")
        except Exception:
            pass

    app.setApplicationName("Helix‑AGI")
    app.setStyleSheet(Theme.stylesheet())

    # Set dark palette as fallback
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(Theme.BG_DARK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(Theme.TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor("#2a2f4a"))
    palette.setColor(QPalette.ColorRole.Text, QColor(Theme.TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6a6a8a"))
    palette.setColor(QPalette.ColorRole.Button, QColor(Theme.BG_PANEL))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(Theme.TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(Theme.ACCENT))
    app.setPalette(palette)

    window = HelixApp(force_wizard=args.wizard)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
