#!/usr/bin/env python3
"""
Helix — Cognitive Dashboard

Real-time monitoring dashboard for the Helix cognitive architecture.
Runs alongside main.py: reads telemetry and accepts explicit staging/module edits.

Usage:
    python dashboard/dashboard.py              # default: localhost:5050
    python dashboard/dashboard.py --port 8080  # custom port
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import time
import sys
import sqlite3
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
if __package__ in {None, ""}:
    sys.path.insert(0, str(BASE_DIR))
from core.runtime_paths import RuntimePaths
from core.canvas_state import normalize_canvas_payload
from core.agent_home import write_home_json
LOG_PATH = BASE_DIR / "logs" / "helix.log"
BELIEFS_DIR = BASE_DIR / "data" / "beliefs"
SPATIAL_DIR = BASE_DIR / "data" / "spatial"
from core.mindscape_config import configuration_path
CONFIG_PATH = configuration_path(BASE_DIR)
_startup = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
_data = Path(_startup.get("data_dir", "data"))
DATA_DIR = _data if _data.is_absolute() else BASE_DIR / _data
BELIEFS_DIR = DATA_DIR / "beliefs"
SPATIAL_DIR = DATA_DIR / "spatial"
WIDGET_WEB_DIR = BASE_DIR / "desktop_widget" / "web"
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

def _selected_paths():
    return RuntimePaths.from_config(_read_config(), root=BASE_DIR, default_data=DATA_DIR)


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
    "concepts": "#38BDF8",
    "desires": "#E879F9",
    "premises": "#818CF8",
    "propositions": "#A78BFA",
    "memory": "#60A5FA",
    "trail": "#F59E0B",
    "belief": "#34D399",
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
    """Project Nx8 positions to Nx3 via PCA (numpy only) and normalize spread."""
    if not NUMPY_AVAILABLE:
        return positions
    if len(positions) < 2:
        return positions[:, :3] if positions.shape[1] >= 3 else positions
    centered = positions - positions.mean(axis=0)
    cov = np.cov(centered, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    # Top 3 components (eigh returns ascending order)
    top3 = eigenvectors[:, -3:][:, ::-1]
    proj = centered @ top3

    # Normalize spread so nodes span ~[-4.5, 4.5] for clear 3D visualization
    std = proj.std(axis=0)
    median_std = float(np.median(std)) if len(std) > 0 and np.median(std) > 1e-5 else 1.0
    scale = 2.8 / median_std
    return proj * scale


def _get_latest_pulse_traversal(paths=None) -> Dict[str, Any]:
    """Read latest graph trace and active vaults from receipts.jsonl."""
    traversal = {
        "y_paths": [],
        "vault_record_ids": [],
        "surface_candidates": [],
        "pulse": None,
    }
    receipts_candidates = [
        (paths.data / "mindscape" / "receipts.jsonl") if paths else None,
        DATA_DIR / "mindscape" / "receipts.jsonl",
        BASE_DIR / "data" / "mindscape" / "receipts.jsonl",
    ]
    receipts_path = None
    for p in receipts_candidates:
        if p and p.exists():
            receipts_path = p
            break

    if receipts_path:
        try:
            file_size = receipts_path.stat().st_size
            read_size = min(file_size, 131072)
            with open(receipts_path, "rb") as f:
                if file_size > read_size:
                    f.seek(file_size - read_size)
                chunk = f.read().decode("utf-8", errors="ignore")
            for line in reversed(chunk.strip().split("\n")):
                if '"kind": "pulse_context"' in line:
                    entry = json.loads(line)
                    gt = entry.get("graph_trace") or {}
                    traversal["y_paths"] = gt.get("y_paths", [])
                    traversal["vault_record_ids"] = gt.get("vault_record_ids", [])
                    traversal["surface_candidates"] = gt.get("surface_candidates", [])
                    traversal["pulse"] = entry.get("helix_pulse") or entry.get("habitus_pulse")
                    break
        except Exception:
            pass

    return traversal


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

    # Project to 3D with balanced Habitus Cortex basis
    projected = []
    if all_positions:
        if NUMPY_AVAILABLE:
            pos_array = np.array(all_positions, dtype=np.float32)
            # Separate persistent habitus nodes (beliefs/memories) from transient trails
            is_core = np.array([m["type"] != "trail" for m in point_meta], dtype=bool)
            core_pos = pos_array[is_core] if np.any(is_core) else pos_array
            
            mean = core_pos.mean(axis=0)
            centered_core = core_pos - mean
            cov = np.cov(centered_core, rowvar=False) if len(core_pos) > 1 else np.eye(pos_array.shape[1])
            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            top3 = eigenvectors[:, -3:][:, ::-1]
            
            core_proj = centered_core @ top3
            std_mean = float(np.mean(core_proj.std(axis=0))) if len(core_pos) > 1 and float(np.mean(core_proj.std(axis=0))) > 1e-5 else 1.0
            scale = 2.4 / std_mean
            
            # Project all points into habitus basis
            full_proj = (pos_array - mean) @ top3 * scale
            # Clamp extreme trail spikes to stay within visible galaxy
            full_proj = np.clip(full_proj, -8.0, 8.0)
            
            for i, meta in enumerate(point_meta):
                cat = belief_categories.get(meta["id"], meta["category"])
                projected.append({
                    "x": round(float(full_proj[i, 0]), 4),
                    "y": round(float(full_proj[i, 1]), 4),
                    "z": round(float(full_proj[i, 2]), 4),
                    "id": meta["id"],
                    "type": meta["type"],
                    "content": meta["content"],
                    "mass": round(meta["mass"], 3),
                    "category": cat,
                    "color": CATEGORY_COLORS.get(cat, "#38BDF8"),
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

    # Read active pulse telemetry from spatial injection and receipts
    active_belief_ids = []
    active_memory_ids = []
    pulse_num = None

    if SPATIAL_INJECTION_PATH.exists():
        try:
            with open(SPATIAL_INJECTION_PATH) as f:
                inj = json.load(f)
            pulse_num = inj.get("pulse")
            active_belief_ids = inj.get("active_belief_ids") or [
                b.get("id") for b in inj.get("beliefs", []) if b.get("id")
            ]
            active_memory_ids = inj.get("active_memory_ids") or [
                m.get("id") for m in inj.get("memories", []) if m.get("id")
            ]
            if not active_belief_ids and inj.get("beliefs"):
                for b in inj.get("beliefs", []):
                    b_content = b.get("content", "")
                    if b_content:
                        for p in projected:
                            p_cnt = p.get("content", "")
                            if p_cnt and (p_cnt[:35] in b_content or b_content[:35] in p_cnt):
                                if p["id"] not in active_belief_ids:
                                    active_belief_ids.append(p["id"])
        except Exception:
            pass

    traversal_info = _get_latest_pulse_traversal()
    vault_record_ids = traversal_info.get("vault_record_ids", [])
    y_paths = traversal_info.get("y_paths", [])
    if pulse_num is None:
        pulse_num = traversal_info.get("pulse")

    active_id_set = set(active_belief_ids) | set(active_memory_ids) | set(vault_record_ids)

    # Classify vault for points and mark active
    def _classify_vault(pid: str, ptype: str, pcat: str) -> str:
        if pid.startswith("gestation:") or "boot" in pid or pcat in {"premises", "propositions"}:
            return "gestation"
        if ptype == "memory" or "mem_" in pid or pcat in {"memory", "episodes"}:
            return "episodes"
        if pcat in {"concepts", "facts", "knowledge"}:
            return "facts"
        if pcat in {"observations", "tools", "system"}:
            return "observations"
        if pcat in {"skills", "procedures"}:
            return "skills"
        return "facts"

    for p in projected:
        pid = p["id"]
        p["active"] = (pid in active_id_set) or any(act and (act in pid or pid in act) for act in active_id_set)
        p["vault"] = _classify_vault(pid, p["type"], p["category"])

    # Define the canonical semantic vault hubs in 3D lattice space
    known_vaults = [
        {"id": "vault:gestation", "name": "Gestation Core", "vault": "gestation", "color": "#f43f5e", "pos": [0.0, 3.2, -5.5]},
        {"id": "vault:episodes", "name": "Episodes Vault", "vault": "episodes", "color": "#06b6d4", "pos": [-5.5, -1.2, 2.2]},
        {"id": "vault:facts", "name": "Facts Vault", "vault": "facts", "color": "#10b981", "pos": [5.5, -1.2, 2.2]},
        {"id": "vault:observations", "name": "Observations Vault", "vault": "observations", "color": "#f59e0b", "pos": [-3.5, 2.4, 4.5]},
        {"id": "vault:skills", "name": "Skills Vault", "vault": "skills", "color": "#a855f7", "pos": [3.5, 2.4, -4.5]},
    ]

    vault_hubs = []
    for kv in known_vaults:
        v_name = kv["vault"]
        member_pts = [p for p in projected if p.get("vault") == v_name]
        active_in_vault = [p["id"] for p in member_pts if p.get("active")]
        for v_rec in vault_record_ids:
            if _classify_vault(v_rec, "", "") == v_name and v_rec not in active_in_vault:
                active_in_vault.append(v_rec)

        if member_pts and len(member_pts) >= 3:
            avg_x = sum(p["x"] for p in member_pts) / len(member_pts)
            avg_y = sum(p["y"] for p in member_pts) / len(member_pts)
            avg_z = sum(p["z"] for p in member_pts) / len(member_pts)
            norm = (avg_x**2 + avg_y**2 + avg_z**2)**0.5 or 1.0
            scale_out = max(5.5, norm * 1.3) / norm
            pos_x, pos_y, pos_z = round(avg_x * scale_out, 3), round(avg_y * scale_out, 3), round(avg_z * scale_out, 3)
        else:
            pos_x, pos_y, pos_z = kv["pos"]

        vault_hubs.append({
            "id": kv["id"],
            "name": kv["name"],
            "vault": v_name,
            "color": kv["color"],
            "x": pos_x,
            "y": pos_y,
            "z": pos_z,
            "active": len(active_in_vault) > 0,
            "active_count": len(active_in_vault),
            "record_count": len(member_pts),
        })

    # Traversal paths formatted for 3D visualization
    traversal_paths = []
    for yp in y_paths:
        nodes = yp.get("path_node_ids", [])
        if nodes:
            traversal_paths.append({
                "trace_id": yp.get("trace_id", ""),
                "nodes": nodes,
                "target": yp.get("target_node_id", ""),
                "score": round(float(yp.get("endpoint_score", 0.0)), 4),
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

        scale_attn = scale if "scale" in locals() else 1.0
        ac = _load_npy(ATTENTION_NPY)
        if ac is not None and len(ac) == len(mean):
            proj = np.clip((ac - mean) @ top3 * scale_attn, -8.0, 8.0)
            attn = {"x": round(float(proj[0]), 4), "y": round(float(proj[1]), 4), "z": round(float(proj[2]), 4)}

        ap = _load_npy(ATTENTION_PREV)
        if ap is not None and len(ap) == len(mean):
            proj = np.clip((ap - mean) @ top3 * scale_attn, -8.0, 8.0)
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
        "active_belief_ids": active_belief_ids,
        "active_memory_ids": active_memory_ids,
        "vault_record_ids": vault_record_ids,
        "vault_hubs": vault_hubs,
        "traversal_paths": traversal_paths,
        "pulse": pulse_num or 0,
    }


def read_status(paths=None) -> Dict[str, Any]:
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

    # Live agent process tracking via PID
    try:
        from dashboard.dashboard_comms import get_comms
    except ImportError:
        from dashboard_comms import get_comms
    comms = get_comms()
    proc_info = comms.get_agent_process()
    is_online = proc_info is not None

    # Parse last known values from log
    omega = 0.5
    pulse = 0
    state = "ONLINE" if is_online else "OFFLINE"
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
                m = re.search(r"→ (DORMANT|RESTING|REGULAR|ACTIVE|PAUSED)", line)
                if m:
                    state = m.group(1)
                if "state=" in line.lower():
                    m2 = re.search(r"state['\"]?\s*[:=]\s*['\"]?(DORMANT|RESTING|REGULAR|ACTIVE|PAUSED)", line, re.I)
                    if m2:
                        state = m2.group(1).upper()
                if "Pulse loop paused" in line:
                    state = "PAUSED"
                if "Pulse loop stopped" in line and not is_online:
                    state = "OFFLINE"
        except Exception:
            pass

    if not is_online:
        state = "OFFLINE"

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

    # Read only the selected agent and its published checkpoint lineage.
    paths = paths or _selected_paths()
    home_dir = paths.home
    home_error = None
    try:
        current_room = paths.workspace_position()
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        current_room = "."
        home_error = str(error)

    rooms = {}
    room_entries = []
    if home_dir.exists():
        home_json = home_dir / "home.json"
        if home_json.exists():
            try:
                with open(home_json) as f:
                    rooms = json.load(f).get("rooms", {})
            except Exception:
                pass
        target_path = home_dir if current_room in (".", "") else home_dir / current_room
        if target_path.resolve().is_relative_to(home_dir) and target_path.is_dir():
            for item in sorted(target_path.iterdir()):
                if item.name.startswith("."):
                    continue
                room_entries.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0
                })

    return {
        "beliefs": stats,
        "omega": omega,
        "gamma": gamma,
        "pulse": pulse,
        "state": state,
        "is_online": is_online,
        "is_paused": state == "PAUSED",
        "agent_pid": proc_info.get("pid") if proc_info else None,
        "affect": affect,
        "room": current_room,
        "rooms": rooms,
        "room_entries": room_entries,
        "home_status_error": home_error,
    }


# ── Flask App ─────────────────────────────────────────────────────────

def create_app():
    from flask import Flask, jsonify, request, send_from_directory
    try:
        from dashboard.dashboard_comms import get_comms
    except ImportError:
        from dashboard_comms import get_comms

    paths = _selected_paths()
    canvas_dir = paths.data / "spatial"
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

    @app.route("/widget")
    @app.route("/widget/")
    def desktop_widget():
        """Serve the presentation-only floating widget shell."""
        return send_from_directory(str(WIDGET_WEB_DIR), "index.html")

    @app.route("/widget/<path:filename>")
    def desktop_widget_asset(filename: str):
        return send_from_directory(str(WIDGET_WEB_DIR), filename)

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
        return jsonify(read_status(paths))

    # ── Agent Canvas UI Endpoints ──────────────────────────────────────────

    @app.route("/api/canvas", methods=["GET", "POST"])
    def api_canvas():
        """Get or update current Agent-controlled UI Canvas state."""
        canvas_path = canvas_dir / "agent_canvas.json"
        if request.method == "POST":
            try:
                data = normalize_canvas_payload(request.get_json(force=True, silent=True))
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            try:
                canvas_dir.mkdir(parents=True, exist_ok=True)
                write_home_json(canvas_path, data)
                return jsonify({"ok": True})
            except OSError as exc:
                return jsonify({"error": str(exc)}), 500

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
        history_path = canvas_dir / "agent_canvas_history.json"
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

    @app.route("/api/motor")
    def api_motor_state():
        """Actual body state and returns, independent of a language reply."""
        data = paths.data
        state_path = data / "mindscape/motor-state.json"
        if not state_path.exists():
            return jsonify({"status": "not_started", "jobs": []})
        state = json.loads(state_path.read_text())
        health = data / "mindscape/foreground-health.json"
        if health.exists():
            state["foreground"] = json.loads(health.read_text())
        return jsonify(state)

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

    @app.route("/api/control", methods=["POST"])
    def api_control():
        """Handle agent lifecycle control actions (pause, resume, shutdown)."""
        data = request.get_json(force=True, silent=True) or {}
        action = (data.get("action") or "").strip().lower()
        if action not in ("pause", "resume", "shutdown"):
            return jsonify({"ok": False, "error": f"Invalid action: {action}"}), 400

        comms.push_control(action)
        proc_info = comms.get_agent_process()
        pid = proc_info.get("pid") if proc_info else None

        if action == "shutdown" and pid:
            import signal, os
            try:
                # Deliver SIGTERM so main.py triggers its safe shutdown immediately
                os.kill(pid, signal.SIGTERM)
            except OSError as e:
                logger.warning(f"Failed to signal PID {pid}: {e}")

        return jsonify({
            "ok": True,
            "action": action,
            "agent_pid": pid,
            "message": f"Action '{action}' dispatched successfully."
        })

    # ── Safe File Staging Endpoints ──────────────────────────────────────────

    staging_dir = paths.home / "staging"

    @app.route("/api/stage_file", methods=["POST"])
    def api_stage_file():
        """Safely stage a file into the agent's staging room for gradual observation."""
        try:
            staging_dir.mkdir(parents=True, exist_ok=True)
            if "file" in request.files:
                f = request.files["file"]
                filename = Path(f.filename).name
                dest = staging_dir / filename
                f.save(str(dest))
                return jsonify({"ok": True, "filename": filename, "size": dest.stat().st_size, "path": f"staging/{filename}"})
            
            data = request.get_json(force=True, silent=True) or {}
            filename = Path(data.get("filename", "staged_input.txt")).name
            content = data.get("content", "")
            dest = staging_dir / filename
            dest.write_text(content, encoding="utf-8")
            return jsonify({"ok": True, "filename": filename, "size": len(content.encode("utf-8")), "path": f"staging/{filename}"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/staged_files", methods=["GET"])
    def api_staged_files():
        """List all files currently in the agent's safe staging area."""
        try:
            items = []
            for item in sorted(staging_dir.iterdir()) if staging_dir.exists() else ():
                if item.is_file() and not item.name.startswith("."):
                    items.append({
                        "name": item.name,
                        "size": item.stat().st_size,
                        "modified": item.stat().st_mtime
                    })
            return jsonify({"staged": items})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/staged_files/<path:filename>", methods=["DELETE"])
    def api_delete_staged_file(filename: str):
        """Remove a staged file."""
        try:
            target = (staging_dir / Path(filename).name).resolve()
            if target.exists() and staging_dir in target.parents:
                target.unlink()
                return jsonify({"ok": True})
            return jsonify({"error": "File not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Module Studio & Pseudo-IDE Endpoints ─────────────────────────────────

    modules_dir = paths.home / "modules"

    @app.route("/api/modules", methods=["GET", "POST"])
    def api_modules():
        """List or add modules in the agent's modules directory."""
        import ast
        if request.method == "POST":
            data = request.get_json(force=True, silent=True)
            if not isinstance(data, dict):
                return jsonify({"error": "Module payload must be an object."}), 400
            raw_name, code = data.get("name"), data.get("code")
            if not isinstance(raw_name, str) or not isinstance(code, str):
                return jsonify({"error": "Both module name and code must be text."}), 400
            raw_name = raw_name.strip()
            if not raw_name or Path(raw_name).name in {"", ".", "..", ".py"} or not code.strip():
                return jsonify({"error": "Both module name and code are required."}), 400
            name = Path(raw_name).name
            if not name.endswith(".py"):
                name += ".py"
            
            # Syntax validation via AST
            try:
                ast.parse(code)
            except SyntaxError as e:
                return jsonify({"error": f"Python Syntax Error: {e.msg} at line {e.lineno}"}), 400
            
            modules_dir.mkdir(parents=True, exist_ok=True)
            dest = modules_dir / name
            try:
                with dest.open("x", encoding="utf-8") as stream:
                    stream.write(code)
            except FileExistsError:
                return jsonify({"error": "Module already exists; choose another name."}), 409
            except OSError as exc:
                return jsonify({"error": str(exc)}), 500

            # Update home.json if present
            home_json = paths.home / "home.json"
            if home_json.exists():
                try:
                    with open(home_json, "r") as f:
                        hdata = json.load(f)
                    mod_key = name[:-3]
                    hdata.setdefault("modules", {})[mod_key] = {
                        "path": str(dest.resolve()),
                        "room": "modules",
                        "network": "requests" in code or "urllib" in code,
                        "parameters": []
                    }
                    with open(home_json, "w") as f:
                        json.dump(hdata, f, indent=2)
                except Exception:
                    pass

            return jsonify({"ok": True, "name": name, "size": len(code.encode("utf-8"))})

        # GET: list modules
        mod_list = []
        for mf in sorted(modules_dir.glob("*.py")):
            doc = ""
            code_text = ""
            try:
                code_text = mf.read_text(encoding="utf-8")
                tree = ast.parse(code_text)
                doc = ast.get_docstring(tree) or ""
            except Exception:
                pass
            mod_list.append({
                "name": mf.name,
                "doc": doc.strip(),
                "size": mf.stat().st_size,
                "lines": len(code_text.splitlines())
            })
        return jsonify({"modules": mod_list})

    @app.route("/api/modules/<path:filename>", methods=["GET"])
    def api_get_module_code(filename: str):
        """Get source code for a specific module."""
        target = (modules_dir / Path(filename).name).resolve()
        if target.exists() and modules_dir in target.parents:
            return jsonify({
                "name": target.name,
                "code": target.read_text(encoding="utf-8"),
                "size": target.stat().st_size
            })
        return jsonify({"error": "Module not found"}), 404

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
