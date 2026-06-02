"""
Helix — Spatial Physics Engine (Wrapper)

Thin wrapper around SpatialMind that preserves the external API used by
pulse_loop.py, preconscious.py, and dream_engine.py.

Internally delegates to SpatialMind which owns:
  - Dual CognitiveSpace instances (belief field + memory field)
  - KDTree-indexed 8D spatial queries (O(log N))
  - GravityField (512-anchor grid)
  - Real Shannon entropy, KL divergence, local temperature
  - Euler-Lagrange attention dynamics with force integration

Previous implementation (single flat dict, brute-force O(N)) saved to:
  previous_versions/physics_engine_pre_manifold.txt
"""

import re
import time
import math
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

import numpy as np

from core.cognitive_space import CognitiveSpace, CognitiveProjection, PROJECTION_DIM
from core.spatial_mind import SpatialMind
from memory.semantic_index import SemanticIndex

logger = logging.getLogger("helix.core.physics_engine")

# ── Constants ────────────────────────────────────────────────────────
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2
PROJECTION_SEED = 42


class PhysicsEngine:
    """Helix's spatial physics engine.

    Wraps SpatialMind to provide the same external API that pulse_loop,
    preconscious, and dream_engine depend on:

      step_pulse(thought_text, incoming_text, omega)
      attention_center
      get_spatial_state() → dict
      query_neighborhood(focus_text, k, exclude_trails) → list
      query_temporal_chain(anchor_pulse, window) → list
      embed_and_project(text) → np.ndarray
      embed_text(text) → np.ndarray

    Internally uses SpatialMind with dual belief+memory spaces,
    KDTree indexing, and real Lagrangian physics.
    """

    def __init__(self, data_dir: str = None, gravity_constant: float = 0.1):
        self.G = gravity_constant

        # ── Data directory ──
        self.data_dir = Path(data_dir) if data_dir else None
        if self.data_dir:
            self.data_dir.mkdir(parents=True, exist_ok=True)

        # ── SpatialMind (dual 8D spaces) ──
        self.spatial_mind = SpatialMind(
            embedding_dim=EMBEDDING_DIM,
            base_dir=self.data_dir,
        )

        # ── 384D Semantic Index (conscious recall) ──
        self.semantic_index = SemanticIndex(dim=EMBEDDING_DIM)
        if self.data_dir:
            idx_path = self.data_dir / "semantic_index"
            loaded = self.semantic_index.load(idx_path)
            if loaded > 0:
                logger.info(f"SemanticIndex loaded: {loaded} vectors")

        # ── Embedder (lazy-loaded, shared with SpatialMind) ──
        self._embedder = None

        # ── Pulse counter (mind's proper time) ──
        self._pulse_count = 0

        # ── Trail flashes (consumed by preconscious each pulse) ──
        self.last_flashes: List[str] = []

        # ── Load persisted attention state ──
        self._load_attention()

        logger.info("PhysicsEngine initialized (dual 8D manifold + 384D semantic index)")

    # ── Properties delegated to SpatialMind ───────────────────────────

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
        """Lazy-load ChromaDB's all-MiniLM-L6-v2 (CPU, no Ollama)."""
        if self._embedder is None:
            try:
                from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
                self._embedder = DefaultEmbeddingFunction()
                logger.info("Embedder loaded (all-MiniLM-L6-v2, CPU)")
            except Exception as e:
                logger.warning(f"Embedder init failed: {e}")
        return self._embedder

    def embed_text(self, text: str) -> np.ndarray:
        """Embed text → 384D vector. Returns zeros on failure."""
        embedder = self._get_embedder()
        if embedder is None:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)
        try:
            result = embedder([text])
            return np.array(result[0], dtype=np.float32)
        except Exception as e:
            logger.debug(f"Embedding failed: {e}")
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

    def embed_and_project(self, text: str) -> np.ndarray:
        """Text → 384D embedding → 8D position. The main interface."""
        emb = self.embed_text(text)
        return self.spatial_mind.belief_space.projection.project(emb)

    # ── Pulse Step (called once per heartbeat) ────────────────────────

    def step_pulse(
        self,
        thought_text: str,
        incoming_text: str = None,
        omega: float = 0.5,
        cluster_centroid: "np.ndarray | None" = None,
    ):
        """Advance the spatial mind one pulse.

        Delegates to SpatialMind.pulse_from_text() which:
        1. Embeds thought → 8D stimulus position
        2. Gets omega from sentinel for stability coupling
        3. Updates gravity fields in both spaces
        4. Steps attention via 3-force integration
        5. Updates γ (inertia)
        6. Traces cognitive trail → ⟪flash⟫ fragments
        7. Queries both spaces for gravity-ranked context

        Args:
            thought_text: The model's last thought output.
            incoming_text: New stimulus text (message, event), or None.
            omega: Sentinel's hedonic Ω.
            cluster_centroid: Optional 8D position of the weighted centroid
                of retrieved belief clusters. When present, the spatial mind
                uses this as the stimulus position instead of computing a
                raw text midpoint, ensuring attention steers toward actual
                knowledge locations.
        """
        self._pulse_count += 1

        # Set omega on the sentinel reference within spatial_mind
        # (spatial_mind reads sentinel.omega if wired, else uses 0.5)
        # We pass omega directly by temporarily setting it
        if self.spatial_mind.sentinel:
            # Sentinel is wired — it provides omega directly
            pass
        else:
            # No sentinel wired to spatial_mind — create a mock omega
            # so spatial_mind.pulse() uses our passed omega value
            class _OmegaProxy:
                def __init__(self, val):
                    self.omega = val
            self.spatial_mind.sentinel = _OmegaProxy(omega)
            self.spatial_mind._temp_sentinel = True

        # Embed and pulse
        thought_emb = self.embed_text(thought_text) if thought_text else np.zeros(EMBEDDING_DIM, dtype=np.float32)
        incoming_emb = self.embed_text(incoming_text) if incoming_text else None

        context = self.spatial_mind.pulse(
            thought_embedding=thought_emb,
            incoming_embedding=incoming_emb,
            agent_age_seconds=3600.0,
            cluster_centroid=cluster_centroid,
        )

        # Clean up temp sentinel proxy
        if getattr(self.spatial_mind, '_temp_sentinel', False):
            self.spatial_mind.sentinel = None
            self.spatial_mind._temp_sentinel = False

        # Extract flashes from the formatted context
        self.last_flashes = []
        if context:
            import re as _re
            flash_matches = _re.findall(r'⟪(.+?)⟫', context)
            self.last_flashes = flash_matches[:5]

        # Deposit trail particles in both spaces
        self.spatial_mind.belief_space.deposit_trail_particle(
            position=self.attention_center,
            content=thought_text[:80] if thought_text else "",
            pulse_id=self._pulse_count,
            omega=omega,
        )

        # Periodic save
        if self._pulse_count % 10 == 0:
            self._save_attention()
            if self.data_dir:
                self.semantic_index.save(self.data_dir / "semantic_index")

        logger.debug(
            f"Pulse {self._pulse_count}: "
            f"γ={self._gamma:.2f}, flashes={len(self.last_flashes)}"
        )

    # ── Spatial State for Preconscious ────────────────────────────────

    def get_spatial_state(self) -> Dict[str, Any]:
        """Return spatial state for preconscious injection."""
        return {
            "pulse": self._pulse_count,
            "gamma": round(self._gamma, 3),
            "velocity_mag": round(float(np.linalg.norm(self._velocity)), 4),
            "identity_dist": round(float(np.linalg.norm(
                self.attention_center - self.spatial_mind._identity_center
            )), 3),
            "memory_points": (
                self.spatial_mind.belief_space.point_count +
                self.spatial_mind.memory_space.point_count
            ),
            "flashes": self.last_flashes,
        }

    # ── Gravitational Neighborhood Query ──────────────────────────────

    def query_neighborhood(
        self,
        focus_text: str = None,
        focus_position: np.ndarray = None,
        k: int = 8,
        exclude_trails: bool = True,
    ) -> List[Dict[str, Any]]:
        """Query the K most gravitationally relevant points.

        Queries BOTH belief and memory spaces and merges results.
        Points scored by gravity = T × mass / distance².
        """
        # Determine focus position
        if focus_position is not None:
            center = focus_position
        elif focus_text:
            center = self.embed_and_project(focus_text)
        else:
            center = self.attention_center

        # Query both spaces
        belief_results = self.spatial_mind.belief_space.gravity_ranked_query(
            center, k=k
        )
        memory_results = self.spatial_mind.memory_space.gravity_ranked_query(
            center, k=k
        )

        # Merge and format
        scored = []
        for pid, gravity, dist in belief_results:
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

        for pid, gravity, dist in memory_results:
            pt = self.spatial_mind.memory_space.get_point(pid)
            if not pt:
                continue
            if exclude_trails and pt.get("type") == "trail":
                continue
            scored.append({
                "point_id": pid,
                "content": pt.get("content", ""),
                "relevance": round(gravity, 4),
                "distance": round(dist, 4),
                "mass": round(self.spatial_mind.memory_space._compute_structural_mass(pt), 3),
                "temperature": round(self.spatial_mind.memory_space._compute_temperature(pt), 4),
                "type": pt.get("type", "memory"),
                "creation_pulse": pt.get("creation_pulse", 0),
            })

        # Sort by relevance, return top K
        scored.sort(key=lambda x: x["relevance"], reverse=True)

        # Mark as accessed (route to correct space)
        for s in scored[:k]:
            pid = s["point_id"]
            if s["type"] == "belief":
                self.spatial_mind.belief_space.update_access(pid)
            else:
                self.spatial_mind.memory_space.update_access(pid)

        return scored[:k]

    def query_temporal_chain(
        self,
        anchor_pulse: int,
        window: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get points temporally adjacent to a given pulse.

        Searches both belief and memory spaces.
        """
        chain = []
        for space in [self.spatial_mind.belief_space, self.spatial_mind.memory_space]:
            for pid, p in space._points.items():
                cp = p.get("creation_pulse", 0)
                if abs(cp - anchor_pulse) <= window and cp != anchor_pulse:
                    chain.append({
                        "point_id": pid,
                        "content": p.get("content", ""),
                        "creation_pulse": cp,
                        "type": p.get("type", "memory"),
                        "distance_pulses": cp - anchor_pulse,
                    })
        chain.sort(key=lambda x: x["creation_pulse"])
        return chain

    # ── Dual Registration (single source of truth) ─────────────────────

    def _register_point(
        self,
        point_id: str,
        emb: np.ndarray,
        point_type: str,
        spatial_kwargs: dict,
        semantic_metadata: dict,
    ) -> None:
        """Register a point in BOTH the 8D manifold and 384D semantic index.

        This is the single place where dual-registration happens.
        All public add methods and bootstrap logic delegate here.

        Args:
            point_id: Unique ID (e.g., "bel_42", "mem_17")
            emb: Raw 384D embedding (pre-projected for 8D internally)
            point_type: "belief" or "memory"
            spatial_kwargs: Extra kwargs for the SpatialMind add
                            (confidence, importance, content, etc.)
            semantic_metadata: Metadata dict for the 384D index
                               (content, type, importance, etc.)
        """
        # 8D manifold
        if point_type == "belief":
            self.spatial_mind.add_belief(point_id, emb, **spatial_kwargs)
        elif point_type == "memory":
            self.spatial_mind.add_memory(point_id, emb, **spatial_kwargs)
        else:
            logger.warning(f"Unknown point_type '{point_type}' for {point_id}")

        # 384D semantic index
        self.semantic_index.add(
            id=point_id,
            embedding=emb,
            metadata=semantic_metadata,
        )

    # ── Public Add Methods (deprecated — use _register_point) ────────
    # Kept for backward compatibility with existing callers.
    # Will be removed once all call sites are verified.

    def add_belief_point(self, belief_id: str, text: str, **metadata):
        """Add a belief to both the 8D manifold and 384D semantic index.

        .. deprecated:: Use _register_point() directly for new code.
        """
        emb = self.embed_text(text)
        self._register_point(
            point_id=belief_id,
            emb=emb,
            point_type="belief",
            spatial_kwargs=metadata,
            semantic_metadata={
                "content": text[:500],
                "type": "belief",
                "confidence": metadata.get("confidence", 0.5),
                "importance": metadata.get("mass", 1.0),
            },
        )

    def add_memory_point(self, memory_id: str, text: str, **metadata):
        """Add a memory to both the 8D manifold and 384D semantic index.

        .. deprecated:: Use _register_point() directly for new code.
        """
        emb = self.embed_text(text)
        self._register_point(
            point_id=memory_id,
            emb=emb,
            point_type="memory",
            spatial_kwargs=metadata,
            semantic_metadata={
                "content": text[:500],
                "type": "memory",
                "importance": metadata.get("importance", 0.5),
            },
        )

    # ── Semantic Search (384D, for conscious recall) ──────────────────

    def semantic_search(
        self,
        query_text: str,
        k: int = 10,
        filter_fn: Optional[Callable] = None,
        return_embeddings: bool = False,
    ) -> list:
        """Search the 384D semantic index for conscious recall.

        Used by the memory_recall tool and Curator deep search.
        Returns results sorted by cosine similarity (most similar first).

        Args:
            query_text: Natural language query string
            k: Maximum number of results
            filter_fn: Optional predicate (id, metadata) → bool to filter
                       results before ranking
            return_embeddings: If True, include the normalized 384D embedding
                               in each result dict under key "embedding"
        """
        emb = self.embed_text(query_text)
        results = self.semantic_index.search(emb, k=k, filter_fn=filter_fn)

        if return_embeddings:
            for r in results:
                vid = r["id"]
                if self.semantic_index.contains(vid):
                    idx = self.semantic_index._id_to_idx[vid]
                    r["embedding"] = self.semantic_index._embeddings[idx].tolist()

        return results

    # ── Bootstrap from existing stores ────────────────────────────────

    def bootstrap_from_stores(self, belief_store, memory_manager):
        """Populate both 8D spaces and the 384D index from existing stores.

        Called once during initialization to hydrate the manifold with
        existing data so gravity fields are non-empty from the start.
        Every entry is registered via _register_point() to ensure both
        the 8D manifold and 384D semantic index stay in sync.
        """
        if self.semantic_index.count > 0:
            logger.info("SemanticIndex already loaded from disk — skipping heavy embedding bootstrap")
            return

        beliefs_added = 0
        memories_added = 0

        # Bootstrap beliefs
        try:
            all_beliefs = belief_store.get_all_beliefs_flat()
            for b in all_beliefs:
                content = b.get("content", "")
                if not content or len(content) < 5:
                    continue
                emb = self.embed_text(content)
                bid = b.get("id", f"belief_{beliefs_added}")

                # Extract encoding Lagrangian components
                lag = b.get("encoding_lagrangian", {})
                if not isinstance(lag, dict):
                    lag = {}

                self._register_point(
                    point_id=bid,
                    emb=emb,
                    point_type="belief",
                    spatial_kwargs={
                        "confidence": b.get("confidence", 0.5),
                        "importance": b.get("mass", 1.0),
                        "content": content,
                        "encoding_omega": lag.get("omega", 0.5),
                        "encoding_s_total": lag.get("s_total", 0.15),
                        "relations_count": len(b.get("relations", [])),
                        "metadata": {
                            "verifications": b.get("verifications", 0),
                            "stability_index": b.get("stability_index", 0.5),
                            "memory_refs": b.get("memory_refs", []),
                            "created_at": b.get("created_at", ""),
                            "last_verified": b.get("last_verified", ""),
                            "formation_type": b.get("formation_type", ""),
                            "encoding_lagrangian": lag,
                        },
                    },
                    semantic_metadata={
                        "content": content[:500],
                        "type": "belief",
                        "confidence": b.get("confidence", 0.5),
                        "importance": b.get("mass", 1.0),
                        "category": b.get("_category", ""),
                        "verifications": b.get("verifications", 0),
                        "memory_refs_count": len(b.get("memory_refs", [])),
                        "encoding_omega": lag.get("omega", 0.5),
                    },
                )
                beliefs_added += 1
        except Exception as e:
            logger.warning(f"Belief bootstrap failed: {e}")

        # Bootstrap memories — load broadly so historical episodic
        # memories (people, places, events) are present in the manifold.
        # No time cutoff: the whole journal is Helix's lived experience.
        try:
            recent = memory_manager.get_historical_sample(limit=2000)
            for m in recent:
                content = m.get("content", "")
                if not content or len(content) < 10:
                    continue
                emb = self.embed_text(content)
                mid = m.get("id", f"mem_{memories_added}")

                # Extract encoding Lagrangian if available
                mem_lag = m.get("lagrangian_snapshot", {})
                if isinstance(mem_lag, str):
                    try:
                        import json as _json
                        mem_lag = _json.loads(mem_lag)
                    except Exception:
                        mem_lag = {}
                if not isinstance(mem_lag, dict):
                    mem_lag = {}

                self._register_point(
                    point_id=mid,
                    emb=emb,
                    point_type="memory",
                    spatial_kwargs={
                        "importance": m.get("importance", 0.5),
                        "content": content[:200],
                        "encoding_omega": mem_lag.get("omega",
                                            m.get("encoding_omega", 0.5)),
                        "encoding_s_total": mem_lag.get("s_total", 0.15),
                    },
                    semantic_metadata={
                        "content": content[:500],
                        "type": "memory",
                        "importance": m.get("importance", 0.5),
                        "memory_type": m.get("memory_type", ""),
                        "created_at": m.get("created_at", ""),
                        "encoding_omega": mem_lag.get("omega",
                                            m.get("encoding_omega", 0.5)),
                    },
                )
                memories_added += 1
        except Exception as e:
            logger.warning(f"Memory bootstrap failed: {e}")

        # Rebuild 8D trees
        if beliefs_added > 0:
            self.spatial_mind.belief_space._rebuild_tree()
        if memories_added > 0:
            self.spatial_mind.memory_space._rebuild_tree()

        # Compute identity center from beliefs
        self.spatial_mind._compute_identity_center()

        # Save the fully hydrated semantic index to disk so we don't re-embed on next boot
        if self.data_dir:
            self.semantic_index.save(self.data_dir / "semantic_index")

        logger.info(
            f"Spatial mind bootstrapped: {beliefs_added} beliefs, "
            f"{memories_added} memories, "
            f"{self.semantic_index.count} vectors in 384D index"
        )

    # ── Persistence ───────────────────────────────────────────────────

    def _save_attention(self):
        """Persist attention state via SpatialMind."""
        self.spatial_mind.save_state()

    def _load_attention(self):
        """Load persisted attention state via SpatialMind."""
        self.spatial_mind.load_state()

    def save_all(self):
        """Save all state (called on shutdown)."""
        self.spatial_mind.save_state()
        if self.data_dir:
            self.semantic_index.save(self.data_dir / "semantic_index")
            logger.info("PhysicsEngine: all state saved (8D manifold + 384D index)")
