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
                text = f.read()
                return self._check_postponed(text)
        except Exception:
            return "# Scratchpad\n\n"

    def _write(self, text: str):
        """Write the full scratchpad."""
        with open(self.filepath, "w") as f:
            f.write(text)

    def _check_postponed(self, text: str) -> str:
        """Find any expired postponed notes and activate them back to '- [ ]'."""
        now = _now_iso()
        modified = False
        new_lines = []
        
        for line in text.splitlines(keepends=True):
            match = re.match(r"^\s*-\s*\[P\]\s*\((\w+)\)\s*(.*?)\s*\[postponed_until:\s*([^\]]+)\](.*)$", line)
            if match:
                note_id = match.group(1)
                content = match.group(2)
                postpone_time = match.group(3).strip()
                rest = match.group(4)
                
                # Check if it has expired
                if postpone_time <= now:
                    # Activate it! Change [P] to [ ] and strip the [postponed_until: ...] part
                    activated_line = f"- [ ] ({note_id}) {content}{rest}"
                    new_lines.append(activated_line)
                    modified = True
                    logger.info(f"Scratchpad: activated expired postponed note {note_id}")
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        new_text = "".join(new_lines)
        if modified:
            self._write(new_text)
        return new_text

    # ── Note Management ──────────────────────────────────────────────

    def add_note(
        self,
        content: str,
        due_at: Optional[str] = None,
        postpone_until: Optional[str] = None,
    ) -> str:
        """Add a note to the scratchpad. Returns the note marker."""
        text = self._read()
        timestamp = _now_short()

        # Generate a short ID
        note_id = f"n{int(datetime.now().timestamp()) % 100000}"

        # Build the note line
        status_box = "[P]" if postpone_until else "[ ]"
        postpone_str = f" [postponed_until: {postpone_until}]" if postpone_until else ""
        due_str = f" [due: {due_at}]" if due_at else ""
        note_line = f"- {status_box} ({note_id}) {content}{due_str}{postpone_str}  ← {timestamp}\n"

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
        pattern = rf"- \[[ x/P]\] \({re.escape(nid)}\) .*?(?:\s*←\s*.*?)?(?=\n- \[|\Z)\n?"
        
        new_text, count = re.subn(pattern, "", text, count=1, flags=re.DOTALL)
        if count > 0:
            self._write(new_text)
            logger.info(f"Scratchpad: removed '{nid}'")
            return True
        return False

    def update_note(self, note_id: str, new_content: str, postpone_until: Optional[str] = None) -> bool:
        """Update the content of an existing note in-place, and optionally update postpone lock."""
        nid = str(note_id)
        if not nid.startswith("n"):
            nid = f"n{nid}"

        text = self._read()
        timestamp = _now_short()

        lines = text.splitlines(keepends=True)
        modified = False
        new_lines = []

        for line in lines:
            match = re.match(rf"^(\s*-\s*\[([ x/P])\]\s*\({re.escape(nid)}\)\s*)(.*?)(?:\s*←\s*.*?)?(\s*)$", line)
            if match:
                prefix = match.group(1)
                old_status = match.group(2)
                old_text = match.group(3)
                suffix = match.group(4)

                # Parse existing due_at
                due_match = re.search(r"\[due:\s*([^\]]+)\]", old_text)
                due_str = f" [due: {due_match.group(1)}]" if due_match else ""

                # Strip out existing metadata from new_content
                clean_content = re.sub(r"\s*\[due:\s*[^\]]+\]", "", new_content)
                clean_content = re.sub(r"\s*\[postponed_until:\s*[^\]]+\]", "", clean_content).strip()

                # Determine new status box and postpone string
                if postpone_until == "clear":
                    status_box = "[ ]"
                    postpone_str = ""
                elif postpone_until:
                    status_box = "[P]"
                    postpone_str = f" [postponed_until: {postpone_until}]"
                else:
                    status_box = f"[{old_status}]"
                    postpone_match = re.search(r"\[postponed_until:\s*([^\]]+)\]", old_text)
                    postpone_str = f" [postponed_until: {postpone_match.group(1)}]" if postpone_match else ""

                new_prefix = re.sub(r"-\s*\[[ x/P]\]", f"- {status_box}", prefix)

                new_line = f"{new_prefix}{clean_content}{due_str}{postpone_str}  ← {timestamp}{suffix}"
                new_lines.append(new_line)
                modified = True
            else:
                new_lines.append(line)

        if modified:
            new_text = "".join(new_lines)
            self._write(new_text)
            logger.info(f"Scratchpad: updated '{nid}'")
            return True
        return False

    def clear_completed(self) -> int:
        """Remove all checked [x] notes. Returns count removed."""
        text = self._read()
        pattern = r"- \[x\] \(\w+\) .*?(?:\s*←\s*.*?)?(?=\n- \[|\Z)\n?"
        new_text, count = re.subn(pattern, "", text, flags=re.DOTALL)
        if count > 0:
            self._write(new_text)
            logger.info(f"Scratchpad: cleared {count} completed notes")
        return count

    def clear_all(self) -> int:
        """Remove ALL notes (active and completed). Returns count removed."""
        text = self._read()
        pattern = r"- \[[ x/]\] \(\w+\) .*?(?:\s*←\s*.*?)?(?=\n- \[|\Z)\n?"
        new_text, count = re.subn(pattern, "", text, flags=re.DOTALL)
        if count > 0:
            self._write(new_text)
            logger.info(f"Scratchpad: cleared ALL {count} notes")
        return count

    # ── Queries ──────────────────────────────────────────────────────

    def get_active_notes(self) -> List[Dict[str, Any]]:
        """Parse out all unchecked notes."""
        text = self._read()
        notes = []

        pattern = r"- \[ \] \((\w+)\) (.*?)(?:\s+\[due: ([^\]]+)\])?\s*←\s*(.*?)(?=\n- \[|\Z)"
        for match in re.finditer(pattern, text, re.DOTALL):
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
