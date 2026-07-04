"""
Helix — Concept Reranker (Cross-Encoder Precision Gate)

A lightweight cross-encoder reranking stage for the preconscious belief
query. It slots between the two existing retrieval phases in
`Preconscious._gravity_query`:

    Phase 1  — 384D bi-encoder cosine gate  (top SEMANTIC_ANCHOR_K)
    Phase 1.5 — THIS: cross-encoder rerank   (top RERANK_TOP_N)   ← new
    Phase 2  — 8D Verlinde gravity re-rank

Why a cross-encoder and not a generative "micro-LM"?
  The per-concept search is a *retrieval* problem, not a generation
  problem. A bi-encoder (all-MiniLM) embeds the query and each belief
  independently, so it can only measure coarse topical overlap. A
  cross-encoder feeds (concept, belief) through the transformer
  *together*, attending across both, which resolves fine distinctions
  the bi-encoder blurs — e.g. "python the language" vs "python the
  snake", or "async concurrency" vs "parallel hardware". It is the
  correct small transformer for sharpening retrieval: deterministic,
  CPU-friendly (~1ms/pair), and it never invents text.

Design invariants (match the rest of the codebase):
  - Lazy load. The model is only pulled into memory on first use.
  - Graceful degradation. If sentence-transformers is missing or the
    model cannot be fetched (offline first run), the reranker disables
    itself and every call becomes an identity passthrough — retrieval
    silently falls back to the plain cosine gate.
  - CPU by default. Avoids contending with a locally-hosted conscious
    model for the GPU. Override with device="cuda" when the conscious
    model is remote and the GPU is free.
"""

import logging
import time
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger("helix.core.concept_reranker")

# Default cross-encoder. ms-marco MiniLM-L-6 is ~80MB, trained for
# query/passage relevance, and scores ~1ms/pair on CPU. Higher score =
# more relevant (raw logit; sign is not meaningful, only the ordering).
DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class ConceptReranker:
    """Cross-encoder reranker with lazy load and graceful fallback."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "cpu",
        max_length: int = 256,
    ):
        """Configure the reranker. The model is NOT loaded here.

        Args:
            model_name: HuggingFace cross-encoder id.
            device: "cpu" (default, no GPU contention) or "cuda".
            max_length: Token truncation length. Beliefs are short, so
                256 keeps scoring fast without clipping real content.
        """
        self.model_name = model_name
        self.device = device
        self.max_length = max_length

        self._model = None
        self._load_attempted = False
        self._disabled = False  # set True after a failed load — never retries

    # ── Lifecycle ─────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if the model is loaded and ready (lazy-loads on first check)."""
        if self._disabled:
            return False
        if self._model is None and not self._load_attempted:
            self._load()
        return self._model is not None

    def _load(self):
        """Lazy-load the cross-encoder. Disables self on any failure."""
        self._load_attempted = True
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            logger.info(
                "Concept reranker disabled: sentence-transformers not installed. "
                "Belief retrieval falls back to the cosine gate."
            )
            self._disabled = True
            return

        try:
            t0 = time.perf_counter()
            self._model = CrossEncoder(
                self.model_name,
                device=self.device,
                max_length=self.max_length,
            )
            logger.info(
                "Concept reranker loaded: %s on %s (%.1fs)",
                self.model_name, self.device, time.perf_counter() - t0,
            )
        except Exception as e:
            # Offline first-run, bad model id, OOM, etc. Disable and
            # let retrieval proceed on the cosine gate alone.
            logger.warning(
                "Concept reranker unavailable (%s) — falling back to cosine gate: %s",
                self.model_name, e,
            )
            self._disabled = True
            self._model = None

    # ── Scoring ───────────────────────────────────────────────────────

    def score(self, query: str, texts: Sequence[str]) -> Optional[List[float]]:
        """Score each text's relevance to the query in one batched pass.

        Returns a list of floats aligned with `texts` (higher = more
        relevant), or None if the reranker is unavailable / inputs empty.
        """
        if not query or not texts or not self.available:
            return None
        try:
            pairs = [[query, t] for t in texts]
            scores = self._model.predict(pairs, show_progress_bar=False)
            return [float(s) for s in scores]
        except Exception as e:
            logger.debug("Cross-encoder scoring failed: %s", e)
            return None

    def top_indices(
        self,
        query: str,
        texts: Sequence[str],
        top_n: int,
    ) -> Optional[List[int]]:
        """Return indices of the top_n texts by cross-encoder relevance.

        Returns None (not an empty list) when the reranker is unavailable,
        so callers can distinguish "disabled — keep your candidate set" from
        "ran and matched nothing".
        """
        scores = self.score(query, texts)
        if scores is None:
            return None
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return order[:top_n]

    def rerank(
        self,
        query: str,
        items: List[dict],
        text_fn: Callable[[dict], str] = lambda d: d.get("content", ""),
        top_n: Optional[int] = None,
        score_key: str = "rerank_score",
    ) -> List[dict]:
        """Rerank a list of candidate dicts, keeping the top_n.

        Attaches the cross-encoder score under `score_key` on each kept
        item. If the reranker is unavailable, returns `items` unchanged
        (identity passthrough) so this is always safe to call.
        """
        if not items:
            return items
        texts = [text_fn(it) for it in items]
        scores = self.score(query, texts)
        if scores is None:
            return items
        for it, s in zip(items, scores):
            it[score_key] = s
        ranked = sorted(items, key=lambda it: it.get(score_key, 0.0), reverse=True)
        return ranked[:top_n] if top_n is not None else ranked
