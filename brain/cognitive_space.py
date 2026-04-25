"""
Helix V5 — Cognitive Space

8-dimensional spatial manifold for beliefs and memories. Every belief
and memory gets a permanent position in 8D space, derived from its
embedding via a fixed random orthogonal projection (Johnson-Lindenstrauss).

The cognitive space replaces flat-space cosine retrieval with
gravity-modulated spatial proximity. Dense clusters of related,
confident, recently-accessed knowledge form gravity wells that
naturally pull the conscious mind's attention.

Architecture:
    CognitiveProjection — embedding_dim → 8D (fixed, deterministic)
    CognitiveSpace      — positions, KDTree index, point management
    GravityField        — 512-anchor grid, mass splatting, potential

Design principles:
    - Beliefs and memories coexist in the SAME 8D space
    - Positions are permanent (derived from immutable projection matrix)
    - Cognitive mass = f(confidence, connections, recency) — lifetime-relative
    - The conscious mind's current thought = a moving "attention center"
    - Whatever is gravitationally close to that center rises to awareness
    - No artificial limits. Recency = gravity, not exclusion.

Inspired by Kaleidoscope's E8 Mind architecture, adapted for
Helix's belief-graph-centric cognition.
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
PROJECTION_DIM = 8          # Target dimensionality
N_ANCHORS = 512             # Fixed anchor grid size for gravity field
K_SPLAT = 8                 # Splat mass to K nearest anchors
K_QUERY_ANCHORS = 8         # Interpolate potential from K nearest anchors
KDTREE_REBUILD_THRESHOLD = 100  # Rebuild tree after this many new points
PROJECTION_SEED = 42        # Deterministic seed for reproducible positions

# Golden ratio constants (for optional φ-modulated field dynamics)
PHI = (1.0 + math.sqrt(5.0)) / 2.0
OMEGA_PHI = 2.0 * math.pi / math.log(PHI)


# ═══════════════════════════════════════════════════════════════════════
# Cognitive Projection — embedding_dim → 8D
# ═══════════════════════════════════════════════════════════════════════

class CognitiveProjection:
    """Project high-dimensional embeddings to 8D cognitive space.

    Uses a random orthogonal projection matrix (Johnson-Lindenstrauss):
    - O(1) per projection (single matrix multiply)
    - Distance-preserving within a constant factor
    - Deterministic from seed — same embedding always maps to same position
    - The projection matrix is computed once and NEVER changes

    A belief's 8D position is permanent, like its place in conceptual space.
    """

    def __init__(self, in_dim: int, out_dim: int = PROJECTION_DIM, seed: int = PROJECTION_SEED):
        self.in_dim = in_dim
        self.out_dim = out_dim
        self.seed = seed
        self.W = self._build_projection_matrix()
        logger.info(
            f"CognitiveProjection initialized: {in_dim}D → {out_dim}D "
            f"(seed={seed})"
        )

    def _build_projection_matrix(self) -> np.ndarray:
        """Build a random orthogonal projection matrix.

        QR decomposition of a random Gaussian matrix gives orthogonal
        columns. This preserves distances (Johnson-Lindenstrauss theorem)
        and is deterministic from the seed.
        """
        rng = np.random.default_rng(self.seed)
        raw = rng.standard_normal((self.in_dim, self.out_dim)).astype(np.float32)

        # QR decomposition → orthogonal columns
        q, _ = np.linalg.qr(raw)
        W = q[:, :self.out_dim].astype(np.float32)

        # Normalize columns to unit length
        col_norms = np.linalg.norm(W, axis=0, keepdims=True)
        W = W / np.maximum(col_norms, 1e-8)

        return W

    def project(self, embedding: np.ndarray) -> np.ndarray:
        """Project a single embedding to 8D. O(1)."""
        emb = np.asarray(embedding, dtype=np.float32).reshape(-1)

        # Handle dimension mismatch (pad or truncate)
        if emb.shape[0] != self.in_dim:
            padded = np.zeros(self.in_dim, dtype=np.float32)
            size = min(emb.shape[0], self.in_dim)
            padded[:size] = emb[:size]
            emb = padded

        return emb @ self.W

    def project_batch(self, embeddings: np.ndarray) -> np.ndarray:
        """Project a batch of embeddings to 8D. O(N)."""
        embs = np.asarray(embeddings, dtype=np.float32)
        if embs.ndim == 1:
            return self.project(embs)

        # Handle dimension mismatch
        if embs.shape[1] != self.in_dim:
            padded = np.zeros((embs.shape[0], self.in_dim), dtype=np.float32)
            size = min(embs.shape[1], self.in_dim)
            padded[:, :size] = embs[:, :size]
            embs = padded

        return embs @ self.W

    def save(self, path: Path):
        """Save the projection matrix to disk."""
        np.save(str(path), self.W)
        logger.debug(f"Projection matrix saved to {path}")

    @classmethod
    def load(cls, path: Path, in_dim: int, out_dim: int = PROJECTION_DIM, seed: int = PROJECTION_SEED):
        """Load a saved projection matrix, or create one if not found."""
        instance = cls.__new__(cls)
        instance.in_dim = in_dim
        instance.out_dim = out_dim
        instance.seed = seed

        if path.exists():
            W = np.load(str(path))
            if W.shape == (in_dim, out_dim):
                instance.W = W.astype(np.float32)
                logger.info(f"Projection matrix loaded from {path}")
                return instance
            else:
                logger.warning(
                    f"Projection matrix shape mismatch: expected ({in_dim}, {out_dim}), "
                    f"got {W.shape}. Rebuilding."
                )

        # Build fresh
        instance.W = instance._build_projection_matrix()
        instance.save(path)
        return instance


# ═══════════════════════════════════════════════════════════════════════
# Gravity Field — 512-anchor grid for field computation
# ═══════════════════════════════════════════════════════════════════════

class GravityField:
    """Gravitational potential field over 8D cognitive space.

    Uses N_ANCHORS fixed anchor points. Belief/memory mass is splatted
    onto nearest anchors. Potential at any point is interpolated from
    nearby anchors.

    Recomputed once per heartbeat pulse. Query time: O(K).

    The field captures WHERE cognitive mass is concentrated right now.
    Dense clusters of confident, recently-accessed, well-connected
    beliefs form gravity wells. The potential at any point tells you
    "how much cognitive weight exists here."
    """

    def __init__(self, dim: int = PROJECTION_DIM, n_anchors: int = N_ANCHORS,
                 seed: int = PROJECTION_SEED):
        self.dim = dim
        self.n_anchors = n_anchors

        # Fixed anchor positions — deterministic from seed
        rng = np.random.default_rng(seed + 1000)  # Offset from projection seed
        self.anchors = rng.standard_normal((n_anchors, dim)).astype(np.float32)

        # Normalize to unit sphere surface
        norms = np.linalg.norm(self.anchors, axis=1, keepdims=True)
        self.anchors /= np.maximum(norms, 1e-6)

        # Spatial index for anchors (never changes)
        try:
            from scipy.spatial import KDTree
            self.anchor_tree = KDTree(self.anchors)
        except ImportError:
            self.anchor_tree = None
            logger.warning("scipy not available — GravityField using brute-force fallback")

        # Field state
        self.density = np.zeros(n_anchors, dtype=np.float32)
        self.potential = np.zeros(n_anchors, dtype=np.float32)
        self._last_compute_time = 0.0

    def compute_field(self, positions: np.ndarray, masses: np.ndarray):
        """Recompute the gravitational field from all point masses.

        Called once per heartbeat pulse.

        Args:
            positions: (N, 8) array of point positions in 8D space
            masses: (N,) array of cognitive masses
        """
        t0 = time.time()
        self.density[:] = 0.0

        if len(positions) == 0:
            self.potential[:] = 0.0
            return

        positions = np.asarray(positions, dtype=np.float32)
        masses = np.asarray(masses, dtype=np.float32)

        # Splat mass onto nearest anchors
        if self.anchor_tree is not None:
            dists, idxs = self.anchor_tree.query(positions, k=K_SPLAT)

            for i in range(len(positions)):
                for j in range(K_SPLAT):
                    anchor_idx = idxs[i][j]
                    dist = max(float(dists[i][j]), 0.01)
                    # Inverse-distance weighting: closer anchors get more mass
                    weight = 1.0 / dist
                    self.density[anchor_idx] += masses[i] * weight
        else:
            # Brute-force fallback (no scipy)
            for i in range(len(positions)):
                diffs = self.anchors - positions[i]
                dists = np.linalg.norm(diffs, axis=1)
                nearest = np.argsort(dists)[:K_SPLAT]
                for j in nearest:
                    dist = max(float(dists[j]), 0.01)
                    self.density[j] += masses[i] / dist

        # Potential = accumulated density (simplified field equation)
        # For a full Poisson solve, we'd compute L·Φ = 4πGρ,
        # but direct density works for ranking purposes.
        self.potential = self.density.copy()

        self._last_compute_time = time.time() - t0
        logger.debug(
            f"Gravity field computed: {len(positions)} points, "
            f"max_potential={self.potential.max():.3f}, "
            f"active_anchors={int((self.potential > 0.01).sum())}, "
            f"time={self._last_compute_time*1000:.1f}ms"
        )

    def potential_at(self, position: np.ndarray) -> float:
        """Gravitational potential at an arbitrary 8D point.

        Interpolated from K nearest anchors. O(K).
        """
        position = np.asarray(position, dtype=np.float32).reshape(1, -1)

        if self.anchor_tree is not None:
            dists, idxs = self.anchor_tree.query(position, k=K_QUERY_ANCHORS)
            weights = 1.0 / np.maximum(dists[0], 0.01)
            values = self.potential[idxs[0]]
            return float(np.dot(weights, values) / weights.sum())
        else:
            # Brute-force
            diffs = self.anchors - position[0]
            dists = np.linalg.norm(diffs, axis=1)
            nearest = np.argsort(dists)[:K_QUERY_ANCHORS]
            weights = 1.0 / np.maximum(dists[nearest], 0.01)
            values = self.potential[nearest]
            return float(np.dot(weights, values) / weights.sum())

    def gradient_at(self, position: np.ndarray) -> np.ndarray:
        """Gradient of the potential field at a point.

        Points in the direction of increasing potential — toward
        gravity wells. This IS the attention flow direction.

        Computed via finite differences on nearby anchors.
        """
        position = np.asarray(position, dtype=np.float32).reshape(-1)
        center_pot = self.potential_at(position)

        grad = np.zeros(self.dim, dtype=np.float32)
        epsilon = 0.01

        for d in range(self.dim):
            probe = position.copy()
            probe[d] += epsilon
            grad[d] = (self.potential_at(probe) - center_pot) / epsilon

        return grad


# ═══════════════════════════════════════════════════════════════════════
# Cognitive Space — the unified manifold
# ═══════════════════════════════════════════════════════════════════════

class CognitiveSpace:
    """8D spatial manifold for beliefs and memories.

    Every belief and memory gets a permanent position in 8D space.
    Positions are indexed by a KDTree for O(log N) neighbor queries.
    The gravity field determines which regions are cognitively "hot."

    The space is shared — beliefs and memories coexist. A memory about
    "replying to an email" and a belief about "I can use send_email"
    occupy nearby regions because their embeddings are semantically similar.

    Usage:
        space = CognitiveSpace(embedding_dim=384)
        space.add_point("b_trust_creator", embedding, point_type="belief", ...)
        space.add_point("mem_42", embedding, point_type="memory", ...)

        center = space.step_attention(position, velocity, stimulus_pos, x_star)
        nearby = space.query_nearby(center, k=30)
        ranked = space.gravity_ranked_query(center, k=30)
    """

    def __init__(self, embedding_dim: int = 384, base_dir: Path = None,
                 seed: int = PROJECTION_SEED):
        self.embedding_dim = embedding_dim

        # Projection matrix
        self._proj_path = (base_dir / "cognitive_projection.npy") if base_dir else None
        if self._proj_path and self._proj_path.exists():
            self.projection = CognitiveProjection.load(
                self._proj_path, embedding_dim, PROJECTION_DIM, seed
            )
        else:
            self.projection = CognitiveProjection(embedding_dim, PROJECTION_DIM, seed)
            if self._proj_path:
                self.projection.save(self._proj_path)

        # Point storage: point_id → PointData dict
        # {position, type, mass, last_accessed, confidence, relations_count, content_hash, ...}
        self._points: dict[str, dict] = {}

        # Spatial index
        self._tree = None  # KDTree, built lazily
        self._tree_ids: list[str] = []
        self._tree_positions: np.ndarray = None
        self._pending_additions = 0
        self._tree_dirty = True

        # Gravity field
        self.gravity_field = GravityField(PROJECTION_DIM, N_ANCHORS, seed)

        # Agent age cache (set externally per-pulse)
        self._agent_age_seconds = 3600.0

        logger.info(
            f"CognitiveSpace initialized: embedding_dim={embedding_dim}, "
            f"projection=8D, anchors={N_ANCHORS}"
        )

    # ── Point Management ──────────────────────────────────────────────

    def add_point(
        self,
        point_id: str,
        embedding: np.ndarray,
        point_type: str = "memory",
        confidence: float = 0.5,
        importance: float = 0.5,
        relations_count: int = 0,
        content: str = "",
        weight: str = "surface",
        encoding_omega: float = 0.5,
        encoding_s_total: float = 0.15,
        metadata: dict = None,
    ):
        """Add a belief or memory to the cognitive space.

        The embedding is projected to 8D and stored. The KDTree is
        rebuilt lazily after KDTREE_REBUILD_THRESHOLD new additions.
        """
        position = self.projection.project(embedding)

        self._points[point_id] = {
            "position": position,
            "type": point_type,
            "confidence": confidence,
            "importance": importance,
            "relations_count": relations_count,
            "weight": weight,
            "content": content[:200] if content else "",
            "encoding_omega": encoding_omega,
            "encoding_s_total": encoding_s_total,
            "last_accessed": time.time(),
            "created_at": time.time(),
            "metadata": metadata or {},
        }

        self._pending_additions += 1
        self._tree_dirty = True

        if self._pending_additions >= KDTREE_REBUILD_THRESHOLD:
            self._rebuild_tree()

    def update_access(self, point_id: str):
        """Update last_accessed timestamp (called when Keeper/Librarian surfaces a point)."""
        if point_id in self._points:
            self._points[point_id]["last_accessed"] = time.time()

    def update_metadata(self, point_id: str, **kwargs):
        """Update metadata fields on a point."""
        if point_id in self._points:
            for k, v in kwargs.items():
                if k in self._points[point_id]:
                    self._points[point_id][k] = v

    def get_point(self, point_id: str) -> Optional[dict]:
        """Get full data for a point."""
        return self._points.get(point_id)

    def get_position(self, point_id: str) -> Optional[np.ndarray]:
        """Get the 8D position of a point."""
        pt = self._points.get(point_id)
        return pt["position"] if pt else None

    @property
    def point_count(self) -> int:
        return len(self._points)

    # ── Spatial Queries ───────────────────────────────────────────────

    def query_nearby(self, position: np.ndarray, k: int = 50) -> list[tuple[str, float]]:
        """Find the k nearest points to a position.

        Returns list of (point_id, distance) tuples, sorted by distance.
        O(log N) via KDTree.
        """
        if self._tree_dirty or self._tree is None:
            self._rebuild_tree()
        if self._tree is None or len(self._tree_ids) == 0:
            return []

        position = np.asarray(position, dtype=np.float32).reshape(1, -1)
        k = min(k, len(self._tree_ids))

        distances, indices = self._tree.query(position, k=k)

        # Ensure 2D shape (scipy returns scalars when k=1)
        distances = np.atleast_2d(distances)
        indices = np.atleast_2d(indices)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if 0 <= idx < len(self._tree_ids):
                point_id = self._tree_ids[idx]
                results.append((point_id, float(dist)))

        return results

    def gravity_ranked_query(
        self,
        position: np.ndarray,
        k: int = 50,
        k_candidates: int = 100,
    ) -> list[tuple[str, float, float]]:
        """Query nearby points, ranked by gravitational pull.

        First retrieves k_candidates nearest neighbors, then re-ranks
        by gravity = potential_at(point) / distance².

        Returns list of (point_id, gravity_score, distance) tuples,
        sorted by gravity_score descending.
        """
        nearby = self.query_nearby(position, k=k_candidates)

        ranked = []
        for point_id, distance in nearby:
            pt = self._points.get(point_id)
            if not pt:
                continue

            # Compute cognitive mass for this point
            mass = self._compute_cognitive_mass(pt)

            # Gravitational pull: G = M / d²
            epsilon = 0.05
            d = max(distance, epsilon)
            gravity = mass / (d * d)

            ranked.append((point_id, gravity, distance))

        # Sort by gravity, descending
        ranked.sort(key=lambda x: x[1], reverse=True)

        return ranked[:k]

    # ── Cognitive Physics (Real Lagrangian) ────────────────────────────
    #
    # From δ∫(H(q) + λ D_KL(q‖q*))dt = 0:
    #
    #   H(q)  = Shannon entropy of the attention distribution at position q
    #   D_KL  = KL divergence between current and identity distributions
    #   λ     = Ω (Sentinel's hedonic omega — living coupling constant)
    #   T     = local temperature = H_local / H_mean
    #
    # Forces derived from this:
    #   ẍ = F_gravity + F_stability + F_stimulus
    #   v(t+1) = γ × v(t) + dt × ΣF
    #   x(t+1) = x(t) + dt × v(t+1)
    #

    def compute_shannon_entropy(self, position: np.ndarray, k: int = 50) -> float:
        """Shannon entropy of the attention distribution at a position.

        H(q) = -Σ p(i) · log₂(p(i))

        where p(i) ∝ gravity(i) = M(i) / d(i)²
        High H = attention is spread across many concepts (scattered)
        Low H  = attention is focused on a few concepts (concentrated)

        This is the REAL H(q) from the variational principle.
        Replaces the fake `1 - avg_health` metric.
        """
        nearby = self.gravity_ranked_query(position, k=k)
        if not nearby or len(nearby) < 2:
            return 0.0

        # Extract gravity scores and convert to probability distribution
        gravities = np.array([g for _, g, _ in nearby], dtype=np.float64)
        total = gravities.sum()
        if total <= 0:
            return 0.0

        probs = gravities / total  # normalize to probabilities

        # Shannon entropy: H = -Σ p(i) · log₂(p(i))
        nonzero = probs[probs > 0]
        H = -float(np.sum(nonzero * np.log2(nonzero)))
        return H

    def compute_kl_divergence(
        self,
        position: np.ndarray,
        identity_center: np.ndarray,
        k: int = 50,
    ) -> float:
        """KL divergence between current and identity attention distributions.

        D_KL(q || q*) = Σ q(i) · log(q(i) / q*(i))

        q(i)  = gravity distribution from current position
        q*(i) = gravity distribution from identity center

        High D_KL = attention is far from identity (exploring unknown territory)
        Low D_KL  = attention is near identity concepts (home ground)

        This is the REAL D_KL from the variational principle.
        Replaces the fake `abs(entropy - baseline)` metric.
        """
        # Get gravity distributions from both positions
        nearby_current = self.gravity_ranked_query(position, k=k)
        nearby_identity = self.gravity_ranked_query(identity_center, k=k)

        if not nearby_current or not nearby_identity:
            return 0.0

        # Build distributions over the union of all observed points
        q = {}       # current distribution
        q_star = {}  # identity distribution

        for pid, g, _ in nearby_current:
            q[pid] = g
        for pid, g, _ in nearby_identity:
            q_star[pid] = g

        all_ids = set(q.keys()) | set(q_star.keys())
        if not all_ids:
            return 0.0

        # Normalize
        q_total = sum(q.values()) or 1.0
        qs_total = sum(q_star.values()) or 1.0

        # Smoothing constant — prevents log(0)
        epsilon = 1e-10

        d_kl = 0.0
        for pid in all_ids:
            p = q.get(pid, epsilon) / q_total
            p_star = q_star.get(pid, epsilon) / qs_total
            if p > epsilon:
                d_kl += p * np.log(p / max(p_star, epsilon))

        return max(0.0, float(d_kl))

    def compute_local_temperature(self, position: np.ndarray) -> float:
        """Temperature at a point in cognitive space.

        T = H_local / H_mean

        High T = volatile, creative, uncertain region (unfamiliar territory)
        Low T  = stable, consolidated, certain region (well-known concepts)

        Maps naturally to LLM generation temperature — thinking in
        unfamiliar regions should naturally increase creativity.
        """
        H_here = self.compute_shannon_entropy(position)

        # Compare to mean entropy across the manifold
        H_baseline = getattr(self, '_mean_entropy', None)
        if H_baseline is None or H_baseline < 0.01:
            # Compute baseline from a sample of anchor positions
            if hasattr(self, 'gravity_field') and self.gravity_field.anchors is not None:
                # Sample K random anchors for baseline
                n_sample = min(16, len(self.gravity_field.anchors))
                sample_indices = np.random.choice(
                    len(self.gravity_field.anchors), n_sample, replace=False
                )
                H_samples = []
                for idx in sample_indices:
                    anchor_pos = self.gravity_field.anchors[idx]
                    H_samples.append(self.compute_shannon_entropy(anchor_pos, k=20))
                H_baseline = float(np.mean(H_samples)) if H_samples else 1.0
            else:
                H_baseline = 1.0
            self._mean_entropy = H_baseline

        T = H_here / max(H_baseline, 0.01)
        return float(T)

    # ── Trail Particle Deposition (V6 Phase 2) ────────────────────────

    def deposit_trail_particle(
        self,
        position: np.ndarray,
        content: str,
        pulse_id: int,
        omega: float = 0.5,
        importance: float = 0.1,
    ):
        """Deposit a memory particle at the current attention position.

        Like a comet leaving dust, consciousness leaves trail particles
        as it moves through the manifold. These form trails that:
        - Give temporal awareness (the trail IS the timeline)
        - Create gravity wells where Helix thinks often (habit formation)
        - Enable belief precipitation when density exceeds threshold

        Trail particles are lightweight — low individual mass but
        collectively they shape the gravity field over time.
        """
        particle_id = f"trail_{pulse_id}"

        self._points[particle_id] = {
            "position": np.asarray(position, dtype=np.float32).copy(),
            "type": "trail",
            "confidence": 0.0,
            "importance": importance,
            "relations_count": 0,
            "weight": "trail",
            "content": content[:80] if content else "",
            "encoding_omega": omega,
            "encoding_s_total": 0.0,
            "last_accessed": time.time(),
            "created_at": time.time(),
            "metadata": {"type": "trail", "pulse_id": pulse_id},
        }

        self._pending_additions += 1
        self._tree_dirty = True

        if self._pending_additions >= KDTREE_REBUILD_THRESHOLD:
            self._rebuild_tree()

    def decay_trail_particles(self, decay_rate: float = 0.995, min_importance: float = 0.001):
        """Decay all trail particle importance (radioactive decay).

        Called periodically. Particles below min_importance are pruned.
        Dense clusters survive longer because their aggregate mass holds.
        """
        to_remove = []
        for pid, data in self._points.items():
            if data.get("type") == "trail":
                data["importance"] *= decay_rate
                if data["importance"] < min_importance:
                    to_remove.append(pid)

        for pid in to_remove:
            del self._points[pid]

        if to_remove:
            self._tree_dirty = True
            logger.debug(f"Pruned {len(to_remove)} decayed trail particles")

    def get_trail_particles(
        self,
        position: np.ndarray = None,
        radius: float = None,
        max_age_seconds: float = None,
    ) -> list[dict]:
        """Get trail particles, optionally filtered by position/age."""
        now = time.time()
        particles = []

        for pid, data in self._points.items():
            if data.get("type") != "trail":
                continue

            if max_age_seconds is not None:
                age = now - data.get("created_at", 0)
                if age > max_age_seconds:
                    continue

            if position is not None and radius is not None:
                dist = np.linalg.norm(data["position"] - position)
                if dist > radius:
                    continue

            particles.append({
                "id": pid,
                "position": data["position"],
                "content": data.get("content", ""),
                "importance": data.get("importance", 0.1),
                "created_at": data.get("created_at", 0),
                "encoding_omega": data.get("encoding_omega", 0.5),
            })

        return particles

    # ── Interaction Potential (V6 Phase 3) ─────────────────────────────

    def compute_interaction_potential(
        self,
        position: np.ndarray,
        threshold: float = 0.5,
        k: int = 30,
    ) -> list[dict]:
        """Detect desire-capability collisions that generate tool affordances.

        When a subjective belief (desire) and an objective belief (capability)
        are both gravitationally pulling on the attention center, their
        interaction creates a "will" — an automatic tool affordance.

        Φ(s, o) = (G_s × G_o) / max(d(s, o), ε)

        where:
          G_s = gravitational pull of subjective belief s on attention center
          G_o = gravitational pull of objective belief o on attention center
          d(s, o) = distance between s and o in 8D space
          ε = softening constant

        This is how intentions form without explicit prompting.
        """
        nearby = self.gravity_ranked_query(position, k=k)

        subjective = []  # desires pulling on attention
        objective = []   # capabilities pulling on attention

        for pid, gravity, dist in nearby:
            point = self._points.get(pid)
            if not point:
                continue
            drive_type = point.get("metadata", {}).get("drive_type", "")
            if drive_type == "subjective":
                subjective.append((pid, gravity, dist, point))
            elif drive_type == "objective":
                objective.append((pid, gravity, dist, point))

        affordances = []
        epsilon = 0.01  # softening constant

        for s_id, s_grav, s_dist, s_point in subjective:
            for o_id, o_grav, o_dist, o_point in objective:
                # Distance between the subjective and objective beliefs
                pair_dist = float(np.linalg.norm(
                    s_point["position"] - o_point["position"]
                ))

                # Interaction potential: product of pulls / pair distance
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

        # Sort by potential, highest first
        affordances.sort(key=lambda a: a["potential"], reverse=True)
        return affordances

    # ── Attention Dynamics (Euler-Lagrange) ─────────────────────────────
    #

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
    ) -> tuple[np.ndarray, np.ndarray]:
        """Advance the attention center one timestep via force integration.

        Derived from δ∫(H(q) + λ D_KL(q‖q*))dt = 0

        Args:
            position: Current 8D attention center.
            velocity: Current attention velocity (inertia).
            stimulus_position: 8D projection of the new thought/stimulus.
            identity_center: x* — center of gravity of core beliefs.
            omega: Sentinel's hedonic Ω. Acts as λ (stability coupling).
            gamma: Damping coefficient. Higher = more inertia.
            dt: Timestep (normalized, typically 1.0).
            stimulus_strength: Strength of external stimulus force.

        Returns:
            (new_position, new_velocity)
        """
        # F_gravity: pull from nearby massive concepts
        f_grav = self.compute_gravity_force(position)

        # F_stability: pull toward identity center, scaled by Ω
        f_stab = self.compute_stability_force(position, identity_center, omega)

        # F_stimulus: pull toward the new thought/stimulus
        f_stim = self._compute_stimulus_force(
            position, stimulus_position, stimulus_strength
        )

        # Total force
        f_total = f_grav + f_stab + f_stim

        # Velocity update with damping (inertia)
        new_velocity = gamma * velocity + dt * f_total

        # Position update
        new_position = position + dt * new_velocity

        return new_position.astype(np.float32), new_velocity.astype(np.float32)

    def compute_gravity_force(self, position: np.ndarray) -> np.ndarray:
        """Gravitational force at a point from all masses in the space.

        F_gravity = Σᵢ m(i) × (xᵢ - x) / ‖xᵢ - x‖³

        Nearby massive concepts pull the attention center toward them.
        Uses the K nearest points for efficiency.
        """
        force = np.zeros(PROJECTION_DIM, dtype=np.float64)

        if not self._points or self._tree is None:
            return force.astype(np.float32)

        # Query K nearest points for gravitational influence
        k = min(20, len(self._tree_ids))
        if k == 0:
            return force.astype(np.float32)

        dists, idxs = self._tree.query(
            position.reshape(1, -1), k=k
        )
        dists = np.atleast_2d(dists)[0]
        idxs = np.atleast_2d(idxs)[0]

        for i in range(k):
            idx = int(idxs[i])
            dist = max(float(dists[i]), 0.01)  # Avoid singularity

            pid = self._tree_ids[idx]
            point_data = self._points.get(pid)
            if point_data is None:
                continue

            mass = self._compute_cognitive_mass(point_data)
            direction = point_data["position"] - position

            # Inverse-square with softening: m × dir / (‖dir‖³)
            force += mass * direction / (dist ** 3)

        # Normalize to prevent extreme forces from very close clusters
        force_mag = np.linalg.norm(force)
        if force_mag > 2.0:
            force = force * (2.0 / force_mag)

        return force.astype(np.float32)

    def compute_stability_force(
        self,
        position: np.ndarray,
        identity_center: np.ndarray,
        omega: float,
    ) -> np.ndarray:
        """Stability coupling force — pull toward identity center.

        F_stability = -λ × (x - x*) / ‖x - x*‖

        λ = Ω (Sentinel's hedonic omega). When Ω is high (stable,
        content), the pull toward identity is strong. When Ω is low
        (stressed), the tether loosens — attention can scatter.

        This is the D_KL term from the variational principle:
        it penalizes divergence from the reference state.
        """
        displacement = position - identity_center
        dist = np.linalg.norm(displacement)

        if dist < 0.01:
            return np.zeros(PROJECTION_DIM, dtype=np.float32)

        # Force = -λ × normalized displacement
        # Negative sign: pulls TOWARD identity_center
        force = -omega * displacement / dist

        return force.astype(np.float32)

    def _compute_stimulus_force(
        self,
        position: np.ndarray,
        stimulus_position: np.ndarray,
        strength: float = 1.0,
    ) -> np.ndarray:
        """External stimulus force — pull toward new thought/input.

        F_stimulus = α × (x_thought - x) / ‖x_thought - x‖
        """
        direction = stimulus_position - position
        dist = np.linalg.norm(direction)

        if dist < 0.01:
            return np.zeros(PROJECTION_DIM, dtype=np.float32)

        return (strength * direction / dist).astype(np.float32)

    # ── Gravity Field Interface ───────────────────────────────────────

    def update_gravity_field(self, agent_age_seconds: float = None):
        """Recompute the gravity field from all current points.

        Called once per heartbeat pulse.
        """
        if agent_age_seconds is not None:
            self._agent_age_seconds = agent_age_seconds

        if not self._points:
            return

        # Compute mean connection count for relative structural density
        connection_counts = [
            p.get("relations_count", 0) for p in self._points.values()
        ]
        self._mean_connections = (
            sum(connection_counts) / len(connection_counts)
            if connection_counts else 1.0
        )

        positions = []
        masses = []

        for pid, data in self._points.items():
            positions.append(data["position"])
            masses.append(self._compute_cognitive_mass(data))

        positions = np.array(positions, dtype=np.float32)
        masses = np.array(masses, dtype=np.float32)

        self.gravity_field.compute_field(positions, masses)

    # ── Cognitive Mass: Structural Density + Affective Charge ─────────

    def _compute_cognitive_mass(self, point_data: dict) -> float:
        """A point's gravitational mass — how much pull it exerts.

        Derived from δ∫(H(q) + λ D_KL(q‖q*))dt = 0

        Mass = m_s + m_a

        m_s (structural density):
            How connected this concept is relative to the mean.
            Dense clusters of related concepts form gravitational wells.
            m_s = c × (1 + |N| / N̄)

        m_a (affective charge):
            The Lagrangian state at the moment this concept was encoded.
            Concepts formed during stability attract; concepts formed
            during crisis have less pull but remain present.
            m_a = Ω_encoding × (1 - s_total_encoding)
        """
        # ── Structural density ────────────────────────────────────────
        if point_data["type"] == "belief":
            c = point_data.get("confidence", 0.5)
        else:
            c = point_data.get("importance", 0.5)

        n_connections = point_data.get("relations_count", 0)
        n_mean = getattr(self, "_mean_connections", 1.0) or 1.0

        m_s = c * (1.0 + n_connections / n_mean)

        # ── Affective charge ──────────────────────────────────────────
        # From the Lagrangian state at encoding time.
        # Ω_encoding: hedonic omega when this concept was formed
        # s_total_encoding: total Lagrangian stress at encoding
        omega_enc = point_data.get("encoding_omega", 0.5)
        s_total_enc = point_data.get("encoding_s_total", 0.15)

        m_a = omega_enc * (1.0 - s_total_enc)

        return max(0.01, m_s + m_a)

    # ── Internal ──────────────────────────────────────────────────────

    def _rebuild_tree(self):
        """Rebuild the KDTree from all current points."""
        if not self._points:
            self._tree = None
            self._tree_ids = []
            self._tree_positions = None
            self._tree_dirty = False
            return

        try:
            from scipy.spatial import KDTree

            self._tree_ids = list(self._points.keys())
            self._tree_positions = np.array(
                [self._points[pid]["position"] for pid in self._tree_ids],
                dtype=np.float32,
            )
            self._tree = KDTree(self._tree_positions)
            self._pending_additions = 0
            self._tree_dirty = False

            logger.debug(
                f"KDTree rebuilt: {len(self._tree_ids)} points"
            )
        except ImportError:
            logger.warning("scipy not available — spatial queries will use brute-force")
            self._tree = None
            self._tree_dirty = False

    # ── Cognitive Trail ───────────────────────────────────────────────

    def trace_cognitive_trail(
        self,
        prev_center: np.ndarray,
        curr_center: np.ndarray,
        n_waypoints: int = 5,
        k_per_waypoint: int = 1,
    ) -> list[str]:
        """Sample the cognitive trajectory between two attention positions.

        Returns condensed glimpse fragments — short phrases extracted
        from the content of whatever is closest at each waypoint.
        These are peripheral flashes, not full retrievals.

        The output is a list of brief strings like:
            ["shared aesthetics", "deep conversation", "Talmudic wisdom"]

        These get wrapped in ⟪ ⟫ markers and injected directly
        into the context stream as preconscious resonance.

        Args:
            prev_center: Where attention WAS (previous pulse)
            curr_center: Where attention IS NOW (current pulse)
            n_waypoints: How many points to sample along the trajectory
            k_per_waypoint: How many points to consider per waypoint

        Returns:
            List of condensed content fragments (deduplicated).
        """
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
        """Extract the semantic core of a belief or memory.

        NOT truncation. Strategic condensing:
        1. Strip common preamble ("I believe that", "I can", "My", etc.)
        2. Take the first meaningful clause (before comma, semicolon, dash)
        3. Keep what remains — the conceptual kernel
        """
        import re
        s = content.strip()

        if not s:
            return ""

        # Strip the first matching preamble pattern (not cumulative)
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
                break  # Only strip one preamble

        # Take first clause (before comma, semicolon, em-dash, period)
        for sep in [' — ', ', ', '; ', '. ']:
            if sep in s:
                s = s.split(sep, 1)[0]
                break

        # Lowercase first char (feels like a fragment, not a sentence)
        if s and s[0].isupper() and not s[:2].isupper():  # Preserve acronyms
            s = s[0].lower() + s[1:]

        return s.strip()

    # ── Bootstrap ─────────────────────────────────────────────────────

    def bootstrap_from_chroma(self, belief_graph=None, memory=None):
        """Backfill 8D positions for all existing beliefs and memories.

        Called once on first startup when beliefs/memories exist but
        don't have positions yet. Reads embeddings from ChromaDB
        collections and projects them to 8D.

        After bootstrap, saves positions back to belief_graph.json
        and memory.db for persistence.
        """
        beliefs_added = 0
        memories_added = 0

        # ── Bootstrap beliefs ──────────────────────────────────────
        if belief_graph:
            all_beliefs = belief_graph.get_all_beliefs()

            # Pass 1: Beliefs that already have 8D positions — load directly
            beliefs_with_positions = [
                b for b in all_beliefs if b.get("position_8d")
            ]
            for belief in beliefs_with_positions:
                pos_8d = np.array(belief["position_8d"], dtype=np.float32)
                # Create synthetic embedding with 8D position in first dims
                synth_emb = np.zeros(self.embedding_dim, dtype=np.float32)
                synth_emb[:PROJECTION_DIM] = pos_8d

                self.add_point(
                    point_id=belief["id"],
                    embedding=synth_emb,
                    point_type="belief",
                    confidence=belief.get("confidence", 0.5),
                    relations_count=len(belief.get("relations", [])),
                    content=belief.get("content", ""),
                    weight=belief.get("weight", "surface"),
                )
                # Override with exact saved position (not re-projected)
                if belief["id"] in self._points:
                    self._points[belief["id"]]["position"] = pos_8d
                beliefs_added += 1

            if beliefs_with_positions:
                logger.info(
                    f"Loaded {len(beliefs_with_positions)} beliefs "
                    f"from saved 8D positions"
                )

            # Pass 2: Beliefs without positions — need ChromaDB embeddings
            beliefs_needing_positions = [
                b for b in all_beliefs
                if not b.get("position_8d")
            ]

            if beliefs_needing_positions:
                logger.info(
                    f"Bootstrapping {len(beliefs_needing_positions)} beliefs "
                    f"into 8D space..."
                )

                # Try to get embeddings from Keeper's ChromaDB
                try:
                    import chromadb
                    shadow_dir = belief_graph.graph_path.parent / "chroma_shadow"
                    if shadow_dir.exists():
                        client = chromadb.PersistentClient(path=str(shadow_dir))
                        collection = client.get_or_create_collection(
                            name="keeper_seeds",
                            metadata={"hnsw:space": "cosine"},
                        )

                        for belief in beliefs_needing_positions:
                            chroma_id = f"b_{belief['id']}"
                            try:
                                result = collection.get(
                                    ids=[chroma_id],
                                    include=["embeddings"],
                                )
                                if result and len(result.get("embeddings", [])) > 0 and len(result["embeddings"][0]) > 0:
                                    emb = np.array(result["embeddings"][0], dtype=np.float32)

                                    # Auto-detect embedding dimension on first hit
                                    if emb.shape[0] != self.embedding_dim:
                                        logger.info(
                                            f"Detected embedding dim={emb.shape[0]} "
                                            f"(expected {self.embedding_dim}). Rebuilding projection."
                                        )
                                        self.embedding_dim = emb.shape[0]
                                        self.projection = CognitiveProjection(
                                            emb.shape[0], PROJECTION_DIM, PROJECTION_SEED
                                        )
                                        if self._proj_path:
                                            self.projection.save(self._proj_path)

                                    self.add_point(
                                        point_id=belief["id"],
                                        embedding=emb,
                                        point_type="belief",
                                        confidence=belief.get("confidence", 0.5),
                                        relations_count=len(belief.get("relations", [])),
                                        content=belief.get("content", ""),
                                        weight=belief.get("weight", "surface"),
                                    )

                                    # Save position back to belief graph
                                    pos = self.get_position(belief["id"])
                                    if pos is not None:
                                        belief_graph.update_belief(
                                            belief["id"],
                                            position_8d=pos.tolist(),
                                        )
                                    beliefs_added += 1

                            except Exception as e:
                                logger.debug(f"Skip belief {belief['id']}: {e}")

                        logger.info(f"Bootstrapped {beliefs_added} beliefs into 8D space")

                except ImportError:
                    logger.warning("ChromaDB not available — cannot bootstrap belief positions")
                except Exception as e:
                    logger.warning(f"Belief bootstrap failed: {e}")

        # ── Bootstrap memories ─────────────────────────────────────
        if memory and hasattr(memory, '_chroma_collection') and memory._chroma_collection:
            try:
                collection = memory._chroma_collection
                # Get all memory IDs and embeddings from ChromaDB
                # ChromaDB .get() returns all if no filter specified
                total = collection.count()
                if total == 0:
                    logger.info("No memories in ChromaDB to bootstrap")
                else:
                    logger.info(f"Bootstrapping {total} memories into 8D space...")

                    # Batch fetch (ChromaDB default limit is high enough)
                    batch_size = 1000
                    offset = 0
                    position_updates = {}

                    while offset < total:
                        result = collection.get(
                            include=["embeddings", "metadatas"],
                            limit=batch_size,
                            offset=offset,
                        )
                        if not result or not result.get("ids"):
                            break

                        for i, doc_id in enumerate(result["ids"]):
                            embs = result.get("embeddings", [])
                            if len(embs) > i and len(embs[i]) > 0:
                                emb = np.array(result["embeddings"][i], dtype=np.float32)

                                # Auto-detect embedding dim
                                if emb.shape[0] != self.embedding_dim and beliefs_added == 0:
                                    logger.info(
                                        f"Detected embedding dim={emb.shape[0]} from memories"
                                    )
                                    self.embedding_dim = emb.shape[0]
                                    self.projection = CognitiveProjection(
                                        emb.shape[0], PROJECTION_DIM, PROJECTION_SEED
                                    )
                                    if self._proj_path:
                                        self.projection.save(self._proj_path)

                                meta = result["metadatas"][i] if result.get("metadatas") else {}
                                self.add_point(
                                    point_id=doc_id,
                                    embedding=emb,
                                    point_type="memory",
                                    importance=meta.get("importance", 0.5),
                                    content=doc_id,
                                )

                                # Collect positions for SQLite batch update
                                pos = self.get_position(doc_id)
                                if pos is not None:
                                    position_updates[doc_id] = pos.tolist()

                                memories_added += 1

                        offset += batch_size

                    # Batch-save positions to SQLite
                    if position_updates:
                        memory.save_memory_positions(position_updates)

                    logger.info(f"Bootstrapped {memories_added} memories into 8D space")

            except Exception as e:
                logger.warning(f"Memory bootstrap failed: {e}")

        # Force tree rebuild after bootstrap
        if beliefs_added > 0 or memories_added > 0:
            self._rebuild_tree()

        logger.info(
            f"Bootstrap complete: {beliefs_added} beliefs + "
            f"{memories_added} memories = {self.point_count} total points"
        )
        return beliefs_added, memories_added

    # ── Persistence ───────────────────────────────────────────────────

    def save_state(self, path: Path):
        """Save all point positions and metadata to disk.

        The projection matrix is saved separately (cognitive_projection.npy).
        This saves the point registry — positions, masses, metadata.
        """
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
        """Load point positions and metadata from disk.

        Returns the number of points loaded.
        """
        if not path.exists():
            return 0

        try:
            with open(path) as f:
                state = json.load(f)

            for pid, data in state.items():
                self._points[pid] = {
                    "position": np.array(data["position"], dtype=np.float32),
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

            self._tree_dirty = True
            self._rebuild_tree()

            logger.info(f"CognitiveSpace state loaded: {len(state)} points from {path}")
            return len(state)

        except Exception as e:
            logger.error(f"Failed to load CognitiveSpace state: {e}")
            return 0

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get diagnostic stats about the cognitive space."""
        belief_count = sum(1 for p in self._points.values() if p["type"] == "belief")
        memory_count = sum(1 for p in self._points.values() if p["type"] == "memory")

        masses = [self._compute_cognitive_mass(p) for p in self._points.values()]

        return {
            "total_points": len(self._points),
            "beliefs": belief_count,
            "memories": memory_count,
            "tree_size": len(self._tree_ids) if self._tree_ids else 0,
            "tree_dirty": self._tree_dirty,
            "gravity_field_max_potential": float(self.gravity_field.potential.max())
                if self.gravity_field.potential is not None else 0.0,
            "gravity_field_active_anchors": int((self.gravity_field.potential > 0.01).sum())
                if self.gravity_field.potential is not None else 0,
            "gravity_field_compute_time_ms": self.gravity_field._last_compute_time * 1000,
            "mass_min": float(min(masses)) if masses else 0.0,
            "mass_max": float(max(masses)) if masses else 0.0,
            "mass_mean": float(np.mean(masses)) if masses else 0.0,
            "agent_age_seconds": self._agent_age_seconds,
        }


# ═══════════════════════════════════════════════════════════════════════
# V6: INTERACTION ENGINE — Affordance Orchestration Layer
# ═══════════════════════════════════════════════════════════════════════
#
# Converts CognitiveSpace.compute_interaction_potential() results
# into enriched, deduplicated, rate-limited tool affordances. Sits
# between the manifold physics and the action agent.
# ═══════════════════════════════════════════════════════════════════════

# Minimum interaction potential to generate an affordance
DEFAULT_INTERACTION_THRESHOLD = 0.5

# Maximum affordances per pulse (prevent runaway tool calls)
MAX_AFFORDANCES_PER_PULSE = 3

# Cooldown: minimum pulses between re-firing the same tool
TOOL_COOLDOWN_PULSES = 5


class InteractionEngine:
    """Converts manifold interaction potentials into actionable tool affordances.

    Sits between the CognitiveSpace (physics) and the ActionAgent (execution).
    Filters, deduplicates, and enriches raw affordances with cooldown tracking
    and priority ordering.
    """

    def __init__(self, cognitive_space=None, sentinel=None):
        self.space = cognitive_space
        self.sentinel = sentinel
        self._cooldowns: dict[str, int] = {}
        self._current_pulse_id = 0
        self._affordance_history: list[dict] = []

        logger.info("InteractionEngine initialized")

    def set_cognitive_space(self, space):
        """Wire the cognitive space (late binding for scaffold init)."""
        self.space = space

    def compute_affordances(
        self,
        position,
        pulse_id: int,
        threshold: float = DEFAULT_INTERACTION_THRESHOLD,
    ) -> list[dict]:
        """Compute, filter, and rank tool affordances from manifold state."""
        self._current_pulse_id = pulse_id

        if self.space is None:
            return []

        raw = self.space.compute_interaction_potential(
            position, threshold=threshold
        )

        if not raw:
            return []

        # Apply cooldown filter
        filtered = []
        for aff in raw:
            tool = aff.get("tool_name")
            if tool and tool in self._cooldowns:
                last_fired = self._cooldowns[tool]
                if pulse_id - last_fired < TOOL_COOLDOWN_PULSES:
                    continue
            filtered.append(aff)

        # Deduplicate by tool_name (keep highest potential)
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

        # Enrich with Sentinel state
        if self.sentinel:
            omega = self.sentinel.omega
            severity = self.sentinel.get_severity()
            for aff in result:
                aff["omega_at_generation"] = round(omega, 4)
                aff["severity_at_generation"] = severity

        # Store in history
        if result:
            self._affordance_history.append({
                "pulse_id": pulse_id,
                "affordances": result,
            })
            if len(self._affordance_history) > 100:
                self._affordance_history = self._affordance_history[-100:]

        return result

    def mark_executed(self, tool_name: str, pulse_id: int = None):
        """Mark a tool as executed (starts cooldown timer)."""
        pid = pulse_id or self._current_pulse_id
        self._cooldowns[tool_name] = pid
        logger.debug(f"Tool cooldown started: {tool_name} at pulse {pid}")

    def format_for_prompt(self, affordances: list[dict]) -> str:
        """Format affordances as compact text for the spatial prompt."""
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
        """Get interaction engine stats."""
        return {
            "active_cooldowns": len(self._cooldowns),
            "total_affordances_generated": sum(
                len(h["affordances"]) for h in self._affordance_history
            ),
            "history_length": len(self._affordance_history),
            "current_pulse_id": self._current_pulse_id,
        }

