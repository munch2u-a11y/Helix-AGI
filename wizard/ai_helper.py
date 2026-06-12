"""
AI Setup Assistant

Provides contextual help banners for each wizard page.
When the AI Helper is enabled, each page shows an expandable
tip card with guidance tailored to that step.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)
from PyQt6.QtCore import Qt


# ── Contextual help text per wizard step ──────────────────────────────
AI_TIPS = {
    "credentials": {
        "title": "💡 AI Setup Tip — Credentials",
        "body": (
            "• If you're just getting started, <b>Gemini</b> is the easiest choice — "
            "it has a generous free tier that works well for experimentation.\n\n"
            "• <b>Ollama</b> is ideal if you have a GPU (8GB+ VRAM) and want "
            "fully private, zero-cost operation. Run <code>ollama pull llama3</code> to get started.\n\n"
            "• You can configure <b>multiple providers</b> — Helix can use a free provider "
            "for background tasks and a premium one for complex reasoning.\n\n"
            "• <b>Telegram/Discord</b> are optional but convenient for chatting with your "
            "agent from your phone while away."
        ),
    },
    "agent_info": {
        "title": "💡 AI Setup Tip — Identity",
        "body": (
            "• <b>Agent Name</b> is how your agent refers to itself. Pick something "
            "that feels like a real companion!\n\n"
            "• <b>Bootstrap Profile</b> defines what your agent knows from birth:\n"
            "  — <b>Birth</b>: True blank slate. It will need to learn everything, "
            "but develops its own unique perspective.\n"
            "  — <b>Prepared</b> (recommended): Comes with tool knowledge and basic skills. "
            "Ready to help immediately.\n"
            "  — <b>Developed</b>: Advanced self-awareness and meta-cognition. Best for "
            "power users who want autonomous operation from day one.\n\n"
            "• <b>Personality</b> shapes communication style. 'Curious' agents explore more, "
            "'Professional' agents are concise and efficient."
        ),
    },
    "tools": {
        "title": "💡 AI Setup Tip — Tools",
        "body": (
            "• <b>Core tools</b> (reply, memory, journal) are always enabled — they're "
            "essential for basic operation.\n\n"
            "• <b>Web + Filesystem + Terminal</b> are recommended for most users. "
            "They let your agent browse the web, manage files, and run commands.\n\n"
            "• <b>Desktop control</b> (mouse/keyboard) is powerful but risky — "
            "enable Safety Mode if you use this.\n\n"
            "• <b>GitHub, Google, Vision</b> are specialized — only enable what you need. "
            "Each adds capabilities but also API usage.\n\n"
            "• You can always change this later from Settings!"
        ),
    },
    "safety": {
        "title": "💡 AI Setup Tip — Safety",
        "body": (
            "• <b>Safety Mode ON</b> (recommended) means your agent asks permission "
            "before visiting new websites or running unfamiliar commands.\n\n"
            "• The <b>Balanced</b> whitelist preset is a great starting point — "
            "it covers major development, research, and productivity sites.\n\n"
            "• Your agent will send <b>whitelist requests</b> when it encounters "
            "a new domain or command. You can approve them from the Settings tab.\n\n"
            "• The whitelist applies to both <b>web browsing</b> and "
            "<b>terminal commands</b>. DuckDuckGo search always works regardless."
        ),
    },
    "schedule": {
        "title": "💡 AI Setup Tip — Schedule",
        "body": (
            "• Your agent runs autonomously during <b>active hours</b>, thinking "
            "in \"pulses\" every 30-90 seconds during conversation.\n\n"
            "• During <b>sleep</b>, the Dream Engine consolidates memories, "
            "strengthens important beliefs, and prunes noise. This is crucial "
            "for long-term cognitive health.\n\n"
            "• <b>4+ hours of sleep</b> is recommended. Less than 3 hours "
            "may cause belief fragmentation.\n\n"
            "• The <b>Resting Pulse Rate</b> controls how often your agent thinks "
            "when idle (no conversation). 15 min is a good balance — lower values "
            "mean more autonomous exploration but higher API costs.\n\n"
            "• If using <b>paid API providers</b>, shorter active windows + longer "
            "pulse intervals = lower costs."
        ),
    },
    "summary": {
        "title": "💡 AI Setup Tip — Launch",
        "body": (
            "• Review everything above carefully — <b>Agent Name</b> and "
            "<b>Bootstrap Profile</b> cannot be changed after creation.\n\n"
            "• Everything else (tools, safety, schedule, whitelist) can be "
            "adjusted from the <b>Settings tab</b> at any time.\n\n"
            "• After clicking Create, the setup will:\n"
            "  1. Save your configuration\n"
            "  2. Write API credentials securely\n"
            "  3. Bootstrap the cognitive graph\n"
            "  4. Launch the Dashboard\n\n"
            "• Your agent will begin its first pulse automatically!"
        ),
    },
}


class AiHelperBanner(QWidget):
    """
    A collapsible contextual help banner for wizard pages.
    Only visible when ai_assist is enabled in config.
    """

    def __init__(self, page_key: str, wizard, parent=None):
        super().__init__(parent)
        self.wizard = wizard
        self.page_key = page_key
        self._expanded = True
        self._build()

    def _build(self):
        tip = AI_TIPS.get(self.page_key)
        if not tip:
            self.setVisible(False)
            return

        self.setObjectName("aiHelperBanner")
        self.setStyleSheet("""
            QWidget#aiHelperBanner {
                background: rgba(124, 58, 237, 0.08);
                border: 1px solid rgba(124, 58, 237, 0.25);
                border-radius: 10px;
                padding: 0px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # Header row with title + collapse button
        header = QHBoxLayout()
        title = QLabel(tip["title"])
        title.setStyleSheet("font-weight: 600; font-size: 12px; color: #a78bfa;")
        header.addWidget(title)
        header.addStretch()

        self.toggle_btn = QPushButton("▼")
        self.toggle_btn.setFixedSize(24, 24)
        self.toggle_btn.setStyleSheet("""
            background: transparent;
            border: none;
            color: #a78bfa;
            font-size: 11px;
            padding: 0;
            min-height: 0;
        """)
        self.toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self.toggle_btn)
        layout.addLayout(header)

        # Body text
        self.body = QLabel(tip["body"])
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setStyleSheet("font-size: 11px; color: #c4b5fd; line-height: 1.5;")
        layout.addWidget(self.body)

        # Visibility depends on config
        self._update_visibility()

    def _toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.toggle_btn.setText("▼" if self._expanded else "▶")

    def _update_visibility(self):
        self.setVisible(self.wizard.config.get("ai_assist", False))

    def refresh(self):
        """Re-check visibility (called when entering a page)."""
        self._update_visibility()
