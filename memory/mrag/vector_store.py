"""Helix — Vector store shim for the semantic retrieval lane.

mRAG's VectorStore abstraction assumed it owned an embedding model and an
index (ChromaDB, Pinecone, or a dummy). Helix already has both: MiniLM-L6-v2
behind PhysicsEngine.embed_text, and the 384D SemanticIndex which every belief
and memory is registered into on the ingest path.

This shim satisfies the same three-method contract against those, so both
retrieval lanes share one embedding model and one index. Standing up a second
vector database would mean re-embedding the whole corpus and keeping two
indexes in sync for no retrieval benefit.
"""

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("helix.memory.mrag.vector_store")


class HelixVectorStore:
    """Embedding + similarity search over Helix's own SemanticIndex."""

    def __init__(self, physics_engine, dim: int = 384):
        self._physics = physics_engine
        self.dim = dim
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
            emb = np.asarray(self._physics.embed_text(key), dtype=np.float32).ravel()
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
            return np.zeros(self.dim, dtype=np.float32)

        norm = float(np.linalg.norm(emb))
        if norm > 1e-8:
            emb = emb / norm

        # Bounded so a long session can't grow this without limit.
        if len(self._query_cache) > 512:
            self._query_cache.clear()
        self._query_cache[key] = emb
        return emb

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
