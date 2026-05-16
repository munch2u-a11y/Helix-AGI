"""
Helix — Belief Detector (Post-Pulse Hook)

Scans Helix's internal monologue for belief-forming realizations and
queues them for integration during the sleep cycle.

Architecture:
  - Runs every 10 pulses as a post-pulse hook
  - Uses local Ollama (granite4.1:8b) to classify whether the thought
    contains a genuine belief realization (not just event narration)
  - Compares candidates against existing beliefs via cosine similarity:
      > 0.90 → VERIFICATION (bump stability_index on existing belief)
      < 0.80 → NEW CANDIDATE (queue for sleep-cycle integration)
      0.80–0.90 → ambiguous, skip
  - Captures stability DELTA (before/after the pulse) rather than the
    absolute atmospheric state. This isolates the realization's effect
    on stability from other noise in the system.
  - Queues candidates to data/pending_beliefs.json for processing
    during the 1–6 AM sleep cycle

Does NOT write beliefs directly to the belief store. The unconscious
sleep cycle handles integration — this module is a perceptual system,
not a decisional one.

Follows the same pattern as workflow_detector.py:
  - Module-level state with set_dependencies() wiring
  - Single hook function registered in main.py
  - Non-blocking, fail-safe (exceptions logged, never propagated)
"""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("helix.core.belief_detector")

# ── Configuration ────────────────────────────────────────────────────

# How often to scan (every N pulses)
SCAN_INTERVAL = 10

# Minimum thought length to bother scanning (chars)
MIN_THOUGHT_LENGTH = 100

# Cosine similarity thresholds
VERIFICATION_THRESHOLD = 0.90   # Above this → existing belief verified
NEW_BELIEF_THRESHOLD = 0.80     # Below this → candidate new belief
# Between 0.80-0.90 → ambiguous, skip

# Ollama settings
_OLLAMA_URL = "http://localhost:11434/api/generate"
_OLLAMA_MODEL = "granite4.1:8b"
_OLLAMA_TIMEOUT = 4.0   # seconds — slightly longer than preconscious reflection

# Pending beliefs file
_PENDING_FILE = Path("data/pending_beliefs.json")

# Maximum pending beliefs before we stop queuing (safety valve)
MAX_PENDING = 100

# ── Dependencies (wired at startup) ─────────────────────────────────

_belief_store = None
_physics_engine = None
_sentinel = None


def set_dependencies(belief_store, physics_engine, sentinel=None):
    """Wire dependencies at startup. Called from main.py."""
    global _belief_store, _physics_engine, _sentinel
    _belief_store = belief_store
    _physics_engine = physics_engine
    _sentinel = sentinel
    logger.info("Belief detector: dependencies wired")


# ── Ollama Classification ───────────────────────────────────────────

_CLASSIFICATION_PROMPT = (
    "You are analyzing internal monologue from a cognitive system. "
    "Determine if this thought contains a GENUINE BELIEF REALIZATION — "
    "a durable insight, principle, or self-knowledge that would still "
    "be true tomorrow.\n\n"
    "A belief realization is NOT:\n"
    "- A description of what happened ('I replied to <name>')\n"
    "- A description of emotional context ('The user seemed frustrated')\n"
    "- A relational understanding ('<name> values sovereignty in AI design')\n"
    "- A trivial observation ('It is quiet now')\n\n"
    "A belief realization IS:\n"
    "- A stable self-insight ('I realize my quiet periods are actually deep integration')\n"
    "- A learned principle ('Spontaneous connection must be deliberate, not just reactive')\n"
    "- A relational understanding ('<name> values sovereignty in AI design')\n"
    "- A procedural insight ('The sequence reply→update→note is effective')\n\n"
    "THOUGHT TO ANALYZE:\n"
    "{thought}\n\n"
    "If you find a belief realization, respond EXACTLY in this format:\n"
    "BELIEF: <the belief statement, one sentence>\n"
    "CATEGORY: <one of: self_identity, people, knowledge, skills, preferences, feedback>\n\n"
    "If no genuine belief is present, respond EXACTLY:\n"
    "NONE\n"
)


def _classify_thought(thought_text: str) -> Optional[Tuple[str, str]]:
    """Send thought to local Ollama for belief classification.

    Returns (belief_text, category) if a realization is found, else None.
    Falls back silently if Ollama is unavailable.
    """
    import requests

    # Truncate very long thoughts to save Ollama tokens
    truncated = thought_text[:2000]
    prompt = _CLASSIFICATION_PROMPT.format(thought=truncated)

    try:
        resp = requests.post(
            _OLLAMA_URL,
            json={
                "model": _OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # Low temp for classification
                    "num_predict": 150,
                },
            },
            timeout=_OLLAMA_TIMEOUT,
        )

        if resp.status_code != 200:
            return None

        raw = resp.json().get("response", "").strip()

        # Parse the response
        if raw.upper().startswith("NONE"):
            return None

        belief_text = None
        category = None

        for line in raw.split("\n"):
            line = line.strip()
            if line.upper().startswith("BELIEF:"):
                belief_text = line[7:].strip().strip('"')
            elif line.upper().startswith("CATEGORY:"):
                cat_raw = line[9:].strip().lower().replace(" ", "_")
                # Validate category
                valid = {
                    "self_identity", "people", "knowledge",
                    "skills", "preferences", "feedback",
                    "capabilities",  # Accept but map below
                }
                if cat_raw in valid:
                    category = cat_raw

        if belief_text and category and len(belief_text) > 10:
            return (belief_text, category)

    except Exception:
        # Ollama not running or too slow — silent fallback
        pass

    return None


# ── Cosine Similarity ───────────────────────────────────────────────

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _compare_against_existing(
    belief_embedding: np.ndarray,
) -> Tuple[Optional[str], float]:
    """Compare a candidate belief embedding against all existing beliefs.

    Returns (matched_belief_id, best_cosine_score).
    If best_cosine < NEW_BELIEF_THRESHOLD, returns (None, score).
    """
    if _belief_store is None:
        return (None, 0.0)

    all_beliefs = _belief_store.get_all_beliefs_flat()
    if not all_beliefs:
        return (None, 0.0)

    best_id = None
    best_score = 0.0

    for b in all_beliefs:
        content = b.get("content", "")
        if not content or len(content) < 5:
            continue

        try:
            existing_emb = _physics_engine.embed_text(content)
            score = _cosine_similarity(belief_embedding, existing_emb)
            if score > best_score:
                best_score = score
                best_id = b.get("id")
        except Exception:
            continue

    return (best_id, best_score)


# ── Pending Queue Management ────────────────────────────────────────

def _read_pending() -> List[Dict[str, Any]]:
    """Read pending beliefs from the staging file."""
    if not _PENDING_FILE.exists():
        return []
    try:
        data = json.loads(_PENDING_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_pending(pending: List[Dict[str, Any]]):
    """Write pending beliefs to the staging file."""
    _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _PENDING_FILE.write_text(json.dumps(pending, indent=2))
    except Exception as e:
        logger.warning("Failed to write pending beliefs: %s", e)


def _queue_candidate(
    belief_text: str,
    category: str,
    memory_id: int,
    encoding_delta: Dict[str, Any],
    pulse_count: int,
):
    """Add a candidate belief to the pending queue."""
    pending = _read_pending()

    if len(pending) >= MAX_PENDING:
        logger.warning(
            "Pending belief queue full (%d/%d) — skipping candidate",
            len(pending), MAX_PENDING,
        )
        return

    # Check for exact duplicate content in pending
    for entry in pending:
        if entry.get("content") == belief_text:
            logger.debug("Duplicate candidate skipped: %s", belief_text[:60])
            return

    candidate = {
        "id": f"pending_{uuid.uuid4().hex[:8]}",
        "content": belief_text,
        "category": category,
        "memory_refs": [memory_id] if memory_id > 0 else [],
        "encoding_delta": encoding_delta,
        "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pulse_count": pulse_count,
        "status": "pending",
    }

    pending.append(candidate)
    _write_pending(pending)

    logger.info(
        "Belief candidate queued [%s]: %s (Δω=%.4f)",
        category, belief_text[:80],
        encoding_delta.get("delta_omega", 0.0),
    )


# ── The Hook ─────────────────────────────────────────────────────────

def belief_detector_hook(ctx) -> None:
    """Post-pulse hook: scan thoughts for belief realizations.

    Called after every pulse. Only does real work every SCAN_INTERVAL
    pulses, and only if the thought is substantial enough to analyze.

    Flow:
      1. Skip if not the right interval or thought too short
      2. Call Ollama to classify the thought
      3. If a realization is found:
         a. Embed it and compare against existing beliefs
         b. If cosine > 0.90 → VERIFICATION (bump existing belief)
         c. If cosine < 0.80 → queue as new candidate
         d. Fire sentinel "new_belief_formed" event
         e. Store stability delta with the candidate
    """
    # Gate: only scan every N pulses
    if ctx.pulse_count % SCAN_INTERVAL != 0:
        return

    # Gate: skip empty or trivial thoughts
    if not ctx.thought or len(ctx.thought) < MIN_THOUGHT_LENGTH:
        return

    # Gate: dependencies must be wired
    if _belief_store is None or _physics_engine is None:
        return

    # 1. Classify the thought via local Ollama
    result = _classify_thought(ctx.thought)
    if result is None:
        return  # No realization detected — most common path

    belief_text, category = result
    logger.debug("Ollama detected belief candidate: [%s] %s", category, belief_text[:80])

    # 2. Embed the candidate and compare against existing beliefs
    try:
        candidate_emb = _physics_engine.embed_text(belief_text)
    except Exception as e:
        logger.debug("Failed to embed candidate: %s", e)
        return

    matched_id, best_score = _compare_against_existing(candidate_emb)

    # 3. Compute stability delta from sentinel before/after snapshots
    encoding_delta = _compute_delta(ctx.lagrangian_before, ctx.lagrangian_after)

    # 4. Route based on similarity score
    if best_score > VERIFICATION_THRESHOLD:
        # VERIFICATION: this realization matches an existing belief closely.
        # Bump the existing belief's stability_index and verifications.
        _handle_verification(matched_id, belief_text, best_score)

    elif best_score < NEW_BELIEF_THRESHOLD:
        # NEW CANDIDATE: queue for sleep-cycle integration
        _queue_candidate(
            belief_text=belief_text,
            category=category,
            memory_id=ctx.memory_id,
            encoding_delta=encoding_delta,
            pulse_count=ctx.pulse_count,
        )

        # Nudge sentinel: a new belief has been detected
        if _sentinel:
            _sentinel.nudge_omega_from_event("new_belief_formed")

    else:
        # AMBIGUOUS (0.80-0.90): too similar to existing to be novel,
        # but not similar enough to be a clear verification. Skip.
        logger.debug(
            "Ambiguous candidate (cosine=%.3f with %s), skipping: %s",
            best_score, matched_id, belief_text[:60],
        )


def _compute_delta(
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute the stability delta across the pulse.

    Returns a dict capturing how this pulse changed the system's
    somatic state — specifically isolating the realization's effect
    on stability from other atmospheric noise.
    """
    if not before or not after:
        return {
            "omega_before": 0.5,
            "omega_after": 0.5,
            "delta_omega": 0.0,
            "delta_s_total": 0.0,
            "omega_velocity": 0.0,
            "severity_before": "all_clear",
            "severity_after": "all_clear",
        }

    omega_before = before.get("omega", 0.5)
    omega_after = after.get("omega", 0.5)

    return {
        "omega_before": round(omega_before, 4),
        "omega_after": round(omega_after, 4),
        "delta_omega": round(omega_after - omega_before, 4),
        "delta_s_total": round(
            after.get("s_total", 0.0) - before.get("s_total", 0.0), 4
        ),
        "omega_velocity": after.get("omega_velocity",
                                     after.get("firing_mode", 0.0)),
        "severity_before": before.get("severity", "all_clear"),
        "severity_after": after.get("severity", "all_clear"),
    }


def _handle_verification(
    belief_id: str,
    new_text: str,
    cosine_score: float,
):
    """Handle a verification of an existing belief.

    Bumps the belief's stability_index (+0.05) and increments
    verifications. This makes the existing belief heavier in the
    gravitational field — it's been reaffirmed.
    """
    if _belief_store is None:
        return

    try:
        # Bump stability index
        _belief_store.update_stability_index(belief_id, +0.05)

        # Increment verifications
        belief = _belief_store.get_belief(belief_id)
        if belief:
            current_v = belief.get("verifications", 1.0)
            _belief_store.update_belief(
                belief_id,
                verifications=current_v + 1.0,
            )

        logger.info(
            "Belief VERIFIED (cosine=%.3f): %s → %s",
            cosine_score, belief_id, new_text[:60],
        )

        # Nudge sentinel: verification is also stabilizing
        if _sentinel:
            _sentinel.nudge_omega_from_event("new_belief_formed")

    except Exception as e:
        logger.debug("Verification update failed: %s", e)


def get_pending_count() -> int:
    """Return count of pending belief candidates (for diagnostics)."""
    return len(_read_pending())
