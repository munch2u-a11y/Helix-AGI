"""
Helix — Semantic Index (384D Lossless Vector Search)

The conscious mind's library catalog. Searched explicitly when
the agent uses memory_recall or when the Curator needs precise
semantic matching during nightly synthesis.

Separate from the 8D CognitiveSpace which handles ambient
preconscious gravity and attention dynamics. This index stores
the raw, uncompressed all-MiniLM-L6-v2 embeddings for lossless
cosine similarity search.

Scalability strategy:
  - 0–5K vectors:   numpy brute-force (sub-ms)
  - 5K–100K:        FAISS IndexIVFFlat (trained, ~1ms)
  - 100K+:          FAISS IndexIVFFlat with more centroids

The index automatically upgrades its search strategy as the
vector count grows. No manual tuning required.

Thread safety:
  The pulse loop writes (add/remove) while tool execution reads
  (search). A read-write lock ensures consistency without
  blocking the pulse loop unnecessarily.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("helix.memory.semantic_index")

# ── Scaling thresholds ───────────────────────────────────────────────
# Default FAISS switch threshold (configurable per-instance)
_DEFAULT_FAISS_THRESHOLD = 2000
# IVF centroids = sqrt(N), clamped to this range
_MIN_IVF_CENTROIDS = 16
_MAX_IVF_CENTROIDS = 256
# Minimum vectors needed before IVF training is attempted
_IVF_TRAINING_MIN = 256


class SemanticIndex:
    """384D semantic vector index for conscious memory search.

    Stores raw embeddings alongside metadata. Provides cosine-similarity
    search via normalized inner product.

    The index is dynamic — it grows with the agent's lifetime. Search
    strategy scales automatically:
      - Small index (< 5K): numpy dot product (exact)
      - Large index (≥ 5K): FAISS IVFFlat (approximate, trained)

    All vectors are L2-normalized on ingest so cosine similarity
    reduces to inner product.

    Attributes:
        dim: Embedding dimensionality (384 for MiniLM-L6-v2)
        _ids: Ordered list of vector IDs
        _embeddings: (N, dim) array of L2-normalized embeddings
        _metadata: Dict mapping ID → metadata dict
        _faiss_index: FAISS index (None if not available or < threshold)
    """

    def __init__(self, dim: int = 384, faiss_threshold: int = _DEFAULT_FAISS_THRESHOLD):
        self.dim = dim
        self.faiss_threshold = faiss_threshold

        # ── Core storage ──
        self._ids: List[str] = []
        self._embeddings: Optional[np.ndarray] = None  # (N, dim) float32
        self._metadata: Dict[str, Dict[str, Any]] = {}

        # ── ID → row index mapping for O(1) lookup ──
        self._id_to_idx: Dict[str, int] = {}

        # ── FAISS index (lazy, optional) ──
        self._faiss_index = None
        self._faiss_available = False
        try:
            import faiss  # noqa: F401
            self._faiss_available = True
        except ImportError:
            pass

        # ── One-time warning flag (logged once when threshold is
        #    reached but FAISS is unavailable) ──
        self._faiss_warning_emitted = False

        # ── Thread safety ──
        self._lock = threading.RLock()

        # ── Dirty flag for deferred FAISS rebuild ──
        self._dirty = False
        self._additions_since_rebuild = 0

    # ── Public API ───────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Number of vectors in the index."""
        return len(self._ids)

    def add(
        self,
        id: str,
        embedding: np.ndarray,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a vector to the index.

        If the ID already exists, the vector and metadata are updated
        in place (upsert semantics).

        Args:
            id: Unique identifier (belief ID, memory ID, etc.)
            embedding: Raw 384D embedding (will be L2-normalized)
            metadata: Arbitrary metadata dict (content, importance, etc.)
        """
        emb = np.asarray(embedding, dtype=np.float32).ravel()

        # Ensure correct dimensionality
        if len(emb) != self.dim:
            logger.warning(
                "Embedding dim %d != expected %d for id=%s. Truncating/padding.",
                len(emb), self.dim, id,
            )
            padded = np.zeros(self.dim, dtype=np.float32)
            n = min(len(emb), self.dim)
            padded[:n] = emb[:n]
            emb = padded

        # L2 normalize for cosine similarity via inner product
        norm = np.linalg.norm(emb)
        if norm > 1e-8:
            emb = emb / norm

        meta = metadata or {}

        with self._lock:
            if id in self._id_to_idx:
                # Upsert: update in place
                idx = self._id_to_idx[id]
                self._embeddings[idx] = emb
                self._metadata[id] = meta
            else:
                # New entry
                if self._embeddings is None:
                    self._embeddings = emb.reshape(1, -1)
                else:
                    self._embeddings = np.vstack([self._embeddings, emb])

                idx = len(self._ids)
                self._ids.append(id)
                self._id_to_idx[id] = idx
                self._metadata[id] = meta

            self._dirty = True
            self._additions_since_rebuild += 1

            # Auto-upgrade to FAISS when threshold is reached
            if self.count >= self.faiss_threshold:
                if self._faiss_available:
                    # Rebuild periodically (every ~5% growth or 100 adds)
                    if (self._faiss_index is None
                            or self._additions_since_rebuild >= max(100, self.count // 20)):
                        self._rebuild_faiss_index()
                elif not self._faiss_warning_emitted:
                    logger.warning(
                        "SemanticIndex has %d vectors (threshold=%d) but FAISS "
                        "is not installed. Search will use numpy brute-force "
                        "which is slower at this scale. Install with: "
                        "pip install faiss-cpu",
                        self.count, self.faiss_threshold,
                    )
                    self._faiss_warning_emitted = True

    def search(
        self,
        query: np.ndarray,
        k: int = 10,
        filter_fn: Optional[Callable[[str, Dict], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Search for the K most similar vectors by cosine similarity.

        Args:
            query: 384D query embedding (will be L2-normalized)
            k: Maximum results to return
            filter_fn: Optional predicate (id, metadata) → bool.
                       If provided, only vectors where filter_fn returns
                       True are included in results.

        Returns:
            List of dicts: {id, distance, similarity, metadata}
            Sorted by similarity descending (most similar first).
        """
        if self.count == 0:
            return []

        q = np.asarray(query, dtype=np.float32).ravel()
        if len(q) != self.dim:
            return []

        # Normalize query
        norm = np.linalg.norm(q)
        if norm < 1e-8:
            return []
        q = q / norm

        with self._lock:
            if filter_fn is not None:
                # Filtered search always uses numpy (filter before score)
                return self._numpy_search(q, k, filter_fn)

            # Unfiltered: choose strategy based on index size
            if (self._faiss_index is not None
                    and self.count >= self.faiss_threshold):
                return self._faiss_search(q, k)
            else:
                return self._numpy_search(q, k)

    def remove(self, id: str) -> bool:
        """Remove a vector from the index.

        Returns True if the vector was found and removed.
        """
        with self._lock:
            if id not in self._id_to_idx:
                return False

            idx = self._id_to_idx[id]

            # Remove from arrays
            self._embeddings = np.delete(self._embeddings, idx, axis=0)
            self._ids.pop(idx)
            del self._id_to_idx[id]
            self._metadata.pop(id, None)

            # Rebuild index mapping (indices shifted)
            self._id_to_idx = {vid: i for i, vid in enumerate(self._ids)}

            self._dirty = True

            # Invalidate FAISS index (will be rebuilt on next search if needed)
            if self._faiss_index is not None:
                self._faiss_index = None

            return True

    def contains(self, id: str) -> bool:
        """Check if a vector ID exists in the index."""
        return id in self._id_to_idx

    def get_metadata(self, id: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a vector by ID."""
        return self._metadata.get(id)

    # ── Search Implementations ───────────────────────────────────────

    def _numpy_search(
        self,
        query: np.ndarray,
        k: int,
        filter_fn: Optional[Callable] = None,
    ) -> List[Dict[str, Any]]:
        """Brute-force cosine similarity via numpy dot product.

        Exact search. O(N×D) but sub-millisecond for N < 5K, D = 384.
        """
        # Inner product on L2-normalized vectors = cosine similarity
        similarities = self._embeddings @ query  # (N,)

        if filter_fn is not None:
            # Apply filter, then rank
            mask = np.array([
                filter_fn(self._ids[i], self._metadata.get(self._ids[i], {}))
                for i in range(len(self._ids))
            ], dtype=bool)
            if not mask.any():
                return []
            # Mask out filtered vectors
            similarities = np.where(mask, similarities, -2.0)

        # Get top-k indices
        actual_k = min(k, self.count)
        if actual_k <= 0:
            return []

        # argpartition is O(N) vs O(N log N) for full sort
        if actual_k < len(similarities):
            top_indices = np.argpartition(similarities, -actual_k)[-actual_k:]
            top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]
        else:
            top_indices = np.argsort(similarities)[::-1]

        results = []
        for idx in top_indices:
            idx = int(idx)
            sim = float(similarities[idx])
            if sim <= -2.0:  # Filtered out
                continue
            vid = self._ids[idx]
            results.append({
                "id": vid,
                "similarity": sim,
                "distance": 1.0 - sim,  # cosine distance
                "metadata": self._metadata.get(vid, {}),
            })

        return results

    def _faiss_search(
        self,
        query: np.ndarray,
        k: int,
    ) -> List[Dict[str, Any]]:
        """FAISS IVF search for large collections.

        Approximate search. Much faster than brute-force at > 5K vectors.
        """
        if self._faiss_index is None:
            self._rebuild_faiss_index()
            if self._faiss_index is None:
                return self._numpy_search(query, k)

        import faiss  # noqa: F811

        q = query.reshape(1, -1).astype(np.float32)
        actual_k = min(k, self.count)

        # nprobe = sqrt(nlist) for good recall/speed tradeoff
        if hasattr(self._faiss_index, 'nprobe'):
            nlist = getattr(self._faiss_index, 'nlist', 16)
            self._faiss_index.nprobe = max(1, int(nlist ** 0.5))

        try:
            scores, indices = self._faiss_index.search(q, actual_k)
        except Exception as e:
            logger.warning("FAISS search failed: %s — falling back to numpy", e)
            return self._numpy_search(query, k)

        results = []
        for i in range(actual_k):
            idx = int(indices[0][i])
            if idx < 0 or idx >= len(self._ids):
                continue
            sim = float(scores[0][i])  # inner product = cosine sim
            vid = self._ids[idx]
            results.append({
                "id": vid,
                "similarity": sim,
                "distance": 1.0 - sim,
                "metadata": self._metadata.get(vid, {}),
            })

        return results

    def _rebuild_faiss_index(self) -> None:
        """Build or rebuild the FAISS IVF index.

        Centroids scale as sqrt(N), clamped to [16, 256].
        Training requires at least 256 vectors.
        """
        if not self._faiss_available or self._embeddings is None:
            return

        n = len(self._embeddings)
        if n < min(_IVF_TRAINING_MIN, self.faiss_threshold):
            self._faiss_index = None
            return

        try:
            import faiss  # noqa: F811

            # Dynamic centroid count: sqrt(N)
            nlist = max(_MIN_IVF_CENTROIDS, min(_MAX_IVF_CENTROIDS, int(n ** 0.5)))

            # IndexIVFFlat with inner product (cosine on normalized vectors)
            quantizer = faiss.IndexFlatIP(self.dim)
            index = faiss.IndexIVFFlat(quantizer, self.dim, nlist, faiss.METRIC_INNER_PRODUCT)

            # Train on all vectors
            index.train(self._embeddings)
            index.add(self._embeddings)

            self._faiss_index = index
            self._additions_since_rebuild = 0
            self._dirty = False

            logger.info(
                "FAISS IVF index rebuilt: %d vectors, %d centroids",
                n, nlist,
            )
        except Exception as e:
            logger.warning("FAISS index build failed: %s", e)
            self._faiss_index = None

    # ── Persistence ──────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """Persist the index to disk.

        Saves:
          - embeddings.npy — (N, dim) float32 array
          - ids.json — ordered list of vector IDs
          - metadata.json — ID → metadata mapping

        FAISS index is NOT persisted — rebuilt on load from embeddings.
        This keeps the format simple and portable.
        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        with self._lock:
            if self._embeddings is not None and len(self._ids) > 0:
                np.save(path / "embeddings.npy", self._embeddings)

                with open(path / "ids.json", "w", encoding="utf-8") as f:
                    json.dump(self._ids, f)

                with open(path / "metadata.json", "w", encoding="utf-8") as f:
                    json.dump(self._metadata, f, default=str)

                logger.info(
                    "SemanticIndex saved: %d vectors → %s",
                    self.count, path,
                )
            else:
                logger.debug("SemanticIndex: nothing to save (empty)")

    def load(self, path: Path) -> int:
        """Load a persisted index from disk.

        Returns the number of vectors loaded. If files don't exist
        or are corrupted, returns 0 and the index stays empty.
        """
        path = Path(path)
        emb_path = path / "embeddings.npy"
        ids_path = path / "ids.json"
        meta_path = path / "metadata.json"

        if not emb_path.exists() or not ids_path.exists():
            return 0

        try:
            with self._lock:
                embeddings = np.load(emb_path).astype(np.float32)

                with open(ids_path, "r", encoding="utf-8") as f:
                    ids = json.load(f)

                metadata = {}
                if meta_path.exists():
                    with open(meta_path, "r", encoding="utf-8") as f:
                        metadata = json.load(f)

                # Validate consistency
                if embeddings.shape[0] != len(ids):
                    logger.error(
                        "Index corrupt: %d embeddings but %d IDs",
                        embeddings.shape[0], len(ids),
                    )
                    return 0

                if embeddings.shape[1] != self.dim:
                    logger.error(
                        "Index dim mismatch: stored %d, expected %d",
                        embeddings.shape[1], self.dim,
                    )
                    return 0

                self._embeddings = embeddings
                self._ids = ids
                self._metadata = metadata
                self._id_to_idx = {vid: i for i, vid in enumerate(ids)}
                self._dirty = False

                # Build FAISS index if applicable
                if self._faiss_available and self.count >= self.faiss_threshold:
                    self._rebuild_faiss_index()

            logger.info(
                "SemanticIndex loaded: %d vectors from %s",
                self.count, path,
            )
            return self.count

        except Exception as e:
            logger.error("Failed to load SemanticIndex: %s", e)
            return 0

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Diagnostic statistics about the index."""
        return {
            "total_vectors": self.count,
            "dim": self.dim,
            "search_strategy": (
                "faiss_ivf" if self._faiss_index is not None
                else "numpy_brute"
            ),
            "faiss_available": self._faiss_available,
            "dirty": self._dirty,
            "memory_bytes": (
                self._embeddings.nbytes if self._embeddings is not None else 0
            ),
        }
