"""
Wizard Page 4: Tool Selection

Displays available toolsets from the tool registry with descriptions,
allowing users to enable/disable each group. Tool groups are auto-loaded
from the registry if available, otherwise uses a hardcoded fallback.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QScrollArea, QSpacerItem, QSizePolicy,
)
from PyQt6.QtCore import Qt
from wizard.ai_helper import AiHelperBanner


def _load_toolset_info():
    """Load toolset metadata from the declarations layer when available."""
    try:
        from tools.tool_declarations import TOOLSETS
        return [
            {
                "name": name,
                "description": meta.get("description", ""),
                "detail": meta.get("detail", meta.get("description", "")),
                "always_on": meta.get("always_on", False),
                "recommended": meta.get("recommended", False),
                "default_enabled": meta.get("default", False),
            }
            for name, meta in TOOLSETS.items()
        ]
    except Exception:
        return [
            {
                "name": "operational",
                "description": "Always-on communication and toolset management",
                "detail": "Minimum baseline so the agent can respond and manage optional tool groups.",
                "always_on": True,
                "recommended": True,
                "default_enabled": True,
            },
            {
                "name": "core",
                "description": "Optional memory, scratchpad, journaling, and verbalization tools",
                "detail": "Adds cognitive support tools without making them mandatory in every session.",
                "always_on": False,
                "recommended": True,
                "default_enabled": False,
            },
        ]


TOOLSET_INFO = _load_toolset_info()


class ToolSelectionPage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.checks = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 24, 60, 24)
        layout.setSpacing(12)

        heading = QLabel("Tool Selection")
        heading.setProperty("class", "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        sub = QLabel(
            "Choose which capabilities your agent should have.\n"
            "You can change these later in Settings. Recommended tools are marked."
        )
        sub.setProperty("class", "subheading")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # AI Helper
        self.ai_banner = AiHelperBanner("tools", self.wizard)
        layout.addWidget(self.ai_banner)

        layout.addSpacing(8)

        # Scrollable tool list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(8)

        current_tools = set(self.wizard.config.get("tool_set", []))

        for ts in TOOLSET_INFO:
            card = QWidget()
            card.setStyleSheet("""
                background: rgba(30, 42, 74, 0.5);
                border: 1px solid rgba(42, 42, 94, 0.6);
                border-radius: 10px;
                padding: 12px 16px;
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setSpacing(12)

            check = QCheckBox()
            if ts["always_on"]:
                check.setChecked(True)
                check.setEnabled(False)
            else:
                check.setChecked(ts["name"] in current_tools)
            self.checks[ts["name"]] = check
            card_layout.addWidget(check)

            text_layout = QVBoxLayout()
            text_layout.setSpacing(4)

            name_row = QHBoxLayout()
            name_lbl = QLabel(ts["name"].upper())
            name_lbl.setStyleSheet("font-weight: 700; font-size: 13px; color: #a78bfa; background: transparent; border: none;")
            name_row.addWidget(name_lbl)

            if ts["recommended"]:
                rec_badge = QLabel("RECOMMENDED")
                rec_badge.setStyleSheet("""
                    background: rgba(74, 222, 128, 0.15);
                    color: #4ade80;
                    border: 1px solid rgba(74, 222, 128, 0.3);
                    border-radius: 6px;
                    padding: 2px 8px;
                    font-size: 9px;
                    font-weight: 600;
                    letter-spacing: 1px;
                """)
                name_row.addWidget(rec_badge)

            if ts["always_on"]:
                req_badge = QLabel("REQUIRED")
                req_badge.setStyleSheet("""
                    background: rgba(251, 191, 36, 0.15);
                    color: #fbbf24;
                    border: 1px solid rgba(251, 191, 36, 0.3);
                    border-radius: 6px;
                    padding: 2px 8px;
                    font-size: 9px;
                    font-weight: 600;
                    letter-spacing: 1px;
                """)
                name_row.addWidget(req_badge)

            name_row.addStretch()
            text_layout.addLayout(name_row)

            desc_lbl = QLabel(ts["description"])
            desc_lbl.setStyleSheet("font-size: 12px; color: #e8e8f0; background: transparent; border: none;")
            desc_lbl.setWordWrap(True)
            text_layout.addWidget(desc_lbl)

            detail_lbl = QLabel(ts["detail"])
            detail_lbl.setStyleSheet("font-size: 11px; color: #8888aa; background: transparent; border: none;")
            detail_lbl.setWordWrap(True)
            text_layout.addWidget(detail_lbl)

            card_layout.addLayout(text_layout, stretch=1)
            scroll_layout.addWidget(card)

        scroll_layout.addStretch()
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

    def _save_and_next(self):
        selected = []
        for name, check in self.checks.items():
            if check.isChecked():
                selected.append(name)
        self.wizard.config["tool_set"] = selected
        self.wizard.next_page()
