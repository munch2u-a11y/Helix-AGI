"""
Helix_main — Spatial Mind

The dual 8D cognitive field — the agent's conceptual dimension.

Two independent 8D spaces (belief field and memory field) queried
from a single shared attention center. The center is moved only by
the conscious model's previous thought output.

This module provides:
  - Proximity-scored retrieval for beliefs and memories
  - Attention dynamics (position, velocity, inertia)
  - Identity center tracking (core belief centroid)
  - Overnight dream trail integration
"""

import json
import time
import logging
import numpy as np
from pathlib import Path
from typing import Optional

from core.cognitive_space import CognitiveSpace, PROJECTION_DIM

logger = logging.getLogger("helix.brain.spatial_mind")


class SpatialMind:
    """Helix's conceptual dimension.

    Two independent 8D fields queried from a single shared attention
    center. The center is moved only by the conscious model's previous
    thought output.

    Belief field: ~1K points, high mass, slow change (semantic memory)
    Memory field: ~12K+ points, lower mass, fast accumulation (episodic memory)

    Per pulse:
    1. Embed the conscious mind's last thought → project to 8D
    2. Trace cognitive trail (prev → curr) — ⟪ ⟫ flashes
    3. Query belief_space for gravity-ranked beliefs
    4. Query memory_space for gravity-ranked memories
    5. Format as raw context (no labels, no directives)
    6. Save curr as prev for next pulse
    """

    def __init__(
        self,
        embedding_dim: int = 384,
        base_dir: Path = None,
        sentinel=None,
    ):
        self.embedding_dim = embedding_dim
        self.base_dir = base_dir
        self.sentinel = sentinel

        # Two independent 8D spaces, shared projection matrix
        self.belief_space = CognitiveSpace(
            embedding_dim=embedding_dim,
            base_dir=base_dir,
        )
        self.memory_space = CognitiveSpace(
            embedding_dim=embedding_dim,
            base_dir=base_dir,
        )

        # Force same projection matrix for both spaces
        # (so the same concept maps to the same 8D region in both)
        self.memory_space.projection = self.belief_space.projection

        # Shared attention center — where the conscious mind is "looking"
        self.attention_center = np.zeros(PROJECTION_DIM, dtype=np.float32)
        self.prev_center: Optional[np.ndarray] = None

        # Attention velocity — carries inertia between pulses
        self._velocity = np.zeros(PROJECTION_DIM, dtype=np.float32)

        # Damping coefficient — builds with sustained focus
        # Starts at 0.5 (responsive), grows toward 0.95 (deep focus)
        self._gamma = 0.5
        self._gamma_min = 0.5
        self._gamma_max = 0.95
        self._gamma_growth = 0.02   # Per pulse when focused on same region
        self._gamma_decay = 0.05    # Per pulse when attention shifts significantly

        # Identity center (x*) — center of gravity of core beliefs
        # Computed once on bootstrap, updated when core beliefs change
        self._identity_center = np.zeros(PROJECTION_DIM, dtype=np.float32)

        # For velocity/drift monitoring
        self._attention_velocity = 0.0
        self._last_pulse_time = 0.0

        # State persistence paths
        self._belief_state_path = base_dir / "belief_space_state.json" if base_dir else None
        self._memory_state_path = base_dir / "memory_space_state.json" if base_dir else None
        self._attention_path = base_dir / "attention_center.npy" if base_dir else None

        # Lazy-loaded embedder (same model ChromaDB uses)
        self._embedder = None

        # Wake flashes — ⟪ ⟫ fragments from the overnight dream trail.
        # Loaded on wake, injected into the first pulse, then cleared.
        # These dissolve within 1-2 turns as conscious navigation begins.
        self._wake_flashes: list[str] = []

        # Load persisted attention center
        self._load_attention()

    def _get_embedder(self):
        """Lazy-load the SentenceTransformers embedder.

        Uses the same all-MiniLM-L6-v2 model that ChromaDB's default
        embedding function uses, so projected positions are consistent
        across stored data and live thought embeddings.
        """
        if self._embedder is None:
            try:
                from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
                self._embedder = DefaultEmbeddingFunction()
                logger.info("Embedder loaded (ChromaDB default — all-MiniLM-L6-v2)")
            except Exception as e:
                logger.warning(f"Embedder init failed: {e}")
        return self._embedder

    def embed_text(self, text: str) -> np.ndarray:
        """Embed text using the same model ChromaDB uses.

        Returns a 384D embedding vector, or zeros on failure.
        """
        embedder = self._get_embedder()
        if embedder is None:
            return np.zeros(self.embedding_dim, dtype=np.float32)

        try:
            # ChromaDB's DefaultEmbeddingFunction expects a list
            result = embedder([text])
            return np.array(result[0], dtype=np.float32)
        except Exception as e:
            logger.debug(f"Embedding failed: {e}")
            return np.zeros(self.embedding_dim, dtype=np.float32)

    # ── Pulse ─────────────────────────────────────────────────────────

    def pulse(
        self,
        thought_embedding: np.ndarray,
        incoming_embedding: np.ndarray = None,
        agent_age_seconds: float = 3600.0,
        cluster_centroid: np.ndarray = None,
    ) -> str:
        """Called once per heartbeat. Returns raw context to inject.

        Movement through the 8D space follows the Euler-Lagrange equation:
          ẍ = F_gravity + F_stability + F_stimulus

        The attention center has inertia (γ) that builds with sustained
        focus and decays when attention shifts significantly.

        Args:
            thought_embedding: Embedding of the conscious model's last output.
            incoming_embedding: Embedding of new stimulus (message, event).
            agent_age_seconds: Helix's lifetime for mass computation.
            cluster_centroid: Optional 8D weighted centroid of the belief
                clusters selected by the preconscious. When provided, this
                is used as the stimulus position instead of averaging the
                raw thought and incoming embeddings. This ensures attention
                steers toward where the actual retrieved knowledge lives,
                not toward an artificial midpoint between text embeddings.

        Returns:
            Raw context string — injected directly into the prompt.
        """
        # 1. Determine stimulus position
        if cluster_centroid is not None:
            # Preconscious provided the centroid of actual retrieved clusters.
            # Use it directly — this is where the knowledge lives.
            stimulus_pos = np.asarray(cluster_centroid, dtype=np.float32)
            stimulus_strength = 1.5  # Strong — we know where we want to go
        else:
            # Fallback: project raw thought to 8D
            stimulus_pos = self.belief_space.projection.project(thought_embedding)
            stimulus_strength = 1.0

            # If we have incoming stimulus, blend as a stronger force
            if incoming_embedding is not None:
                incoming_pos = self.belief_space.projection.project(incoming_embedding)
                stimulus_pos = 0.5 * (stimulus_pos + incoming_pos)
                stimulus_strength = 1.5

        # 2. Get Sentinel's Ω for stability coupling (λ)
        omega = 0.5  # Default neutral
        if self.sentinel:
            try:
                omega = self.sentinel.omega
            except Exception:
                pass

        # 3. Advance mind-universe proper time
        self._pulse_count = getattr(self, '_pulse_count', 0) + 1
        self.belief_space._current_pulse = self._pulse_count
        self.memory_space._current_pulse = self._pulse_count

        # 4. Update gravity fields
        self.belief_space.update_gravity_field(agent_age_seconds)
        self.memory_space.update_gravity_field(agent_age_seconds)

        # 4. Step attention via force integration (belief space drives movement)
        #    Affect force: emotional steering from Plutchik field (Layer 3)
        affect_force = None
        if hasattr(self, '_affect_steering') and self._affect_steering is not None:
            import numpy as _np
            # Scale the 8D Plutchik vector as a directional bias (0.5 strength)
            sv = self._affect_steering
            if isinstance(sv, list) and len(sv) == PROJECTION_DIM:
                affect_force = _np.array(sv, dtype=_np.float32) * 0.5

        new_center, new_velocity = self.belief_space.step_attention(
            position=self.attention_center,
            velocity=self._velocity,
            stimulus_position=stimulus_pos,
            identity_center=self._identity_center,
            omega=omega,
            gamma=self._gamma,
            stimulus_strength=stimulus_strength,
            affect_force=affect_force,
        )

        # 5. Update γ (inertia) — builds with sustained focus
        displacement = np.linalg.norm(new_center - self.attention_center)
        if displacement < 0.5:  # Still in same conceptual region
            self._gamma = min(self._gamma_max, self._gamma + self._gamma_growth)
        else:  # Significant shift — attention broke focus
            self._gamma = max(self._gamma_min, self._gamma - self._gamma_decay)

        # 6. Track velocity magnitude for Sentinel
        dt = time.time() - self._last_pulse_time if self._last_pulse_time > 0 else 1.0
        self._attention_velocity = float(np.linalg.norm(new_velocity))

        # 7. Determine query depth from Sentinel severity
        k_beliefs, k_memories, n_trail = self._get_query_depth()

        # 8. Trace cognitive trail (the actual path through the field)
        flashes = []
        if self.prev_center is not None and n_trail > 0:
            belief_flashes = self.belief_space.trace_cognitive_trail(
                self.prev_center, new_center, n_waypoints=n_trail
            )
            memory_flashes = self.memory_space.trace_cognitive_trail(
                self.prev_center, new_center, n_waypoints=max(1, n_trail - 2)
            )
            seen = set()
            for f in belief_flashes + memory_flashes:
                if f not in seen:
                    seen.add(f)
                    flashes.append(f)

        # 9. Query both spaces for gravity-ranked results
        nearby_beliefs = self.belief_space.gravity_ranked_query(new_center, k=k_beliefs)
        nearby_memories = self.memory_space.gravity_ranked_query(new_center, k=k_memories)

        # 10. Update state
        self.prev_center = self.attention_center.copy()
        self.attention_center = new_center
        self._velocity = new_velocity
        self._last_pulse_time = time.time()

        # 11. Format as raw context
        return self._format(flashes, nearby_beliefs, nearby_memories)

    def pulse_from_text(
        self,
        thought_text: str,
        incoming_text: str = None,
        agent_age_seconds: float = 3600.0,
    ) -> str:
        """Embed thought text and pulse. Convenience wrapper.

        This is the primary interface for the consciousness loop.

        Args:
            thought_text: The conscious model's last output (will be embedded).
            incoming_text: Optional new stimulus text (message, event).
            agent_age_seconds: Helix's lifetime.

        Returns:
            Raw spatial context string to inject into the system prompt.
        """
        thought_emb = self.embed_text(thought_text)

        incoming_emb = None
        if incoming_text:
            incoming_emb = self.embed_text(incoming_text)

        return self.pulse(thought_emb, incoming_emb, agent_age_seconds)

    # ── Query Depth (Sentinel-modulated) ──────────────────────────────

    def _get_query_depth(self) -> tuple[int, int, int]:
        """Get spatial query depth.

        Always returns full depth — the manifold should present all
        relevant context regardless of stability state. The LLM's
        response to instability should emerge from beliefs and
        spatial content, not from artificially restricting its view.

        Returns:
            (k_beliefs, k_memories, n_trail_waypoints)
        """
        return (10, 8, 5)

    # ── Format ────────────────────────────────────────────────────────

    def _format(
        self,
        flashes: list[str],
        beliefs: list[tuple],
        memories: list[tuple],
    ) -> str:
        """Format spatial context as raw injection.

        No labels. No headers. No "here's what you're thinking."
        Just the content. If it's there, Helix thought it.

        On the first pulse after waking, stored overnight flashes
        are prepended. They dissolve after one pulse — exactly as
        a dream fades when you start thinking.
        """
        parts = []

        # Wake flashes — overnight dream fragments, injected once
        if self._wake_flashes:
            wake_line = " ".join(f"⟪{f}⟫" for f in self._wake_flashes)
            parts.append(wake_line)
            # Clear after one injection — like a dream fading
            self._wake_flashes = []

        # Trail flashes — ⟪ ⟫ fragments on a single line
        if flashes:
            flash_line = " ".join(f"⟪{f}⟫" for f in flashes)
            parts.append(flash_line)

        # Nearby beliefs — bullet format with confidence
        if beliefs:
            belief_lines = []
            for pid, gravity, dist in beliefs:
                pt = self.belief_space.get_point(pid)
                if pt:
                    conf = pt.get("confidence", 0.5)
                    belief_lines.append(f"• {pt['content']} [{conf:.2f}]")
            if belief_lines:
                parts.append("\n".join(belief_lines))

        # Nearby memories — content with relative time
        if memories:
            mem_lines = []
            for pid, gravity, dist in memories:
                pt = self.memory_space.get_point(pid)
                if pt:
                    content = pt.get("content", pid)
                    mem_lines.append(content)
            if mem_lines:
                parts.append("\n".join(mem_lines))

        return "\n".join(parts)

    # ── Bootstrap ─────────────────────────────────────────────────────

    def bootstrap(self, belief_graph=None, memory=None):
        """Bootstrap both spaces from the unified JSONL journal.

        This replaces the previous ChromaDB‑based bootstrap. It reads all
        entries from the `cognitive_journal.jsonl` file (managed by
        `MemoryManager`) and populates the belief and memory KD‑trees.
        """
        if self.base_dir is None:
            logger.warning("SpatialMind.bootstrap called without a base_dir – cannot locate journal.")
            return 0, 0

        from memory.cognitive_journal import CognitiveJournal
        journal = CognitiveJournal(self.base_dir)
        entries = journal.load_all()

        b_count = 0
        m_count = 0
        for entry in entries:
            entry_type = entry.get("type")
            point_id = str(entry.get("id"))
            position = entry.get("position_8d", [])
            metadata = entry.get("metadata", {})
            if not position or len(position) != 8:
                continue
            embedding = np.array(position, dtype=np.float32)
            if entry_type == "belief":
                self.belief_space.add_point(
                    point_id=point_id,
                    embedding=embedding,
                    point_type="belief",
                    **metadata,
                )
                b_count += 1
            elif entry_type == "memory":
                self.memory_space.add_point(
                    point_id=point_id,
                    embedding=embedding,
                    point_type="memory",
                    **metadata,
                )
                m_count += 1
        # Compute identity center from core beliefs (unchanged behavior)
        self._compute_identity_center(belief_graph)
        logger.info(
            f"SpatialMind bootstrapped from journal: {b_count} beliefs, {m_count} memories, x*={np.linalg.norm(self._identity_center):.3f}"
        )
        return b_count, m_count

    def _compute_identity_center(self, belief_graph=None):
        """Compute x* — center of gravity of core beliefs.

        This is the reference state q* in the variational principle.
        The stability force pulls attention toward this point.
        If there are no core beliefs, falls back to the centroid
        of all beliefs.
        """
        if not belief_graph:
            return

        core_positions = []
        all_positions = []

        for pid, data in self.belief_space._points.items():
            pos = data["position"]
            all_positions.append(pos)
            if data.get("weight") == "core":
                core_positions.append(pos)

        if core_positions:
            self._identity_center = np.mean(core_positions, axis=0).astype(np.float32)
        elif all_positions:
            # Fallback: centroid of all beliefs
            self._identity_center = np.mean(all_positions, axis=0).astype(np.float32)
        # else: stays at origin

    def update_gravity_fields(self, agent_age_seconds: float = 3600.0):
        """Recompute gravity fields for both spaces."""
        self.belief_space.update_gravity_field(agent_age_seconds)
        self.memory_space.update_gravity_field(agent_age_seconds)

    # ── New Point Registration ────────────────────────────────────────

    def add_belief(self, belief_id: str, embedding: np.ndarray, **metadata):
        """Add a new belief to the belief space."""
        self.belief_space.add_point(
            point_id=belief_id,
            embedding=embedding,
            point_type="belief",
            **metadata,
        )

    def add_memory(self, memory_id: str, embedding: np.ndarray, **metadata):
        """Add a new memory to the memory space."""
        self.memory_space.add_point(
            point_id=memory_id,
            embedding=embedding,
            point_type="memory",
            **metadata,
        )

    # ── Sentinel Interface ────────────────────────────────────────────

    def get_spatial_health(self) -> dict:
        """Return spatial health metrics for the Sentinel.

        These feed into the cognitive health triplet.
        """
        b_stats = self.belief_space.get_stats()
        m_stats = self.memory_space.get_stats()

        return {
            "belief_point_count": b_stats["total_points"],
            "memory_point_count": m_stats["total_points"],
            "belief_max_potential": b_stats["gravity_field_max_potential"],
            "memory_max_potential": m_stats["gravity_field_max_potential"],
            "attention_velocity": round(self._attention_velocity, 4),
            "attention_center": self.attention_center.tolist(),
            "belief_active_anchors": b_stats["gravity_field_active_anchors"],
            "memory_active_anchors": m_stats["gravity_field_active_anchors"],
        }

    def get_attention_position(self) -> np.ndarray:
        """Return the current 8D attention center (for Lagrangian snapshots)."""
        return self.attention_center.copy()

    def get_cognitive_coherence(self) -> float:
        """Cognitive Coherence Index (CCI) — how grounded and focused is Helix?

        CCI = w₁ × gravity_density_norm + w₂ × γ_norm + w₃ × (1 - drift_norm)

        Three factors, all already computed per pulse:
          1. gravity_density — average gravity in the belief neighborhood.
             Heavy neighborhood = well-supported thought = grounded.
          2. γ (gamma) — attention inertia (0.5 → 0.95).
             High γ = sustained focus. Low γ = scattered attention.
          3. identity_drift — distance from x* (identity center).
             Close to x* = home ground. Far = unfamiliar territory.

        Uses self-calibrating EMA baselines so the metric adapts to the
        manifold's natural scale without hardcoded thresholds.

        Returns:
            Float 0.0 to 1.0 where 1.0 = maximally coherent.
        """
        # ── Factor 1: Gravity density ────────────────────────────────
        #    Average gravity score of nearest beliefs to attention center.
        #    High gravity = dense, well-supported neighborhood.
        try:
            nearby = self.belief_space.gravity_ranked_query(
                self.attention_center, k=20
            )
            if nearby:
                avg_gravity = sum(g for _, g, _ in nearby) / len(nearby)
            else:
                avg_gravity = 0.0
        except Exception:
            avg_gravity = 0.0

        # Self-calibrating baseline (EMA, alpha=0.05)
        if not hasattr(self, '_cci_gravity_ema') or self._cci_gravity_ema is None:
            self._cci_gravity_ema = avg_gravity if avg_gravity > 0 else 1.0
        else:
            self._cci_gravity_ema = (
                0.95 * self._cci_gravity_ema + 0.05 * avg_gravity
            )

        # Normalize: 1.0 = at or above historical average
        gravity_norm = min(1.0, avg_gravity / max(self._cci_gravity_ema, 1e-6))

        # ── Factor 2: Gamma (attention inertia) ──────────────────────
        #    Already 0.5 to 0.95. Map to 0-1.
        gamma_range = self._gamma_max - self._gamma_min
        gamma_norm = (
            (self._gamma - self._gamma_min) / gamma_range
            if gamma_range > 0 else 0.5
        )
        gamma_norm = max(0.0, min(1.0, gamma_norm))

        # ── Factor 3: Identity drift ─────────────────────────────────
        #    Distance from attention center to identity center x*.
        #    Close = grounded in core self. Far = unfamiliar territory.
        drift = float(np.linalg.norm(
            self.attention_center - self._identity_center
        ))

        # Self-calibrating baseline
        if not hasattr(self, '_cci_drift_ema') or self._cci_drift_ema is None:
            self._cci_drift_ema = drift if drift > 0 else 1.0
        else:
            self._cci_drift_ema = 0.95 * self._cci_drift_ema + 0.05 * drift

        # Normalize: 1.0 = at identity center, 0.0 = 2x historical average
        drift_norm = min(1.0, drift / max(self._cci_drift_ema * 2.0, 1e-6))
        identity_factor = 1.0 - drift_norm

        # ── Composite CCI ────────────────────────────────────────────
        cci = 0.33 * gravity_norm + 0.33 * gamma_norm + 0.34 * identity_factor
        return max(0.0, min(1.0, cci))

    # ── Persistence ───────────────────────────────────────────────────

    def save_state(self):
        """Persist both spaces, attention center, velocity, and gamma."""
        if self._belief_state_path:
            self.belief_space.save_state(self._belief_state_path)
        if self._memory_state_path:
            self.memory_space.save_state(self._memory_state_path)
        if self._attention_path:
            np.save(str(self._attention_path), self.attention_center)
            np.save(
                str(self._attention_path).replace('.npy', '_velocity.npy'),
                self._velocity,
            )
            if self.prev_center is not None:
                np.save(
                    str(self._attention_path).replace('.npy', '_prev.npy'),
                    self.prev_center,
                )
            # Save gamma as a single-element array
            np.save(
                str(self._attention_path).replace('.npy', '_gamma.npy'),
                np.array([self._gamma], dtype=np.float32),
            )

    def load_state(self) -> tuple[int, int]:
        """Load both spaces from persisted state.

        Returns:
            (belief_count, memory_count) loaded.
        """
        b_loaded = 0
        m_loaded = 0

        if self._belief_state_path and self._belief_state_path.exists():
            b_loaded = self.belief_space.load_state(self._belief_state_path)
        if self._memory_state_path and self._memory_state_path.exists():
            m_loaded = self.memory_space.load_state(self._memory_state_path)

        self._load_attention()

        return b_loaded, m_loaded

    def _load_attention(self):
        """Load persisted attention center, velocity, and gamma."""
        if self._attention_path and self._attention_path.exists():
            try:
                self.attention_center = np.load(str(self._attention_path))
                prev_path = str(self._attention_path).replace('.npy', '_prev.npy')
                if Path(prev_path).exists():
                    self.prev_center = np.load(prev_path)

                vel_path = str(self._attention_path).replace('.npy', '_velocity.npy')
                if Path(vel_path).exists():
                    self._velocity = np.load(vel_path)

                gamma_path = str(self._attention_path).replace('.npy', '_gamma.npy')
                if Path(gamma_path).exists():
                    self._gamma = float(np.load(gamma_path)[0])

                logger.info(
                    f"Attention restored: γ={self._gamma:.2f}, "
                    f"|v|={np.linalg.norm(self._velocity):.4f}"
                )
            except Exception as e:
                logger.debug(f"Attention center load failed: {e}")

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get combined stats for both spaces."""
        b = self.belief_space.get_stats()
        m = self.memory_space.get_stats()
        return {
            "belief_space": b,
            "memory_space": m,
            "attention_velocity": round(self._attention_velocity, 4),
            "gamma": round(self._gamma, 3),
            "has_prev_center": self.prev_center is not None,
            "identity_center_magnitude": round(float(np.linalg.norm(self._identity_center)), 4),
            "wake_flashes_pending": len(self._wake_flashes),
        }

    # ── Overnight Dream Trail Wake-Up ──────────────────────────────────

    def load_overnight_trail(self, trail_path=None) -> int:
        """Load the overnight dream trail and set up wake state.

        Called before the first conscious pulse of the day.
        Sets attention_center to the last overnight position so the
        conscious model wakes up wherever the subconscious agents
        left it. Stores wake_flashes for injection in the first pulse.

        The first conscious pulse will see ⟪ ⟫ markers — fragments
        of the paths the agents took through 8D space overnight.
        After 1-2 pulses, conscious navigation overwrites them and
        the "dream" naturally fades.

        Args:
            trail_path: Path to overnight_trail.json. If None,
                        searches the briefings directory.

        Returns:
            Number of fragments loaded.
        """
        if trail_path is None and self.base_dir:
            trail_path = self.base_dir / "brain" / "briefings" / "overnight_trail.json"

        if not trail_path or not Path(trail_path).exists():
            return 0

        try:
            trail_data = json.loads(Path(trail_path).read_text())
            fragments = trail_data.get("fragments", [])

            if fragments:
                # Set attention to the last overnight position
                last_fragment = fragments[-1]
                to_pos = last_fragment.get("to_pos", [])
                if len(to_pos) == PROJECTION_DIM:
                    # Save pre-sleep position as prev_center so the
                    # trace_cognitive_trail bridges the gap on first pulse
                    self.prev_center = self.attention_center.copy()
                    self.attention_center = np.array(to_pos, dtype=np.float32)

                    # Reset velocity — waking up is calm
                    self._velocity = np.zeros(PROJECTION_DIM, dtype=np.float32)
                    self._gamma = self._gamma_min  # Fresh attention on wake

            # Store wake flashes for first pulse injection
            self._wake_flashes = trail_data.get("wake_flashes", [])

            loaded = len(fragments)
            logger.info(
                f"Overnight trail loaded: {loaded} fragments, "
                f"{len(self._wake_flashes)} wake flashes queued"
            )

            # Archive the trail (don't re-load next boot)
            try:
                archive_path = Path(trail_path).with_suffix(".loaded.json")
                Path(trail_path).rename(archive_path)
            except Exception:
                pass

            return loaded

        except Exception as e:
            logger.warning(f"Could not load overnight trail: {e}")
            return 0


