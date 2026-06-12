"""
Assistant Panel — Interactive chat widget for the wizard sidebar.

A collapsible right-side panel (~300px) that provides an interactive
AI chat experience during setup. Uses QThread for async LLM calls
to keep the UI responsive.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTextEdit, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QTextCursor
import time


# ── Page Context Builder ─────────────────────────────────────────────

PAGE_CONTEXT = {
    0: {
        "name": "Welcome",
        "desc": "Introduction to Helix-AGI and AI helper opt-in.",
        "fields": lambda cfg: [],
    },
    1: {
        "name": "Credentials",
        "desc": "API key configuration for LLM providers (Gemini, Anthropic, Ollama, etc.)",
        "fields": lambda cfg: [
            ("Provider", cfg.get("llm_provider", "not set")),
            ("Gemini Key", "configured" if cfg.get("gemini_api_key") else "not set"),
            ("Anthropic Key", "configured" if cfg.get("anthropic_api_key") else "not set"),
            ("Ollama", f"{cfg.get('ollama_model', 'not set')} @ {cfg.get('ollama_url', 'localhost')}" if cfg.get("llm_provider") == "ollama" else "not selected"),
        ],
    },
    2: {
        "name": "Identity",
        "desc": "Agent name, bootstrap profile, and personality archetype.",
        "fields": lambda cfg: [
            ("Agent Name", cfg.get("agent_name", "not set")),
            ("Creator", cfg.get("creator_name", "not set")),
            ("Profile", cfg.get("bootstrap_profile", "not set")),
            ("Personality", cfg.get("personality", "not set")),
        ],
    },
    3: {
        "name": "Tools",
        "desc": "Which tool sets to enable (core, web, terminal, filesystem, etc.)",
        "fields": lambda cfg: [
            ("Selected", ", ".join(cfg.get("tool_set", ["core"]))),
        ],
    },
    4: {
        "name": "Safety",
        "desc": "Safety mode toggle and domain/command whitelist configuration.",
        "fields": lambda cfg: [
            ("Safety Mode", "ON" if cfg.get("safety_mode", True) else "OFF"),
            ("Whitelist entries", str(len(cfg.get("whitelist", [])))),
        ],
    },
    5: {
        "name": "Schedule",
        "desc": "Active hours (wake/sleep), resting pulse rate configuration.",
        "fields": lambda cfg: [
            ("Wake", cfg.get("active_hours", {}).get("start", "not set")),
            ("Sleep", cfg.get("active_hours", {}).get("end", "not set")),
            ("Resting Pulse", f"{cfg.get('resting_pulse_minutes', 15)} min"),
        ],
    },
    6: {
        "name": "Review & Launch",
        "desc": "Final review of all settings before creating the agent.",
        "fields": lambda cfg: [],
    },
}


def build_context_message(page_index: int, config: dict) -> str:
    """Build a context update message for the assistant."""
    page = PAGE_CONTEXT.get(page_index, {})
    name = page.get("name", f"Page {page_index}")
    desc = page.get("desc", "")
    fields_fn = page.get("fields", lambda c: [])
    fields = fields_fn(config)

    lines = [
        f"The user is now on the '{name}' page.",
        f"Page purpose: {desc}",
    ]

    if fields:
        lines.append("Current settings entered so far:")
        for label, value in fields:
            lines.append(f"  • {label}: {value}")

    # Add summary of all prior pages' data
    prior_summary = []
    if config.get("agent_name") and config["agent_name"] != "Helix":
        prior_summary.append(f"Agent: {config['agent_name']}")
    if config.get("llm_provider"):
        prior_summary.append(f"Provider: {config['llm_provider']}")
    if config.get("bootstrap_profile"):
        prior_summary.append(f"Profile: {config['bootstrap_profile']}")

    if prior_summary:
        lines.append(f"Overall config so far: {', '.join(prior_summary)}")

    return "\n".join(lines)


# ── Worker Thread ────────────────────────────────────────────────────

class AssistantWorker(QThread):
    """Background thread for LLM calls."""

    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, assistant, message: str):
        super().__init__()
        self.assistant = assistant
        self.message = message

    def run(self):
        try:
            response = self.assistant.send_message(self.message)
            self.response_ready.emit(response)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ContextWorker(QThread):
    """Background thread for context updates (non-blocking)."""

    def __init__(self, assistant, context: str):
        super().__init__()
        self.assistant = assistant
        self.context = context

    def run(self):
        try:
            self.assistant.send_context_update(self.context)
        except Exception:
            pass  # Non-critical


# ── Chat Panel Widget ────────────────────────────────────────────────

class AssistantPanel(QWidget):
    """Collapsible right-side chat panel for the AI Setup Assistant."""

    def __init__(self, wizard, parent=None):
        super().__init__(parent)
        self.wizard = wizard
        self._assistant = None
        self._worker = None
        self._context_worker = None
        self._collapsed = False
        self._typing_timer = None
        self._typing_dots = 0
        self.setFixedWidth(320)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet("""
            background: rgba(124, 58, 237, 0.12);
            border-bottom: 1px solid rgba(124, 58, 237, 0.3);
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 8, 0)

        title = QLabel("🤖  Setup Assistant")
        title.setStyleSheet(
            "font-weight: 700; font-size: 13px; color: #a78bfa; "
            "background: transparent; border: none;"
        )
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.collapse_btn = QPushButton("◀")
        self.collapse_btn.setFixedSize(28, 28)
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #a78bfa;
                font-size: 12px;
                border-radius: 14px;
                min-height: 0;
                padding: 0;
            }
            QPushButton:hover {
                background: rgba(124, 58, 237, 0.2);
            }
        """)
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        header_layout.addWidget(self.collapse_btn)

        layout.addWidget(header)

        # ── Chat Body (collapsible) ───────────────────────────────
        self.chat_body = QWidget()
        body_layout = QVBoxLayout(self.chat_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Message area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("""
            QScrollArea {
                background: rgba(15, 22, 41, 0.5);
                border: none;
            }
        """)

        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.messages_layout.setSpacing(8)
        self.messages_layout.addStretch()
        self.scroll.setWidget(self.messages_widget)

        body_layout.addWidget(self.scroll, stretch=1)

        # Typing indicator
        self.typing_label = QLabel("")
        self.typing_label.setStyleSheet(
            "font-size: 11px; color: #666688; padding: 4px 14px; "
            "background: transparent; border: none;"
        )
        self.typing_label.setVisible(False)
        body_layout.addWidget(self.typing_label)

        # ── Input Area ────────────────────────────────────────────
        input_frame = QWidget()
        input_frame.setStyleSheet("""
            background: rgba(30, 42, 74, 0.8);
            border-top: 1px solid rgba(42, 42, 94, 0.6);
        """)
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 8, 10, 8)
        input_layout.setSpacing(8)

        self.input_field = QTextEdit()
        self.input_field.setFixedHeight(36)
        self.input_field.setPlaceholderText("Ask about Helix...")
        self.input_field.setStyleSheet("""
            QTextEdit {
                background: rgba(15, 22, 41, 0.8);
                border: 1px solid rgba(42, 42, 94, 0.6);
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 12px;
                color: #e8e8f0;
            }
            QTextEdit:focus {
                border-color: #7c3aed;
            }
        """)
        self.input_field.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        input_layout.addWidget(self.input_field, stretch=1)

        self.send_btn = QPushButton("→")
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #7c3aed, stop:1 #6366f1);
                border: none;
                border-radius: 8px;
                color: white;
                font-size: 16px;
                font-weight: 700;
                min-height: 0;
                padding: 0;
            }
            QPushButton:hover {
                background: #6d28d9;
            }
            QPushButton:disabled {
                background: rgba(42, 42, 94, 0.4);
                color: #666688;
            }
        """)
        self.send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(self.send_btn)

        body_layout.addWidget(input_frame)
        layout.addWidget(self.chat_body, stretch=1)

        # Install enter key handler
        self.input_field.installEventFilter(self)

        # Show welcome message
        self._add_message(
            "assistant",
            "👋 Hi! I'm the Setup Assistant. I can answer questions about "
            "Helix's architecture, explain what each setting does, and help "
            "troubleshoot. Ask me anything!"
        )

    # ── Event Filter (Enter to send) ─────────────────────────────

    def eventFilter(self, obj, event):
        if obj == self.input_field and event.type() == event.Type.KeyPress:
            from PyQt6.QtCore import Qt as QtCore_Qt
            key = event.key()
            modifiers = event.modifiers()
            if key in (QtCore_Qt.Key.Key_Return, QtCore_Qt.Key.Key_Enter):
                if modifiers & QtCore_Qt.KeyboardModifier.ShiftModifier:
                    return False  # Allow Shift+Enter for newline
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    # ── Collapse/Expand ──────────────────────────────────────────

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self.chat_body.setVisible(not self._collapsed)
        self.collapse_btn.setText("▶" if self._collapsed else "◀")
        self.setFixedWidth(48 if self._collapsed else 320)

    # ── Messages ─────────────────────────────────────────────────

    def _add_message(self, role: str, text: str):
        """Add a message bubble to the chat."""
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.TextFormat.PlainText)
        bubble.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        if role == "user":
            bubble.setStyleSheet("""
                background: rgba(124, 58, 237, 0.15);
                border: 1px solid rgba(124, 58, 237, 0.3);
                border-radius: 10px;
                padding: 10px 12px;
                font-size: 12px;
                color: #e8e8f0;
                margin-left: 30px;
            """)
            bubble.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            bubble.setStyleSheet("""
                background: rgba(30, 42, 74, 0.6);
                border: 1px solid rgba(42, 42, 94, 0.5);
                border-radius: 10px;
                padding: 10px 12px;
                font-size: 12px;
                color: #c4b5fd;
                margin-right: 30px;
            """)

        # Insert before the stretch
        count = self.messages_layout.count()
        self.messages_layout.insertWidget(count - 1, bubble)

        # Scroll to bottom
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        scrollbar = self.scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ── Typing Indicator ─────────────────────────────────────────

    def _start_typing(self):
        self._typing_dots = 0
        self.typing_label.setVisible(True)
        self.typing_label.setText("Thinking...")
        self._typing_timer = QTimer()
        self._typing_timer.timeout.connect(self._animate_typing)
        self._typing_timer.start(400)

    def _animate_typing(self):
        self._typing_dots = (self._typing_dots + 1) % 4
        dots = "." * self._typing_dots
        self.typing_label.setText(f"Thinking{dots}")

    def _stop_typing(self):
        if self._typing_timer:
            self._typing_timer.stop()
            self._typing_timer = None
        self.typing_label.setVisible(False)

    # ── Send Message ─────────────────────────────────────────────

    def _on_send(self):
        text = self.input_field.toPlainText().strip()
        if not text:
            return

        # Check if assistant is available
        if not self._ensure_assistant():
            return

        # Show user message
        self._add_message("user", text)
        self.input_field.clear()

        # Disable input while waiting
        self.send_btn.setEnabled(False)
        self.input_field.setEnabled(False)
        self._start_typing()

        # Send in background thread
        self._worker = AssistantWorker(self._assistant, text)
        self._worker.response_ready.connect(self._on_response)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.start()

    def _on_response(self, response: str):
        self._stop_typing()
        self._add_message("assistant", response)

    def _on_error(self, error: str):
        self._stop_typing()
        self._add_message(
            "assistant",
            f"⚠️ Sorry, something went wrong: {error[:200]}"
        )

    def _on_worker_done(self):
        self.send_btn.setEnabled(True)
        self.input_field.setEnabled(True)
        self.input_field.setFocus()
        self._worker = None

    # ── Assistant Lifecycle ──────────────────────────────────────

    def _ensure_assistant(self) -> bool:
        """Create the assistant if needed. Returns True if ready."""
        if self._assistant is not None and self._assistant.is_available():
            return True

        from wizard.setup_assistant import SetupAssistant
        self._assistant = SetupAssistant(self.wizard.config)

        if not self._assistant.is_available():
            provider = self.wizard.config.get("llm_provider", "gemini")
            self._add_message(
                "assistant",
                f"🔑 I need API credentials to help you! Please configure "
                f"your {provider.title()} API key on the Credentials page first, "
                f"then come back and ask me anything."
            )
            self._assistant = None
            return False

        return True

    def notify_page_change(self, page_index: int):
        """Called when the user navigates to a new wizard page.

        Sends a backend context update to the assistant so it knows
        what the user is currently looking at.
        """
        if self._assistant is None:
            return  # Not initialized yet

        context = build_context_message(page_index, self.wizard.config)

        # Send in background to avoid blocking UI
        self._context_worker = ContextWorker(self._assistant, context)
        self._context_worker.start()

    def refresh(self):
        """Re-check if the assistant should be visible."""
        enabled = self.wizard.config.get("ai_assist", False)
        self.setVisible(enabled)
