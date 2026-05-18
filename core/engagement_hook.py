"""
Helix — Cognitive Engagement Hook (Post-Pulse)

Tracks thought repetition and tool activity to modulate Ω (hedonic
omega) through the Stability Sentinel.  The effect:

  Looping (same thought 3+ times)  → Ω drops → S_total rises → boredom
  Active tool use                  → Ω boosts → S_total stable → flow

Uses DUAL metrics to detect stagnation:
  1. Word-overlap ratio  (cheap, catches literal repeats)
  2. Cosine similarity   (semantic, catches paraphrases)

Only counts as stagnation when BOTH metrics exceed their thresholds.
This avoids false positives when Helix is genuinely reconsidering a
lexicon term or rephrasing a real insight.

Architecture follows the same pattern as belief_detector.py:
  - Module-level state with set_dependencies() wiring
  - Single hook function registered in main.py
  - Non-blocking, fail-safe
"""

import logging
from typing import Any, Dict, List, Optional, Set

import numpy as np

logger = logging.getLogger("helix.core.engagement_hook")

# ── Configuration ────────────────────────────────────────────────────

# Rolling window of recent thoughts for comparison
THOUGHT_WINDOW_SIZE = 5

# Thresholds — BOTH must be exceeded to count as stagnant
WORD_OVERLAP_THRESHOLD = 0.80   # Ratio of shared words
COSINE_SIMILARITY_THRESHOLD = 0.85  # Semantic similarity

# Stagnation escalation
STAGNATION_ONSET = 3     # Consecutive stagnant pulses before first nudge
DEEP_STAGNATION_ONSET = 6  # Consecutive stagnant pulses for stronger nudge

# ── Dependencies (wired at startup) ─────────────────────────────────

_sentinel = None
_physics_engine = None  # For embedder access


def set_dependencies(sentinel, physics_engine=None):
    """Wire dependencies at startup. Called from main.py."""
    global _sentinel, _physics_engine
    _sentinel = sentinel
    _physics_engine = physics_engine
    logger.info("Engagement hook: dependencies wired")


# ── Module State ─────────────────────────────────────────────────────

_recent_thoughts: List[str] = []
_recent_embeddings: List[np.ndarray] = []
_stagnation_counter: int = 0


# ── Similarity Metrics ───────────────────────────────────────────────

def _word_overlap(a: str, b: str) -> float:
    """Compute word-overlap ratio between two strings.

    Returns the Jaccard similarity of word sets: |A ∩ B| / |A ∪ B|.
    Fast and effective for catching literal repeats like "I am ready."
    """
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two embedding vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _embed_thought(thought: str) -> Optional[np.ndarray]:
    """Embed a thought using the physics engine's embedder.

    Returns None if the embedder is unavailable.
    """
    if _physics_engine is None:
        return None
    try:
        return _physics_engine.embed_text(thought[:500])
    except Exception:
        return None


def _is_stagnant(thought: str, embedding: Optional[np.ndarray]) -> bool:
    """Check if the current thought is stagnant relative to recent history.

    Requires BOTH word overlap AND cosine similarity to exceed their
    respective thresholds against ANY thought in the recent window.
    This dual-gate prevents false positives from lexicon-heavy but
    genuinely varied thoughts.
    """
    if not _recent_thoughts:
        return False

    for i, prev_thought in enumerate(_recent_thoughts):
        # Metric 1: Word overlap (always available)
        overlap = _word_overlap(thought, prev_thought)
        if overlap < WORD_OVERLAP_THRESHOLD:
            continue  # Words are different enough — not stagnant vs this one

        # Metric 2: Cosine similarity (when embeddings available)
        if embedding is not None and i < len(_recent_embeddings):
            prev_emb = _recent_embeddings[i]
            cosine = _cosine_similarity(embedding, prev_emb)
            if cosine < COSINE_SIMILARITY_THRESHOLD:
                continue  # Semantically different — not stagnant

        # BOTH metrics exceeded against this previous thought
        return True

    return False


# ── The Hook ─────────────────────────────────────────────────────────

def engagement_hook(ctx) -> None:
    """Post-pulse hook: track engagement and nudge Ω accordingly.

    Called after every pulse. Measures thought diversity and tool
    activity, feeding the result into the sentinel's omega signal.

    Effects:
      - Tool calls reset stagnation counter and boost Ω
      - Multiple unique tools give an extra boost
      - Repeated thoughts increment stagnation counter
      - After 3+ stagnant pulses, Ω is nudged downward
      - After 6+, a stronger downward nudge is applied
    """
    global _stagnation_counter

    if _sentinel is None:
        return

    thought = ctx.thought or ""
    tool_calls = ctx.tool_calls or []

    # ── Tool activity: boost Ω and reset stagnation ──────────────
    if tool_calls:
        _sentinel.nudge_omega_from_event("productive_tool_use")

        # Bonus for diverse tool usage (2+ different tools)
        unique_tools = set(tc.get("name", "") for tc in tool_calls)
        if len(unique_tools) >= 2:
            _sentinel.nudge_omega_from_event("diverse_tool_use")

        # Reset stagnation — active engagement breaks the loop
        _stagnation_counter = 0

        logger.debug(
            "Engagement: tools used (%s), stagnation reset",
            ", ".join(unique_tools),
        )
        # Still update the thought window (but don't penalize)
        _update_window(thought)
        return

    # ── No tools: check for thought stagnation ───────────────────
    # Skip very short thoughts (pulse headers, empty)
    if len(thought) < 20:
        _update_window(thought)
        return

    embedding = _embed_thought(thought)
    stagnant = _is_stagnant(thought, embedding)

    if stagnant:
        _stagnation_counter += 1

        if _stagnation_counter >= DEEP_STAGNATION_ONSET:
            _sentinel.nudge_omega_from_event("deep_stagnation")
            logger.info(
                "Engagement: DEEP STAGNATION (count=%d, Ω nudge: "
                "cognitive_stagnation + deep_stagnation)",
                _stagnation_counter,
            )
            # Also fire the regular stagnation nudge (cumulative)
            _sentinel.nudge_omega_from_event("cognitive_stagnation")

        elif _stagnation_counter >= STAGNATION_ONSET:
            _sentinel.nudge_omega_from_event("cognitive_stagnation")
            logger.info(
                "Engagement: STAGNATION detected (count=%d, Ω nudge: "
                "cognitive_stagnation)",
                _stagnation_counter,
            )

        else:
            logger.debug(
                "Engagement: similar thought (count=%d, onset at %d)",
                _stagnation_counter, STAGNATION_ONSET,
            )
    else:
        # Gradually recover from stagnation (not instant reset)
        if _stagnation_counter > 0:
            _stagnation_counter = max(0, _stagnation_counter - 1)
            logger.debug(
                "Engagement: thought varied, stagnation recovering (count=%d)",
                _stagnation_counter,
            )

    _update_window(thought, embedding)


def _update_window(thought: str, embedding: Optional[np.ndarray] = None):
    """Update the rolling thought window."""
    global _recent_thoughts, _recent_embeddings

    _recent_thoughts.append(thought)
    if len(_recent_thoughts) > THOUGHT_WINDOW_SIZE:
        _recent_thoughts.pop(0)

    if embedding is not None:
        _recent_embeddings.append(embedding)
        if len(_recent_embeddings) > THOUGHT_WINDOW_SIZE:
            _recent_embeddings.pop(0)


# ── Diagnostics ──────────────────────────────────────────────────────

def get_engagement_status() -> Dict[str, Any]:
    """Return current engagement metrics (for diagnostics)."""
    return {
        "stagnation_counter": _stagnation_counter,
        "thought_window_size": len(_recent_thoughts),
        "stagnation_onset": STAGNATION_ONSET,
        "deep_stagnation_onset": DEEP_STAGNATION_ONSET,
    }
