"""
Helix — Belief Detector (Post-Pulse Hook)

Tags pulses that contain belief-forming realizations for review
during the nightly sleep cycle.

Architecture:
  - Runs every pulse as a post-pulse hook
  - Uses local Ollama (granite4.1:8b) to answer ONE question per pass:
    "Does this thought contain a durable belief realization?"
  - Two passes per pulse:
      Pass 1: Scans the thought (internal monologue)
      Pass 2: Scans any expressive tool outputs (messages sent,
              journal entries, posts written) — separate call so
              the local model isn't overloaded
  - If YES on either pass → tags the pulse's memory_id in
    data/pending_beliefs.json for nightly extraction + classification
  - Does NO extraction, classification, embedding, or comparison.
    All of that happens during the sleep cycle (batch_service.py)

The pending file is just a list of tagged pulses:
  {
    "id": "tag_<uuid>",
    "memory_id": <short-term memory ID>,
    "pulse_count": <int>,
    "thought_text": "<full raw thought, never truncated>",
    "tool_output_text": "<expressive tool output if applicable>",
    "detected_at": "<ISO timestamp>",
    "status": "pending"
  }

Follows the same pattern as workflow_detector.py:
  - Module-level state with set_dependencies() wiring
  - Single hook function registered in main.py
  - Non-blocking, fail-safe (exceptions logged, never propagated)
"""

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("helix.core.belief_detector")

# ── Configuration ────────────────────────────────────────────────────

# How often to scan (every N pulses) — 1 means every thought is evaluated
SCAN_INTERVAL = 1

# Minimum thought length to bother scanning (chars)
MIN_THOUGHT_LENGTH = 100

# Pending beliefs file
_PENDING_FILE = Path("data/pending_beliefs.json")

# Maximum pending tags before we stop queuing (safety valve)
MAX_PENDING = 200

# Tools whose output text reflects Helix's expressive/written thought.
# These get a separate belief-signal pass alongside the monologue pass.
_EXPRESSIVE_TOOLS = {
    "reply", "send_message", "journal", "write_file",
    "moltbook_post", "moltbook_comment", "verbalize",
}

# ── Dependencies (wired at startup) ─────────────────────────────────

_belief_store = None
_physics_engine = None
_sentinel = None
_gguf_manager = None


def set_dependencies(belief_store, physics_engine, sentinel=None, gguf_manager=None):
    """Wire dependencies at startup. Called from main.py.

    belief_store and physics_engine are accepted for forward-compatibility
    (the night cycle uses them) but the detector itself no longer needs
    them for real-time operation.
    """
    global _belief_store, _physics_engine, _sentinel, _gguf_manager
    _belief_store = belief_store
    _physics_engine = physics_engine
    _sentinel = sentinel
    _gguf_manager = gguf_manager
    logger.info("Belief detector: dependencies wired")


# ── Ollama Signal Detection ─────────────────────────────────────────

_SIGNAL_PROMPT = (
    "Does this thought contain a GENUINE BELIEF REALIZATION — "
    "a durable insight, principle, or self-knowledge that would "
    "still be true tomorrow?\n\n"
    "NOT a belief: status updates, event narration, plans, "
    "trivial observations.\n"
    "A belief: stable self-insight, learned principle, relational "
    "understanding, procedural realization.\n\n"
    "THOUGHT:\n{text}\n\n"
    "Answer YES or NO only."
)


def _has_belief_signal(text: str) -> bool:
    """Ask the micro-model if the text contains a belief signal."""
    if not text or len(text) < 20:
        return False
        
    if not _gguf_manager:
        logger.warning("GGUFManager not wired, skipping belief detection.")
        return False

    prompt = _SIGNAL_PROMPT.format(text=text)
    
    # We force the model to output ONLY "YES" or "NO"
    # This entirely avoids <think> block timeouts in reasoning models
    # and keeps inference time under 0.5s for the 3B model.
    grammar = 'root ::= "YES" | "NO"'
    
    try:
        result = _gguf_manager.generate(
            alias="fast_classifier",
            prompt=prompt,
            max_tokens=2,
            temperature=0.0,
            grammar_string=grammar
        )
        return "YES" in result.upper()
    except Exception as e:
        logger.warning(f"Belief detection inference failed: {e}")
        return False


# ── Pending Tag Management ──────────────────────────────────────────

def _read_pending() -> List[Dict[str, Any]]:
    """Read pending belief tags from the staging file."""
    if not _PENDING_FILE.exists():
        return []
    try:
        data = json.loads(_PENDING_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_pending(pending: List[Dict[str, Any]]):
    """Write pending belief tags to the staging file."""
    _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _PENDING_FILE.write_text(json.dumps(pending, indent=2))
    except Exception as e:
        logger.warning("Failed to write pending beliefs: %s", e)


# Lock for thread-safe pending file access
_pending_lock = threading.Lock()


def _tag_pulse(
    thought_text: str,
    memory_id: int,
    pulse_count: int,
    encoding_delta: Dict[str, Any],
    tool_output_text: str = "",
    source: str = "thought",
    injected_belief_ids: Optional[List[str]] = None,
):
    """Tag a pulse as containing belief material (thread-safe).

    Args:
        thought_text: Full raw thought — never truncated.
        memory_id: Short-term memory ID for this pulse.
        pulse_count: Monotonic pulse counter.
        tool_output_text: Expressive tool output that triggered the tag
                          (empty if the tag came from the thought pass).
        source: "thought" or "tool_output" — which pass detected it.
    """
    with _pending_lock:
        pending = _read_pending()

        if len(pending) >= MAX_PENDING:
            logger.warning(
                "Pending tag queue full (%d/%d) — skipping",
                len(pending), MAX_PENDING,
            )
            return

        # Check for duplicate memory_id + source in pending
        for entry in pending:
            if (entry.get("memory_id") == memory_id
                    and entry.get("source") == source):
                return  # Already tagged this pulse for this source

        tag = {
            "id": f"tag_{uuid.uuid4().hex[:8]}",
            "memory_id": memory_id,
            "pulse_count": pulse_count,
            "thought_text": thought_text,
            "tool_output_text": tool_output_text,
            "source": source,
            "encoding_delta": encoding_delta,
            "injected_belief_ids": injected_belief_ids or [],
            "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "status": "pending",
        }

        pending.append(tag)
        _write_pending(pending)

    logger.info(
        "Pulse tagged for belief review [%s] (pulse=%d, mem=%d): %s",
        source, pulse_count, memory_id, thought_text[:80],
    )

    # Nudge sentinel immediately so Helix "feels" the realization in real-time
    if _sentinel:
        _sentinel.nudge_omega_from_event("new_belief_formed")


# ── The Hook ─────────────────────────────────────────────────────────

def belief_detector_hook(ctx) -> None:
    """Post-pulse hook: tag thoughts that contain belief material.

    Called after every pulse. Runs two lightweight Ollama passes in
    a background thread:

      Pass 1: Does the thought (internal monologue) contain a belief?
      Pass 2: Do any expressive tool outputs (messages, journals,
              posts) from this pulse contain a belief?

    If either pass returns YES, the pulse's memory_id is tagged in
    pending_beliefs.json for the nightly extraction cycle.
    """
    # Gate: only scan every N pulses
    if ctx.pulse_count % SCAN_INTERVAL != 0:
        return

    # Gate: skip empty or trivial thoughts
    if not ctx.thought or len(ctx.thought) < MIN_THOUGHT_LENGTH:
        return

    # Snapshot all data NOW before dispatching to background.
    # The ctx object may be reused/mutated by the next pulse.
    thought_snapshot = ctx.thought
    memory_id_snapshot = ctx.memory_id
    pulse_count_snapshot = ctx.pulse_count
    injected_belief_ids_snapshot = list(ctx.injected_belief_ids) if ctx.injected_belief_ids else []
    
    # Compute stability delta across this pulse (for cognitive mass)
    before = dict(ctx.lagrangian_before) if ctx.lagrangian_before else {}
    after = dict(ctx.lagrangian_after) if ctx.lagrangian_after else {}
    encoding_delta = {
        "omega_before": round(before.get("omega", 0.5), 4),
        "omega_after": round(after.get("omega", 0.5), 4),
        "delta_omega": round(after.get("omega", 0.5) - before.get("omega", 0.5), 4),
        "delta_s_total": round(after.get("s_total", 0.0) - before.get("s_total", 0.0), 4),
        "omega_velocity": after.get("omega_velocity", after.get("firing_mode", 0.0)),
        "severity_before": before.get("severity", "all_clear"),
        "severity_after": after.get("severity", "all_clear"),
    }

    # Collect expressive tool outputs from this pulse
    tool_output_parts = []
    for tc in (ctx.tool_calls or []):
        name = tc.get("name", "")
        if name in _EXPRESSIVE_TOOLS:
            # For writing tools, the args contain what Helix wrote
            args = tc.get("args", {})
            # Different tools store the text in different arg names
            text = (
                args.get("text", "")
                or args.get("content", "")
                or args.get("message", "")
                or args.get("body", "")
            )
            if text and len(text) > 20:
                tool_output_parts.append(f"[{name}]: {text}")

    tool_output_snapshot = "\n".join(tool_output_parts) if tool_output_parts else ""

    t = threading.Thread(
        target=_run_detection,
        args=(
            thought_snapshot, memory_id_snapshot, pulse_count_snapshot,
            encoding_delta, tool_output_snapshot, injected_belief_ids_snapshot,
        ),
        daemon=True,
        name=f"belief_detect_p{pulse_count_snapshot}",
    )
    t.start()


def _run_detection(
    thought: str,
    memory_id: int,
    pulse_count: int,
    encoding_delta: Dict[str, Any],
    tool_output: str,
    injected_belief_ids: List[str],
) -> None:
    """Background thread: check thought + tool outputs for belief signal."""
    try:
        # Pass 1: Scan the thought (internal monologue)
        if _has_belief_signal(thought):
            _tag_pulse(
                thought_text=thought,
                memory_id=memory_id,
                pulse_count=pulse_count,
                encoding_delta=encoding_delta,
                source="thought",
                injected_belief_ids=injected_belief_ids,
            )

        # Pass 2: Scan expressive tool outputs (separate call)
        if tool_output and _has_belief_signal(tool_output):
            _tag_pulse(
                thought_text=thought,
                memory_id=memory_id,
                pulse_count=pulse_count,
                encoding_delta=encoding_delta,
                tool_output_text=tool_output,
                source="tool_output",
                injected_belief_ids=injected_belief_ids,
            )

    except Exception as e:
        logger.warning("Background belief detection failed: %s", e)


# ── Diagnostics ──────────────────────────────────────────────────────

def get_pending_count() -> int:
    """Return count of pending belief tags (for diagnostics)."""
    return len(_read_pending())
