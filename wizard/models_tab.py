"""
Models Tab — Active Model Selector and Configuration

Allows editing active LLM provider, active model, and API keys / local endpoints
directly from the running settings dashboard. Updates credentials.env on save.
"""

import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QLineEdit, QScrollArea, QFormLayout,
    QMessageBox,
)
from PyQt6.QtCore import Qt

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


class ModelsTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._build()
        self._load_existing()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 20, 40, 20)

        heading = QLabel("🤖  Models")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #a78bfa;")
        outer.addWidget(heading)

        sub = QLabel("Configure your active LLM provider, select model parameters, and auto-detect available models.")
        sub.setStyleSheet("font-size: 12px; color: #8888aa; margin-bottom: 12px;")
        outer.addWidget(sub)

        # Scrollable settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        settings_layout = QVBoxLayout(scroll_content)
        settings_layout.setSpacing(16)

        # ── Primary Provider Group ────────────────────────────────────
        provider_group = QGroupBox("Primary LLM Provider")
        provider_form = QFormLayout(provider_group)
        provider_form.setSpacing(12)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["gemini", "anthropic", "openai", "alibaba", "ollama", "llama_cpp"])
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        provider_form.addRow("Active Provider:", self.provider_combo)

        self.provider_desc = QLabel()
        self.provider_desc.setWordWrap(True)
        self.provider_desc.setStyleSheet("font-size: 11px; color: #8888aa;")
        self._update_provider_desc(self.provider_combo.currentText())
        provider_form.addRow(self.provider_desc)

        # ── Model Selection Group ─────────────────────────────────────
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setPlaceholderText("Select or type model name...")

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

        model_row = QHBoxLayout()
        model_row.addWidget(self.model_combo, stretch=1)
        model_row.addWidget(self.detect_btn)
        provider_form.addRow("Active Model:", model_row)

        settings_layout.addWidget(provider_group)

        # ── Credentials & Endpoints Group ──────────────────────────────
        self.cred_group = QGroupBox("API Keys & Local Endpoints")
        self.cred_form = QFormLayout(self.cred_group)
        self.cred_form.setSpacing(12)

        self.gemini_key = self._key_field()
        self.cred_form.addRow("Gemini API Key:", self.gemini_key)

        self.anthropic_key = self._key_field()
        self.cred_form.addRow("Anthropic API Key:", self.anthropic_key)

        self.openai_key = self._key_field()
        self.cred_form.addRow("OpenAI API Key:", self.openai_key)

        self.alibaba_key = self._key_field()
        self.cred_form.addRow("Alibaba API Key:", self.alibaba_key)

        self.ollama_url = QLineEdit()
        self.ollama_url.setPlaceholderText("http://localhost:11434")
        self.cred_form.addRow("Ollama URL:", self.ollama_url)

        settings_layout.addWidget(self.cred_group)

        scroll.setWidget(scroll_content)
        outer.addWidget(scroll, stretch=1)

        # ── Save Button ───────────────────────────────────────────────
        self.save_btn = QPushButton("💾  Save Model Settings")
        self.save_btn.setFixedHeight(40)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #8b5cf6;
                color: white;
                font-size: 13px;
                font-weight: bold;
                border-radius: 8px;
            }
            QPushButton:hover {
                background: #7c3aed;
            }
        """)
        self.save_btn.clicked.connect(self._save_settings)
        outer.addWidget(self.save_btn)

    def _key_field(self) -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText("Paste API key here")
        return field

    def _update_provider_desc(self, provider: str):
        descs = {
            "gemini": "Google Gemini — excellent tool use, free tier available. Recommended for most users.",
            "anthropic": "Anthropic Claude — strong reasoning and coding. Requires paid API key.",
            "openai": "OpenAI GPT — widely supported, strong general performance. Requires paid API key.",
            "alibaba": "Alibaba Qwen — competitive open-weight models via DashScope API.",
            "ollama": "Ollama (Local) — fully private, no API costs. Requires local GPU for best results.",
            "llama_cpp": "llama.cpp (Local) — run GGUF models directly on CPU/GPU without external services.",
        }
        self.provider_desc.setText(descs.get(provider, ""))

    def _on_provider_changed(self, provider: str):
        self._update_provider_desc(provider)
        self._update_models_list()

    def _update_models_list(self):
        provider = self.provider_combo.currentText()
        from wizard.model_detector import get_default_models
        defaults = get_default_models(provider)

        self.model_combo.clear()
        self.model_combo.addItems(defaults)

        creds = _load_existing_creds()
        config_model = self.app.config.get("llm_model") or creds.get("HELIX_MODEL", "")
        if config_model:
            config_provider = self.app.config.get("llm_provider") or creds.get("HELIX_PROVIDER", "gemini")
            if provider == config_provider:
                self.model_combo.setEditText(config_model)

    def _on_detect_clicked(self):
        provider = self.provider_combo.currentText()
        from wizard.model_detector import (
            detect_ollama_models,
            detect_gguf_models,
            fetch_gemini_models,
        )
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
        creds = _load_existing_creds()
        self.gemini_key.setText(creds.get("GEMINI_API_KEY", ""))
        self.anthropic_key.setText(creds.get("ANTHROPIC_API_KEY", ""))
        self.openai_key.setText(creds.get("OPENAI_API_KEY", ""))
        self.alibaba_key.setText(creds.get("ALIBABA_API_KEY", ""))
        self.ollama_url.setText(creds.get("OLLAMA_URL", "http://localhost:11434"))

        provider = creds.get("HELIX_PROVIDER", "gemini")
        self.provider_combo.setCurrentText(provider)

        self._update_models_list()

    def _save_settings(self):
        # Update app configuration dict
        cfg = self.app.config
        cfg["gemini_api_key"] = self.gemini_key.text().strip()
        cfg["anthropic_api_key"] = self.anthropic_key.text().strip()
        cfg["openai_api_key"] = self.openai_key.text().strip()
        cfg["alibaba_api_key"] = self.alibaba_key.text().strip()
        cfg["ollama_url"] = self.ollama_url.text().strip() or "http://localhost:11434"
        cfg["llm_provider"] = self.provider_combo.currentText()
        cfg["llm_model"] = self.model_combo.currentText().strip()

        # Update legacy parameters
        if cfg["llm_provider"] == "ollama":
            cfg["ollama_model"] = cfg["llm_model"]

        # Write credentials.env file
        try:
            self.app._write_credentials()
            QMessageBox.information(self, "Saved", "Model settings saved and synchronized successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error Saving", f"Failed to write configuration: {e}")
