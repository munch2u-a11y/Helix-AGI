"""
Wizard Page 7: Summary & Launch

Displays a review of all configuration choices and a final
'Create <Agent Name>' button to bootstrap and launch.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpacerItem, QSizePolicy, QFrame, QCheckBox,
)
from PyQt6.QtCore import Qt
from wizard.ai_helper import AiHelperBanner


class SummaryPage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 24, 60, 24)
        layout.setSpacing(16)

        heading = QLabel("Review & Launch")
        heading.setProperty("class", "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        sub = QLabel(
            "Review your configuration below. Click the button at the bottom\n"
            "to create your agent and launch the dashboard."
        )
        sub.setProperty("class", "subheading")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # AI Helper
        self.ai_banner = AiHelperBanner("summary", self.wizard)
        layout.addWidget(self.ai_banner)

        layout.addSpacing(4)

        # Summary content (dynamically updated on enter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        self.summary_widget = QWidget()
        self.summary_layout = QVBoxLayout(self.summary_widget)
        self.summary_layout.setSpacing(12)
        scroll.setWidget(self.summary_widget)
        layout.addWidget(scroll, stretch=1)

        # Checkboxes for desktop shortcuts
        self.shortcuts_layout = QVBoxLayout()
        self.shortcuts_layout.setSpacing(8)
        self.shortcuts_layout.setContentsMargins(0, 8, 0, 8)

        self.shortcut_wizard_chk = QCheckBox("  Create Desktop Shortcut for Setup Wizard")
        self.shortcut_wizard_chk.setChecked(True)
        self.shortcut_agent_chk = QCheckBox("  Create Desktop Shortcut to Launch Helix Agent & Dashboard")
        self.shortcut_agent_chk.setChecked(True)

        self.shortcuts_layout.addWidget(self.shortcut_wizard_chk)
        self.shortcuts_layout.addWidget(self.shortcut_agent_chk)
        layout.addLayout(self.shortcuts_layout)

        # Launch button (dynamically named)
        self.launch_btn = QPushButton("Create Agent")
        self.launch_btn.setFixedHeight(52)
        self.launch_btn.setStyleSheet("""
            font-size: 18px;
            font-weight: 700;
            border-radius: 14px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #7c3aed, stop:0.5 #6366f1, stop:1 #818cf8);
        """)
        self.launch_btn.clicked.connect(self.wizard.finish_wizard)
        layout.addWidget(self.launch_btn)

        # Back button
        nav = QHBoxLayout()
        back_btn = QPushButton("←  Back")
        back_btn.setProperty("class", "secondary")
        back_btn.setFixedWidth(140)
        back_btn.clicked.connect(self.wizard.prev_page)
        nav.addWidget(back_btn)
        nav.addStretch()
        layout.addLayout(nav)

    def on_enter(self):
        """Called when this page becomes visible — rebuild summary from config."""
        # Clear old summary
        while self.summary_layout.count():
            child = self.summary_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        cfg = self.wizard.config
        agent_name = cfg.get("agent_name", "Helix")

        # Update launch button text
        self.launch_btn.setText(f"🚀  Create {agent_name}")

        # Build summary cards
        sections = [
            ("🤖  Identity", [
                ("Agent Name", agent_name),
                ("Creator", cfg.get("creator_name", "")),
                ("Profile", cfg.get("bootstrap_profile", "prepared").title()),
                ("Personality", cfg.get("personality", "curious").title()),
            ]),
            ("🔑  Credentials", self._build_credential_rows(cfg)),
            ("🔧  Tools", [
                ("Enabled Toolsets", ", ".join(cfg.get("tool_set", ["core"]))),
            ]),
            ("🔒  Safety", [
                ("Safety Mode", "Enabled ✅" if cfg.get("safety_mode", True) else "Disabled ⚠️"),
                ("Whitelist Entries", str(len(cfg.get("whitelist", [])))),
            ]),
            ("⏰  Schedule", [
                ("Wake Time", cfg.get("active_hours", {}).get("start", "08:00")),
                ("Sleep Time", cfg.get("active_hours", {}).get("end", "23:00")),
            ]),
            ("💬  Communication", [
                ("Dashboard", "Always enabled ✅"),
                ("Telegram", "Enabled ✅" if cfg.get("telegram_enabled") else "Disabled"),
                ("Discord", "Enabled ✅" if cfg.get("discord_enabled") else "Disabled"),
                ("AI Helper", "Enabled" if cfg.get("ai_assist") else "Disabled"),
            ]),
        ]

        for title, rows in sections:
            card = QWidget()
            card.setStyleSheet("""
                background: rgba(30, 42, 74, 0.5);
                border: 1px solid rgba(42, 42, 94, 0.6);
                border-radius: 10px;
                padding: 14px 18px;
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(6)

            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #a78bfa; background: transparent; border: none;")
            card_layout.addWidget(title_lbl)

            for label, value in rows:
                row = QHBoxLayout()
                k = QLabel(label)
                k.setStyleSheet("font-size: 12px; color: #8888aa; background: transparent; border: none;")
                v = QLabel(str(value))
                v.setStyleSheet("font-size: 12px; font-weight: 500; color: #e8e8f0; background: transparent; border: none;")
                v.setAlignment(Qt.AlignmentFlag.AlignRight)
                row.addWidget(k)
                row.addStretch()
                row.addWidget(v)
                card_layout.addLayout(row)

            self.summary_layout.addWidget(card)

        self.summary_layout.addStretch()

    @staticmethod
    def _build_credential_rows(cfg: dict) -> list:
        """Build credential summary rows, showing only relevant providers."""
        def _mask(key_name):
            val = cfg.get(key_name, "")
            return f"••••{val[-4:]}" if val else "Not set"

        provider = cfg.get("llm_provider", "gemini")
        provider_labels = {
            "gemini": "Google Gemini",
            "anthropic": "Anthropic Claude",
            "openai": "OpenAI GPT",
            "alibaba": "Alibaba Qwen",
            "ollama": "Ollama (Local)",
        }

        rows = [("Primary Provider", provider_labels.get(provider, provider.title()))]

        # Always show the primary provider's key/config prominently
        if provider == "ollama":
            rows.append(("Ollama URL", cfg.get("ollama_url", "http://localhost:11434")))
            rows.append(("Ollama Model", cfg.get("ollama_model", "") or "Not set"))
        elif provider == "alibaba":
            rows.append(("Alibaba Key", _mask("alibaba_api_key")))

        # Show all configured keys
        if cfg.get("gemini_api_key"):
            rows.append(("Gemini Key", _mask("gemini_api_key")))
        if cfg.get("anthropic_api_key"):
            rows.append(("Anthropic Key", _mask("anthropic_api_key")))
        if cfg.get("openai_api_key"):
            rows.append(("OpenAI Key", _mask("openai_api_key")))
        if cfg.get("alibaba_api_key") and provider != "alibaba":
            rows.append(("Alibaba Key", _mask("alibaba_api_key")))
        if cfg.get("ollama_model") and provider != "ollama":
            rows.append(("Ollama", f"{cfg.get('ollama_model')} @ {cfg.get('ollama_url', 'localhost')}"))

        rows.append(("Vision", cfg.get("vision_provider", "local").title()))
        return rows
