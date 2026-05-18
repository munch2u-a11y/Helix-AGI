"""
Helix — Scratchpad (Markdown)

A plain-text notepad. Helix writes notes and reminders here.
The preconscious reads it each pulse to surface due items.

Stored as a single markdown file — natural language, not JSON.
The model reads and writes the same format a human would.

Notes have optional due timestamps. Due/overdue notes get
surfaced as urgent reminders in peripheral awareness.
"""

import os
import re
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("helix.core.scratchpad")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _now_short() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class Scratchpad:
    """Markdown-based notepad for the conscious mind."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.filepath = os.path.join(data_dir, "scratchpad.md")

        if not os.path.exists(self.filepath):
            self._write_initial()

    def _write_initial(self):
        """Create the initial empty scratchpad."""
        with open(self.filepath, "w") as f:
            f.write("# Scratchpad\n\n")

    def _read(self) -> str:
        """Read the full scratchpad text."""
        try:
            with open(self.filepath, "r") as f:
                return f.read()
        except Exception:
            return "# Scratchpad\n\n"

    def _write(self, text: str):
        """Write the full scratchpad."""
        with open(self.filepath, "w") as f:
            f.write(text)

    # ── Note Management ──────────────────────────────────────────────

    def add_note(
        self,
        content: str,
        due_at: Optional[str] = None,
    ) -> str:
        """Add a note to the scratchpad. Returns the note marker."""
        text = self._read()
        timestamp = _now_short()

        # Generate a short ID
        note_id = f"n{int(datetime.now().timestamp()) % 100000}"

        # Build the note line
        due_str = f" [due: {due_at}]" if due_at else ""
        note_line = f"- [ ] ({note_id}) {content}{due_str}  ← {timestamp}\n"

        # Append the note
        text += note_line
        self._write(text)

        logger.info(f"Scratchpad: added '{content[:60]}' ({note_id})")
        return note_id

    def complete_note(self, note_id: str) -> bool:
        """Mark a note as done by checking its box."""
        # Normalize: accept both "n12345" and "12345"
        nid = str(note_id)
        if not nid.startswith("n"):
            nid = f"n{nid}"

        text = self._read()

        # Find the unchecked note with this ID and check it
        pattern = rf"- \[ \] \({re.escape(nid)}\)"
        replacement = f"- [x] ({nid})"

        new_text, count = re.subn(pattern, replacement, text, count=1)
        if count > 0:
            self._write(new_text)
            logger.info(f"Scratchpad: completed '{nid}'")
            return True
        return False

    def remove_note(self, note_id: str) -> bool:
        """Remove a note entirely."""
        # Normalize: accept both "n12345" and "12345"
        nid = str(note_id)
        if not nid.startswith("n"):
            nid = f"n{nid}"

        text = self._read()
        lines = text.split("\n")

        original_count = len(lines)
        lines = [l for l in lines if f"({nid})" not in l]

        if len(lines) < original_count:
            self._write("\n".join(lines))
            return True
        return False

    def update_note(self, note_id: str, new_content: str) -> bool:
        """Update the content of an existing note in-place."""
        nid = str(note_id)
        if not nid.startswith("n"):
            nid = f"n{nid}"

        text = self._read()
        timestamp = _now_short()

        # Match the note line (checked or unchecked)
        pattern = rf"(- \[[ x/]\] \({re.escape(nid)}\)) .+?(\s*←\s*.+)?$"
        replacement = rf"\1 {new_content}  ← {timestamp}"
        new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
        if count > 0:
            self._write(new_text)
            logger.info(f"Scratchpad: updated '{nid}'")
            return True
        return False

    def clear_completed(self) -> int:
        """Remove all checked [x] notes. Returns count removed."""
        text = self._read()
        lines = text.split("\n")
        original = len(lines)
        lines = [l for l in lines if not l.strip().startswith("- [x]")]
        removed = original - len(lines)
        if removed > 0:
            self._write("\n".join(lines))
            logger.info(f"Scratchpad: cleared {removed} completed notes")
        return removed

    def clear_all(self) -> int:
        """Remove ALL notes (active and completed). Returns count removed."""
        text = self._read()
        lines = text.split("\n")
        original = len(lines)
        lines = [l for l in lines if not l.strip().startswith("- [")]
        removed = original - len(lines)
        if removed > 0:
            self._write("\n".join(lines))
            logger.info(f"Scratchpad: cleared ALL {removed} notes")
        return removed

    # ── Queries ──────────────────────────────────────────────────────

    def get_active_notes(self) -> List[Dict[str, Any]]:
        """Parse out all unchecked notes."""
        text = self._read()
        notes = []

        pattern = r"- \[ \] \((\w+)\) (.+?)(?:\s+\[due: ([^\]]+)\])?\s*←\s*(.+)$"
        for match in re.finditer(pattern, text, re.MULTILINE):
            notes.append({
                "id": match.group(1),
                "content": match.group(2).strip(),
                "due_at": match.group(3),
                "created_at": match.group(4).strip(),
                "status": "active",
            })
        return notes

    def get_due_notes(self) -> List[Dict[str, Any]]:
        """Get notes that are past their due time."""
        now = _now_iso()
        active = self.get_active_notes()
        return [n for n in active if n.get("due_at") and n["due_at"] <= now]

    def get_summary(self) -> str:
        """Get a compact summary for preconscious injection.

        Returns natural language — urgent reminders and brief excerpts of active notes.
        """
        active = self.get_active_notes()
        due = self.get_due_notes()
        if not active:
            return ""

        parts = []
        # Due notes first (urgent)
        for note in due:
            parts.append(f"(REMINDER DUE: {note['content'][:80]})")

        # Other active notes – include up to three excerpts
        non_due = [n for n in active if n not in due]
        if non_due:
            excerpts = []
            for note in non_due[:3]:
                excerpts.append(note['content'][:80])
            excerpt_str = "; ".join(excerpts)
            parts.append(f"(scratchpad: {len(non_due)} active note(s): {excerpt_str})")

        return "\n".join(parts)
