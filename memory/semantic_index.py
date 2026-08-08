"""
Helix — High-Dimensional Semantic Index

The conscious mind's library catalog. Searched explicitly when
the agent uses memory_recall or when the Curator needs precise
semantic matching during nightly synthesis.

Separate from the 8D CognitiveSpace which handles ambient preconscious
gravity and attention dynamics. This index stores the semantic encoder's
native, uncompressed vectors for cosine similarity search.

Scalability strategy:
  - Small stores:   numpy exact inner product
  - Larger stores:  FAISS IndexFlatIP (exact, default)
  - Optional scale: FAISS IndexIVFFlat via HELIX_FAISS_MODE=ivf

The index automatically upgrades its search strategy as the
vector count grows. No manual tuning required.

Thread safety:
  The pulse loop writes while retrieval reads. A re-entrant lock protects
  vector, metadata, and FAISS row alignment.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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
    """Semantic vector index for mRAG and conscious memory search.

    Stores raw embeddings alongside metadata. Provides cosine-similarity
    search via normalized inner product.

    The index is dynamic — it grows with the agent's lifetime. Search
    strategy scales automatically:
      - Small index (< threshold): numpy dot product (exact)
      - Large index: FAISS FlatIP (exact) or optional IVFFlat

    All vectors are L2-normalized on ingest so cosine similarity
    reduces to inner product.

    Attributes:
        dim: Native embedding dimensionality of the semantic encoder
        _ids: Ordered list of vector IDs
        _embeddings: (N, dim) array of L2-normalized embeddings
        _metadata: Dict mapping ID → metadata dict
        _faiss_index: FAISS index (None if not available or < threshold)
    """

    def __init__(
        self,
        dim: int = 1024,
        faiss_threshold: int = _DEFAULT_FAISS_THRESHOLD,
        *,
        model_id: str = "",
        faiss_mode: Optional[str] = None,
    ):
        self.dim = dim
        self.faiss_threshold = faiss_threshold
        self.model_id = str(model_id or "")
        self.faiss_mode = str(
            faiss_mode or os.environ.get("HELIX_FAISS_MODE", "flat")
        ).strip().lower()
        if self.faiss_mode not in {"flat", "ivf"}:
            logger.warning(
                "Unknown HELIX_FAISS_MODE=%s; using exact flat", self.faiss_mode,
            )
            self.faiss_mode = "flat"

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
            embedding: Native semantic embedding (will be L2-normalized)
            metadata: Arbitrary metadata dict (content, importance, etc.)
        """
        emb = np.asarray(embedding, dtype=np.float32).ravel()

        # Never pad a legacy 384D vector into a 1024D index. It would look
        # valid to FAISS while defeating the native semantic representation.
        if len(emb) != self.dim:
            raise ValueError(
                f"Embedding dim {len(emb)} != expected {self.dim} for id={id}"
            )

        # L2 normalize for cosine similarity via inner product
        norm = np.linalg.norm(emb)
        if norm > 1e-8:
            emb = emb / norm

        meta = metadata or {}

        with self._lock:
            is_update = id in self._id_to_idx
            vector_changed = False
            if is_update:
                # Upsert: update in place
                idx = self._id_to_idx[id]
                vector_changed = not np.allclose(
                    self._embeddings[idx], emb, rtol=1e-5, atol=1e-6,
                )
                if vector_changed:
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
            if not is_update:
                self._additions_since_rebuild += 1

            # Auto-upgrade to FAISS when threshold is reached
            if self.count >= self.faiss_threshold:
                if self._faiss_available:
                    # New memories must be visible immediately. FAISS Flat and
                    # IVF both support append; vector-changing upserts rebuild
                    # because this index does not perform row replacement.
                    if self._faiss_index is not None and not is_update:
                        try:
                            self._faiss_index.add(emb.reshape(1, -1).astype(np.float32))
                        except Exception as e:
                            logger.warning("FAISS incremental add failed: %s", e)
                            self._faiss_index = None

                    # IVF periodically retrains centroids as the store grows.
                    # Exact FlatIP only rebuilds for changed vectors.
                    # Metadata-only touches require no FAISS write.
                    if (self._faiss_index is None or vector_changed
                            or (
                                self.faiss_mode == "ivf"
                                and self._additions_since_rebuild
                                >= max(100, self.count // 20)
                            )):
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
            query: Native-dimension query embedding (will be L2-normalized)
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
            if (
                self._faiss_index is None
                and self._faiss_available
                and self.count >= self.faiss_threshold
            ):
                self._rebuild_faiss_index()
            if (self._faiss_index is not None
                    and self.count >= self.faiss_threshold):
                return self._faiss_search(q, k)
            else:
                return self._numpy_search(q, k)

    def search_batch(
        self,
        queries: np.ndarray,
        k: int = 10,
    ) -> List[List[Dict[str, Any]]]:
        """Search several query heads in one matrix/FAISS operation.

        mRAG commonly issues a full-query head plus sentence and RAKE heads.
        Batching them avoids repeating Python and FAISS dispatch overhead and
        lets BLAS evaluate exact search as one matrix multiplication.
        """
        matrix = np.asarray(queries, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.ndim != 2 or matrix.shape[1] != self.dim:
            return [[] for _ in range(matrix.shape[0] if matrix.ndim else 0)]
        if self.count == 0 or k <= 0:
            return [[] for _ in range(len(matrix))]

        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        valid = norms[:, 0] > 1e-8
        normalized = np.divide(
            matrix,
            norms,
            out=np.zeros_like(matrix),
            where=norms > 1e-8,
        )

        with self._lock:
            actual_k = min(k, self.count)
            if (
                self._faiss_index is None
                and self._faiss_available
                and self.count >= self.faiss_threshold
            ):
                self._rebuild_faiss_index()
            if (
                self._faiss_index is not None
                and self.count >= self.faiss_threshold
            ):
                if hasattr(self._faiss_index, "nprobe"):
                    nlist = getattr(self._faiss_index, "nlist", 16)
                    self._faiss_index.nprobe = max(1, int(nlist ** 0.5))
                try:
                    scores, indices = self._faiss_index.search(
                        normalized.astype(np.float32), actual_k,
                    )
                except Exception as exc:
                    logger.warning(
                        "FAISS batch search failed: %s — falling back to numpy",
                        exc,
                    )
                    scores = normalized @ self._embeddings.T
                    indices = None
            else:
                scores = normalized @ self._embeddings.T
                indices = None

            rows: List[List[Dict[str, Any]]] = []
            for row_idx in range(len(normalized)):
                if not valid[row_idx]:
                    rows.append([])
                    continue
                if indices is None:
                    row_scores = scores[row_idx]
                    if actual_k < len(row_scores):
                        top = np.argpartition(row_scores, -actual_k)[-actual_k:]
                        top = top[np.argsort(row_scores[top])[::-1]]
                    else:
                        top = np.argsort(row_scores)[::-1]
                    row_indices = top
                    selected_scores = row_scores[top]
                else:
                    row_indices = indices[row_idx]
                    selected_scores = scores[row_idx]

                results = []
                for raw_idx, raw_score in zip(row_indices, selected_scores):
                    idx = int(raw_idx)
                    if idx < 0 or idx >= len(self._ids):
                        continue
                    similarity = float(raw_score)
                    vector_id = self._ids[idx]
                    results.append({
                        "id": vector_id,
                        "similarity": similarity,
                        "distance": 1.0 - similarity,
                        "metadata": self._metadata.get(vector_id, {}),
                    })
                rows.append(results)
            return rows

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

        Exact search. O(N×D), evaluated by optimized matrix multiplication.
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
        """FAISS inner-product search for larger collections.

        Exact under the default FlatIP mode; approximate only when the
        operator explicitly selects IVFFlat.
        """
        if self._faiss_index is None:
            self._rebuild_faiss_index()
            if self._faiss_index is None:
                return self._numpy_search(query, k)

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
        """Build or rebuild the configured FAISS inner-product index.

        Exact FlatIP is the default because retrieval recall is Helix's
        priority. IVFFlat remains an explicit large-store option; its
        centroids scale as sqrt(N), clamped to [16, 256].
        """
        if not self._faiss_available or self._embeddings is None:
            return

        n = len(self._embeddings)
        if n < self.faiss_threshold:
            self._faiss_index = None
            return

        try:
            import faiss  # noqa: F811

            if self.faiss_mode == "ivf" and n >= _IVF_TRAINING_MIN:
                nlist = max(
                    _MIN_IVF_CENTROIDS,
                    min(_MAX_IVF_CENTROIDS, int(n ** 0.5)),
                )
                quantizer = faiss.IndexFlatIP(self.dim)
                index = faiss.IndexIVFFlat(
                    quantizer,
                    self.dim,
                    nlist,
                    faiss.METRIC_INNER_PRODUCT,
                )
                index.train(self._embeddings)
                detail = f"{nlist} centroids"
            else:
                index = faiss.IndexFlatIP(self.dim)
                detail = "exact"

            index.add(self._embeddings)

            self._faiss_index = index
            self._additions_since_rebuild = 0
            self._dirty = False

            logger.info(
                "FAISS %s index rebuilt: %d vectors, %s",
                self.faiss_mode if self.faiss_mode == "ivf" else "flat",
                n,
                detail,
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
          - config.json — semantic model and index compatibility metadata

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

                with open(path / "config.json", "w", encoding="utf-8") as f:
                    json.dump({
                        "dim": self.dim,
                        "model_id": self.model_id,
                        "faiss_mode": self.faiss_mode,
                    }, f, indent=2)

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
        config_path = path / "config.json"

        if not emb_path.exists() or not ids_path.exists():
            return 0

        try:
            with self._lock:
                if config_path.exists():
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    stored_model = str(config.get("model_id", "") or "")
                    if (
                        self.model_id
                        and stored_model
                        and stored_model != self.model_id
                    ):
                        logger.warning(
                            "Semantic model mismatch: stored %s, expected %s; "
                            "index will be rebuilt",
                            stored_model,
                            self.model_id,
                        )
                        return 0

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
                f"faiss_{self.faiss_mode}" if self._faiss_index is not None
                else "numpy_brute"
            ),
            "faiss_available": self._faiss_available,
            "model_id": self.model_id,
            "dirty": self._dirty,
            "memory_bytes": (
                self._embeddings.nbytes if self._embeddings is not None else 0
            ),
        }
