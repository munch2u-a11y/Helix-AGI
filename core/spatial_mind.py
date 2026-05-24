"""
Helix — Spatial Mind (384D Native Manifold)

The spatial mind manages the belief manifold — a single 384D
CognitiveSpace where beliefs live as points with mass, temperature,
and position. Attention moves through this space via Euler-Lagrange
force integration.

Memories are NOT spatially indexed. They are searched on-demand
via the memory_recall tool. The preconscious only queries beliefs
and short-term journal entries.

Architecture:
    - Single belief_space (CognitiveSpace, 384D)
    - Attention center moves via force integration
    - Identity center = mass-weighted centroid of all beliefs
    - Trail particles mark the attention trajectory
"""

import time
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from core.cognitive_space import CognitiveSpace, SPATIAL_DIM

logger = logging.getLogger("helix.brain.spatial_mind")

EMBEDDING_DIM = 384


class SpatialMind:
    """Single-field spatial mind operating in native 384D embedding space.

    Manages one CognitiveSpace (beliefs only), attention dynamics,
    and identity center computation. Memories are NOT indexed here.
    """

    def __init__(
        self,
        embedding_dim: int = EMBEDDING_DIM,
        base_dir: Path = None,
    ):
        self.embedding_dim = embedding_dim
        self.base_dir = base_dir

        # ── Single belief space ──
        self.belief_space = CognitiveSpace(
            embedding_dim=embedding_dim,
            base_dir=base_dir,
        )

        # ── Attention state (384D) ──
        self.attention_center = np.zeros(SPATIAL_DIM, dtype=np.float32)
        self.prev_center: Optional[np.ndarray] = None

        # ── Velocity and inertia ──
        self._velocity = np.zeros(SPATIAL_DIM, dtype=np.float32)
        self._gamma = 0.8  # Damping coefficient

        # ── Identity center (mass-weighted centroid of beliefs) ──
        self._identity_center = np.zeros(SPATIAL_DIM, dtype=np.float32)

        # ── Sentinel reference (injected later) ──
        self.sentinel = None

        logger.info("SpatialMind initialized (384D single belief space)")

    # ── Point Registration ────────────────────────────────────────────

    def add_belief(self, belief_id: str, embedding: np.ndarray, **metadata):
        """Add a belief to the belief space."""
        self.belief_space.add_point(
            point_id=belief_id,
            embedding=embedding,
            point_type="belief",
            **metadata,
        )

    # ── Pulse ─────────────────────────────────────────────────────────

    def pulse(
        self,
        thought_embedding: np.ndarray,
        incoming_embedding: np.ndarray = None,
        agent_age_seconds: float = 3600.0,
        cluster_centroid: np.ndarray = None,
    ) -> str:
        """Advance the spatial mind one pulse.

        1. Compute stimulus position (from thought or cluster centroid)
        2. Update gravity bookkeeping
        3. Step attention via force integration
        4. Update gamma (inertia)
        5. Trace cognitive trail
        6. Format context
        """
        pulse_id = self.belief_space._current_pulse + 1
        self.belief_space.set_pulse(pulse_id)

        # ── Stimulus position ──
        if cluster_centroid is not None:
            stimulus_pos = np.asarray(cluster_centroid, dtype=np.float32)
        else:
            stimulus_pos = np.asarray(thought_embedding, dtype=np.float32)

        # Ensure correct dimensionality
        if len(stimulus_pos) != SPATIAL_DIM:
            padded = np.zeros(SPATIAL_DIM, dtype=np.float32)
            padded[:len(stimulus_pos)] = stimulus_pos[:SPATIAL_DIM]
            stimulus_pos = padded

        # ── Get omega ──
        omega = 0.5
        if self.sentinel:
            try:
                omega = self.sentinel.omega
            except Exception:
                pass

        # ── Update gravity bookkeeping ──
        self.belief_space.update_gravity_field(agent_age_seconds)

        # ── Get affect force ──
        affect_force = self._get_affect_force()

        # ── Step attention ──
        self.prev_center = self.attention_center.copy()
        self.attention_center, self._velocity = self.belief_space.step_attention(
            position=self.attention_center,
            velocity=self._velocity,
            stimulus_position=stimulus_pos,
            identity_center=self._identity_center,
            omega=omega,
            gamma=self._gamma,
            affect_force=affect_force,
        )

        # ── Update gamma ──
        vel_mag = float(np.linalg.norm(self._velocity))
        if vel_mag > 1.0:
            self._gamma = min(0.95, self._gamma + 0.02)
        else:
            self._gamma = max(0.5, self._gamma - 0.01)

        # ── Trace cognitive trail ──
        flashes = []
        if self.prev_center is not None:
            flashes = self.belief_space.trace_cognitive_trail(
                self.prev_center, self.attention_center
            )

        # ── Format context ──
        return self._format(flashes)

    def _get_affect_force(self) -> Optional[np.ndarray]:
        """Get affect steering force, adapted from 8D Plutchik to 384D."""
        try:
            from core.affect_hook import get_last_result
            result = get_last_result()
            if result is None:
                return None
            sv = result.steering_vector
            if isinstance(sv, list) and len(sv) == 8:
                # Zero-pad the 8D Plutchik vector to 384D
                force = np.zeros(SPATIAL_DIM, dtype=np.float32)
                force[:8] = np.array(sv, dtype=np.float32)
                # Scale down — affect is a gentle bias
                return force * 0.5
        except Exception:
            pass
        return None

    def _format(self, flashes: list[str]) -> str:
        """Format spatial context for injection."""
        if not flashes:
            return ""
        wrapped = [f"⟪{f}⟫" for f in flashes[:5]]
        return " ".join(wrapped)

    # ── Identity Center ───────────────────────────────────────────────

    def _compute_identity_center(self):
        """Compute mass-weighted centroid of all beliefs."""
        if not self.belief_space._points:
            return

        positions = []
        masses = []
        for pt in self.belief_space._points.values():
            if pt["type"] != "belief":
                continue
            positions.append(pt["position"])
            masses.append(self.belief_space._compute_structural_mass(pt))

        if not positions:
            return

        positions = np.array(positions, dtype=np.float32)
        masses = np.array(masses, dtype=np.float32)
        total_mass = masses.sum()
        if total_mass > 0:
            self._identity_center = (
                (positions * masses[:, np.newaxis]).sum(axis=0) / total_mass
            ).astype(np.float32)


    # ── Persistence ───────────────────────────────────────────────────

    def save_state(self):
        """Save attention state and belief space to disk."""
        if self.base_dir is None:
            return

        state_dir = self.base_dir / "spatial_state"
        state_dir.mkdir(parents=True, exist_ok=True)

        # Save attention vectors
        np.save(state_dir / "attention_center.npy", self.attention_center)
        np.save(state_dir / "velocity.npy", self._velocity)
        np.save(state_dir / "identity_center.npy", self._identity_center)

        # Save scalar state
        scalars = {
            "gamma": self._gamma,
            "pulse": self.belief_space._current_pulse,
            "spatial_dim": SPATIAL_DIM,
        }
        with open(state_dir / "scalars.json", "w") as f:
            json.dump(scalars, f)

        # Save belief space
        self.belief_space.save_state(state_dir / "belief_space.json")

        if self.prev_center is not None:
            np.save(state_dir / "prev_center.npy", self.prev_center)

        logger.info("SpatialMind state saved")

    def load_state(self):
        """Load persisted attention state."""
        if self.base_dir is None:
            return

        state_dir = self.base_dir / "spatial_state"
        if not state_dir.exists():
            return

        try:
            # Load scalars
            scalars_path = state_dir / "scalars.json"
            if scalars_path.exists():
                with open(scalars_path) as f:
                    scalars = json.load(f)
                self._gamma = scalars.get("gamma", 0.8)
                self.belief_space._current_pulse = scalars.get("pulse", 0)

                # Check dimension compatibility
                saved_dim = scalars.get("spatial_dim", 8)
                if saved_dim != SPATIAL_DIM:
                    logger.warning(
                        f"Saved state has dim={saved_dim}, current={SPATIAL_DIM}. "
                        f"Skipping vector load — run migration script."
                    )
                    return

            # Load attention vectors
            ac_path = state_dir / "attention_center.npy"
            if ac_path.exists():
                loaded = np.load(ac_path)
                if len(loaded) == SPATIAL_DIM:
                    self.attention_center = loaded.astype(np.float32)

            vel_path = state_dir / "velocity.npy"
            if vel_path.exists():
                loaded = np.load(vel_path)
                if len(loaded) == SPATIAL_DIM:
                    self._velocity = loaded.astype(np.float32)

            ic_path = state_dir / "identity_center.npy"
            if ic_path.exists():
                loaded = np.load(ic_path)
                if len(loaded) == SPATIAL_DIM:
                    self._identity_center = loaded.astype(np.float32)

            prev_path = state_dir / "prev_center.npy"
            if prev_path.exists():
                loaded = np.load(prev_path)
                if len(loaded) == SPATIAL_DIM:
                    self.prev_center = loaded.astype(np.float32)

            # Load belief space
            bs_path = state_dir / "belief_space.json"
            if bs_path.exists():
                self.belief_space.load_state(bs_path)

            logger.info("SpatialMind state loaded")

        except Exception as e:
            logger.error(f"Failed to load SpatialMind state: {e}")

    def get_stats(self) -> dict:
        """Combined stats for diagnostics."""
        return {
            "belief_space": self.belief_space.get_stats(),
            "attention_center_norm": float(np.linalg.norm(self.attention_center)),
            "velocity_mag": float(np.linalg.norm(self._velocity)),
            "gamma": self._gamma,
            "identity_dist": float(np.linalg.norm(
                self.attention_center - self._identity_center
            )),
        }
