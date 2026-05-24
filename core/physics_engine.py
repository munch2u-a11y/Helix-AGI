"""
Helix — Spatial Physics Engine (Wrapper)

Thin wrapper around SpatialMind that preserves the external API used by
pulse_loop.py, preconscious.py, and dream_engine.py.

Internally delegates to SpatialMind which owns:
  - Single CognitiveSpace (belief field, 384D native)
  - Numpy/FAISS spatial queries
  - On-demand gravity computation (no pre-computed anchor grid)
  - Real Shannon entropy, KL divergence, local temperature
  - Euler-Lagrange attention dynamics with force integration

Previous implementation (8D projected, dual-space) saved to:
  previous_versions/physics_engine_pre_384d.txt
"""

import re
import time
import math
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any

import numpy as np

from core.cognitive_space import CognitiveSpace, SPATIAL_DIM
from core.spatial_mind import SpatialMind

logger = logging.getLogger("helix.core.physics_engine")

# ── Constants ────────────────────────────────────────────────────────
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


class PhysicsEngine:
    """Helix's spatial physics engine.

    Wraps SpatialMind to provide the external API that pulse_loop,
    preconscious, and dream_engine depend on.

    Key change: no projection step. embed() returns native 384D.
    Single belief space — memories not spatially indexed.
    """

    def __init__(self, data_dir: str = None, gravity_constant: float = 0.1):
        self.G = gravity_constant
        self.data_dir = Path(data_dir) if data_dir else None
        if self.data_dir:
            self.data_dir.mkdir(parents=True, exist_ok=True)

        # ── SpatialMind (single 384D belief space) ──
        self.spatial_mind = SpatialMind(
            embedding_dim=EMBEDDING_DIM,
            base_dir=self.data_dir,
        )

        # ── Embedder (lazy-loaded) ──
        self._embedder = None

        # ── Pulse counter ──
        self._pulse_count = 0

        # ── Trail flashes ──
        self.last_flashes: List[str] = []

        # ── Load persisted state ──
        self._load_attention()

        logger.info("PhysicsEngine initialized (384D native manifold via SpatialMind)")

    # ── Properties ────────────────────────────────────────────────────

    @property
    def attention_center(self) -> np.ndarray:
        return self.spatial_mind.attention_center

    @attention_center.setter
    def attention_center(self, value):
        self.spatial_mind.attention_center = value

    @property
    def prev_center(self) -> Optional[np.ndarray]:
        return self.spatial_mind.prev_center

    @property
    def _gamma(self) -> float:
        return self.spatial_mind._gamma

    @_gamma.setter
    def _gamma(self, value):
        self.spatial_mind._gamma = value

    @property
    def _velocity(self) -> np.ndarray:
        return self.spatial_mind._velocity

    # ── Embedder ──────────────────────────────────────────────────────

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
                self._embedder = DefaultEmbeddingFunction()
                logger.info("Embedder loaded (all-MiniLM-L6-v2, CPU)")
            except Exception as e:
                logger.warning(f"Embedder init failed: {e}")
        return self._embedder

    def embed_text(self, text: str) -> np.ndarray:
        """Embed text → 384D vector."""
        embedder = self._get_embedder()
        if embedder is None:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)
        try:
            result = embedder([text])
            return np.array(result[0], dtype=np.float32)
        except Exception as e:
            logger.debug(f"Embedding failed: {e}")
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

    def embed(self, text: str) -> np.ndarray:
        """Text → 384D embedding. Native position, no projection."""
        return self.embed_text(text)

    def embed_and_project(self, text: str) -> np.ndarray:
        """Backward-compat alias for embed(). No projection in 384D."""
        return self.embed_text(text)

    # ── Pulse Step ────────────────────────────────────────────────────

    def step_pulse(
        self,
        thought_text: str,
        incoming_text: str = None,
        omega: float = 0.5,
        cluster_centroid: "np.ndarray | None" = None,
    ):
        """Advance the spatial mind one pulse."""
        self._pulse_count += 1

        if self.spatial_mind.sentinel:
            pass
        else:
            class _OmegaProxy:
                def __init__(self, val):
                    self.omega = val
            self.spatial_mind.sentinel = _OmegaProxy(omega)
            self.spatial_mind._temp_sentinel = True

        thought_emb = self.embed_text(thought_text) if thought_text else np.zeros(EMBEDDING_DIM, dtype=np.float32)
        incoming_emb = self.embed_text(incoming_text) if incoming_text else None

        context = self.spatial_mind.pulse(
            thought_embedding=thought_emb,
            incoming_embedding=incoming_emb,
            agent_age_seconds=3600.0,
            cluster_centroid=cluster_centroid,
        )

        if getattr(self.spatial_mind, '_temp_sentinel', False):
            self.spatial_mind.sentinel = None
            self.spatial_mind._temp_sentinel = False

        self.last_flashes = []
        if context:
            flash_matches = re.findall(r'⟪(.+?)⟫', context)
            self.last_flashes = flash_matches[:5]

        self.spatial_mind.belief_space.deposit_trail_particle(
            position=self.attention_center,
            content=thought_text if thought_text else "",
            pulse_id=self._pulse_count,
            omega=omega,
        )

        if self._pulse_count % 10 == 0:
            self._save_attention()

    def extract_cooled_trail_particles(self) -> list[dict]:
        return self.spatial_mind.belief_space.extract_cooled_trail_particles(temp_threshold=0.10)

    # ── Spatial State ─────────────────────────────────────────────────

    def get_spatial_state(self) -> Dict[str, Any]:
        return {
            "pulse": self._pulse_count,
            "gamma": round(self._gamma, 3),
            "velocity_mag": round(float(np.linalg.norm(self._velocity)), 4),
            "identity_dist": round(float(np.linalg.norm(
                self.attention_center - self.spatial_mind._identity_center
            )), 3),
            "memory_points": self.spatial_mind.belief_space.point_count,
            "flashes": self.last_flashes,
        }

    # ── Neighborhood Query ────────────────────────────────────────────

    def query_neighborhood(
        self,
        focus_text: str = None,
        focus_position: np.ndarray = None,
        k: int = 8,
        exclude_trails: bool = True,
    ) -> List[Dict[str, Any]]:
        """Query the K most gravitationally relevant beliefs."""
        if focus_position is not None:
            center = focus_position
        elif focus_text:
            center = self.embed(focus_text)
        else:
            center = self.attention_center

        results = self.spatial_mind.belief_space.gravity_ranked_query(center, k=k)

        scored = []
        for pid, gravity, dist in results:
            pt = self.spatial_mind.belief_space.get_point(pid)
            if not pt:
                continue
            if exclude_trails and pt.get("type") == "trail":
                continue
            scored.append({
                "point_id": pid,
                "content": pt.get("content", ""),
                "relevance": round(gravity, 4),
                "distance": round(dist, 4),
                "mass": round(self.spatial_mind.belief_space._compute_structural_mass(pt), 3),
                "temperature": round(self.spatial_mind.belief_space._compute_temperature(pt), 4),
                "type": pt.get("type", "belief"),
                "creation_pulse": pt.get("creation_pulse", 0),
            })

        scored.sort(key=lambda x: x["relevance"], reverse=True)

        for s in scored[:k]:
            self.spatial_mind.belief_space.update_access(s["point_id"])

        return scored[:k]

    def query_temporal_chain(self, anchor_pulse: int, window: int = 5) -> List[Dict[str, Any]]:
        chain = []
        for pid, p in self.spatial_mind.belief_space._points.items():
            cp = p.get("creation_pulse", 0)
            if abs(cp - anchor_pulse) <= window and cp != anchor_pulse:
                chain.append({
                    "point_id": pid,
                    "content": p.get("content", ""),
                    "creation_pulse": cp,
                    "type": p.get("type", "belief"),
                    "distance_pulses": cp - anchor_pulse,
                })
        chain.sort(key=lambda x: x["creation_pulse"])
        return chain

    # ── Point Registration ────────────────────────────────────────────

    def add_belief_point(self, belief_id: str, text: str, **metadata):
        emb = self.embed_text(text)
        self.spatial_mind.add_belief(belief_id, emb, **metadata)

    def add_memory_point(self, memory_id: str, text: str, **metadata):
        """Backward compat — adds to belief space as type 'memory'."""
        emb = self.embed_text(text)
        self.spatial_mind.belief_space.add_point(
            point_id=memory_id, embedding=emb, point_type="memory", **metadata
        )

    # ── Bootstrap ─────────────────────────────────────────────────────

    def bootstrap_from_stores(self, belief_store, memory_manager):
        """Populate belief space from existing belief store."""
        beliefs_added = 0
        try:
            all_beliefs = belief_store.get_all_beliefs_flat()
            for b in all_beliefs:
                content = b.get("content", "")
                if not content or len(content) < 5:
                    continue
                emb = self.embed_text(content)
                self.spatial_mind.belief_space.add_point(
                    point_id=b.get("id", f"belief_{beliefs_added}"),
                    embedding=emb,
                    point_type="belief",
                    confidence=b.get("confidence", 0.5),
                    importance=b.get("mass", 1.0),
                    content=content,
                )
                beliefs_added += 1
        except Exception as e:
            logger.warning(f"Belief bootstrap failed: {e}")

        if beliefs_added > 0:
            self.spatial_mind.belief_space._rebuild_index()

        self.spatial_mind._compute_identity_center()
        logger.info(f"Spatial mind bootstrapped: {beliefs_added} beliefs (memories not spatially indexed)")

    # ── Persistence ───────────────────────────────────────────────────

    def _save_attention(self):
        self.spatial_mind.save_state()

    def _load_attention(self):
        self.spatial_mind.load_state()

    def save_all(self):
        self.spatial_mind.save_state()
