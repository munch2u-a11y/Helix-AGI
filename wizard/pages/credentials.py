"""
Wizard Page 2: Credentials

Collects API keys for LLM providers, vision, and optional comms channels.
Fields are password-masked with a toggle. Existing credentials.env values
are pre-populated for migration.
"""

import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QFormLayout, QComboBox, QCheckBox,
    QSpacerItem, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import Qt
from wizard.ai_helper import AiHelperBanner


CRED_PATH = Path(os.path.expanduser("~/.config/helix/credentials.env"))


def _load_existing_creds() -> dict:
    """Read existing credentials.env if present."""
    creds = {}
    if CRED_PATH.exists():
        with open(CRED_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    creds[k.strip()] = v.strip().strip('"')
    return creds


class CredentialsPage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self._build()
        self._load_existing()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(60, 24, 60, 24)

        heading = QLabel("API Credentials")
        heading.setProperty("class", "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(heading)

        sub = QLabel(
            "Enter your API keys below. At minimum, one LLM provider key is required.\n"
            "Keys are stored locally in ~/.config/helix/credentials.env — never uploaded."
        )
        sub.setProperty("class", "subheading")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        outer.addWidget(sub)
        outer.addSpacing(8)

        # AI Helper
        self.ai_banner = AiHelperBanner("credentials", self.wizard)
        outer.addWidget(self.ai_banner)
        outer.addSpacing(8)

        # Scrollable form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        form_layout = QVBoxLayout(scroll_content)
        form_layout.setSpacing(16)

        # ── LLM Providers ─────────────────────────────────────────────
        llm_group = QGroupBox("LLM Providers")
        llm_form = QFormLayout(llm_group)
        llm_form.setSpacing(10)

        desc = QLabel(
            "⚠️ Helix runs continuously, which can accumulate API costs.\n"
            "A Gemini API key (free tier) is recommended for subconscious systems.\n"
            "Use Ollama for fully local, free operation (requires Ollama installed)."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #fbbf24; font-size: 11px; padding: 4px 0;")
        llm_form.addRow(desc)

        # ── Cloud Providers ───────────────────────────────────────────
        cloud_label = QLabel("☁️  Cloud Providers")
        cloud_label.setStyleSheet("font-weight: 600; font-size: 12px; color: #a78bfa; margin-top: 4px;")
        llm_form.addRow(cloud_label)

        self.gemini_key = self._key_field()
        self.gemini_key.setPlaceholderText("Gemini API key (free tier available)")
        llm_form.addRow("Gemini:", self.gemini_key)

        self.anthropic_key = self._key_field()
        self.anthropic_key.setPlaceholderText("Anthropic API key (Claude models)")
        llm_form.addRow("Anthropic:", self.anthropic_key)

        self.openai_key = self._key_field()
        self.openai_key.setPlaceholderText("OpenAI API key (GPT models)")
        llm_form.addRow("OpenAI:", self.openai_key)

        self.alibaba_key = self._key_field()
        self.alibaba_key.setPlaceholderText("Alibaba DashScope API key (Qwen models)")
        llm_form.addRow("Alibaba (Qwen):", self.alibaba_key)

        # ── Local Provider ────────────────────────────────────────────
        local_label = QLabel("🖥️  Local Provider")
        local_label.setStyleSheet("font-weight: 600; font-size: 12px; color: #4ade80; margin-top: 8px;")
        llm_form.addRow(local_label)

        self.ollama_url = QLineEdit()
        self.ollama_url.setPlaceholderText("http://localhost:11434  (default Ollama URL)")
        self.ollama_url.setText(self.wizard.config.get("ollama_url", "http://localhost:11434"))
        llm_form.addRow("Ollama URL:", self.ollama_url)

        self.ollama_model = QLineEdit()
        self.ollama_model.setPlaceholderText("e.g. llama3, qwen2.5, gemma2, mistral...")
        self.ollama_model.setText(self.wizard.config.get("ollama_model", ""))
        llm_form.addRow("Ollama Model:", self.ollama_model)

        ollama_hint = QLabel(
            "💡 Ollama runs models locally — no API costs. Install from ollama.com\n"
            "   then pull a model: ollama pull llama3"
        )
        ollama_hint.setWordWrap(True)
        ollama_hint.setStyleSheet("font-size: 10px; color: #666688; padding-left: 4px;")
        llm_form.addRow(ollama_hint)

        # ── Primary Provider Selector ─────────────────────────────────
        provider_label = QLabel("⭐  Primary Provider")
        provider_label.setStyleSheet("font-weight: 600; font-size: 12px; color: #c4b5fd; margin-top: 8px;")
        llm_form.addRow(provider_label)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["gemini", "anthropic", "openai", "alibaba", "ollama"])
        self.provider_combo.setCurrentText(self.wizard.config.get("llm_provider", "gemini"))

        # Provider description that updates on selection
        self.provider_desc = QLabel()
        self.provider_desc.setWordWrap(True)
        self.provider_desc.setStyleSheet("font-size: 10px; color: #8888aa; padding-left: 4px;")
        self._update_provider_desc(self.provider_combo.currentText())
        self.provider_combo.currentTextChanged.connect(self._update_provider_desc)

        llm_form.addRow("Use as primary:", self.provider_combo)
        llm_form.addRow(self.provider_desc)

        form_layout.addWidget(llm_group)

        # ── Vision ────────────────────────────────────────────────────
        vision_group = QGroupBox("Vision Configuration")
        vision_form = QFormLayout(vision_group)

        vision_desc = QLabel(
            "Helix can see through your webcam using either a local model (free) or Gemini Flash."
        )
        vision_desc.setProperty("class", "description")
        vision_desc.setWordWrap(True)
        vision_desc.setStyleSheet("color: #8888aa; font-size: 11px; background: transparent; border: none;")
        vision_form.addRow(vision_desc)

        self.vision_combo = QComboBox()
        self.vision_combo.addItems(["local", "gemini"])
        self.vision_combo.setCurrentText(self.wizard.config.get("vision_provider", "local"))
        vision_form.addRow("Vision Provider:", self.vision_combo)

        form_layout.addWidget(vision_group)

        # ── Communication Channels ────────────────────────────────────
        comms_group = QGroupBox("Communication Channels (Optional)")
        comms_form = QFormLayout(comms_group)

        comms_desc = QLabel(
            "The web dashboard chat is always enabled. Add Telegram or Discord for mobile access."
        )
        comms_desc.setProperty("class", "description")
        comms_desc.setWordWrap(True)
        comms_desc.setStyleSheet("color: #8888aa; font-size: 11px; background: transparent; border: none;")
        comms_form.addRow(comms_desc)

        self.telegram_check = QCheckBox("  Enable Telegram")
        self.telegram_check.setChecked(self.wizard.config.get("telegram_enabled", False))
        comms_form.addRow(self.telegram_check)

        self.telegram_token = self._key_field()
        comms_form.addRow("  Bot Token:", self.telegram_token)

        self.telegram_owner = QLineEdit()
        self.telegram_owner.setPlaceholderText("Your numeric Telegram user ID")
        comms_form.addRow("  Owner ID:", self.telegram_owner)

        self.discord_check = QCheckBox("  Enable Discord")
        self.discord_check.setChecked(self.wizard.config.get("discord_enabled", False))
        comms_form.addRow(self.discord_check)

        self.discord_token = self._key_field()
        comms_form.addRow("  Bot Token:", self.discord_token)

        form_layout.addWidget(comms_group)

        scroll.setWidget(scroll_content)
        outer.addWidget(scroll, stretch=1)

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
        outer.addLayout(nav)

    def _key_field(self) -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText("Paste your API key here")
        return field

    def _update_provider_desc(self, provider: str):
        """Update the description label based on selected provider."""
        descs = {
            "gemini": "Google Gemini — excellent tool use, free tier available. Recommended for most users.",
            "anthropic": "Anthropic Claude — strong reasoning and coding. Requires paid API key.",
            "openai": "OpenAI GPT — widely supported, strong general performance. Requires paid API key.",
            "alibaba": "Alibaba Qwen — competitive open-weight models via DashScope API.",
            "ollama": "Ollama (Local) — fully private, no API costs. Requires local GPU for best results.",
        }
        self.provider_desc.setText(descs.get(provider, ""))

    def _load_existing(self):
        """Pre-populate from existing credentials.env."""
        creds = _load_existing_creds()
        if creds.get("GEMINI_API_KEY"):
            self.gemini_key.setText(creds["GEMINI_API_KEY"])
        if creds.get("ANTHROPIC_API_KEY"):
            self.anthropic_key.setText(creds["ANTHROPIC_API_KEY"])
        if creds.get("OPENAI_API_KEY"):
            self.openai_key.setText(creds["OPENAI_API_KEY"])
        if creds.get("ALIBABA_API_KEY"):
            self.alibaba_key.setText(creds["ALIBABA_API_KEY"])
        if creds.get("OLLAMA_URL"):
            self.ollama_url.setText(creds["OLLAMA_URL"])
        if creds.get("OLLAMA_MODEL"):
            self.ollama_model.setText(creds["OLLAMA_MODEL"])
        if creds.get("HELIX_TELEGRAM_TOKEN"):
            self.telegram_token.setText(creds["HELIX_TELEGRAM_TOKEN"])
            self.telegram_check.setChecked(True)
        if creds.get("TELEGRAM_OWNER_ID"):
            self.telegram_owner.setText(creds["TELEGRAM_OWNER_ID"])
        if creds.get("HELIX_DISCORD_TOKEN"):
            self.discord_token.setText(creds["HELIX_DISCORD_TOKEN"])
            self.discord_check.setChecked(True)
        if creds.get("HELIX_VISION_PROVIDER"):
            self.vision_combo.setCurrentText(creds["HELIX_VISION_PROVIDER"])
        if creds.get("HELIX_PROVIDER"):
            self.provider_combo.setCurrentText(creds["HELIX_PROVIDER"])

    def _save_and_next(self):
        """Save credential values to config and advance."""
        cfg = self.wizard.config
        cfg["gemini_api_key"] = self.gemini_key.text().strip()
        cfg["anthropic_api_key"] = self.anthropic_key.text().strip()
        cfg["openai_api_key"] = self.openai_key.text().strip()
        cfg["alibaba_api_key"] = self.alibaba_key.text().strip()
        cfg["ollama_url"] = self.ollama_url.text().strip() or "http://localhost:11434"
        cfg["ollama_model"] = self.ollama_model.text().strip()
        cfg["llm_provider"] = self.provider_combo.currentText()
        cfg["vision_provider"] = self.vision_combo.currentText()
        cfg["telegram_enabled"] = self.telegram_check.isChecked()
        cfg["telegram_token"] = self.telegram_token.text().strip()
        cfg["telegram_owner_id"] = self.telegram_owner.text().strip()
        cfg["discord_enabled"] = self.discord_check.isChecked()
        cfg["discord_token"] = self.discord_token.text().strip()
        self.wizard.next_page()
