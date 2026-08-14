"""Helix — Vector store shim for the semantic retrieval lane.

mRAG's VectorStore abstraction assumed it owned an embedding model and an
index (ChromaDB, Pinecone, or a dummy). Helix already has both: a dedicated
native 1024D semantic encoder behind PhysicsEngine.embed_semantic_text, and the
SemanticIndex which every belief and memory is registered into on ingest.

This shim satisfies the same three-method contract against those, so both
retrieval lanes share one embedding model and one index. Standing up a second
vector database would mean re-embedding the whole corpus and keeping two
indexes in sync for no retrieval benefit.
"""

import logging
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("helix.memory.mrag.vector_store")


class HelixVectorStore:
    """Embedding + similarity search over Helix's own SemanticIndex."""

    def __init__(self, physics_engine, dim: int = None):
        self._physics = physics_engine
        index = getattr(physics_engine, "semantic_index", None)
        self.dim = int(dim or getattr(index, "dim", 1024))
        self._query_cache: dict = {}

    @property
    def _index(self):
        return getattr(self._physics, "semantic_index", None)

    def embed_text(self, text: str) -> np.ndarray:
        """L2-normalized embedding of `text`.

        Query embeddings are cached for the lifetime of the store: multi-head
        retrieval fires up to MAX_SEARCH_HEADS queries per pulse and heads
        repeat heavily across consecutive pulses (the same names, the same
        topic words), so this removes most of the per-pulse embedding cost.
        """
        if not text or not text.strip():
            return np.zeros(self.dim, dtype=np.float32)

        key = text[:500]
        cached = self._query_cache.get(key)
        if cached is not None:
            return cached

        try:
            emb = np.asarray(
                self._physics.embed_semantic_text(key, is_query=True),
                dtype=np.float32,
            ).ravel()
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
            return np.zeros(self.dim, dtype=np.float32)

        norm = float(np.linalg.norm(emb))
        if norm > 1e-8:
            emb = emb / norm
        else:
            # Do not cache an outage. If Ollama starts later in the session,
            # the same head must be allowed to recover on its next query.
            return np.zeros(self.dim, dtype=np.float32)

        # Bounded so a long session can't grow this without limit.
        if len(self._query_cache) > 512:
            self._query_cache.clear()
        self._query_cache[key] = emb
        return emb

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Batch and cache a set of mRAG query heads."""
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)

        vectors: List[Optional[np.ndarray]] = [None] * len(texts)
        missing_texts = []
        missing_indices = []
        for index, text in enumerate(texts):
            key = (text or "")[:500]
            cached = self._query_cache.get(key)
            if cached is not None:
                vectors[index] = cached
            else:
                missing_texts.append(key)
                missing_indices.append(index)

        if missing_texts:
            try:
                encoded = self._physics.embed_semantic_batch(
                    missing_texts,
                    is_query=True,
                )
            except Exception as exc:
                logger.warning("Batch semantic embedding failed: %s", exc)
                encoded = np.zeros((len(missing_texts), self.dim), dtype=np.float32)
            for target, key, vector in zip(missing_indices, missing_texts, encoded):
                vector = np.asarray(vector, dtype=np.float32).ravel()
                if len(vector) != self.dim:
                    vector = np.zeros(self.dim, dtype=np.float32)
                else:
                    norm = float(np.linalg.norm(vector))
                    if norm > 1e-8:
                        vector = vector / norm
                vectors[target] = vector
                if len(vector) == self.dim and float(np.linalg.norm(vector)) > 1e-8:
                    self._query_cache[key] = vector

        if len(self._query_cache) > 512:
            self._query_cache.clear()
        return np.vstack([
            vector if vector is not None else np.zeros(self.dim, dtype=np.float32)
            for vector in vectors
        ])

    def query_top_k(self, query_embedding: np.ndarray, k: int = 100) -> List[Tuple[str, float]]:
        """Top-k (id, cosine similarity) from the SemanticIndex."""
        index = self._index
        if index is None or index.count == 0:
            return []
        try:
            results = index.search(query_embedding, k=k)
        except Exception as e:
            logger.warning("SemanticIndex search failed: %s", e)
            return []
        return [(r["id"], r["similarity"]) for r in results]

    def query_top_k_filtered(
        self,
        query_embedding: np.ndarray,
        *,
        k: int = 20,
        filter_fn: Optional[Callable[[str, Dict], bool]] = None,
    ) -> List[Tuple[str, float]]:
        """Exact semantic search over a typed metadata view.

        ``SemanticIndex`` applies the predicate before ranking, so a rare
        outbound message or tool result cannot disappear merely because the
        untyped global top-k was crowded with thoughts.  This remains one
        canonical vector index; the predicate is only a disposable read view.
        """
        index = self._index
        if index is None or index.count == 0:
            return []
        try:
            results = index.search(query_embedding, k=k, filter_fn=filter_fn)
        except Exception as exc:
            logger.warning("Filtered semantic search failed: %s", exc)
            return []
        return [(record["id"], record["similarity"]) for record in results]

    def query_top_k_batch(
        self,
        query_embeddings: np.ndarray,
        k: int = 100,
    ) -> List[List[Tuple[str, float]]]:
        """Search every mRAG head in one index call."""
        index = self._index
        if index is None or index.count == 0:
            return [[] for _ in range(len(query_embeddings))]
        try:
            rows = index.search_batch(query_embeddings, k=k)
        except Exception as exc:
            logger.warning("SemanticIndex batch search failed: %s", exc)
            return [self.query_top_k(vector, k=k) for vector in query_embeddings]
        return [
            [(record["id"], record["similarity"]) for record in row]
            for row in rows
        ]

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two 1D arrays.

        Not assumed pre-normalized: the corpus normalizes what it hands back,
        but query vectors from callers outside this module may not be.
        """
        if a is None or b is None:
            return 0.0
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a < 1e-8 or norm_b < 1e-8:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def add_vectors(self, ids: List[str], embeddings: List[np.ndarray],
                    metadatas: Optional[List[dict]] = None):
        """No-op: writes happen on Helix's ingest path.

        PhysicsEngine._register_point is the single place that adds to the
        SemanticIndex, and it is called for every belief and memory as they're
        stored. A retrieval lane writing vectors here would create a second
        write path into the same index.
        """
        return None
