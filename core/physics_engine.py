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
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

import numpy as np

from core.cognitive_space import CognitiveSpace, CognitiveProjection, PROJECTION_DIM
from core.spatial_mind import SpatialMind
from memory.semantic_encoder import SemanticEncoder
from memory.semantic_index import SemanticIndex

logger = logging.getLogger("helix.core.physics_engine")

# ── Constants ────────────────────────────────────────────────────────
SPATIAL_EMBEDDING_DIM = 384  # Stable all-MiniLM-L6-v2 -> 8D projection
# Backward-compatible name for callers that mean the spatial representation.
EMBEDDING_DIM = SPATIAL_EMBEDDING_DIM
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
            embedding_dim=SPATIAL_EMBEDDING_DIM,
            base_dir=self.data_dir,
        )

        # ── Independent 1024D semantic representation ──
        # Spatial memory intentionally keeps its original 384D -> 8D mapping;
        # changing the semantic model must never reposition lived memories.
        self.semantic_encoder = SemanticEncoder()
        self.semantic_index = SemanticIndex(
            dim=self.semantic_encoder.dim,
            model_id=self.semantic_encoder.identity,
        )
        self._semantic_index_path = None
        if self.data_dir:
            self._semantic_index_path = (
                self.data_dir / f"semantic_index_{self.semantic_encoder.dim}d"
            )
            loaded = self.semantic_index.load(self._semantic_index_path)
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

        # Continue the mind's proper time from the persisted state
        # instead of restarting at pulse 0 every boot.
        self._pulse_count = getattr(self.spatial_mind, "_pulse_count", 0)

        logger.info(
            "PhysicsEngine initialized (stable 384D->8D spatial manifold + "
            "%dD semantic index via %s)",
            self.semantic_encoder.dim,
            self.semantic_encoder.model,
        )

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

    def derive_query_center(
        self,
        focus_text: str = None,
        focus_position: np.ndarray = None,
        attention_relative: bool = False,
    ) -> np.ndarray:
        """Resolve a query center for recall without mutating live state.

        For conscious/preconscious recall we often want new input to perturb
        the current attention trajectory rather than replacing it outright.
        ``attention_relative=True`` keeps the carried-forward center and
        velocity as the base frame, then nudges toward the incoming stimulus.
        """
        if focus_position is not None:
            stimulus_center = np.asarray(focus_position, dtype=np.float32).reshape(-1)
        elif focus_text:
            stimulus_center = self.embed_and_project(focus_text)
        else:
            stimulus_center = None

        base_center = np.asarray(self.attention_center, dtype=np.float32).reshape(-1)
        if stimulus_center is None:
            return base_center.copy()
        if not attention_relative:
            return stimulus_center

        trajectory_center = base_center.copy()
        velocity = np.asarray(self._velocity, dtype=np.float32).reshape(-1)
        velocity_mag = float(np.linalg.norm(velocity))
        if velocity_mag > 1e-6:
            trajectory_center = trajectory_center + (self._gamma * velocity / (1.0 + velocity_mag))

        displacement = float(np.linalg.norm(stimulus_center - trajectory_center))
        novelty = min(1.0, displacement / 3.0)
        stimulus_weight = 0.20 + (0.25 * novelty)
        if self._gamma > 0.85:
            stimulus_weight *= 0.75
        stimulus_weight = max(0.15, min(0.50, stimulus_weight))

        return (
            trajectory_center * (1.0 - stimulus_weight)
            + stimulus_center * stimulus_weight
        ).astype(np.float32)

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
        """Embed text for the stable spatial projection (384D MiniLM)."""
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
        """Text → stable 384D MiniLM embedding → persistent 8D position."""
        emb = self.embed_text(text)
        return self.spatial_mind.belief_space.projection.project(emb)

    def embed_semantic_text(self, text: str, *, is_query: bool = False) -> np.ndarray:
        """Embed text into the independent native 1024D semantic space."""
        if is_query:
            return self.semantic_encoder.encode_query(text)
        return self.semantic_encoder.encode_document(text)

    def embed_semantic_batch(
        self,
        texts: List[str],
        *,
        is_query: bool = False,
    ) -> np.ndarray:
        """Batch semantic encoding used by mRAG heads and index migration."""
        if is_query:
            return self.semantic_encoder.encode_queries(texts)
        return self.semantic_encoder.encode_documents(texts)

    @staticmethod
    def memory_point_id(memory_id: Any) -> str:
        """Canonical manifold/index ID for a journal memory entry."""
        return f"mem_{memory_id}"

    @staticmethod
    def memory_journal_id(point_id: str) -> str:
        """Recover the underlying journal ID from a canonical memory point ID."""
        if isinstance(point_id, str) and point_id.startswith("mem_"):
            return point_id[4:]
        return str(point_id)

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
            content=thought_text[:250] if thought_text else "",
            pulse_id=self._pulse_count,
            omega=omega,
        )

        # Periodic save
        if self._pulse_count % 10 == 0:
            self._save_attention()
            if self._semantic_index_path:
                self.semantic_index.save(self._semantic_index_path)

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
        attention_relative: bool = False,
        refresh_access: bool = True,
    ) -> List[Dict[str, Any]]:
        """Query the K most gravitationally relevant points.

        Queries BOTH belief and memory spaces and merges results.
        Points scored by gravity = T × mass / distance².
        """
        center = self.derive_query_center(
            focus_text=focus_text,
            focus_position=focus_position,
            attention_relative=attention_relative,
        )

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

        # Candidate generation can opt out; unified retrieval refreshes only
        # the items that actually survive semantic-first selection.  Counting
        # every raw-8D candidate as a recall would reinforce projection noise.
        if refresh_access:
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
        refresh_access: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get points temporally adjacent to a given pulse.

        Searches both belief and memory spaces. By default, any point returned
        here is treated as surfaced context and has its access metadata refreshed,
        so temporal-chain recall reinforces future gravitational retrieval.
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
                    if refresh_access:
                        space.update_access(pid)
        chain.sort(key=lambda x: x["creation_pulse"])
        return chain

    # ── Dual Registration (single source of truth) ─────────────────────

    def _upsert_semantic_point(
        self,
        point_id: str,
        content: str,
        metadata: dict,
        embedding: np.ndarray = None,
    ) -> bool:
        """Upsert one native semantic vector without touching 8D state."""
        semantic_text = str(content or "").strip()
        if not point_id or not semantic_text:
            return False

        content_hash = hashlib.sha256(
            semantic_text.encode("utf-8", errors="ignore")
        ).hexdigest()
        existing_meta = self.semantic_index.get_metadata(point_id) or {}
        semantic_embedding = embedding
        if (
            semantic_embedding is None
            and self.semantic_index.contains(point_id)
            and existing_meta.get("semantic_content_hash") == content_hash
        ):
            idx = self.semantic_index._id_to_idx[point_id]
            semantic_embedding = self.semantic_index._embeddings[idx]
        if semantic_embedding is None:
            semantic_embedding = self.embed_semantic_text(
                semantic_text,
                is_query=False,
            )

        semantic_embedding = np.asarray(
            semantic_embedding, dtype=np.float32,
        ).ravel()
        if (
            len(semantic_embedding) != self.semantic_encoder.dim
            or float(np.linalg.norm(semantic_embedding)) < 1e-8
        ):
            return False

        semantic_metadata = dict(metadata or {})
        semantic_metadata["semantic_content_hash"] = content_hash
        semantic_metadata["semantic_model"] = self.semantic_encoder.identity
        self.semantic_index.add(
            id=point_id,
            embedding=semantic_embedding,
            metadata=semantic_metadata,
        )
        return True

    def _register_point(
        self,
        point_id: str,
        emb: np.ndarray,
        point_type: str,
        spatial_kwargs: dict,
        semantic_metadata: dict,
        semantic_embedding: np.ndarray = None,
        register_spatial: bool = True,
        register_semantic: bool = True,
    ) -> np.ndarray:
        """Register a point in the independent spatial and semantic stores.

        This is the single place where dual-registration happens.
        All public add methods and bootstrap logic delegate here.

        Args:
            point_id: Unique ID (e.g., "bel_42", "mem_17")
            emb: Raw 384D MiniLM embedding for the 8D manifold
            point_type: "belief" or "memory"
            spatial_kwargs: Extra kwargs for the SpatialMind add
                            (confidence, importance, content, etc.)
            semantic_metadata: Metadata dict for the 1024D semantic index
        """
        # 8D manifold
        if register_spatial:
            if point_type == "belief":
                self.spatial_mind.add_belief(point_id, emb, **spatial_kwargs)
            elif point_type == "memory":
                self.spatial_mind.add_memory(point_id, emb, **spatial_kwargs)
            else:
                logger.warning(f"Unknown point_type '{point_type}' for {point_id}")

        if register_semantic:
            semantic_text = spatial_kwargs.get("content") or semantic_metadata.get("content", "")
            self._upsert_semantic_point(
                point_id,
                semantic_text,
                semantic_metadata,
                embedding=semantic_embedding,
            )

        if point_type == "belief" and register_spatial:
            self.spatial_mind.refresh_identity_center()

        space = (
            self.spatial_mind.belief_space
            if point_type == "belief"
            else self.spatial_mind.memory_space
        )
        return space.get_position(point_id)

    def _remove_point(self, point_id: str, point_type: str) -> bool:
        """Remove a point from both the manifold and semantic index."""
        space = (
            self.spatial_mind.belief_space
            if point_type == "belief"
            else self.spatial_mind.memory_space
        )
        removed = space.remove_point(point_id)
        removed = self.semantic_index.remove(point_id) or removed
        if point_type == "belief" and removed:
            self.spatial_mind.refresh_identity_center()
        return removed

    # ── Public Add Methods (deprecated — use _register_point) ────────
    # Kept for backward compatibility with existing callers.
    # Will be removed once all call sites are verified.

    def add_belief_point(self, belief_id: str, text: str, **metadata):
        """Add a belief to both the 8D manifold and 1024D semantic index.

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
        """Add a memory to both the 8D manifold and 1024D semantic index.

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

    def remove_belief_point(self, belief_id: str) -> bool:
        """Remove a belief from both runtime stores."""
        return self._remove_point(belief_id, "belief")

    def remove_memory_point(self, memory_id: Any) -> bool:
        """Remove a memory from both runtime stores."""
        return self._remove_point(self.memory_point_id(memory_id), "memory")

    def sync_belief_record(
        self,
        belief: Dict[str, Any],
        embedding: np.ndarray = None,
        register_semantic: bool = True,
    ) -> tuple[list[float], list[float]]:
        """Upsert a belief record into the live manifold and semantic index."""
        content = belief.get("content", "")
        emb = np.asarray(embedding, dtype=np.float32) if embedding is not None else self.embed_text(content)
        lag = belief.get("encoding_lagrangian", {})
        if not isinstance(lag, dict):
            lag = {}

        position = self._register_point(
            point_id=belief.get("id", ""),
            emb=emb,
            point_type="belief",
            spatial_kwargs={
                "confidence": belief.get("confidence", 0.5),
                "importance": belief.get("mass", 1.0),
                "content": content,
                "encoding_omega": lag.get("omega", 0.5),
                "encoding_s_total": lag.get("s_total", 0.15),
                "relations_count": len(belief.get("relations", [])),
                "access_count": belief.get("access_count", 0),
                "stability_index": belief.get("stability_index", 0.5),
                "weight": belief.get("weight", "surface"),
                "position_override": belief.get("position_8d"),
                "volatile_mass": belief.get("volatile_mass", 0.0),
                "last_accessed_pulse": belief.get("last_accessed_pulse"),
                "metadata": {
                    "category": belief.get("_category", ""),
                    "verifications": belief.get("verifications", 0),
                    "memory_refs": belief.get("memory_refs", []),
                    "created_at": belief.get("created_at", ""),
                    "last_accessed": belief.get("last_accessed", ""),
                    "formation_type": belief.get("formation_type", ""),
                    "encoding_lagrangian": lag,
                },
            },
            semantic_metadata={
                "content": content[:500],
                "type": "belief",
                "confidence": belief.get("confidence", 0.5),
                "importance": belief.get("mass", 1.0),
                "category": belief.get("_category", ""),
                "verifications": belief.get("verifications", 0),
                "memory_refs_count": len(belief.get("memory_refs", [])),
                "encoding_omega": lag.get("omega", 0.5),
                "weight": belief.get("weight", "surface"),
                "stability_index": belief.get("stability_index", 0.5),
                "position_8d": belief.get("position_8d") or [],
            },
            register_semantic=register_semantic,
        )
        return position.tolist() if position is not None else [], emb.tolist()

    def register_memory_entry(
        self,
        memory_id: Any,
        content: str,
        *,
        importance: float = 0.5,
        memory_type: str = "observation",
        source: str = "system",
        created_at: str = "",
        lagrangian_snapshot: Optional[Dict[str, Any]] = None,
        pulse_id: int = 0,
        embedding_384d: Optional[List[float]] = None,
        position_8d: Optional[List[float]] = None,
        access_count: int = 0,
        tags: Optional[List[str]] = None,
        belief_ids: Optional[List[str]] = None,
        register_semantic: bool = True,
    ) -> tuple[str, list[float], list[float]]:
        """Upsert a journal memory entry into the live manifold and semantic index."""
        lag = lagrangian_snapshot or {}
        point_id = self.memory_point_id(memory_id)
        emb = (
            np.asarray(embedding_384d, dtype=np.float32)
            if embedding_384d is not None
            else self.embed_text(content)
        )
        position = self._register_point(
            point_id=point_id,
            emb=emb,
            point_type="memory",
            spatial_kwargs={
                "importance": importance,
                "content": content,
                "encoding_omega": lag.get("omega", 0.5),
                "encoding_s_total": lag.get("s_total", 0.15),
                "access_count": access_count,
                "position_override": position_8d,
                "creation_pulse": pulse_id,
                "last_accessed_pulse": pulse_id,
                "weight": "memory",
                "metadata": {
                    "point_id": point_id,
                    "memory_type": memory_type,
                    "source": source,
                    "created_at": created_at,
                    "tags": tags or [],
                    "belief_ids": belief_ids or [],
                },
            },
            semantic_metadata={
                "content": content[:500],
                "type": "memory",
                "importance": importance,
                "memory_type": memory_type,
                "created_at": created_at,
                "source": source,
                "encoding_omega": lag.get("omega", 0.5),
                "journal_id": str(memory_id),
                "pulse_id": pulse_id,
                "position_8d": position_8d or [],
                "tags": tags or [],
                "belief_ids": belief_ids or [],
            },
            register_semantic=register_semantic,
        )
        return point_id, position.tolist() if position is not None else [], emb.tolist()

    # ── Semantic Search (1024D, for mRAG and conscious recall) ────────

    def semantic_search(
        self,
        query_text: str,
        k: int = 10,
        filter_fn: Optional[Callable] = None,
        return_embeddings: bool = False,
    ) -> list:
        """Search the independent 1024D semantic index for conscious recall.

        Used by the memory_recall tool and Curator deep search.
        Returns results sorted by cosine similarity (most similar first).

        Args:
            query_text: Natural language query string
            k: Maximum number of results
            filter_fn: Optional predicate (id, metadata) → bool to filter
                       results before ranking
            return_embeddings: If True, include the normalized semantic embedding
                               in each result dict under key "embedding"
        """
        emb = self.embed_semantic_text(query_text, is_query=True)
        results = self.semantic_index.search(emb, k=k, filter_fn=filter_fn)

        if return_embeddings:
            for r in results:
                vid = r["id"]
                if self.semantic_index.contains(vid):
                    idx = self.semantic_index._id_to_idx[vid]
                    r["embedding"] = self.semantic_index._embeddings[idx].tolist()

        return results

    # ── Bootstrap from existing stores ────────────────────────────────

    def _bootstrap_semantic_records(
        self,
        beliefs: List[Dict[str, Any]],
        memories: List[Dict[str, Any]],
    ) -> int:
        """Batch-reembed canonical stores into the native semantic index."""
        records = []
        for belief in beliefs:
            content = str(belief.get("content", "") or "").strip()
            belief_id = str(belief.get("id", "") or "")
            if not belief_id or len(content) < 5:
                continue
            records.append((belief_id, content, {
                "content": content[:500],
                "type": "belief",
                "confidence": belief.get("confidence", 0.5),
                "importance": belief.get("mass", 1.0),
                "category": belief.get("_category") or belief.get("category", ""),
                "stability_index": belief.get("stability_index", 0.5),
                "position_8d": belief.get("position_8d") or [],
            }))

        for memory in memories:
            if memory.get("type") not in (None, "memory"):
                continue
            content = str(memory.get("content", "") or "").strip()
            metadata = memory.get("metadata", {}) or {}
            journal_id = str(memory.get("id", "") or "")
            point_id = str(metadata.get("point_id") or self.memory_point_id(journal_id))
            if not journal_id or len(content) < 5:
                continue
            records.append((point_id, content, {
                "content": content[:500],
                "type": "memory",
                "importance": metadata.get("importance", 0.5),
                "memory_type": metadata.get("memory_type", ""),
                "created_at": metadata.get("created_at") or memory.get("timestamp", ""),
                "source": metadata.get("source", ""),
                "journal_id": journal_id,
                "pulse_id": memory.get("pulse_id", 0),
                "position_8d": memory.get("position_8d") or [],
                "tags": metadata.get("tags", []) or [],
                "belief_ids": metadata.get("belief_ids", []) or [],
            }))

        added = 0
        migration_batch = max(16, self.semantic_encoder.batch_size * 4)
        for start in range(0, len(records), migration_batch):
            batch = records[start:start + migration_batch]
            vectors = self.embed_semantic_batch(
                [record[1] for record in batch],
                is_query=False,
            )
            for (point_id, content, metadata), vector in zip(batch, vectors):
                if self._upsert_semantic_point(
                    point_id,
                    content,
                    metadata,
                    embedding=vector,
                ):
                    added += 1
            logger.info(
                "Semantic migration: %d/%d records encoded",
                min(start + len(batch), len(records)),
                len(records),
            )
        return added

    def bootstrap_from_stores(self, belief_store, memory_manager):
        """Populate stable 8D spaces and the independent semantic index.

        Called once during initialization to hydrate the manifold with
        existing data so gravity fields are non-empty from the start.
        Existing 8D positions are never regenerated merely because the
        semantic model changed. A missing 1024D index is rebuilt separately
        from all canonical beliefs and journal memories.

        Checks belief and memory spaces INDEPENDENTLY — if beliefs are
        already loaded from a previous boot but memories are empty, only
        the memory bootstrap runs (and vice versa).
        """
        # Check each space independently instead of a single early-exit.
        # The old guard checked semantic_index.count > 0 and returned,
        # which skipped memory loading when beliefs were already present.
        belief_loaded = self.spatial_mind.belief_space.point_count > 0
        memory_loaded = self.spatial_mind.memory_space.point_count > 0
        semantic_loaded = self.semantic_index.count > 0

        if belief_loaded and memory_loaded and semantic_loaded:
            logger.info(
                "Spatial and semantic stores already populated "
                "(beliefs=%d, memories=%d, semantic=%d) — skipping bootstrap",
                self.spatial_mind.belief_space.point_count,
                self.spatial_mind.memory_space.point_count,
                self.semantic_index.count,
            )
            return

        beliefs_added = 0
        memories_added = 0
        all_beliefs: List[Dict[str, Any]] = []
        semantic_memories: List[Dict[str, Any]] = []

        try:
            all_beliefs = belief_store.get_all_beliefs_flat()
        except Exception as e:
            logger.warning("Belief bootstrap read failed: %s", e)

        try:
            semantic_memories = list(memory_manager.journal.latest_by_id().values())
        except Exception as e:
            logger.warning("Semantic memory bootstrap read failed: %s", e)

        # Bootstrap beliefs (skip if already loaded from persisted state)
        if not belief_loaded:
            try:
                for b in all_beliefs:
                    content = b.get("content", "")
                    if not content or len(content) < 5:
                        continue
                    bid = b.get("id", f"belief_{beliefs_added}")
                    self.sync_belief_record(
                        b,
                        register_semantic=semantic_loaded,
                    )
                    beliefs_added += 1
            except Exception as e:
                logger.warning(f"Belief bootstrap failed: {e}")
        else:
            logger.info(f"Belief space already populated ({self.spatial_mind.belief_space.point_count} points) — skipping belief bootstrap")

        # Bootstrap memories — load ALL core memories (importance >= 0.7)
        # plus 10% of the remaining timeline for temporal coverage.
        # No time cutoff: the whole journal is Helix's lived experience.
        if not memory_loaded:
            try:
                recent = memory_manager.get_historical_sample()
                logger.info(f"Memory bootstrap: loading {len(recent)} historical memories into 8D space")
                for m in recent:
                    content = m.get("content", "")
                    if not content or len(content) < 10:
                        continue
                    mid = m.get("id", memories_added)

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

                    self.register_memory_entry(
                        memory_id=mid,
                        content=content,
                        importance=m.get("importance", 0.5),
                        memory_type=m.get("memory_type", ""),
                        source=m.get("source", ""),
                        created_at=m.get("created_at", ""),
                        lagrangian_snapshot=mem_lag,
                        pulse_id=m.get("pulse_id", 0),
                        embedding_384d=m.get("embedding_384d"),
                        position_8d=m.get("position_8d"),
                        access_count=m.get("access_count", 0),
                        tags=m.get("tags", []),
                        register_semantic=semantic_loaded,
                    )
                    memories_added += 1
            except Exception as e:
                logger.warning(f"Memory bootstrap failed: {e}")
        else:
            logger.info(f"Memory space already populated ({self.spatial_mind.memory_space.point_count} points) — skipping memory bootstrap")

        # Rebuild 8D trees
        if beliefs_added > 0:
            self.spatial_mind.belief_space._rebuild_tree()
        if memories_added > 0:
            self.spatial_mind.memory_space._rebuild_tree()

        # Compute identity center from beliefs
        self.spatial_mind.refresh_identity_center()

        semantic_added = 0
        if not semantic_loaded:
            semantic_added = self._bootstrap_semantic_records(
                all_beliefs,
                semantic_memories,
            )

        # Save the fully hydrated semantic index to disk so we don't re-embed on next boot
        if self._semantic_index_path:
            self.semantic_index.save(self._semantic_index_path)
            # Also save spatial state so memory_space_state.json is populated
            self.spatial_mind.save_state()

        logger.info(
            f"Spatial mind bootstrapped: {beliefs_added} beliefs, "
            f"{memories_added} memories, "
            f"{semantic_added} newly encoded / {self.semantic_index.count} "
            f"vectors in {self.semantic_encoder.dim}D semantic index"
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
        if self._semantic_index_path:
            self.semantic_index.save(self._semantic_index_path)
            logger.info(
                "PhysicsEngine: all state saved (8D manifold + %dD semantic index)",
                self.semantic_encoder.dim,
            )
