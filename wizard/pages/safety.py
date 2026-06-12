"""
Wizard Page 5: Safety & Whitelist

Toggle safety mode, choose a whitelist preset (Strict / Balanced / Loose),
and customize the list. Presets are curated domain+command lists.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QTextEdit, QRadioButton, QButtonGroup,
    QSpacerItem, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import Qt
from wizard.ai_helper import AiHelperBanner


# ── Whitelist Presets ─────────────────────────────────────────────────

WHITELIST_STRICT = {
    "label": "🔒  Strict",
    "badge": "Research only",
    "desc": (
        "Only the highest-quality research, documentation, and reference sites.\n"
        "Best for agents focused on development, science, or education."
    ),
    "domains": [
        # Search
        "google.com",
        "scholar.google.com",
        "duckduckgo.com",
        # Code & Docs
        "github.com",
        "docs.python.org",
        "docs.rs",
        "developer.mozilla.org",
        "devdocs.io",
        "man7.org",
        # Research & Reference
        "arxiv.org",
        "wikipedia.org",
        "en.wikipedia.org",
        "nature.com",
        "sciencedirect.com",
        "pubmed.ncbi.nlm.nih.gov",
        # Stack Exchange
        "stackoverflow.com",
        "stackexchange.com",
        "superuser.com",
        "serverfault.com",
    ],
    "commands": [
        "git status",
        "git diff",
        "git log",
        "git add",
        "git commit",
        "git push",
        "git pull",
        "pip install",
        "pip list",
        "python3",
        "cat",
        "ls",
        "head",
        "tail",
        "wc",
        "grep",
        "find",
    ],
}

WHITELIST_BALANCED = {
    "label": "🛡️  Balanced",
    "badge": "RECOMMENDED",
    "desc": (
        "A broad list of generally safe, well-known sites for development,\n"
        "learning, news, and productivity. Good for most users."
    ),
    "domains": [
        # Everything in Strict
        *WHITELIST_STRICT["domains"],
        # General reference & learning
        "python.org",
        "pypi.org",
        "npmjs.com",
        "crates.io",
        "hub.docker.com",
        "readthedocs.io",
        "jupyter.org",
        # Tech news & discussion
        "news.ycombinator.com",
        "lobste.rs",
        "arstechnica.com",
        "techcrunch.com",
        "theverge.com",
        # Productivity & cloud
        "docs.google.com",
        "drive.google.com",
        "calendar.google.com",
        "notion.so",
        "trello.com",
        # Education
        "coursera.org",
        "edx.org",
        "khanacademy.org",
        "mit.edu",
        "stanford.edu",
        # AI / ML
        "huggingface.co",
        "openai.com",
        "anthropic.com",
        "deepmind.google",
        "ollama.com",
        # Utilities
        "regex101.com",
        "jsonlint.com",
        "draw.io",
        "excalidraw.com",
        "pastebin.com",
        # General knowledge
        "britannica.com",
        "bbc.com",
        "reuters.com",
        "apnews.com",
    ],
    "commands": [
        *WHITELIST_STRICT["commands"],
        "git branch",
        "git checkout",
        "git merge",
        "git stash",
        "git remote",
        "pip show",
        "pip freeze",
        "npm install",
        "npm run",
        "cargo build",
        "make",
        "cmake",
        "curl",
        "wget",
        "ssh",
        "scp",
        "docker ps",
        "docker images",
        "systemctl status",
        "journalctl",
        "df",
        "du",
        "free",
        "top",
        "htop",
        "ps aux",
        "whoami",
        "hostname",
        "uname",
        "date",
        "echo",
        "mkdir",
        "cp",
        "mv",
        "chmod",
        "touch",
    ],
}

WHITELIST_LOOSE = {
    "label": "🌐  Loose",
    "badge": "Exploratory",
    "desc": (
        "Everything in Balanced plus a wide range of sites useful for general\n"
        "research, hobbies, media, shopping, and everyday curiosity."
    ),
    "domains": [
        *WHITELIST_BALANCED["domains"],
        # Social & forums
        "reddit.com",
        "quora.com",
        "medium.com",
        "dev.to",
        "hashnode.dev",
        "substack.com",
        "discord.com",
        "twitter.com",
        "x.com",
        "mastodon.social",
        # Media & entertainment
        "youtube.com",
        "twitch.tv",
        "spotify.com",
        "soundcloud.com",
        "imdb.com",
        "rottentomatoes.com",
        "letterboxd.com",
        "goodreads.com",
        # Shopping & services
        "amazon.com",
        "ebay.com",
        "etsy.com",
        "newegg.com",
        # Maps & travel
        "maps.google.com",
        "openstreetmap.org",
        "tripadvisor.com",
        "booking.com",
        # Finance & data
        "finance.yahoo.com",
        "coinmarketcap.com",
        "tradingview.com",
        # DIY / Maker / Hobbies
        "instructables.com",
        "hackaday.com",
        "thingiverse.com",
        "printables.com",
        "allrecipes.com",
        # General
        "wolframalpha.com",
        "archive.org",
        "gutenberg.org",
        "weather.com",
        "timeanddate.com",
    ],
    "commands": [
        *WHITELIST_BALANCED["commands"],
        "docker run",
        "docker build",
        "docker exec",
        "docker compose",
        "apt list",
        "apt search",
        "snap list",
        "flatpak list",
        "ffmpeg",
        "ffprobe",
        "convert",
        "pdftk",
        "zip",
        "unzip",
        "tar",
        "gzip",
        "rsync",
        "screen",
        "tmux",
        "nmap",
        "ping",
        "traceroute",
        "dig",
        "whois",
    ],
}

PRESETS = [WHITELIST_STRICT, WHITELIST_BALANCED, WHITELIST_LOOSE]


def _preset_to_text(preset: dict) -> str:
    """Convert a preset dict into whitelist text (domains then commands)."""
    lines = []
    lines.append("# ── Allowed Domains ──")
    # Deduplicate while preserving order
    seen = set()
    for d in preset["domains"]:
        if d not in seen:
            lines.append(d)
            seen.add(d)
    lines.append("")
    lines.append("# ── Allowed Commands ──")
    seen = set()
    for c in preset["commands"]:
        if c not in seen:
            lines.append(c)
            seen.add(c)
    return "\n".join(lines)


class SafetyPage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 24, 60, 24)
        layout.setSpacing(16)

        heading = QLabel("Safety & Permissions")
        heading.setProperty("class", "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        sub = QLabel(
            "Control what your agent is allowed to do. Safety Mode sandboxes\n"
            "browser access, terminal commands, and desktop control behind a whitelist.\n"
            "You can always change these settings later."
        )
        sub.setProperty("class", "subheading")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # AI Helper
        self.ai_banner = AiHelperBanner("safety", self.wizard)
        layout.addWidget(self.ai_banner)

        layout.addSpacing(8)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(12)

        # ── Safety Mode Toggle ────────────────────────────────────────
        safety_group = QGroupBox("Safety Mode")
        safety_layout = QVBoxLayout(safety_group)
        safety_layout.setSpacing(12)

        self.safety_check = QCheckBox("  Enable Safety Mode  (Recommended)")
        self.safety_check.setChecked(self.wizard.config.get("safety_mode", True))
        self.safety_check.setStyleSheet("font-size: 14px; font-weight: 600;")
        safety_layout.addWidget(self.safety_check)

        safety_desc = QLabel(
            "When enabled, your agent's browser, terminal, and desktop actions are sandboxed.\n"
            "The agent must request permission for new domains, commands, and system actions.\n"
            "You'll be able to approve or deny these requests from the Settings tab."
        )
        safety_desc.setWordWrap(True)
        safety_desc.setStyleSheet("color: #8888aa; font-size: 11px; padding-left: 26px;")
        safety_layout.addWidget(safety_desc)

        # Warning for disabled safety
        self.safety_warning = QLabel(
            "⚠️ With Safety Mode OFF, your agent has unrestricted access to terminal,\n"
            "browser, and desktop controls. Only disable if you fully trust the environment."
        )
        self.safety_warning.setStyleSheet("""
            color: #f87171; font-size: 11px; background: rgba(248,113,113,0.08);
            border: 1px solid rgba(248,113,113,0.3); border-radius: 8px;
            padding: 10px; margin-left: 26px;
        """)
        self.safety_warning.setWordWrap(True)
        self.safety_warning.setVisible(not self.safety_check.isChecked())
        self.safety_check.toggled.connect(lambda checked: self.safety_warning.setVisible(not checked))
        safety_layout.addWidget(self.safety_warning)

        scroll_layout.addWidget(safety_group)

        # ── Whitelist Preset Selector ─────────────────────────────────
        preset_group = QGroupBox("Whitelist Preset")
        preset_layout = QVBoxLayout(preset_group)
        preset_layout.setSpacing(10)

        preset_desc = QLabel(
            "Choose a starter whitelist, then customize it below.\n"
            "The whitelist controls which websites and terminal commands your agent can use."
        )
        preset_desc.setWordWrap(True)
        preset_desc.setStyleSheet("color: #8888aa; font-size: 11px;")
        preset_layout.addWidget(preset_desc)

        self.preset_group = QButtonGroup(self)

        for i, preset in enumerate(PRESETS):
            card = QWidget()
            card.setObjectName(f"presetCard{i}")
            card.setStyleSheet(f"""
                QWidget#presetCard{i} {{
                    background: rgba(15, 22, 41, 0.7);
                    border: 1px solid rgba(42, 42, 94, 0.6);
                    border-radius: 10px;
                    padding: 10px 14px;
                }}
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setSpacing(12)

            radio = QRadioButton()
            # Default to Balanced
            radio.setChecked(i == 1)
            radio.setProperty("preset_index", i)
            self.preset_group.addButton(radio, i)
            card_layout.addWidget(radio)

            text_layout = QVBoxLayout()
            text_layout.setSpacing(4)

            # Title row with badge
            title_row = QHBoxLayout()
            title_lbl = QLabel(preset["label"])
            title_lbl.setStyleSheet("font-weight: 600; font-size: 13px; color: #e8e8f0;")
            title_row.addWidget(title_lbl)

            badge = QLabel(preset["badge"])
            if preset["badge"] == "RECOMMENDED":
                badge.setStyleSheet("""
                    background: rgba(74, 222, 128, 0.15);
                    color: #4ade80;
                    border: 1px solid rgba(74, 222, 128, 0.3);
                    border-radius: 6px;
                    padding: 2px 8px;
                    font-size: 9px;
                    font-weight: 600;
                    letter-spacing: 1px;
                """)
            else:
                badge.setStyleSheet("""
                    background: rgba(136, 136, 170, 0.12);
                    color: #8888aa;
                    border: 1px solid rgba(136, 136, 170, 0.25);
                    border-radius: 6px;
                    padding: 2px 8px;
                    font-size: 9px;
                    font-weight: 500;
                """)
            title_row.addWidget(badge)

            # Count badge
            n_domains = len(set(preset["domains"]))
            n_cmds = len(set(preset["commands"]))
            count_lbl = QLabel(f"{n_domains} sites · {n_cmds} commands")
            count_lbl.setStyleSheet("font-size: 10px; color: #666688;")
            title_row.addStretch()
            title_row.addWidget(count_lbl)

            text_layout.addLayout(title_row)

            desc_lbl = QLabel(preset["desc"])
            desc_lbl.setStyleSheet("font-size: 11px; color: #8888aa;")
            desc_lbl.setWordWrap(True)
            text_layout.addWidget(desc_lbl)

            card_layout.addLayout(text_layout, stretch=1)
            preset_layout.addWidget(card)

        self.preset_group.idToggled.connect(self._on_preset_changed)

        scroll_layout.addWidget(preset_group)

        # ── Editable Whitelist ────────────────────────────────────────
        edit_group = QGroupBox("Customize Whitelist")
        edit_layout = QVBoxLayout(edit_group)
        edit_layout.setSpacing(8)

        edit_desc = QLabel(
            "Edit the whitelist below. One entry per line.\n"
            "Lines starting with # are comments. You can add or remove entries freely."
        )
        edit_desc.setWordWrap(True)
        edit_desc.setStyleSheet("color: #8888aa; font-size: 11px;")
        edit_layout.addWidget(edit_desc)

        self.whitelist_edit = QTextEdit()
        self.whitelist_edit.setFixedHeight(180)
        self.whitelist_edit.setStyleSheet("""
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 11px;
            line-height: 1.4;
        """)

        # Pre-populate from existing config or default preset
        existing_wl = self.wizard.config.get("whitelist", [])
        if existing_wl:
            self.whitelist_edit.setPlainText("\n".join(existing_wl))
        else:
            # Default to Balanced preset
            self.whitelist_edit.setPlainText(_preset_to_text(WHITELIST_BALANCED))

        edit_layout.addWidget(self.whitelist_edit)

        scroll_layout.addWidget(edit_group)

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

    def _on_preset_changed(self, button_id, checked):
        """When a preset radio is selected, update the whitelist text."""
        if checked and 0 <= button_id < len(PRESETS):
            self.whitelist_edit.setPlainText(_preset_to_text(PRESETS[button_id]))

    def _save_and_next(self):
        cfg = self.wizard.config
        cfg["safety_mode"] = self.safety_check.isChecked()
        wl_text = self.whitelist_edit.toPlainText().strip()
        # Parse lines, skip comments and blanks
        cfg["whitelist"] = [
            line.strip() for line in wl_text.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        self.wizard.next_page()
