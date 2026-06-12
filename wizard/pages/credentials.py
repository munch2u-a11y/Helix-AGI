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

        # ── Local Providers ────────────────────────────────────────────
        local_label = QLabel("🖥️  Local Providers")
        local_label.setStyleSheet("font-weight: 600; font-size: 12px; color: #4ade80; margin-top: 8px;")
        llm_form.addRow(local_label)

        # Ollama
        ollama_sub = QLabel("Ollama  (runs models via ollama service)")
        ollama_sub.setStyleSheet("font-size: 11px; color: #a78bfa; font-weight: 600;")
        llm_form.addRow(ollama_sub)

        self.ollama_url = QLineEdit()
        self.ollama_url.setPlaceholderText("http://localhost:11434  (default Ollama URL)")
        self.ollama_url.setText(self.wizard.config.get("ollama_url", "http://localhost:11434"))
        llm_form.addRow("Ollama URL:", self.ollama_url)

        self.ollama_model = QLineEdit()
        self.ollama_model.setPlaceholderText("e.g. llama3, qwen2.5, gemma4, mistral...")
        self.ollama_model.setText(self.wizard.config.get("ollama_model", ""))
        llm_form.addRow("Ollama Model:", self.ollama_model)

        ollama_hint = QLabel(
            "💡 Ollama runs models locally — no API costs. Install from ollama.com\n"
            "   then pull a model: ollama pull gemma4"
        )
        ollama_hint.setWordWrap(True)
        ollama_hint.setStyleSheet("font-size: 10px; color: #666688; padding-left: 4px;")
        llm_form.addRow(ollama_hint)

        # llama.cpp / GGUF
        gguf_sub = QLabel("llama.cpp  (run GGUF model files directly)")
        gguf_sub.setStyleSheet("font-size: 11px; color: #4ade80; font-weight: 600; margin-top: 6px;")
        llm_form.addRow(gguf_sub)

        # Auto-detect GGUF files
        from wizard.model_detector import detect_gguf_models
        from wizard.app import BASE_DIR
        gguf_models = detect_gguf_models(BASE_DIR)

        if gguf_models:
            gguf_status = QLabel(
                f"✅  Found {len(gguf_models)} model(s) in models/:\n"
                f"   {', '.join(gguf_models)}"
            )
            gguf_status.setStyleSheet("font-size: 11px; color: #4ade80; padding-left: 4px;")
        else:
            gguf_status = QLabel(
                "No .gguf files found in models/ directory.\n"
                "Download GGUF models from huggingface.co and place them in models/"
            )
            gguf_status.setStyleSheet("font-size: 11px; color: #666688; padding-left: 4px;")
        gguf_status.setWordWrap(True)
        llm_form.addRow(gguf_status)

        gguf_hint = QLabel(
            "💡 llama.cpp runs GGUF models directly on your GPU/CPU — no Ollama needed.\n"
            "   Select 'llama.cpp (Local GGUF)' as primary provider below, then click Detect Models."
        )
        gguf_hint.setWordWrap(True)
        gguf_hint.setStyleSheet("font-size: 10px; color: #666688; padding-left: 4px;")
        llm_form.addRow(gguf_hint)

        # ── Primary Provider Selector ─────────────────────────────────
        provider_label = QLabel("⭐  Primary Provider")
        provider_label.setStyleSheet("font-weight: 600; font-size: 12px; color: #c4b5fd; margin-top: 8px;")
        llm_form.addRow(provider_label)

        self.provider_combo = QComboBox()
        self._provider_map = {
            "Gemini (Google)": "gemini",
            "Claude (Anthropic)": "anthropic",
            "GPT (OpenAI)": "openai",
            "Qwen (Alibaba)": "alibaba",
            "Ollama (Local)": "ollama",
            "llama.cpp (Local GGUF)": "llama_cpp",
        }
        self._provider_reverse = {v: k for k, v in self._provider_map.items()}
        self.provider_combo.addItems(list(self._provider_map.keys()))

        # Set current from config
        saved_provider = self.wizard.config.get("llm_provider", "gemini")
        display_name = self._provider_reverse.get(saved_provider, "Gemini (Google)")
        self.provider_combo.setCurrentText(display_name)

        # Provider description that updates on selection
        self.provider_desc = QLabel()
        self.provider_desc.setWordWrap(True)
        self.provider_desc.setStyleSheet("font-size: 10px; color: #8888aa; padding-left: 4px;")
        self._update_provider_desc(self.provider_combo.currentText())
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)

        llm_form.addRow("Use as primary:", self.provider_combo)
        llm_form.addRow(self.provider_desc)

        # ── Primary Model Selector ────────────────────────────────────
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setPlaceholderText("Select or type model name...")

        detect_row = QHBoxLayout()
        self.detect_btn = QPushButton("🔍  Detect Models")
        self.detect_btn.setFixedHeight(30)
        self.detect_btn.setStyleSheet("""
            QPushButton {
                background: rgba(167, 139, 250, 0.1);
                border: 1px solid rgba(167, 139, 250, 0.4);
                color: #c4b5fd;
                border-radius: 6px;
                padding: 0 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: rgba(167, 139, 250, 0.2);
            }
        """)
        self.detect_btn.clicked.connect(self._on_detect_clicked)
        detect_row.addWidget(self.model_combo, stretch=1)
        detect_row.addWidget(self.detect_btn)

        llm_form.addRow("Active Model:", detect_row)

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

    def _get_provider(self) -> str:
        """Get the internal provider key from the display label."""
        display = self.provider_combo.currentText()
        return self._provider_map.get(display, "gemini")

    def _update_provider_desc(self, provider: str):
        """Update the description label based on selected provider."""
        descs = {
            "gemini": "Google Gemini — excellent tool use, free tier available. Recommended for most users.",
            "anthropic": "Anthropic Claude — strong reasoning and coding. Requires paid API key.",
            "openai": "OpenAI GPT — widely supported, strong general performance. Requires paid API key.",
            "alibaba": "Alibaba Qwen — competitive open-weight models via DashScope API.",
            "ollama": "Ollama (Local) — fully private, no API costs. Requires local GPU for best results.",
            "llama_cpp": "llama.cpp (Local) — run GGUF models directly on CPU/GPU without external services.",
        }
        self.provider_desc.setText(descs.get(provider, ""))

    def _on_provider_changed(self, display_name: str):
        """Handle LLM provider selection changes."""
        provider = self._provider_map.get(display_name, "gemini")
        self._update_provider_desc(provider)
        self._update_models_list()

    def _update_models_list(self):
        """Load default models for the selected provider into the dropdown."""
        provider = self._get_provider()
        from wizard.model_detector import get_default_models
        defaults = get_default_models(provider)
        
        self.model_combo.clear()
        self.model_combo.addItems(defaults)
        
        # Prefill from config/existing env if matching provider
        creds = _load_existing_creds()
        config_model = self.wizard.config.get("llm_model") or creds.get("HELIX_MODEL", "")
        if config_model:
            config_provider = self.wizard.config.get("llm_provider") or creds.get("HELIX_PROVIDER", "gemini")
            if provider == config_provider:
                self.model_combo.setEditText(config_model)

    def _on_detect_clicked(self):
        """Trigger dynamic discovery of models for the selected provider."""
        provider = self._get_provider()
        from wizard.model_detector import (
            detect_ollama_models,
            detect_gguf_models,
            fetch_gemini_models
        )
        from PyQt6.QtWidgets import QMessageBox
        
        detected = []
        if provider == "ollama":
            url = self.ollama_url.text().strip() or "http://localhost:11434"
            detected = detect_ollama_models(url)
            if not detected:
                QMessageBox.warning(self, "Detection Failed", f"Could not find any running Ollama models at {url}.")
        elif provider == "llama_cpp":
            from wizard.app import BASE_DIR
            detected = detect_gguf_models(BASE_DIR)
            if not detected:
                QMessageBox.warning(self, "Detection Failed", "No .gguf models found in models/ directory.")
        elif provider == "gemini":
            key = self.gemini_key.text().strip()
            if not key:
                QMessageBox.warning(self, "Missing API Key", "Please enter a Gemini API Key first.")
                return
            detected = fetch_gemini_models(key)
            if not detected:
                QMessageBox.warning(self, "Detection Failed", "Could not fetch models. Check your API key and network connection.")
        else:
            QMessageBox.information(
                self, "Auto-Detection",
                f"Auto-detection is not supported for {provider.title()}. Please select or type the model name manually."
            )
            return
            
        if detected:
            self.model_combo.clear()
            self.model_combo.addItems(detected)
            self.model_combo.setCurrentIndex(0)
            QMessageBox.information(self, "Success", f"Detected {len(detected)} model(s) successfully!")

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
            display = self._provider_reverse.get(
                creds["HELIX_PROVIDER"],
                "Gemini (Google)"
            )
            self.provider_combo.setCurrentText(display)
        
        # Load model list and set current edit text
        self._update_models_list()

    def _save_and_next(self):
        """Save credential values to config and advance."""
        cfg = self.wizard.config
        cfg["gemini_api_key"] = self.gemini_key.text().strip()
        cfg["anthropic_api_key"] = self.anthropic_key.text().strip()
        cfg["openai_api_key"] = self.openai_key.text().strip()
        cfg["alibaba_api_key"] = self.alibaba_key.text().strip()
        cfg["ollama_url"] = self.ollama_url.text().strip() or "http://localhost:11434"
        cfg["llm_provider"] = self._get_provider()
        cfg["llm_model"] = self.model_combo.currentText().strip()
        
        # For legacy compatibility, save to ollama_model if ollama is selected
        if cfg["llm_provider"] == "ollama":
            cfg["ollama_model"] = cfg["llm_model"]
        else:
            cfg["ollama_model"] = self.ollama_model.text().strip()

        cfg["vision_provider"] = self.vision_combo.currentText()
        cfg["telegram_enabled"] = self.telegram_check.isChecked()
        cfg["telegram_token"] = self.telegram_token.text().strip()
        cfg["telegram_owner_id"] = self.telegram_owner.text().strip()
        cfg["discord_enabled"] = self.discord_check.isChecked()
        cfg["discord_token"] = self.discord_token.text().strip()
        self.wizard.next_page()
