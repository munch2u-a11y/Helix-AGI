"""
Helix — Tool Lesson Tracker

The capture-and-verification side of dynamic tool learning. Owns every
write path for tool-bound beliefs so the rest of the system stays
deterministic:

  1. FAILURE CAPTURE (executor boundary → pending queue)
     Every tool result passes through observe_tool_result(). Failures
     are deduplicated by (tool, error-signature) and queued as
     pending-belief candidates carrying `tool_bindings`. The nightly
     batch service distills them into proper lesson beliefs — the LLM
     does the language, this module does the routing.

  2. VERIFICATION LOOP (lesson injected → tool succeeds → lesson gains)
     The preconscious reports which tool-bound lessons it injected via
     note_lessons_injected(). When that tool then succeeds within the
     TTL window, the lesson's verifications and stability are bumped —
     lessons that prove useful gain mass, surface more, and survive
     nightly attrition. Useless lessons decay out naturally.

  3. WORKFLOW SKILLS (deterministic direct write)
     The WorkflowDetector's crystallized patterns are template-generated
     (no LLM language work needed), so they are written straight to the
     belief store as `skills` beliefs with tool_bindings — preserving
     the skills category's reserved injection slots, which the batch
     service would demote away.

Module-level singleton with set_dependencies() wiring, same pattern as
workflow_detector and belief_detector. All failures are logged, never
propagated — this must never break a tool call.
"""

import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("helix.core.tool_lesson_tracker")

# ── Configuration ────────────────────────────────────────────────────

# A tool result matching this is treated as a failure worth learning from.
# Conservative on purpose: exception wrapper prefix, explicit handler
# errors, and unknown-tool dispatch. Nightly LLM formatting + FAISS
# dedup filter any junk that slips through.
_FAILURE_RE = re.compile(r"^(Tool error \(|Error\b|Unknown tool)")

# Re-capture the same (tool, error) signature at most this often.
_SIGNATURE_COOLDOWN_SECONDS = 6 * 3600

# A success verifies an injected lesson only within this window.
#
# Sized originally for a single API tool call, where the gap between
# injecting a lesson and the tool succeeding is seconds. An orchestrated
# local run is plan → several directed passes → tail summary, all on one
# consumer GPU, and can take far longer than ten minutes end to end. At the
# old ceiling those successes landed after expiry, so lessons that were
# working never earned verifications and decayed out of the belief store as
# if they had failed.
_VERIFICATION_TTL_SECONDS = max(
    60, int(os.environ.get("HELIX_TOOL_LESSON_TTL_SECONDS", "2700"))
)

# Cap on how much of args/error text goes into a candidate.
_ARGS_CHARS = 150
_ERROR_CHARS = 300

# Hard cap for directly-written skill beliefs.
_SKILL_MAX_CHARS = 400

# ── Dependencies (wired at startup) ──────────────────────────────────

_belief_store = None
_physics_engine = None

# ── State ────────────────────────────────────────────────────────────

_seen_signatures: Dict[str, float] = {}   # signature → last capture time
_recent_injections: List[Dict[str, Any]] = []  # {belief_id, tools, t, bumped}
_state_lock = threading.Lock()


def set_dependencies(belief_store, physics_engine=None):
    """Wire dependencies at startup. Called from main.py."""
    global _belief_store, _physics_engine
    _belief_store = belief_store
    _physics_engine = physics_engine
    logger.info("Tool lesson tracker: dependencies wired")


# ── Internal helpers ─────────────────────────────────────────────────

def _toolset_of(tool_name: str) -> str:
    """Look up the toolset a tool belongs to (empty if unknown)."""
    try:
        from tools.tool_registry import registry
        entry = registry.get_entry(tool_name)
        return entry.toolset if entry else ""
    except Exception:
        return ""


def _error_signature(tool_name: str, error: str) -> str:
    """Stable signature for dedup: tool + error with volatile parts masked."""
    head = error[:120]
    head = re.sub(r"\d+", "#", head)           # numbers (line nos, ids)
    head = re.sub(r"/[^\s'\"]+", "/PATH", head)  # filesystem paths
    return f"{tool_name}::{head.lower()}"


def _summarize_args(args: Optional[dict]) -> str:
    try:
        s = json.dumps(args or {}, default=str)
    except Exception:
        s = str(args)
    if len(s) > _ARGS_CHARS:
        s = s[:_ARGS_CHARS] + "…"
    return s


def _queue_candidate(candidate: Dict[str, Any]) -> bool:
    """Append a candidate to pending_beliefs.json (shared lock with
    belief_detector, which owns that file's I/O)."""
    try:
        from core.belief_detector import (
            _read_pending, _write_pending, _pending_lock, MAX_PENDING,
        )
        with _pending_lock:
            pending = _read_pending()
            if len(pending) >= MAX_PENDING:
                logger.warning("Pending queue full — tool lesson dropped")
                return False
            # Don't queue a signature already waiting
            sig = candidate.get("error_signature")
            if sig and any(
                p.get("error_signature") == sig
                and p.get("status") == "pending"
                for p in pending
            ):
                return False
            pending.append(candidate)
            _write_pending(pending)
        return True
    except Exception as e:
        logger.warning("Failed to queue tool lesson candidate: %s", e)
        return False


# ── 1. Failure capture / success observation ─────────────────────────

def observe_tool_result(tool_name: str, args: Optional[dict], result: str):
    """Classify a tool result and route it. Called by the executor on
    EVERY function call — must be cheap and must never raise."""
    try:
        if result and _FAILURE_RE.match(result):
            _record_failure(tool_name, args, result)
        else:
            _record_success(tool_name)
    except Exception as e:
        logger.debug("observe_tool_result failed (non-fatal): %s", e)


def _record_failure(tool_name: str, args: Optional[dict], error: str):
    sig = _error_signature(tool_name, error)
    now = time.time()

    with _state_lock:
        last = _seen_signatures.get(sig, 0.0)
        if now - last < _SIGNATURE_COOLDOWN_SECONDS:
            return
        _seen_signatures[sig] = now
        # Expire old signatures
        expired = [s for s, t in _seen_signatures.items()
                   if now - t > 2 * _SIGNATURE_COOLDOWN_SECONDS]
        for s in expired:
            del _seen_signatures[s]

    toolset = _toolset_of(tool_name)
    bindings = [tool_name]
    if toolset and toolset != tool_name:
        bindings.append(toolset)

    candidate = {
        "content": (
            f"Tool '{tool_name}' failed when called with "
            f"{_summarize_args(args)}: {error[:_ERROR_CHARS]}"
        ),
        "category": "propositions",
        "status": "pending",
        "source_type": "tool_failure",
        "tool_bindings": bindings,
        "error_signature": sig,
        "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    if _queue_candidate(candidate):
        logger.info(
            "Tool failure captured for nightly distillation: %s (%s)",
            tool_name, error[:80],
        )


def _record_success(tool_name: str):
    """A tool succeeded — verify any recently injected lesson bound to it."""
    if _belief_store is None:
        return

    now = time.time()
    name = tool_name.lower()
    to_bump = []

    with _state_lock:
        for note in _recent_injections:
            if note["bumped"]:
                continue
            if now - note["t"] > _VERIFICATION_TTL_SECONDS:
                continue
            if name in note["tools"]:
                note["bumped"] = True
                to_bump.append(note["belief_id"])

    for bid in to_bump:
        try:
            belief = _belief_store.get_belief(bid)
            if not belief:
                continue
            _belief_store.update_belief(
                bid, verifications=belief.get("verifications", 1.0) + 1.0,
            )
            _belief_store.update_stability_index(bid, +0.05)
            logger.info(
                "Tool lesson verified by success (%s): %s",
                tool_name, bid,
            )
        except Exception as e:
            logger.debug("Lesson verification bump failed for %s: %s", bid, e)


# ── 2. Injection reporting (called by the preconscious) ──────────────

def note_lessons_injected(items: List[Dict[str, Any]]):
    """Record which tool-bound lessons were just injected.

    Args:
        items: list of {"belief_id": str, "tools": iterable of tool/
               toolset names the lesson is bound to}.
    """
    now = time.time()
    with _state_lock:
        for item in items:
            bid = item.get("belief_id")
            tools = {str(t).lower() for t in item.get("tools", []) if t}
            if not bid or not tools:
                continue
            _recent_injections.append({
                "belief_id": bid,
                "tools": tools,
                "t": now,
                "bumped": False,
            })
        # Keep the window small
        if len(_recent_injections) > 50:
            del _recent_injections[:-50]


# ── 3. Workflow skills (deterministic direct write) ──────────────────

def record_workflow_skill(content: str, tool_names: List[str]) -> Optional[str]:
    """Write a crystallized workflow pattern as a `skills` belief.

    Template-generated content needs no LLM pass, and going through the
    batch service would demote it out of the skills category (losing
    its reserved injection slots). Returns the belief id or None.
    """
    if _belief_store is None or not content:
        return None

    content = content.strip()[:_SKILL_MAX_CHARS]

    bindings = []
    for t in tool_names:
        if t and t not in bindings:
            bindings.append(t)
        ts = _toolset_of(t)
        if ts and ts not in bindings:
            bindings.append(ts)

    try:
        belief_id = _belief_store.generate_id("skills")
        stored = _belief_store.add_belief(
            category="skills",
            belief_id=belief_id,
            content=content,
            mass=1.0,
            confidence=0.5,
            source="workflow_detector",
            tool_bindings=bindings,
            formation_type="workflow_crystallization",
        )
        if not stored:
            return None

        # Register in the live manifold + semantic index
        if _physics_engine is not None:
            try:
                emb = _physics_engine.embed_text(content)
                pos = _physics_engine.embed_and_project(content)
                _belief_store.update_belief(
                    belief_id,
                    position_8d=[round(float(x), 6) for x in pos],
                )
                _physics_engine._register_point(
                    point_id=belief_id,
                    emb=emb,
                    point_type="belief",
                    spatial_kwargs={
                        "confidence": 0.5,
                        "importance": 1.0,
                        "content": content,
                    },
                    semantic_metadata={
                        "content": content[:500],
                        "type": "belief",
                        "confidence": 0.5,
                        "importance": 1.0,
                        "category": "skills",
                    },
                )
            except Exception as e:
                logger.warning(
                    "Skill manifold registration failed for %s: %s",
                    belief_id, e,
                )

        logger.info("Workflow skill written: %s — %s", belief_id, content[:80])
        return belief_id
    except Exception as e:
        logger.warning("Workflow skill write failed: %s", e)
        return None


# ── Diagnostics ──────────────────────────────────────────────────────

def get_stats() -> dict:
    with _state_lock:
        return {
            "seen_signatures": len(_seen_signatures),
            "recent_injections": len(_recent_injections),
            "pending_bumps": sum(
                1 for n in _recent_injections if not n["bumped"]
            ),
        }
