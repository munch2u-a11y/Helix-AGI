"""
Helix — Affect Field Post-Pulse Hook

A post-pulse hook that drives the Plutchik emotional wave packet field
every pulse. Each pulse:
  1. Reads the Lagrangian snapshot (after pulse)
  2. Deposits a wave packet at the mapped Plutchik position
  3. Evolves the field (diffuse, decay, prune)
  4. Samples interference at the current affect position
  5. Distributes results to consumers:
     - spatial_mind._affect_steering (for F_affect force)
     - sentinel Ω nudges (for affect-driven events)
     - _last_result (for preconscious to read surfaced memories)

No LLM calls. CPU-only. O(P) per pulse where P = active packets.
"""

import logging
from typing import Optional

from core.affect_field import AffectField, InterferenceResult

logger = logging.getLogger("helix.core.affect_hook")

# Module-level field instance (set during registration)
_affect_field: Optional[AffectField] = None
_last_result: Optional[InterferenceResult] = None

# References to consumers (set during registration)
_spatial_mind = None
_sentinel = None

# ── Thresholds for Sentinel Ω nudges ────────────────────────────────
RESONANCE_INTENSITY_THRESHOLD = 0.5    # Field intensity above this → positive Ω
BOREDOM_DIVERSITY_THRESHOLD = 0.4      # Diversity signal above this → boredom nudge
HIGH_INTENSITY_THRESHOLD = 0.8         # Very strong field → engagement nudge
SAVE_INTERVAL = 10                     # Save state every N pulses
_pulse_counter = 0


def register_affect_hook(
    sentinel=None,
    spatial_mind=None,
    data_dir: str = "data",
) -> AffectField:
    """Create and register the affect field post-pulse hook.

    Call this during startup to wire the hook into the pulse loop.

    Args:
        sentinel: StabilitySentinel instance (for Ω nudges)
        spatial_mind: SpatialMind instance (for attention steering)
        data_dir: Directory for state persistence

    Returns:
        The AffectField instance
    """
    global _affect_field, _spatial_mind, _sentinel

    from core.post_pulse_hooks import register_hook

    _affect_field = AffectField(data_dir=data_dir)
    _spatial_mind = spatial_mind
    _sentinel = sentinel

    register_hook(_affect_pulse_hook, name="affect_field")
    logger.info(
        "Affect field hook registered (packets=%d, pulse=%d)",
        _affect_field.packet_count, _affect_field.current_pulse,
    )

    return _affect_field


def _affect_pulse_hook(ctx) -> None:
    """Post-pulse hook: deposit, evolve, sample, distribute."""
    global _last_result, _pulse_counter

    if _affect_field is None:
        return

    _pulse_counter += 1

    # ── 1. Read Lagrangian snapshot (post-pulse) ─────────────────
    lagrangian = ctx.lagrangian_after
    if not lagrangian:
        # Fallback: try to read from sentinel directly
        if _sentinel:
            try:
                lagrangian = _sentinel.get_lagrangian_snapshot()
            except Exception:
                lagrangian = {}
        if not lagrangian:
            return

    # ── 2. Determine stagnation counter from context ─────────────
    # The engagement monitor may set this in spatial_state
    stagnation = ctx.spatial_state.get("stagnation_counter", 0)

    # ── 3. Deposit wave packet ───────────────────────────────────
    anchor_ids = ctx.injected_belief_ids or []
    _affect_field.deposit(
        lagrangian_snapshot=lagrangian,
        anchor_ids=anchor_ids,
        stagnation_counter=stagnation,
    )

    # ── 4. Evolve field (diffuse, decay, prune) ──────────────────
    _affect_field.evolve(accessed_memory_ids=anchor_ids)

    # ── 5. Sample interference ───────────────────────────────────
    result = _affect_field.sample(
        co_retrieved_memories=anchor_ids,
    )
    _last_result = result

    # ── 6. Distribute: Steering vector → SpatialMind ─────────────
    if _spatial_mind is not None:
        _spatial_mind._affect_steering = result.steering_vector

    # ── 7. Distribute: Ω nudges → Sentinel ───────────────────────
    if _sentinel is not None and hasattr(_sentinel, 'nudge_omega_from_event'):
        # Positive resonance → stabilizing
        if result.field_intensity >= RESONANCE_INTENSITY_THRESHOLD:
            _sentinel.nudge_omega_from_event("affect_resonance")

        # Boredom → destabilizing (needs novelty)
        if result.cognitive_diversity_signal >= BOREDOM_DIVERSITY_THRESHOLD:
            _sentinel.nudge_omega_from_event("affect_boredom")

        # High intensity → engagement
        if result.field_intensity >= HIGH_INTENSITY_THRESHOLD:
            _sentinel.nudge_omega_from_event("affect_intensity_high")

    # ── 8. Periodic state save ───────────────────────────────────
    if _pulse_counter % SAVE_INTERVAL == 0:
        _affect_field.save_state()

    logger.debug(
        "Affect pulse %d: %d packets, intensity=%.3f, dominant=%s, "
        "diversity=%.3f, surfaced=%d",
        _affect_field.current_pulse,
        _affect_field.packet_count,
        result.field_intensity,
        result.dominant_affect,
        result.cognitive_diversity_signal,
        len(result.surfaced_memories),
    )


def get_affect_field() -> Optional[AffectField]:
    """Get the module-level AffectField instance."""
    return _affect_field


def get_last_result() -> Optional[InterferenceResult]:
    """Get the most recent InterferenceResult (for preconscious)."""
    return _last_result
