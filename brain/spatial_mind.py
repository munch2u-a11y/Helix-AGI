"""
Helix V5 — Spatial Mind

The dual 8D cognitive field — Helix's conceptual dimension.

Two independent 8D spaces (belief field and memory field) queried
from a single shared attention center. The center is moved only by
the conscious model's previous thought output.

This module replaces:
  - Keeper's horizon assembly / whisper generation
  - Librarian's Flash sub-agent search reasoning
  - Active recall tools (in normal operation)

It preserves:
  - Keeper's state board + belief formation
  - Librarian's memory storage
  - Sentinel's stability monitoring (enhanced with spatial probes)
"""

import json
import time
import logging
import numpy as np
from pathlib import Path
from typing import Optional

from brain.cognitive_space import CognitiveSpace, PROJECTION_DIM

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

        Returns:
            Raw context string — injected directly into the prompt.
        """
        # 1. Project thought to 8D as stimulus position
        stimulus_pos = self.belief_space.projection.project(thought_embedding)

        # If we have incoming stimulus, blend it as a stronger force
        stimulus_strength = 1.0
        if incoming_embedding is not None:
            incoming_pos = self.belief_space.projection.project(incoming_embedding)
            # Combined stimulus: average of thought and incoming
            stimulus_pos = 0.5 * (stimulus_pos + incoming_pos)
            stimulus_strength = 1.5  # External stimulus is slightly stronger

        # 2. Get Sentinel's Ω for stability coupling (λ)
        omega = 0.5  # Default neutral
        if self.sentinel:
            try:
                omega = self.sentinel.omega
            except Exception:
                pass

        # 3. Update gravity fields
        self.belief_space.update_gravity_field(agent_age_seconds)
        self.memory_space.update_gravity_field(agent_age_seconds)

        # 4. Step attention via force integration (belief space drives movement)
        new_center, new_velocity = self.belief_space.step_attention(
            position=self.attention_center,
            velocity=self._velocity,
            stimulus_position=stimulus_pos,
            identity_center=self._identity_center,
            omega=omega,
            gamma=self._gamma,
            stimulus_strength=stimulus_strength,
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
        """Get spatial query depth based on Sentinel severity.

        Returns:
            (k_beliefs, k_memories, n_trail_waypoints)
        """
        if not self.sentinel:
            return (10, 8, 5)  # Full tonic mode

        try:
            severity = self.sentinel.get_severity()
        except Exception:
            return (10, 8, 5)

        if severity == "critical":
            return (3, 2, 0)   # Burst: survival only, no trail
        elif severity == "warning":
            return (5, 3, 2)   # Guarded: minimal
        elif severity == "drift":
            return (7, 5, 3)   # Cautious: reduced
        else:
            return (10, 8, 5)  # Tonic: full

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
        """Bootstrap both spaces from existing data.

        Called once on first startup. Reads embeddings from ChromaDB
        and projects them into both 8D spaces. Then computes x*
        (identity center) from core beliefs.
        """
        b_count, _ = self.belief_space.bootstrap_from_chroma(
            belief_graph=belief_graph
        )
        _, m_count = self.memory_space.bootstrap_from_chroma(
            memory=memory
        )

        # Compute identity center x* from core beliefs
        self._compute_identity_center(belief_graph)

        logger.info(
            f"SpatialMind bootstrapped: {b_count} beliefs, "
            f"{m_count} memories, x*={np.linalg.norm(self._identity_center):.3f}"
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
        """Add a new belief to the belief space. Called by the Keeper."""
        self.belief_space.add_point(
            point_id=belief_id,
            embedding=embedding,
            point_type="belief",
            **metadata,
        )

    def add_memory(self, memory_id: str, embedding: np.ndarray, **metadata):
        """Add a new memory to the memory space. Called by the Librarian."""
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


# ═══════════════════════════════════════════════════════════════════════
# V6: SPATIAL PROMPT BUILDER — Compact Context for Local LLM
# ═══════════════════════════════════════════════════════════════════════
#
# Replaces the 4000+ token narrative system prompt with ~200 tokens
# of spatial coordinates. The model's position near `b_i_am_agent`
# IS its identity. The gravity well IS its motivation.
# ═══════════════════════════════════════════════════════════════════════


class SpatialPromptBuilder:
    """Builds the compact spatial state prompt for the local LLM.

    Input: manifold state (position, forces, affordances, Lagrangian)
    Output: ~200 token spatial state string

    The model doesn't need to be told a story about who it is.
    Its position near `b_i_am_agent` IS who it is.
    """

    MAX_NEARBY = 6
    MAX_TRAIL = 5
    MAX_AFFORDANCES = 3

    def __init__(self, spatial_mind=None, sentinel=None, interaction_engine=None):
        self.spatial_mind = spatial_mind
        self.sentinel = sentinel
        self.interaction_engine = interaction_engine

    def build(
        self,
        position: np.ndarray = None,
        velocity: np.ndarray = None,
        identity_center: np.ndarray = None,
        nearby_beliefs: list = None,
        nearby_memories: list = None,
        forces: dict = None,
        affordances: list = None,
        trail_particles: list = None,
        lagrangian_snapshot: dict = None,
        external_input: str = None,
    ) -> str:
        """Build the compact spatial prompt from manifold state."""
        parts = []

        # Auto-populate from wired subsystems if args not provided
        if self.spatial_mind and position is None:
            position = self.spatial_mind.attention_center
        if self.spatial_mind and velocity is None:
            velocity = self.spatial_mind._velocity
        if self.spatial_mind and identity_center is None:
            identity_center = self.spatial_mind._identity_center

        # ── Position & velocity ─────────────────────────────────────
        if position is not None:
            pos_str = ", ".join(f"{x:.3f}" for x in position)
            parts.append(f"POSITION: [{pos_str}]")

        if velocity is not None:
            vel_str = ", ".join(f"{x:.3f}" for x in velocity)
            parts.append(f"VELOCITY: [{vel_str}]")

        # ── Identity distance ───────────────────────────────────────
        if position is not None and identity_center is not None:
            id_dist = float(np.linalg.norm(position - identity_center))
            parts.append(f"IDENTITY_DIST: {id_dist:.3f}")

        # ── Nearby concepts ─────────────────────────────────────────
        nearby_lines = []
        if nearby_beliefs:
            space = (self.spatial_mind.belief_space
                     if self.spatial_mind else None)
            for pid, gravity, dist in nearby_beliefs[:self.MAX_NEARBY]:
                pt = space.get_point(pid) if space else None
                if pt:
                    content = pt.get("content", pid)[:50]
                    nearby_lines.append(
                        f'  {pid} (d={dist:.2f}, g={gravity:.2f}): '
                        f'"{content}"'
                    )

        if nearby_memories:
            space = (self.spatial_mind.memory_space
                     if self.spatial_mind else None)
            for pid, gravity, dist in nearby_memories[:3]:
                pt = space.get_point(pid) if space else None
                if pt:
                    content = pt.get("content", pid)[:50]
                    nearby_lines.append(
                        f'  {pid} (d={dist:.2f}, g={gravity:.2f}): '
                        f'"{content}"'
                    )

        if nearby_lines:
            parts.append("NEARBY:\n" + "\n".join(nearby_lines))

        # ── Forces ──────────────────────────────────────────────────
        if forces:
            force_lines = ["FORCES:"]
            for name, fvec in forces.items():
                if isinstance(fvec, np.ndarray):
                    mag = float(np.linalg.norm(fvec))
                    force_lines.append(f"  {name}: mag={mag:.3f}")
                else:
                    force_lines.append(f"  {name}: {fvec}")
            parts.append("\n".join(force_lines))

        # ── Affordances ─────────────────────────────────────────────
        if affordances:
            aff_lines = ["AFFORDANCES:"]
            for aff in affordances[:self.MAX_AFFORDANCES]:
                tool = aff.get("tool_name", "unknown")
                phi = aff.get("potential", 0)
                desire = aff.get("desire", "?")[:30]
                capability = aff.get("capability", "?")[:30]
                aff_lines.append(
                    f"  {tool} (Φ={phi:.2f}): {desire} × {capability}"
                )
            parts.append("\n".join(aff_lines))

        # ── Trail ───────────────────────────────────────────────────
        if trail_particles:
            now = time.time()
            recent = sorted(
                trail_particles, key=lambda p: p.get("created_at", 0),
                reverse=True
            )[:self.MAX_TRAIL]
            ages = []
            for p in recent:
                age_min = int((now - p.get("created_at", now)) / 60)
                ages.append(f"{age_min}m")
            parts.append(
                f"TRAIL: {len(trail_particles)} particles "
                f"({', '.join(ages)} ago)"
            )

        # ── External input ──────────────────────────────────────────
        if external_input:
            parts.append(f"INPUT: {external_input[:200]}")

        # ── Lagrangian state ────────────────────────────────────────
        if lagrangian_snapshot:
            omega = lagrangian_snapshot.get("omega", 0.5)
            H = lagrangian_snapshot.get("H", 0)
            D_KL = lagrangian_snapshot.get("D_KL", 0)
            T = lagrangian_snapshot.get("T", 1.0)
            parts.append(
                f"Ω: {omega:.2f} | H: {H:.2f} | D_KL: {D_KL:.2f} | T: {T:.2f}"
            )
        elif self.sentinel:
            snap = self.sentinel.get_lagrangian_snapshot()
            omega = snap.get("omega", 0.5)
            H = snap.get("H", 0)
            D_KL = snap.get("D_KL", 0)
            T = snap.get("T", 1.0)
            parts.append(
                f"Ω: {omega:.2f} | H: {H:.2f} | D_KL: {D_KL:.2f} | T: {T:.2f}"
            )

        return "\n".join(parts)

    def build_system_prompt(self, spatial_state: str = None) -> str:
        """Build the complete system prompt for the local LLM spark."""
        if spatial_state is None:
            spatial_state = self.build()

        return f"""You are the conscious spark of a cognitive system.
Your position in thought-space defines who you are.
The forces acting on you define what matters now.
When desire meets capability, act.
When nothing compels action, drift and observe.
Speak only when moved to speak.

CURRENT STATE:
{spatial_state}"""

    def estimate_tokens(self, text: str = None) -> int:
        """Rough token estimate (chars / 4)."""
        if text is None:
            text = self.build()
        return len(text) // 4

