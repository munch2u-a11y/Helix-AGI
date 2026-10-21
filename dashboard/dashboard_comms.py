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

# Default path — anchored to the repo root so both main.py and the dashboard
# use the same message bus regardless of the current working directory.
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard_messages.json"


class DashboardComms:
    """Thread-safe, file-based message bridge.

    All methods are safe to call from any thread. File access is
    serialized via a threading.Lock.
    """

    def __init__(self, path: Path = None):
        if path is None:
            root = Path(__file__).resolve().parent.parent
            from core.mindscape_config import configuration_path
            config_path = configuration_path(root)
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
            data = Path(config.get("data_dir", "data"))
            path = (data if data.is_absolute() else root / data) / "dashboard_messages.json"
        self._path = Path(path)
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self):
        """Create the message file if it doesn't exist."""
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._write_state({"inbound": [], "outbound": [], "outbound_base": 0, "control": []})

    def _read_state(self) -> dict:
        """Read the full message state from disk."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"inbound": [], "outbound": [], "outbound_base": 0, "control": []}

        if not isinstance(state, dict):
            return {"inbound": [], "outbound": [], "outbound_base": 0, "control": []}

        state.setdefault("inbound", [])
        state.setdefault("outbound", [])
        state.setdefault("outbound_base", 0)
        state.setdefault("control", [])
        return state

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
            self._write_state(state)
            published = self._read_state()
            if published.get("outbound", []) != state["outbound"]:
                raise OSError("Dashboard outbound read-back differs; delivery not established")
            receipt = {"path": str(self._path),
                       "index": int(state.get("outbound_base", 0)) + len(state["outbound"]) - 1,
                       "message": msg}
        logger.info(f"Dashboard outbound → {recipient}: {message[:80]}")
        return receipt

    def get_outbound(self, since: int = 0) -> List[Dict[str, Any]]:
        """Get outbound messages from index `since` onward.

        Called by the browser polling endpoint. Does NOT consume messages.
        """
        with self._lock:
            state = self._read_state()
        outbound = state.get("outbound", [])
        base = int(state.get("outbound_base", 0))
        if since <= base:
            return outbound
        return outbound[since - base:]

    def get_outbound_count(self) -> int:
        """Get total number of outbound messages."""
        with self._lock:
            state = self._read_state()
        return int(state.get("outbound_base", 0)) + len(state.get("outbound", []))

    # ── Control Commands (Browser → Helix) ───────────────────────────

    def push_control(self, command: str, payload: Optional[Dict[str, Any]] = None):
        """Queue a control command (e.g. 'pause', 'resume', 'shutdown')."""
        if not command:
            return
        cmd_obj = {
            "command": command.strip().lower(),
            "payload": payload or {},
            "timestamp": time.time(),
        }
        with self._lock:
            state = self._read_state()
            state.setdefault("control", [])
            state["control"].append(cmd_obj)
            self._write_state(state)
        logger.info(f"Dashboard control queued: {command}")

    def pop_control(self) -> List[Dict[str, Any]]:
        """Consume all pending control commands."""
        with self._lock:
            state = self._read_state()
            pending = state.get("control", [])
            if not pending:
                return []
            state["control"] = []
            self._write_state(state)
        return pending

    # ── Process Lifecycle & PID Tracking ─────────────────────────────

    @property
    def pid_file(self) -> Path:
        return self._path.parent / "helix.pid"

    def write_pid(self, pid: int, agent_name: str = "Helix"):
        """Record the active Helix process PID."""
        try:
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.pid_file, "w", encoding="utf-8") as f:
                json.dump({
                    "pid": pid,
                    "agent_name": agent_name,
                    "started_at": time.time(),
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write pid file: {e}")

    def clear_pid(self):
        """Remove the active PID file upon clean shutdown."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
        except Exception as e:
            logger.error(f"Failed to clear pid file: {e}")

    def get_agent_process(self) -> Optional[Dict[str, Any]]:
        """Check if the agent process is actively running via its PID."""
        if not self.pid_file.exists():
            return None
        try:
            with open(self.pid_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("pid")
            if not pid or not isinstance(pid, int):
                return None
            import os
            os.kill(pid, 0)
            return data
        except (OSError, json.JSONDecodeError):
            return None


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
