"""
Wizard Page 7: Summary & Launch

Displays a review of all configuration choices and a final
'Create <Agent Name>' button to bootstrap and launch.
"""

from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpacerItem, QSizePolicy, QFrame, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from bootstrap import personality_label, profile_label
from wizard.ai_helper import AiHelperBanner
from core.agent_creation import ARCHETYPES


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
        try:
            from tools.tool_declarations import normalize_active_toolsets
            enabled_toolsets = sorted(
                normalize_active_toolsets(set(cfg.get("tool_set", [])))
            )
        except Exception:
            enabled_toolsets = sorted(set(cfg.get("tool_set", [])) | {"operational"})

        # Update launch button text
        self.launch_btn.setText(f"🚀  Create {agent_name}")

        # Build summary cards
        sections = [
            ("Mindscape", [
                ("Composition", cfg.get("composition", "helix")),
                ("Foreground model", cfg.get("llm_model") or cfg.get("local_model", "Account default")),
                ("Memory", "MightyMem / Habitus + Context Loom + mRAG" if cfg.get("composition") == "mindscape" else "Helix"),
                ("Startup", cfg.get("mindscape", {}).get("gestation", "if_missing")),
                ("Agent home", cfg.get("mindscape", {}).get("home") or "Created from the agent name"),
                ("Memory directory", cfg.get("data_dir", "data")),
            ]),
            ("🤖  Identity", [
                ("Agent Name", agent_name),
                ("Creator", cfg.get("creator_name", "")),
                ("Archetype", ARCHETYPES[cfg.get("agent_archetype", "balanced")][0]),
                ("Profile", profile_label(cfg.get("bootstrap_profile", "standard"))),
                ("Voice", personality_label(cfg.get("personality", "curious"))),
            ]),
            ("🔑  Credentials", self._build_credential_rows(cfg)),
            ("🔧  Tools", [
                ("Enabled Toolsets", ", ".join(enabled_toolsets)),
            ]),
            ("🔒  Safety", [
                ("Safety Mode", "Enabled ✅" if cfg.get("safety_mode", True) else "Disabled ⚠️"),
                ("Whitelist Entries", str(len(cfg.get("whitelist", [])))),
            ]),
            ("⏰  Schedule", [
                ("Wake Time", cfg.get("active_hours", {}).get("start", "08:00")),
                ("Sleep Time", cfg.get("active_hours", {}).get("end", "23:00")),
                ("Resting Pulse", f"Every {cfg.get('resting_pulse_minutes', 15)} min"),
            ]),
            ("💬  Communication", [
                ("Main channel", cfg.get("primary_channel", "dashboard").title()),
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

        # Dashboard & Habitus Mindscape Visual Card
        base_dir = Path(__file__).resolve().parent.parent.parent
        preview_path = base_dir / "wizard" / "assets" / "habitus_mindscape_preview.png"
        if preview_path.exists():
            preview_card = QWidget()
            preview_card.setStyleSheet("""
                background: rgba(15, 23, 42, 0.65);
                border: 1px solid rgba(56, 189, 248, 0.4);
                border-radius: 10px;
                padding: 12px 16px;
            """)
            p_layout = QVBoxLayout(preview_card)
            p_layout.setSpacing(6)
            p_title = QLabel("🌌 3D Habitus Mindscape & Real-Time Dashboard (Port 5050)")
            p_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #38bdf8; background: transparent; border: none;")
            p_layout.addWidget(p_title)

            p_desc = QLabel("Upon launch, Helix provides real-time 3D habitus memory visualization, thermodynamic stability gauges (Ω), safe file staging, and module code management.")
            p_desc.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; border: none;")
            p_desc.setWordWrap(True)
            p_layout.addWidget(p_desc)

            p_img = QLabel()
            pix = QPixmap(str(preview_path))
            p_img.setPixmap(pix.scaled(520, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            p_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            p_layout.addWidget(p_img)

            self.summary_layout.addWidget(preview_card)

        self.summary_layout.addStretch()

    @staticmethod
    def _build_credential_rows(cfg: dict) -> list:
        """Build credential summary rows, showing only relevant providers."""
        def _mask(key_name):
            val = cfg.get(key_name, "")
            return f"••••{val[-4:]}" if val else "Not set"

        provider = cfg.get("llm_provider", "gemini")
        provider_labels = {
            "rwkv": "Dual RWKV (Local)",
            "claude_cli": "Claude Code CLI",
            "codex_cli": "Codex CLI (ChatGPT login)",
            "gemini": "Google Gemini",
            "anthropic": "Anthropic Claude",
            "openai": "OpenAI GPT",
            "alibaba": "Alibaba Qwen",
            "ollama": "Ollama (Local)",
        }

        rows = [("Primary Provider", provider_labels.get(provider, provider.title()))]

        # Always show the primary provider's key/config prominently
        if provider == "codex_cli":
            rows.append(("Authentication", "Local `codex login`"))
            rows.append(("Model", cfg.get("llm_model", "") or "Account default"))
        elif provider == "rwkv":
            rows.append(("RWKV checkpoint", cfg.get("llm_model") or cfg.get("mindscape", {}).get("rwkv_model", "Not set")))
        elif provider == "ollama":
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
