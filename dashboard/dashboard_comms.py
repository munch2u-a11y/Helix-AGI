"""
Helix — Dashboard Communications Bridge

File-based message bus between the Flask dashboard and the pulse loop.
Uses a JSON file (data/dashboard_messages.json) so the two processes
are fully decoupled — no startup order dependency, no HTTP coupling.

Inbound flow:  Browser → POST /api/messages → push_inbound() → file
               main.py poller → pop_inbound() → pulse_loop.emit()

Outbound flow: pulse_loop → channel_router → push_outbound() → file
               Browser → GET /api/messages/outbound → get_outbound()
"""

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("helix.dashboard.comms")

# Default path — relative to project root
_DEFAULT_PATH = Path("data/dashboard_messages.json")


class DashboardComms:
    """Thread-safe, file-based message bridge.

    All methods are safe to call from any thread. File access is
    serialized via a threading.Lock.
    """

    def __init__(self, path: Path = None):
        self._path = path or _DEFAULT_PATH
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self):
        """Create the message file if it doesn't exist."""
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._write_state({"inbound": [], "outbound": []})

    def _read_state(self) -> dict:
        """Read the full message state from disk."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"inbound": [], "outbound": []}

    def _write_state(self, state: dict):
        """Write the full message state to disk."""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write dashboard messages: {e}")

    # ── Inbound (Browser → Helix) ────────────────────────────────────

    def push_inbound(self, sender: str, content: str):
        """Queue a message from the browser to be picked up by the pulse loop."""
        if not sender or not content:
            return
        msg = {
            "sender": sender.strip(),
            "content": content.strip(),
            "timestamp": time.time(),
        }
        with self._lock:
            state = self._read_state()
            state["inbound"].append(msg)
            self._write_state(state)
        logger.info(f"Dashboard inbound: {sender}: {content[:80]}")

    def pop_inbound(self) -> List[Dict[str, Any]]:
        """Consume all pending inbound messages (clears them from the file).

        Called by main.py's polling thread.
        Returns list of {sender, content, timestamp} dicts.
        """
        with self._lock:
            state = self._read_state()
            pending = state.get("inbound", [])
            if not pending:
                return []
            state["inbound"] = []
            self._write_state(state)
        return pending

    # ── Outbound (Helix → Browser) ───────────────────────────────────

    def push_outbound(self, recipient: str, message: str):
        """Queue a message from Helix to be displayed in the browser chat."""
        msg = {
            "recipient": recipient,
            "content": message,
            "timestamp": time.time(),
        }
        with self._lock:
            state = self._read_state()
            state["outbound"].append(msg)
            # Keep max 200 outbound messages
            if len(state["outbound"]) > 200:
                state["outbound"] = state["outbound"][-200:]
            self._write_state(state)
        logger.info(f"Dashboard outbound → {recipient}: {message[:80]}")

    def get_outbound(self, since: int = 0) -> List[Dict[str, Any]]:
        """Get outbound messages from index `since` onward.

        Called by the browser polling endpoint. Does NOT consume messages.
        """
        with self._lock:
            state = self._read_state()
        outbound = state.get("outbound", [])
        return outbound[since:]

    def get_outbound_count(self) -> int:
        """Get total number of outbound messages."""
        with self._lock:
            state = self._read_state()
        return len(state.get("outbound", []))


# ── Module-level singleton ────────────────────────────────────────────
# Importable by both dashboard.py and main.py.
_instance: Optional[DashboardComms] = None
_instance_lock = threading.Lock()


def get_comms(path: Path = None) -> DashboardComms:
    """Get or create the singleton DashboardComms instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = DashboardComms(path=path)
        return _instance
