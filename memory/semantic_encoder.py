"""Dedicated high-dimensional semantic encoder for Helix retrieval.

Spatial continuity and semantic retrieval have different requirements.  The
8D manifold keeps using its original 384D MiniLM projection so existing
coordinates remain stable.  This module owns the independent representation
used by mRAG, explicit semantic recall, and FAISS.

The default model is Qwen3-Embedding-0.6B through Ollama.  It produces native
1024D vectors and is already part of Helix's local-model stack.  Query inputs
receive a retrieval instruction; stored memories and beliefs do not.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Iterable, List

import numpy as np

logger = logging.getLogger("helix.memory.semantic_encoder")


DEFAULT_SEMANTIC_MODEL = "qwen3-embedding:0.6b"
DEFAULT_SEMANTIC_DIM = 1024
DEFAULT_QUERY_INSTRUCTION = (
    "Instruct: Retrieve Helix memories and beliefs that answer or illuminate "
    "the query.\nQuery: "
)


class SemanticEncoder:
    """Batch-capable Ollama embedding adapter with strict dimensionality."""

    def __init__(
        self,
        model: str | None = None,
        dim: int | None = None,
        query_instruction: str | None = None,
    ):
        self.model = model or os.environ.get(
            "HELIX_SEMANTIC_MODEL", DEFAULT_SEMANTIC_MODEL,
        )
        self.dim = int(
            dim or os.environ.get("HELIX_SEMANTIC_DIM", DEFAULT_SEMANTIC_DIM)
        )
        self.query_instruction = (
            query_instruction
            if query_instruction is not None
            else os.environ.get(
                "HELIX_SEMANTIC_QUERY_INSTRUCTION",
                DEFAULT_QUERY_INSTRUCTION,
            )
        )
        self.keep_alive = os.environ.get("HELIX_SEMANTIC_KEEP_ALIVE", "15m")
        self.batch_size = max(
            1, int(os.environ.get("HELIX_SEMANTIC_BATCH_SIZE", "16"))
        )
        self._failure_reported = False
        try:
            self.max_attempts = max(
                1, int(os.environ.get("HELIX_SEMANTIC_MAX_ATTEMPTS", "4"))
            )
        except (TypeError, ValueError):
            self.max_attempts = 4
        self.strict = os.environ.get(
            "HELIX_SEMANTIC_STRICT", "0"
        ).strip().lower() in ("1", "true", "yes", "on")

    @property
    def identity(self) -> str:
        """Stable index-version identity for this model and vector width."""
        return f"ollama:{self.model}:{self.dim}"

    def encode_query(self, text: str) -> np.ndarray:
        vectors = self.encode_queries([text])
        return vectors[0] if len(vectors) else self._zero()

    def encode_document(self, text: str) -> np.ndarray:
        vectors = self.encode_documents([text])
        return vectors[0] if len(vectors) else self._zero()

    def encode_queries(self, texts: Iterable[str]) -> np.ndarray:
        prepared = [
            self.query_instruction + self._clean(text)
            for text in texts
        ]
        return self._encode(prepared)

    def encode_documents(self, texts: Iterable[str]) -> np.ndarray:
        return self._encode([self._clean(text) for text in texts])

    def _encode(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)

        output: List[np.ndarray] = []
        try:
            import ollama

            for start in range(0, len(texts), self.batch_size):
                batch = texts[start:start + self.batch_size]
                response = None
                for attempt in range(1, self.max_attempts + 1):
                    try:
                        response = ollama.embed(
                            model=self.model,
                            input=batch,
                            dimensions=self.dim,
                            truncate=True,
                            keep_alive=self.keep_alive,
                        )
                        break
                    except Exception as exc:
                        if attempt >= self.max_attempts:
                            raise
                        delay = 2 ** attempt
                        logger.warning(
                            "Semantic encoder call failed (%d/%d): %s; retrying in %ds",
                            attempt, self.max_attempts, exc, delay,
                        )
                        time.sleep(delay)
                if response is None:
                    raise RuntimeError("semantic encoder returned no response")
                vectors = np.asarray(response.embeddings, dtype=np.float32)
                if vectors.shape != (len(batch), self.dim):
                    raise ValueError(
                        f"semantic encoder returned {vectors.shape}; "
                        f"expected {(len(batch), self.dim)}"
                    )
                output.append(self._normalize_rows(vectors))
            self._failure_reported = False
            return np.vstack(output)
        except Exception as exc:
            if not self._failure_reported:
                logger.error(
                    "1024D semantic encoder unavailable (%s). Start Ollama and "
                    "install `%s`; spatial memory remains operational.",
                    exc,
                    self.model,
                )
                self._failure_reported = True
            if self.strict:
                raise RuntimeError(
                    f"Semantic encoder unavailable after {self.max_attempts} attempts"
                ) from exc
            return np.zeros((len(texts), self.dim), dtype=np.float32)

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(str(text or "").split())

    @staticmethod
    def _normalize_rows(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return np.divide(
            vectors,
            norms,
            out=np.zeros_like(vectors),
            where=norms > 1e-8,
        ).astype(np.float32, copy=False)

    def _zero(self) -> np.ndarray:
        return np.zeros(self.dim, dtype=np.float32)
