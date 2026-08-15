#!/usr/bin/env python3
"""
Helix — Cognitive Dashboard

Real-time monitoring dashboard for the Helix cognitive architecture.
Runs alongside main.py, reads files only — never modifies Helix state.

Usage:
    python dashboard/dashboard.py              # default: localhost:5050
    python dashboard/dashboard.py --port 8080  # custom port
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import numpy as np
except ImportError:
    np = None

# Suppress Flask's default request logging
log = logging.getLogger("werkzeug")
log.setLevel(logging.WARNING)

# ── Path Configuration ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
LOG_PATH = BASE_DIR / "logs" / "helix.log"
BELIEFS_DIR = BASE_DIR / "data" / "beliefs"
SPATIAL_DIR = BASE_DIR / "data" / "spatial"
CONFIG_PATH = BASE_DIR / "config" / "config.json"
NUMPY_AVAILABLE = np is not None

def _read_config() -> Dict[str, Any]:
    """Read agent config for dashboard personalization."""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

# Spatial state files written by SpatialMind.save_state()
BELIEF_STATE = SPATIAL_DIR / "belief_space_state.json"
MEMORY_STATE = SPATIAL_DIR / "memory_space_state.json"
ATTENTION_NPY = SPATIAL_DIR / "attention_center.npy"
ATTENTION_PREV = SPATIAL_DIR / "attention_center_prev.npy"
ATTENTION_GAMMA = SPATIAL_DIR / "attention_center_gamma.npy"
SPATIAL_INJECTION_PATH = SPATIAL_DIR / "spatial_injection.json"
SPATIAL_INJECTION_HISTORY_PATH = SPATIAL_DIR / "spatial_injection_history.json"

# Log lines matching these patterns are excluded from the thought stream
NOISE_PATTERNS = re.compile(
    r"telegram_bot|comms\.|chromadb|chroma_db|rate_limit|"
    r"429|socket|httpcore|httpx|urllib3|google\.auth|"
    r"werkzeug|PIL\.|fontTools|"
    r"dashboard_comms|/api/messages|dashboard.*poll|"
    r"faster_whisper|sensory_cortex|whisper",
    re.IGNORECASE,
)

# Tab filters for the thought stream
TAB_FILTERS = {
    "thoughts": re.compile(
        r"\[thought\]|Pulse \d+|internal monologue|💭|💬|_pulse\b",
        re.IGNORECASE,
    ),
    "tools": re.compile(
        r"FC tools used|tool_result|tool_call|send_message|function.call|🔧",
        re.IGNORECASE,
    ),
    "beliefs": re.compile(
        r"belief_detector|[Cc]o.occurrence|[Hh]ebbian|[Bb]elief.*added|"
        r"[Bb]elief.*merged|[Ww]ired.*relation|confidence|attrition",
        re.IGNORECASE,
    ),
    "spatial": re.compile(
        r"[Ss]patial|attention|gravity|bootstrap|manifold|entropy|"
        r"identity.center|[Kk][Dd][Tt]ree|drift",
        re.IGNORECASE,
    ),
}

CATEGORY_COLORS = {
    "self_identity": "#FFD700",
    "knowledge": "#4A9EFF",
    "skills": "#4ADE80",
    "capabilities": "#A78BFA",
    "people": "#F472B6",
    "preferences": "#FB923C",
    "feedback": "#94A3B8",
}


def _coerce_int(
    value: Any,
    default: int = 0,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


# ── Log Tailer ────────────────────────────────────────────────────────

class LogTailer:
    """Tails helix.log and caches recent lines per tab."""

    def __init__(self, path: Path, max_lines: int = 1000):
        self._path = path
        self._max = max_lines
        self._offset = 0
        self._lines: Dict[str, deque] = {
            tab: deque(maxlen=max_lines) for tab in TAB_FILTERS
        }
        self._all = deque(maxlen=max_lines)
        self._lines_total = {tab: 0 for tab in TAB_FILTERS}
        self._lines_total["all"] = 0

    def poll(self) -> None:
        if not self._path.exists():
            return
        try:
            size = self._path.stat().st_size
            if size < self._offset:
                self._offset = 0
            with open(self._path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                new_lines = f.readlines()
                self._offset = f.tell()
            for raw in new_lines:
                line = raw.rstrip()
                if not line or NOISE_PATTERNS.search(line):
                    continue
                self._all.append(line)
                self._lines_total["all"] += 1
                for tab, pattern in TAB_FILTERS.items():
                    if pattern.search(line):
                        self._lines[tab].append(line)
                        self._lines_total[tab] += 1
        except Exception:
            pass

    def get(self, tab: str = "thoughts", since: int = 0) -> List[str]:
        self.poll()
        buf = self._lines.get(tab)
        total = self._lines_total.get(tab, 0)
        if buf is None:
            buf = self._all
            total = self._lines_total.get("all", 0)

        start_idx = total - len(buf)
        idx = max(0, since - start_idx)
        return list(buf)[idx:]

    def get_total(self, tab: str = "thoughts") -> int:
        if tab in self._lines_total:
            return self._lines_total[tab]
        return self._lines_total.get("all", 0)


# ── Spatial Data Reader ───────────────────────────────────────────────

def _load_npy(path: Path) -> Optional[Any]:
    try:
        if NUMPY_AVAILABLE and path.exists():
            return np.load(str(path))
    except Exception:
        pass
    return None


def _coerce_xyz(position: List[float]) -> tuple[float, float, float]:
    values = list(position[:3])
    while len(values) < 3:
        values.append(0.0)
    return float(values[0]), float(values[1]), float(values[2])


def _pca_3d(positions: Any) -> Any:
    """Project Nx8 positions to Nx3 via PCA (numpy only)."""
    if not NUMPY_AVAILABLE:
        return positions
    if len(positions) < 2:
        return positions[:, :3] if positions.shape[1] >= 3 else positions
    centered = positions - positions.mean(axis=0)
    cov = np.cov(centered, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    # Top 3 components (eigh returns ascending order)
    top3 = eigenvectors[:, -3:][:, ::-1]
    return centered @ top3


def read_spatial() -> Dict[str, Any]:
    """Read all spatial state files and return JSON-ready dict."""
    points = []
    all_positions = []
    point_meta = []

    # Read belief space
    if BELIEF_STATE.exists():
        try:
            with open(BELIEF_STATE) as f:
                state = json.load(f)
            for pid, data in state.items():
                pos = data.get("position", [])
                if len(pos) >= 3:
                    all_positions.append(pos)
                    point_meta.append({
                        "id": pid,
                        "type": data.get("type", "belief"),
                        "content": (data.get("content", "") or "")[:120],
                        "mass": data.get("confidence", 0.5),
                        "category": "belief",
                    })
        except Exception:
            pass

    # Read memory space
    if MEMORY_STATE.exists():
        try:
            with open(MEMORY_STATE) as f:
                state = json.load(f)
            for pid, data in state.items():
                pos = data.get("position", [])
                if len(pos) >= 3:
                    all_positions.append(pos)
                    point_meta.append({
                        "id": pid,
                        "type": "memory",
                        "content": (data.get("content", "") or "")[:80],
                        "mass": data.get("importance", 0.3),
                        "category": "memory",
                    })
        except Exception:
            pass

    # Also read belief category for coloring
    belief_categories = {}
    if BELIEFS_DIR.exists():
        for cat_file in BELIEFS_DIR.glob("*.json"):
            cat_name = cat_file.stem
            try:
                with open(cat_file) as f:
                    beliefs = json.load(f)
                for b in beliefs:
                    bid = b.get("id", "")
                    if bid:
                        belief_categories[bid] = cat_name
            except Exception:
                pass

    # Project to 3D
    projected = []
    if all_positions:
        if NUMPY_AVAILABLE:
            pos_array = np.array(all_positions, dtype=np.float32)
            proj_3d = _pca_3d(pos_array)
            for i, meta in enumerate(point_meta):
                cat = belief_categories.get(meta["id"], meta["category"])
                projected.append({
                    "x": round(float(proj_3d[i, 0]), 4),
                    "y": round(float(proj_3d[i, 1]), 4),
                    "z": round(float(proj_3d[i, 2]), 4),
                    "id": meta["id"],
                    "type": meta["type"],
                    "content": meta["content"],
                    "mass": round(meta["mass"], 3),
                    "category": cat,
                    "color": CATEGORY_COLORS.get(cat, "#666666"),
                })
        else:
            for raw_pos, meta in zip(all_positions, point_meta):
                cat = belief_categories.get(meta["id"], meta["category"])
                x, y, z = _coerce_xyz(raw_pos)
                projected.append({
                    "x": round(x, 4),
                    "y": round(y, 4),
                    "z": round(z, 4),
                    "id": meta["id"],
                    "type": meta["type"],
                    "content": meta["content"],
                    "mass": round(meta["mass"], 3),
                    "category": cat,
                    "color": CATEGORY_COLORS.get(cat, "#666666"),
                })

    # Attention center
    attn = {"x": 0, "y": 0, "z": 0}
    attn_prev = {"x": 0, "y": 0, "z": 0}
    identity = {"x": 0, "y": 0, "z": 0}

    if NUMPY_AVAILABLE and all_positions:
        pos_array = np.array(all_positions, dtype=np.float32)
        mean = pos_array.mean(axis=0)
        centered = pos_array - mean
        cov = np.cov(centered, rowvar=False)
        _, eigvec = np.linalg.eigh(cov)
        top3 = eigvec[:, -3:][:, ::-1]

        ac = _load_npy(ATTENTION_NPY)
        if ac is not None and len(ac) == len(mean):
            proj = (ac - mean) @ top3
            attn = {"x": round(float(proj[0]), 4), "y": round(float(proj[1]), 4), "z": round(float(proj[2]), 4)}

        ap = _load_npy(ATTENTION_PREV)
        if ap is not None and len(ap) == len(mean):
            proj = (ap - mean) @ top3
            attn_prev = {"x": round(float(proj[0]), 4), "y": round(float(proj[1]), 4), "z": round(float(proj[2]), 4)}

    gamma = 0.5
    g = _load_npy(ATTENTION_GAMMA)
    if g is not None:
        gamma = round(float(g[0]), 3)

    return {
        "points": projected,
        "attention": attn,
        "attention_prev": attn_prev,
        "identity": identity,
        "gamma": gamma,
        "point_count": len(projected),
    }


def read_status() -> Dict[str, Any]:
    """Read belief stats and last known gauges from log."""
    stats = {"total": 0, "categories": {}}
    if BELIEFS_DIR.exists():
        for cat_file in BELIEFS_DIR.glob("*.json"):
            try:
                with open(cat_file) as f:
                    beliefs = json.load(f)
                cat = cat_file.stem
                stats["categories"][cat] = len(beliefs)
                stats["total"] += len(beliefs)
            except Exception:
                pass

    gamma = 0.5
    g = _load_npy(ATTENTION_GAMMA)
    if g is not None:
        gamma = round(float(g[0]), 3)

    # Parse last known values from log
    omega = 0.5
    pulse = 0
    state = "UNKNOWN"
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH, "rb") as f:
                f.seek(max(0, f.seek(0, 2) - 20000))
                tail = f.read().decode("utf-8", errors="replace")
            for line in tail.split("\n"):
                m = re.search(r"Ω=([0-9.]+)", line)
                if m:
                    omega = float(m.group(1))
                m = re.search(r"Pulse (\d+)", line)
                if m:
                    pulse = int(m.group(1))
                m = re.search(r"→ (DORMANT|RESTING|REGULAR|ACTIVE)", line)
                if m:
                    state = m.group(1)
                if "state=" in line.lower():
                    m2 = re.search(r"state['\"]?\s*[:=]\s*['\"]?(DORMANT|RESTING|REGULAR|ACTIVE)", line, re.I)
                    if m2:
                        state = m2.group(1).upper()
        except Exception:
            pass

    # Load affect from spatial_injection.json if available
    affect = {"dominant": "neutral", "intensity": 0.0}
    if SPATIAL_INJECTION_PATH.exists():
        try:
            with open(SPATIAL_INJECTION_PATH) as f:
                data = json.load(f)
                if "affect" in data:
                    affect = data["affect"]
        except Exception:
            pass

    return {
        "beliefs": stats,
        "omega": omega,
        "gamma": gamma,
        "pulse": pulse,
        "state": state,
        "affect": affect,
    }


# ── Flask App ─────────────────────────────────────────────────────────

def create_app():
    from flask import Flask, jsonify, request, send_from_directory
    try:
        from dashboard.dashboard_comms import get_comms
    except ImportError:
        from dashboard_comms import get_comms

    app = Flask(__name__, static_folder=None)
    tailer = LogTailer(LOG_PATH)
    comms = get_comms()

    @app.route("/")
    def index():
        html_path = Path(__file__).parent / "dashboard_ui.html"
        html = html_path.read_text(encoding="utf-8")
        # Inject config values
        cfg = _read_config()
        agent_name = cfg.get("agent_name", "Helix")
        creator_name = cfg.get("creator_name", "User")
        inject = f"""<script>
    window.HELIX_CONFIG = {{
        agentName: {json.dumps(agent_name)},
        creatorName: {json.dumps(creator_name)},
    }};
    </script>"""
        # Insert before </head>
        html = html.replace("</head>", inject + "\n</head>")
        return html

    @app.route("/api/logs")
    def api_logs():
        tab = request.args.get("tab", "thoughts")
        since = _coerce_int(request.args.get("since", 0), default=0, minimum=0)
        lines = tailer.get(tab, since)
        total = tailer.get_total(tab)
        return jsonify({"lines": lines, "total": total})

    @app.route("/api/spatial")
    def api_spatial():
        return jsonify(read_spatial())

    @app.route("/api/tools")
    def api_tools():
        status_path = SPATIAL_DIR / "tools_status.json"
        if status_path.exists():
            try:
                with open(status_path) as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify({
            "toolsets": [],
            "running_tools": [],
            "recent_tools": []
        })

    @app.route("/api/spatial_injection")
    def api_spatial_injection():
        if SPATIAL_INJECTION_PATH.exists():
            try:
                with open(SPATIAL_INJECTION_PATH) as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify({
            "concepts": [],
            "memories": [],
            "beliefs": [],
            "somatic": {},
            "affect": {}
        })

    @app.route("/api/spatial_injection_history")
    def api_spatial_injection_history():
        limit = _coerce_int(request.args.get("limit", 30), default=30, minimum=1, maximum=200)
        if SPATIAL_INJECTION_HISTORY_PATH.exists():
            try:
                with open(SPATIAL_INJECTION_HISTORY_PATH) as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return jsonify({
                            "entries": list(reversed(data[-limit:])),
                            "total": len(data),
                        })
            except Exception:
                pass
        return jsonify({"entries": [], "total": 0})


    @app.route("/api/status")
    def api_status():
        return jsonify(read_status())

    # ── Agent Canvas UI Endpoints ──────────────────────────────────────────

    @app.route("/api/canvas", methods=["GET", "POST"])
    def api_canvas():
        """Get or update current Agent-controlled UI Canvas state."""
        canvas_path = SPATIAL_DIR / "agent_canvas.json"
        if request.method == "POST":
            data = request.get_json(force=True, silent=True) or {}
            try:
                with open(canvas_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                return jsonify({"ok": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        if canvas_path.exists():
            try:
                with open(canvas_path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify({
            "view_type": "card",
            "title": "Agent Canvas",
            "content": "Helix has not initialized dynamic canvas content yet.",
            "media_url": None,
            "auto_switch": False,
            "timestamp": time.time(),
        })

    @app.route("/api/canvas_history")
    def api_canvas_history():
        """Get recent Agent Canvas UI history."""
        limit = _coerce_int(request.args.get("limit", 20), default=20, minimum=1, maximum=100)
        history_path = SPATIAL_DIR / "agent_canvas_history.json"
        if history_path.exists():
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return jsonify({
                            "entries": list(reversed(data[-limit:])),
                            "total": len(data),
                        })
            except Exception:
                pass
        return jsonify({"entries": [], "total": 0})

    # ── Chat Endpoints ────────────────────────────────────────────

    @app.route("/api/messages", methods=["POST"])
    def api_send_message():
        """Browser sends a message to the agent."""
        data = request.get_json(force=True, silent=True) or {}
        cfg = _read_config()
        sender = (data.get("sender") or cfg.get("creator_name", "User")).strip()
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"error": "No content"}), 400
        comms.push_inbound(sender, content)
        return jsonify({"ok": True})

    @app.route("/api/messages/pending")
    def api_pending_messages():
        """Pulse loop poller consumes inbound messages."""
        pending = comms.pop_inbound()
        return jsonify({"messages": pending})

    @app.route("/api/messages/outbound")
    def api_outbound_messages():
        """Browser polls for Helix's replies."""
        since = _coerce_int(request.args.get("since", 0), default=0, minimum=0)
        messages = comms.get_outbound(since)
        total = comms.get_outbound_count()
        return jsonify({"messages": messages, "total": total})

    return app


def main():
    parser = argparse.ArgumentParser(description="Helix Cognitive Dashboard")
    parser.add_argument("--port", type=int, default=5050, help="Port (default: 5050)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"╔══════════════════════════════════════════╗")
    print(f"║     HELIX COGNITIVE DASHBOARD            ║")
    print(f"║     http://{args.host}:{args.port}             ║")
    print(f"╚══════════════════════════════════════════╝")
    print(f"  Log: {LOG_PATH}")
    print(f"  Beliefs: {BELIEFS_DIR}")
    print(f"  Spatial: {SPATIAL_DIR}")
    print()

    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    _project_root = str(Path(__file__).parent.parent.resolve())
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    main()
