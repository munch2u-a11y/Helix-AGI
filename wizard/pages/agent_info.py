"""
Wizard Page 3: Agent Info

Collects agent name, creator name, bootstrap profile, and personality archetype.
Uses clickable card buttons instead of radio buttons for easy selection.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QFormLayout, QScrollArea,
    QSpacerItem, QSizePolicy, QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSize, QTimer
from PyQt6.QtGui import QColor
from wizard.ai_helper import AiHelperBanner


CARD_NORMAL = """
    QPushButton {{
        background: rgba(15, 22, 41, 0.7);
        border: 1px solid rgba(42, 42, 94, 0.6);
        border-radius: 10px;
        padding: 14px;
        text-align: left;
        color: #e8e8f0;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background: rgba(30, 42, 74, 0.9);
        border-color: rgba(167, 139, 250, 0.4);
    }}
"""

CARD_SELECTED = """
    QPushButton {{
        background: rgba(124, 58, 237, 0.12);
        border: 2px solid rgba(167, 139, 250, 0.7);
        border-radius: 10px;
        padding: 14px;
        text-align: left;
        color: #e8e8f0;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background: rgba(124, 58, 237, 0.18);
    }}
"""

PERSONALITY_NORMAL = """
    QPushButton {{
        background: rgba(15, 22, 41, 0.7);
        border: 1px solid rgba(42, 42, 94, 0.6);
        border-radius: 10px;
        padding: 12px 10px;
        color: #e8e8f0;
        font-size: 11px;
    }}
    QPushButton:hover {{
        background: rgba(30, 42, 74, 0.9);
        border-color: rgba(167, 139, 250, 0.4);
    }}
"""

PERSONALITY_SELECTED = """
    QPushButton {{
        background: rgba(124, 58, 237, 0.12);
        border: 2px solid rgba(167, 139, 250, 0.7);
        border-radius: 10px;
        padding: 12px 10px;
        color: #e8e8f0;
        font-size: 11px;
    }}
    QPushButton:hover {{
        background: rgba(124, 58, 237, 0.18);
    }}
"""


class AgentInfoPage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self._selected_profile = wizard.config.get("bootstrap_profile", "prepared")
        self._selected_personality = wizard.config.get("personality", "curious")
        self._profile_buttons = {}
        self._personality_buttons = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 24, 60, 24)
        layout.setSpacing(12)

        heading = QLabel("Agent Identity")
        heading.setProperty("class", "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        sub = QLabel(
            "Give your agent a name and personality. These define its initial beliefs\n"
            "and communication style. The name and bootstrap profile cannot be changed after creation."
        )
        sub.setProperty("class", "subheading")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # AI Helper
        self.ai_banner = AiHelperBanner("agent_info", self.wizard)
        layout.addWidget(self.ai_banner)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        inner = QVBoxLayout(scroll_content)
        inner.setSpacing(16)

        # ── Names ─────────────────────────────────────────────────────
        name_group = QGroupBox("Names")
        name_form = QFormLayout(name_group)
        name_form.setSpacing(10)

        self.agent_name = QLineEdit()
        self.agent_name.setPlaceholderText("e.g. Helix, Nova, Atlas...")
        self.agent_name.setText(self.wizard.config.get("agent_name", "Helix"))
        name_form.addRow("Agent Name:", self.agent_name)

        self.creator_name = QLineEdit()
        self.creator_name.setPlaceholderText("Your name")
        self.creator_name.setText(self.wizard.config.get("creator_name", ""))
        name_form.addRow("Your Name:", self.creator_name)

        inner.addWidget(name_group)

        # ── Bootstrap Profile ─────────────────────────────────────────
        profile_group = QGroupBox("Cognitive Bootstrap Profile")
        profile_layout = QVBoxLayout(profile_group)
        profile_layout.setSpacing(10)

        profile_desc = QLabel(
            "⚠️  Choose how much pre-loaded knowledge your agent starts with. "
            "This cannot be changed after creation."
        )
        profile_desc.setWordWrap(True)
        profile_desc.setStyleSheet("color: #fbbf24; font-size: 11px;")
        profile_layout.addWidget(profile_desc)

        profiles = [
            ("birth", "🐣  Birth — Blank Slate",
             "Minimal beliefs. Your agent learns everything from scratch. "
             "Develops its own unique perspective over time."),
            ("prepared", "📚  Prepared — Recommended",
             "Standard identity, tool skills, and system knowledge. "
             "Ready to help from pulse #1. Best for most users."),
            ("developed", "🎓  Developed — Advanced",
             "Includes meta-cognition, debugging strategies, and "
             "multi-step autonomy. For power users wanting full autonomy."),
        ]

        for value, title, desc in profiles:
            btn = QPushButton()
            btn.setMinimumHeight(60)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("profile_value", value)
            btn.setProperty("card_title", title)
            btn.setProperty("card_desc", desc)
            btn.clicked.connect(lambda checked, v=value: self._select_profile(v))
            self._profile_buttons[value] = btn
            profile_layout.addWidget(btn)

        self._update_profile_styles()
        inner.addWidget(profile_group)

        # ── Personality ───────────────────────────────────────────────
        personality_group = QGroupBox("Personality Archetype")
        personality_layout = QVBoxLayout(personality_group)
        personality_layout.setSpacing(8)

        personalities = [
            ("curious", "🔍  Curious",
             "Exploratory, inquisitive, loves to learn"),
            ("friendly", "🤝  Friendly",
             "Warm, collaborative, supportive"),
            ("safe", "🛡️  Safe",
             "Cautious, validation-focused, stable"),
            ("professional", "💼  Professional",
             "Concise, objective, efficient"),
        ]

        p_container = QHBoxLayout()
        p_container.setSpacing(8)
        for value, title, desc in personalities:
            btn = QPushButton()
            btn.setMinimumHeight(55)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("personality_value", value)
            btn.setProperty("card_title", title)
            btn.setProperty("card_desc", desc)
            btn.clicked.connect(lambda checked, v=value: self._select_personality(v))
            self._personality_buttons[value] = btn
            p_container.addWidget(btn)

        self._update_personality_styles()
        personality_layout.addLayout(p_container)
        inner.addWidget(personality_group)

        inner.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

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
        layout.addLayout(nav)

    def _select_profile(self, value):
        self._selected_profile = value
        self._update_profile_styles()
        self._animate_card(self._profile_buttons[value])

    def _select_personality(self, value):
        self._selected_personality = value
        self._update_personality_styles()
        self._animate_card(self._personality_buttons[value])

    def _update_profile_styles(self):
        for val, btn in self._profile_buttons.items():
            selected = val == self._selected_profile
            title = btn.property("card_title")
            desc = btn.property("card_desc")
            if selected:
                btn.setText(f"✓  {title}\n{desc}")
                btn.setStyleSheet(CARD_SELECTED)
            else:
                btn.setText(f"{title}\n{desc}")
                btn.setStyleSheet(CARD_NORMAL)
            self._apply_glow(btn, selected)

    def _update_personality_styles(self):
        for val, btn in self._personality_buttons.items():
            selected = val == self._selected_personality
            title = btn.property("card_title")
            desc = btn.property("card_desc")
            if selected:
                btn.setText(f"✓  {title}\n{desc}")
                btn.setStyleSheet(PERSONALITY_SELECTED)
            else:
                btn.setText(f"{title}\n{desc}")
                btn.setStyleSheet(PERSONALITY_NORMAL)
            self._apply_glow(btn, selected)

    def _apply_glow(self, btn, selected):
        """Apply or remove a purple glow shadow effect."""
        if selected:
            shadow = QGraphicsDropShadowEffect(btn)
            shadow.setColor(QColor(167, 139, 250, 120))
            shadow.setBlurRadius(25)
            shadow.setOffset(0, 0)
            btn.setGraphicsEffect(shadow)
        else:
            btn.setGraphicsEffect(None)

    def _animate_card(self, btn):
        """Quick pop animation on the selected card."""
        original_height = btn.minimumHeight()
        # Brief expand
        anim = QPropertyAnimation(btn, b"minimumHeight")
        anim.setDuration(150)
        anim.setStartValue(original_height)
        anim.setKeyValueAt(0.5, original_height + 4)
        anim.setEndValue(original_height)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Keep reference so it doesn't get GC'd
        btn._pop_anim = anim
        anim.start()

    def _save_and_next(self):
        cfg = self.wizard.config
        cfg["agent_name"] = self.agent_name.text().strip() or "Helix"
        cfg["creator_name"] = self.creator_name.text().strip() or "User"
        cfg["bootstrap_profile"] = self._selected_profile
        cfg["personality"] = self._selected_personality
        self.wizard.next_page()
