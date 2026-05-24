"""
Helix — Workflow Pattern Detector (Post-Pulse Hook)

Watches tool call sequences across pulses and detects recurring patterns.
When a pattern repeats 3+ times within 24 hours, it crystallizes into a
belief via the belief store.

This is NOT hardcoded automation. The belief is passive — the preconscious
will surface it when Helix enters a similar context, and Helix decides
whether to follow the pattern or not. The belief describes what Helix
TENDS TO DO, not what it MUST do.

Inspired by Claude Code's skillImprovement.ts — which watches for
repeated corrections and rewrites skill files. Here, instead of
rewriting files, we create beliefs in the gravitational field.

Example crystallized belief:
    "When researching a topic, I tend to: search the web → read relevant
     pages → write journal entries. This helps me synthesize information."

The preconscious will then surface this belief when Helix starts a
similar activity, creating a natural feedback loop without hardcoding.

Usage (registered in main.py at startup):
    from core.post_pulse_hooks import register_hook
    from core.workflow_detector import workflow_pattern_hook

    register_hook(workflow_pattern_hook, name="workflow_detector")
"""

import hashlib
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("helix.core.workflow_detector")

# ── Configuration ────────────────────────────────────────────────────

# Minimum tool calls in a sequence to be considered a pattern
MIN_SEQUENCE_LENGTH = 2

# How many times a sequence must repeat before crystallization
MIN_REPETITIONS = 3

# Time window in seconds (24 hours)
PATTERN_WINDOW_SECONDS = 86400

# Maximum sequences to track (bounded memory)
MAX_TRACKED_SEQUENCES = 200

# Maximum age for entries in the recent sequences deque
MAX_ENTRY_AGE_SECONDS = PATTERN_WINDOW_SECONDS


# ── State ────────────────────────────────────────────────────────────

# Rolling window of (timestamp, tool_sequence_tuple)
_recent_sequences: Deque[Tuple[float, Tuple[str, ...]]] = deque(
    maxlen=MAX_TRACKED_SEQUENCES,
)

# Set of sequence hashes that have already been crystallized
# (prevents duplicate belief creation for the same pattern)
_crystallized_hashes: Set[str] = set()

# References to memory and physics — set during registration
_memory_manager = None
_physics_engine = None
_sentinel = None


def _sequence_hash(seq: Tuple[str, ...]) -> str:
    """Deterministic hash for a tool sequence."""
    joined = "→".join(seq)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def _extract_tool_sequence(
    tool_calls: List[Dict[str, Any]],
) -> Optional[Tuple[str, ...]]:
    """Extract an ordered tool name tuple from a pulse's tool calls.

    Filters out meta-tools (enable_toolset, disable_toolset, list_toolsets)
    since those are toolset management, not workflow steps.

    Returns None if the sequence is too short.
    """
    META_TOOLS = {"enable_toolset", "disable_toolset", "list_toolsets"}

    names = []
    for tc in tool_calls:
        name = tc.get("name", "")
        if name and name not in META_TOOLS:
            names.append(name)

    if len(names) < MIN_SEQUENCE_LENGTH:
        return None

    return tuple(names)


def _find_recurring_patterns(
    now: float,
) -> List[Tuple[Tuple[str, ...], int]]:
    """Scan recent sequences for patterns that repeat >= MIN_REPETITIONS.

    Returns list of (sequence, count) for patterns that qualify,
    excluding already-crystallized ones.
    """
    # Filter to entries within the time window
    cutoff = now - PATTERN_WINDOW_SECONDS

    # Count occurrences of each sequence
    counts: Dict[Tuple[str, ...], int] = {}
    for ts, seq in _recent_sequences:
        if ts >= cutoff:
            counts[seq] = counts.get(seq, 0) + 1

    # Find qualifying patterns
    patterns = []
    for seq, count in counts.items():
        if count >= MIN_REPETITIONS:
            seq_hash = _sequence_hash(seq)
            if seq_hash not in _crystallized_hashes:
                patterns.append((seq, count))

    return patterns


def _synthesize_belief_text(
    sequence: Tuple[str, ...], count: int,
) -> str:
    """Create natural language belief text from a tool sequence pattern.

    This is a simple template-based synthesis. In Tier 3, this could
    be replaced with an Ollama call for richer language.
    """
    # Format tool names nicely: "search_web" → "search web"
    readable = [name.replace("_", " ") for name in sequence]
    steps = " → ".join(readable)

    return (
        f"I tend to follow this workflow pattern: {steps}. "
        f"This sequence has occurred {count} times recently, "
        f"suggesting it's an effective approach for this type of task."
    )


def _crystallize_pattern(
    sequence: Tuple[str, ...], count: int,
) -> bool:
    """Save a detected workflow pattern as a high-impact memory.

    The DreamEngine will naturally crystallize this into a formal belief overnight.
    Returns True if successfully saved.
    """
    if _memory_manager is None or _physics_engine is None:
        logger.warning(
            "Workflow detector: dependencies not wired, "
            "cannot save pattern"
        )
        return False

    belief_text = _synthesize_belief_text(sequence, count)
    seq_hash = _sequence_hash(sequence)

    try:
        # Get lagrangian snapshot if sentinel is available
        lagrangian = None
        position = None
        if _sentinel:
            lagrangian = _sentinel.get_lagrangian_snapshot()
        if _physics_engine.attention_center is not None:
            position = _physics_engine.attention_center.tolist()

        # Save to memory system
        _memory_manager.store(
            content=belief_text,
            memory_type="observation",
            source="workflow_detector",
            importance=min(0.6 + (count * 0.05), 0.9),
            tags=["workflow", "auto_crystallized"] + list(sequence),
            lagrangian_snapshot=lagrangian,
            embedding=position,
        )
        
        # Inject into spatial field so Helix is immediately aware
        omega = _sentinel.omega if _sentinel else 0.5
        _physics_engine.step_pulse(belief_text, omega=omega)
        
        _crystallized_hashes.add(seq_hash)
        logger.info(
            "Stored workflow pattern in memory: %s (seen %dx) → %s",
            " → ".join(sequence), count, belief_text[:80],
        )
        return True
    except Exception as e:
        logger.warning("Failed to store workflow pattern: %s", e)
        return False


# ── The Hook ─────────────────────────────────────────────────────────

def workflow_pattern_hook(ctx) -> None:
    """Post-pulse hook: track tool sequences and detect patterns.

    Called after every pulse. Lightweight — just appends to a deque
    and periodically scans for patterns (every 10 pulses).
    """
    # Extract tool sequence from this pulse
    if not ctx.tool_calls:
        return

    sequence = _extract_tool_sequence(ctx.tool_calls)
    if sequence is None:
        return

    # Record it
    now = time.time()
    _recent_sequences.append((now, sequence))

    # Scan for patterns every 10 pulses (not every pulse — too frequent)
    if ctx.pulse_count % 10 != 0:
        return

    # Prune old entries
    cutoff = now - MAX_ENTRY_AGE_SECONDS
    while _recent_sequences and _recent_sequences[0][0] < cutoff:
        _recent_sequences.popleft()

    # Find and crystallize patterns
    patterns = _find_recurring_patterns(now)
    for seq, count in patterns:
        _crystallize_pattern(seq, count)


def set_dependencies(memory_manager, physics_engine, sentinel=None) -> None:
    """Wire dependencies for memory saving. Call during startup."""
    global _memory_manager, _physics_engine, _sentinel
    _memory_manager = memory_manager
    _physics_engine = physics_engine
    _sentinel = sentinel
    logger.info("Workflow detector: dependencies wired")
