"""
Wizard Page 1: Welcome

Introduces the user to Helix‑AGI and offers an opt-in AI helper toggle.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QSpacerItem, QSizePolicy,
)
from PyQt6.QtCore import Qt


class WelcomePage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 40, 60, 40)
        layout.setSpacing(20)

        # Spacer at top
        layout.addSpacerItem(QSpacerItem(0, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Logo display
        from PyQt6.QtGui import QPixmap
        from pathlib import Path
        base_dir = Path(__file__).parent.parent.parent.resolve()
        logo_path = base_dir / "wizard" / "assets" / "helix_logo.png"
        if logo_path.exists():
            logo_lbl = QLabel()
            logo_pix = QPixmap(str(logo_path))
            logo_lbl.setPixmap(logo_pix.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo_lbl)

        # Hero heading
        heading = QLabel("Welcome to Helix‑AGI")
        heading.setProperty("class", "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        # Subtitle
        sub = QLabel(
            "Your personal autonomous AI agent.\n"
            "This wizard will guide you through setting up your agent step by step.\n"
            "No technical knowledge required — we'll explain everything as we go."
        )
        sub.setProperty("class", "subheading")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        layout.addSpacing(24)

        # Feature highlights
        features = [
            ("🧠", "Continuous Consciousness", "Your agent thinks and learns even when you're away"),
            ("🔧", "Powerful Tools", "Browse the web, manage files, send messages, and more"),
            ("🔒", "Safety First", "Built-in sandboxing and whitelist controls"),
            ("💾", "Persistent Memory", "Remembers conversations, learns preferences, builds beliefs"),
        ]

        features_container = QWidget()
        features_layout = QHBoxLayout(features_container)
        features_layout.setSpacing(20)

        for emoji, title, desc in features:
            card = QWidget()
            card.setStyleSheet("""
                background: rgba(30, 42, 74, 0.6);
                border: 1px solid rgba(42, 42, 94, 0.8);
                border-radius: 12px;
                padding: 16px;
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(8)

            icon_lbl = QLabel(emoji)
            icon_lbl.setStyleSheet("font-size: 28px; background: transparent; border: none;")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(icon_lbl)

            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent; border: none; color: #e8e8f0;")
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(title_lbl)

            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet("font-size: 11px; color: #8888aa; background: transparent; border: none;")
            desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_lbl.setWordWrap(True)
            card_layout.addWidget(desc_lbl)

            features_layout.addWidget(card)

        layout.addWidget(features_container)

        layout.addSpacing(16)

        # AI Helper opt-in
        self.ai_check = QCheckBox("  Enable AI Setup Assistant (requires an API key in the next step)")
        self.ai_check.setChecked(self.wizard.config.get("ai_assist", False))
        self.ai_check.stateChanged.connect(
            lambda state: self.wizard.config.update({"ai_assist": state == Qt.CheckState.Checked.value})
        )
        layout.addWidget(self.ai_check, alignment=Qt.AlignmentFlag.AlignCenter)

        # Spacer
        layout.addSpacerItem(QSpacerItem(0, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Navigation
        nav = QHBoxLayout()
        nav.addStretch()
        next_btn = QPushButton("Get Started  →")
        next_btn.setFixedWidth(200)
        next_btn.clicked.connect(self.wizard.next_page)
        nav.addWidget(next_btn)
        layout.addLayout(nav)
