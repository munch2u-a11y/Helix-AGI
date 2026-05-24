"""
Helix — Cognitive Space (384D Native Manifold)

384-dimensional spatial manifold for beliefs. Every belief gets a
permanent position in native 384D embedding space (all-MiniLM-L6-v2).

No projection. No dimensionality reduction. Positions ARE embeddings.

Gravity computed on-demand from live point masses each pulse.
No pre-computed anchor grid. At ~1K beliefs, brute-force numpy
is sub-millisecond.

Architecture:
    CognitiveSpace — positions, numpy/FAISS index, point management
    InteractionEngine — affordance orchestration layer

Design principles:
    - Positions are native 384D embeddings (deterministic, reproducible)
    - Cognitive mass = f(confidence, recency) — lifetime-relative
    - The conscious mind's current thought = a moving "attention center"
    - Gravity = T × m / d² — computed on-demand from actual point masses
    - No artificial limits. Recency = gravity, not exclusion.
"""

import os
import time
import math
import json
import logging
import hashlib
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("helix.brain.cognitive_space")

# ── Constants ────────────────────────────────────────────────────────
SPATIAL_DIM = 384           # Native embedding dimensionality
PROJECTION_DIM = SPATIAL_DIM  # Backward compat alias
KDTREE_REBUILD_THRESHOLD = 100  # Rebuild index after this many new points

# Golden ratio constants (for optional φ-modulated field dynamics)
PHI = (1.0 + math.sqrt(5.0)) / 2.0
OMEGA_PHI = 2.0 * math.pi / math.log(PHI)


# ═══════════════════════════════════════════════════════════════════════
# Cognitive Space — 384D Native Manifold
# ═══════════════════════════════════════════════════════════════════════

class CognitiveSpace:
    """384D spatial manifold for beliefs with on-demand gravity.

    Each belief occupies a position in native 384D embedding space.
    Gravity is computed on-demand from the live point set — no
    pre-computed anchor grid. At ~1K beliefs, numpy brute-force
    distance computation is sub-millisecond.

    Physics:
        Gravity:   F = Σ T(i) × m(i) × (x_i - x) / |x_i - x|³
        Stability: F = -λ × (x - x*)
        Stimulus:  F = α × (x_stim - x) / |x_stim - x|

    All equations are dimension-agnostic — identical math in 384D as 8D.
    """

    def __init__(
        self,
        embedding_dim: int = 384,
        base_dir: Path = None,
        seed: int = 42,
    ):
        self.embedding_dim = embedding_dim
        self.base_dir = base_dir
        self.seed = seed

        # ── Point registry ──
        self._points: dict[str, dict] = {}

        # ── Index state ──
        self._index = None          # FAISS IndexFlatL2 or None
        self._index_ids: list[str] = []
        self._index_positions: np.ndarray = None
        self._index_dirty = False
        self._pending_additions = 0

        # ── Pulse time ──
        self._current_pulse = 0
        self._agent_age_seconds = 0.0
        self._mean_connections = 1.0

        # ── Density factor for force clamping ──
        self.density_factor = 0.5

    # ── Point Management ─────────────────────────────────────────────

    @property
    def point_count(self) -> int:
        return len(self._points)

    def add_point(
        self,
        point_id: str,
        embedding: np.ndarray,
        point_type: str = "belief",
        **kwargs,
    ):
        """Add a point to the manifold at its native 384D position.

        The embedding IS the position — no projection needed.
        """
        position = np.asarray(embedding, dtype=np.float32)

        # Ensure correct dimensionality
        if len(position) != self.embedding_dim:
            logger.warning(
                f"Embedding dim mismatch: got {len(position)}, "
                f"expected {self.embedding_dim}. Zero-padding."
            )
            padded = np.zeros(self.embedding_dim, dtype=np.float32)
            padded[:len(position)] = position[:self.embedding_dim]
            position = padded

        self._points[point_id] = {
            "position": position,
            "type": point_type,
            "confidence": kwargs.get("confidence", 0.5),
            "importance": kwargs.get("importance", 0.5),
            "relations_count": kwargs.get("relations_count", 0),
            "weight": kwargs.get("weight", "surface"),
            "content": kwargs.get("content", ""),
            "metadata": kwargs.get("metadata", {}),
            "last_accessed": kwargs.get("last_accessed", 0),
            "last_accessed_pulse": kwargs.get("last_accessed_pulse", 0),
            "created_at": kwargs.get("created_at", 0),
            "creation_pulse": kwargs.get("creation_pulse", self._current_pulse),
            "encoding_omega": kwargs.get("encoding_omega", 0.5),
            "encoding_s_total": kwargs.get("encoding_s_total", 0.0),
        }

        # Mark for rebuild
        self._pending_additions += 1
        if self._pending_additions >= KDTREE_REBUILD_THRESHOLD:
            self._rebuild_index()

        self._index_dirty = True

    def remove_point(self, point_id: str):
        if point_id in self._points:
            del self._points[point_id]
            self._index_dirty = True

    def get_point(self, point_id: str) -> Optional[dict]:
        return self._points.get(point_id)

    def update_access(self, point_id: str):
        pt = self._points.get(point_id)
        if pt:
            pt["last_accessed"] = time.time()
            pt["last_accessed_pulse"] = self._current_pulse

    def set_pulse(self, pulse_id: int):
        self._current_pulse = pulse_id

    # ── Spatial Queries (numpy brute-force) ──────────────────────────

    def _ensure_index(self):
        """Rebuild the search index if dirty."""
        if self._index_dirty or self._index_positions is None:
            self._rebuild_index()

    def query_nearby(self, position: np.ndarray, k: int = 10):
        """Find K nearest points to a position.

        Returns list of (point_id, distance) tuples.
        Uses numpy brute-force L2 distance — sub-ms for ~1K points.
        """
        self._ensure_index()

        if not self._index_ids or self._index_positions is None:
            return []

        k = min(k, len(self._index_ids))
        if k == 0:
            return []

        query = np.asarray(position, dtype=np.float32).reshape(1, -1)

        # Try FAISS first, fall back to numpy
        if self._index is not None:
            try:
                dists, idxs = self._index.search(query, k)
                results = []
                for i in range(k):
                    idx = int(idxs[0][i])
                    if idx < 0 or idx >= len(self._index_ids):
                        continue
                    results.append((
                        self._index_ids[idx],
                        float(np.sqrt(dists[0][i]))  # FAISS returns L2²
                    ))
                return results
            except Exception:
                pass

        # Numpy fallback: brute-force L2
        diffs = self._index_positions - query
        dists_sq = np.sum(diffs ** 2, axis=1)
        top_k = np.argpartition(dists_sq, k)[:k]
        top_k = top_k[np.argsort(dists_sq[top_k])]

        return [
            (self._index_ids[int(idx)], float(np.sqrt(dists_sq[idx])))
            for idx in top_k
        ]


    def gravity_ranked_query(
        self, position: np.ndarray, k: int = 10
    ) -> list[tuple[str, float, float]]:
        """Query points ranked by cognitive gravity: T × mass / distance².

        Returns list of (point_id, gravity_score, distance) tuples,
        sorted by gravity descending.
        """
        self._ensure_index()
        if not self._index_ids:
            return []

        # Get more candidates than needed, then rank by gravity
        candidates = self.query_nearby(position, k=min(k * 3, len(self._index_ids)))

        scored = []
        for pid, dist in candidates:
            pt = self._points.get(pid)
            if pt is None:
                continue

            mass = self._compute_structural_mass(pt)
            temp = self._compute_temperature(pt)
            gravity = temp * mass / max(dist ** 2, 0.001)
            scored.append((pid, gravity, dist))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    # ── Trail Particles ──────────────────────────────────────────────

    def deposit_trail_particle(
        self,
        position: np.ndarray,
        content: str,
        pulse_id: int,
        omega: float = 0.5,
    ):
        """Drop a trail particle at the current attention position."""
        trail_id = f"trail_{pulse_id}_{hashlib.md5(content[:50].encode()).hexdigest()[:8]}"
        self._points[trail_id] = {
            "position": np.asarray(position, dtype=np.float32),
            "type": "trail",
            "confidence": 1.0,
            "importance": max(0.3, omega),
            "content": content[:200] if content else "",
            "metadata": {},
            "relations_count": 0,
            "weight": "ephemeral",
            "last_accessed": time.time(),
            "last_accessed_pulse": pulse_id,
            "created_at": time.time(),
            "creation_pulse": pulse_id,
            "encoding_omega": omega,
            "encoding_s_total": 0.0,
        }
        self._index_dirty = True

    def extract_cooled_trail_particles(self, temp_threshold: float = 0.10):
        """Extract trail particles that have cooled below threshold."""
        cooled = []
        to_remove = []
        for pid, pt in self._points.items():
            if pt["type"] != "trail":
                continue
            temp = self._compute_temperature(pt)
            if temp < temp_threshold:
                cooled.append({
                    "point_id": pid,
                    "content": pt.get("content", ""),
                    "creation_pulse": pt.get("creation_pulse", 0),
                    "encoding_omega": pt.get("encoding_omega", 0.5),
                })
                to_remove.append(pid)
        for pid in to_remove:
            del self._points[pid]
        if to_remove:
            self._index_dirty = True
        return cooled

    # ── Entropy & Information Measures ────────────────────────────────

    def compute_shannon_entropy(self) -> float:
        """Shannon entropy of the mass distribution."""
        if not self._points:
            return 0.0

        masses = np.array([
            self._compute_structural_mass(p) for p in self._points.values()
        ])
        total = masses.sum()
        if total < 1e-10:
            return 0.0

        probs = masses / total
        probs = probs[probs > 0]
        return float(-np.sum(probs * np.log(probs + 1e-12)))

    def compute_kl_divergence(self) -> float:
        """KL divergence from uniform distribution."""
        if not self._points:
            return 0.0

        masses = np.array([
            self._compute_structural_mass(p) for p in self._points.values()
        ])
        total = masses.sum()
        if total < 1e-10:
            return 0.0

        probs = masses / total
        uniform = np.ones_like(probs) / len(probs)
        kl = float(np.sum(probs * np.log((probs + 1e-12) / (uniform + 1e-12))))
        return max(0.0, kl)

    def compute_local_temperature(self, position: np.ndarray, radius: float = 1.0) -> float:
        """Average temperature of points within a radius."""
        if not self._points:
            return 0.0

        nearby = self.query_nearby(position, k=min(10, self.point_count))
        if not nearby:
            return 0.0

        temps = []
        for pid, dist in nearby:
            if dist > radius:
                continue
            pt = self._points.get(pid)
            if pt:
                temps.append(self._compute_temperature(pt))

        return float(np.mean(temps)) if temps else 0.0

    # ── Interaction Potential ─────────────────────────────────────────

    def compute_interaction_potential(
        self, position: np.ndarray, threshold: float = 0.5
    ) -> list[dict]:
        """Compute interaction potential between subjective and objective beliefs."""
        self._ensure_index()

        nearby = self.query_nearby(position, k=min(30, self.point_count))
        if not nearby:
            return []

        subjective = []
        objective = []

        for pid, dist in nearby:
            point = self._points.get(pid)
            if point is None or point["type"] == "trail":
                continue

            mass = self._compute_structural_mass(point)
            temp = self._compute_temperature(point)
            gravity = temp * mass / max(dist ** 2, 0.001)

            drive_type = point.get("metadata", {}).get("drive_type", "")
            if drive_type == "subjective":
                subjective.append((pid, gravity, dist, point))
            elif drive_type == "objective":
                objective.append((pid, gravity, dist, point))

        affordances = []
        epsilon = 0.01

        for s_id, s_grav, s_dist, s_point in subjective:
            for o_id, o_grav, o_dist, o_point in objective:
                pair_dist = float(np.linalg.norm(
                    s_point["position"] - o_point["position"]
                ))
                potential = (s_grav * o_grav) / max(pair_dist, epsilon)

                if potential > threshold:
                    affordances.append({
                        "desire": s_point.get("content", s_id),
                        "desire_id": s_id,
                        "capability": o_point.get("content", o_id),
                        "capability_id": o_id,
                        "potential": round(float(potential), 4),
                        "tool_name": o_point.get("metadata", {}).get("tool_name"),
                        "urgency": round(float(s_grav / max(s_dist, epsilon)), 4),
                    })

        affordances.sort(key=lambda a: a["potential"], reverse=True)
        return affordances


    # ── Attention Dynamics (Euler-Lagrange) ─────────────────────────────

    def step_attention(
        self,
        position: np.ndarray,
        velocity: np.ndarray,
        stimulus_position: np.ndarray,
        identity_center: np.ndarray,
        omega: float = 0.5,
        gamma: float = 0.8,
        dt: float = 1.0,
        stimulus_strength: float = 1.0,
        affect_force: np.ndarray = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Advance the attention center one timestep via force integration.

        Derived from δ∫(H(q) + λ D_KL(q‖q*))dt = 0

        Same equations as the 8D version — dimension-agnostic vector math.
        """
        f_grav = self.compute_gravity_force(position)
        f_stab = self.compute_stability_force(position, identity_center, omega)
        f_stim = self._compute_stimulus_force(
            position, stimulus_position, stimulus_strength
        )

        f_affect = np.zeros(SPATIAL_DIM, dtype=np.float32)
        if affect_force is not None:
            f_affect = np.asarray(affect_force, dtype=np.float32)
            if len(f_affect) != SPATIAL_DIM:
                padded = np.zeros(SPATIAL_DIM, dtype=np.float32)
                padded[:len(f_affect)] = f_affect[:SPATIAL_DIM]
                f_affect = padded

        f_total = f_grav + f_stab + f_stim + f_affect
        new_velocity = gamma * velocity + dt * f_total
        new_position = position + dt * new_velocity

        return new_position.astype(np.float32), new_velocity.astype(np.float32)

    def compute_gravity_force(self, position: np.ndarray) -> np.ndarray:
        """Gravitational force at a point from all masses in the space.

        F_gravity = Σᵢ m(i) × (xᵢ - x) / ‖xᵢ - x‖³

        Computed on-demand from the K nearest points. No pre-computed
        anchor grid — at ~1K beliefs this is sub-millisecond.
        """
        force = np.zeros(SPATIAL_DIM, dtype=np.float64)

        if not self._points:
            return force.astype(np.float32)

        self._ensure_index()
        if not self._index_ids:
            return force.astype(np.float32)

        k = min(20, len(self._index_ids))
        nearby = self.query_nearby(position, k=k)

        for pid, dist in nearby:
            dist = max(dist, 0.01)
            point_data = self._points.get(pid)
            if point_data is None:
                continue

            mass = self._compute_structural_mass(point_data)
            temperature = self._compute_temperature(point_data)
            direction = point_data["position"] - position

            force += temperature * mass * direction / (dist ** 3)

        # Dynamic force clamp based on current density
        if self._points:
            positions = np.stack([p["position"] for p in self._points.values()])
            current_density = np.mean(np.linalg.norm(positions, axis=1))
        else:
            current_density = 0.0
        max_force = self.density_factor * current_density
        clamp_limit = max(max_force, 2.0)
        force_mag = np.linalg.norm(force)
        if force_mag > clamp_limit:
            force = force * (clamp_limit / force_mag)

        return force.astype(np.float32)

    def compute_stability_force(
        self, position: np.ndarray, identity_center: np.ndarray, omega: float,
    ) -> np.ndarray:
        """Stability coupling force — pull toward identity center.

        F_stability = -λ × (x - x*)
        """
        displacement = position - identity_center
        dist = np.linalg.norm(displacement)

        if dist < 0.01:
            return np.zeros(SPATIAL_DIM, dtype=np.float32)

        force = -omega * displacement
        return force.astype(np.float32)

    def _compute_stimulus_force(
        self, position: np.ndarray, stimulus_position: np.ndarray, strength: float = 1.0,
    ) -> np.ndarray:
        """External stimulus force — pull toward new thought/input."""
        direction = stimulus_position - position
        dist = np.linalg.norm(direction)

        if dist < 0.01:
            return np.zeros(SPATIAL_DIM, dtype=np.float32)

        return (strength * direction / dist).astype(np.float32)

    # ── Gravity Field Interface (on-demand, no pre-computation) ──────

    def update_gravity_field(self, agent_age_seconds: float = None):
        """Update agent age and mean connections. No pre-computation needed.

        Gravity is computed on-demand in compute_gravity_force().
        This method just updates bookkeeping for temperature/mass.
        """
        if agent_age_seconds is not None:
            self._agent_age_seconds = agent_age_seconds

        if not self._points:
            return

        connection_counts = [
            p.get("relations_count", 0) for p in self._points.values()
        ]
        self._mean_connections = (
            sum(connection_counts) / len(connection_counts)
            if connection_counts else 1.0
        )

    def invalidate_entropy_baseline(self):
        """Reset entropy baseline after context compression.

        Forces re-sampling on next entropy query so stale baselines
        from the previous context window don't persist.
        """
        pass  # On-demand entropy computation has no cached baseline to invalidate


    # ── Cognitive Gravity ──────────────────────────────────────────────

    def _compute_structural_mass(self, point_data: dict) -> float:
        """A point's rest mass — purely intrinsic, never changes.

        Mass = c  (confidence for beliefs, importance for memories)
        """
        if point_data["type"] == "belief":
            c = point_data.get("confidence", 0.5)
        else:
            c = point_data.get("importance", 0.5)
        return max(0.01, c)

    def _compute_temperature(self, point_data: dict) -> float:
        """A point's temperature — recency heat that radiates away.

        T = T₀ / (1 + (pulse_age / τ)²)
        """
        concept_type = point_data.get("type", "memory")

        if concept_type == "belief":
            c = point_data.get("confidence", 0.5)
            T_0 = 0.3
            tau = 60.0
        elif concept_type == "trail":
            c = point_data.get("importance", 0.5)
            T_0 = 2.0 * max(c, 0.3)
            tau = 8.0
        else:
            c = point_data.get("importance", 0.5)
            T_0 = 1.5 * max(c, 0.3)
            tau = 12.0

        creation_pulse = point_data.get("creation_pulse", 0)
        last_accessed_pulse = point_data.get("last_accessed_pulse", 0)

        if self._current_pulse > 0:
            most_recent_pulse = max(creation_pulse, last_accessed_pulse)
            pulse_age = self._current_pulse - most_recent_pulse
            T = T_0 / (1.0 + (pulse_age / tau) ** 2)
        else:
            T = T_0

        return max(0.05, T)

    # ── Internal ──────────────────────────────────────────────────────

    def _rebuild_index(self):
        """Rebuild the spatial index from all current points."""
        if not self._points:
            self._index = None
            self._index_ids = []
            self._index_positions = None
            self._index_dirty = False
            return

        valid_pids = []
        for pid, p in self._points.items():
            if p.get("confidence", 0.0) <= 0.0:
                continue
            if p.get("metadata", {}).get("absorbed_by"):
                continue
            valid_pids.append(pid)

        self._index_ids = valid_pids

        if not self._index_ids:
            self._index = None
            self._index_positions = None
        else:
            self._index_positions = np.array(
                [self._points[pid]["position"] for pid in self._index_ids],
                dtype=np.float32,
            )
            # Try FAISS, fall back to numpy-only
            try:
                import faiss
                self._index = faiss.IndexFlatL2(self.embedding_dim)
                self._index.add(self._index_positions)
                logger.debug(f"FAISS index rebuilt: {len(self._index_ids)} points")
            except ImportError:
                self._index = None  # Will use numpy fallback
                logger.debug(f"Numpy index rebuilt: {len(self._index_ids)} points (FAISS not available)")

        self._pending_additions = 0
        self._index_dirty = False

    # ── Cognitive Trail ───────────────────────────────────────────────

    def trace_cognitive_trail(
        self,
        prev_center: np.ndarray,
        curr_center: np.ndarray,
        n_waypoints: int = 5,
        k_per_waypoint: int = 1,
    ) -> list[str]:
        """Sample the cognitive trajectory between two attention positions."""
        if self.point_count == 0:
            return []

        glimpses = []
        seen_ids = set()

        for i in range(n_waypoints):
            t = (i + 1) / (n_waypoints + 1)
            waypoint = prev_center * (1 - t) + curr_center * t
            nearby = self.query_nearby(waypoint, k=k_per_waypoint)

            for pid, dist in nearby:
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                pt = self.get_point(pid)
                if pt:
                    fragment = self._condense(pt.get("content", ""))
                    if fragment and len(fragment) > 2:
                        glimpses.append(fragment)

        return glimpses

    @staticmethod
    def _condense(content: str) -> str:
        """Extract the semantic core of a belief or memory."""
        import re
        s = content.strip()
        if not s:
            return ""

        preambles = [
            r'^I believe that ',
            r'^I believe ',
            r'^I (can|have|am|do|feel|think|know|value|understand|trust) ',
            r'^My ',
            r'^The ',
            r'^When ',
        ]
        for p in preambles:
            stripped = re.sub(p, '', s, count=1, flags=re.IGNORECASE)
            if stripped != s:
                s = stripped
                break

        for sep in [' — ', ', ', '; ', '. ']:
            if sep in s:
                s = s.split(sep, 1)[0]
                break

        if s and s[0].isupper() and not s[:2].isupper():
            s = s[0].lower() + s[1:]

        return s.strip()

    # ── Bootstrap ─────────────────────────────────────────────────────

    def bootstrap_from_journal(self, belief_graph=None, memory=None):
        """Bootstrap beliefs from the unified JSONL journal."""
        if self.base_dir is None:
            logger.warning("CognitiveSpace.bootstrap_from_journal called without base_dir")
            return 0, 0

        from memory.cognitive_journal import CognitiveJournal
        journal = CognitiveJournal(self.base_dir)
        entries = journal.load_all()

        b_count = 0
        m_count = 0
        for entry in entries:
            entry_type = entry.get("type")
            point_id = str(entry.get("id"))
            # Try 384D embedding first, fall back to position_8d for migration
            embedding = entry.get("embedding", entry.get("position_8d", []))
            metadata = entry.get("metadata", {})

            if not embedding:
                continue

            emb_array = np.array(embedding, dtype=np.float32)
            # Handle old 8D entries — they'll need re-embedding via migration script
            if len(emb_array) != self.embedding_dim:
                continue

            if entry_type == "belief":
                self.add_point(
                    point_id=point_id,
                    embedding=emb_array,
                    point_type="belief",
                    **metadata,
                )
                b_count += 1
            elif entry_type == "memory":
                self.add_point(
                    point_id=point_id,
                    embedding=emb_array,
                    point_type="memory",
                    **metadata,
                )
                m_count += 1

        if b_count > 0 or m_count > 0:
            self._rebuild_index()

        logger.info(
            f"CognitiveSpace bootstrapped from journal: "
            f"{b_count} beliefs, {m_count} memories, total={self.point_count}"
        )
        return b_count, m_count


    # ── Persistence ───────────────────────────────────────────────────

    def save_state(self, path: Path):
        """Save all point positions and metadata to disk."""
        state = {}
        for pid, data in self._points.items():
            state[pid] = {
                "position": data["position"].tolist(),
                "type": data["type"],
                "confidence": data.get("confidence", 0.5),
                "importance": data.get("importance", 0.5),
                "relations_count": data.get("relations_count", 0),
                "weight": data.get("weight", "surface"),
                "content": data.get("content", ""),
                "last_accessed": data.get("last_accessed", 0),
                "created_at": data.get("created_at", 0),
            }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f)

        logger.info(f"CognitiveSpace state saved: {len(state)} points → {path}")

    def load_state(self, path: Path) -> int:
        """Load point positions and metadata from disk."""
        if not path.exists():
            return 0

        try:
            with open(path) as f:
                state = json.load(f)

            for pid, data in state.items():
                position = np.array(data["position"], dtype=np.float32)
                # Skip old 8D positions — need re-embedding
                if len(position) != self.embedding_dim:
                    logger.warning(
                        f"Skipping point {pid}: position dim {len(position)} "
                        f"!= {self.embedding_dim}. Run migration script."
                    )
                    continue

                self._points[pid] = {
                    "position": position,
                    "type": data.get("type", "memory"),
                    "confidence": data.get("confidence", 0.5),
                    "importance": data.get("importance", 0.5),
                    "relations_count": data.get("relations_count", 0),
                    "weight": data.get("weight", "surface"),
                    "content": data.get("content", ""),
                    "last_accessed": data.get("last_accessed", 0),
                    "created_at": data.get("created_at", 0),
                    "metadata": {},
                }

            self._index_dirty = True
            self._rebuild_index()

            logger.info(f"CognitiveSpace state loaded: {len(self._points)} points from {path}")
            return len(self._points)

        except Exception as e:
            logger.error(f"Failed to load CognitiveSpace state: {e}")
            return 0

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get diagnostic stats about the cognitive space."""
        belief_count = sum(1 for p in self._points.values() if p["type"] == "belief")
        memory_count = sum(1 for p in self._points.values() if p["type"] == "memory")
        masses = [self._compute_structural_mass(p) for p in self._points.values()]

        return {
            "total_points": len(self._points),
            "beliefs": belief_count,
            "memories": memory_count,
            "index_size": len(self._index_ids) if self._index_ids else 0,
            "index_dirty": self._index_dirty,
            "index_type": "faiss" if self._index is not None else "numpy",
            "spatial_dim": self.embedding_dim,
            "mass_min": float(min(masses)) if masses else 0.0,
            "mass_max": float(max(masses)) if masses else 0.0,
            "mass_mean": float(np.mean(masses)) if masses else 0.0,
            "agent_age_seconds": self._agent_age_seconds,
        }


# ═══════════════════════════════════════════════════════════════════════
# V6: INTERACTION ENGINE — Affordance Orchestration Layer
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_INTERACTION_THRESHOLD = 0.5
MAX_AFFORDANCES_PER_PULSE = 5
TOOL_COOLDOWN_PULSES = 5


class InteractionEngine:
    """Converts manifold interaction potentials into actionable tool affordances."""

    def __init__(self, cognitive_space=None, sentinel=None):
        self.space = cognitive_space
        self.sentinel = sentinel
        self._cooldowns: dict[str, int] = {}
        self._current_pulse_id = 0
        self._affordance_history: list[dict] = []
        logger.info("InteractionEngine initialized")

    def set_cognitive_space(self, space):
        self.space = space

    def compute_affordances(
        self, position, pulse_id: int,
        threshold: float = DEFAULT_INTERACTION_THRESHOLD,
    ) -> list[dict]:
        self._current_pulse_id = pulse_id
        if self.space is None:
            return []

        raw = self.space.compute_interaction_potential(position, threshold=threshold)
        if not raw:
            return []

        filtered = []
        for aff in raw:
            tool = aff.get("tool_name")
            if tool and tool in self._cooldowns:
                if pulse_id - self._cooldowns[tool] < TOOL_COOLDOWN_PULSES:
                    continue
            filtered.append(aff)

        seen_tools = {}
        for aff in filtered:
            tool = aff.get("tool_name", "unknown")
            if tool in seen_tools:
                if aff["potential"] > seen_tools[tool]["potential"]:
                    seen_tools[tool] = aff
            else:
                seen_tools[tool] = aff

        deduped = list(seen_tools.values())
        deduped.sort(key=lambda a: a["potential"], reverse=True)
        result = deduped[:MAX_AFFORDANCES_PER_PULSE]

        if self.sentinel:
            omega = self.sentinel.omega
            severity = self.sentinel.get_severity()
            for aff in result:
                aff["omega_at_generation"] = round(omega, 4)
                aff["severity_at_generation"] = severity

        if result:
            self._affordance_history.append({
                "pulse_id": pulse_id, "affordances": result,
            })
            if len(self._affordance_history) > 100:
                self._affordance_history = self._affordance_history[-100:]

        return result

    def mark_executed(self, tool_name: str, pulse_id: int = None):
        pid = pulse_id or self._current_pulse_id
        self._cooldowns[tool_name] = pid

    def format_for_prompt(self, affordances: list[dict]) -> str:
        if not affordances:
            return ""
        lines = ["AFFORDANCES:"]
        for aff in affordances:
            tool = aff.get("tool_name", "unknown")
            phi = aff.get("potential", 0)
            urgency = aff.get("urgency", 0)
            desire = aff.get("desire", "?")[:40]
            capability = aff.get("capability", "?")[:40]
            lines.append(
                f"  {tool} (Φ={phi:.2f}, urgency={urgency:.2f}): "
                f"{desire} × {capability}"
            )
        return "\n".join(lines)

    def get_stats(self) -> dict:
        return {
            "active_cooldowns": len(self._cooldowns),
            "total_affordances_generated": sum(
                len(h["affordances"]) for h in self._affordance_history
            ),
            "history_length": len(self._affordance_history),
            "current_pulse_id": self._current_pulse_id,
        }
