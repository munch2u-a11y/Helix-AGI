# Semantic Index Audit

**Status:** Current Runtime Audit · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

**Scope:** [`memory/semantic_index.py`](file:///home/nemo/_mrag_composite_test/memory/semantic_index.py)

---

## 1. 1024D Native Qwen3 Vector Search

`SemanticIndex` ([`memory/semantic_index.py`](file:///home/nemo/_mrag_composite_test/memory/semantic_index.py#L40-L510)) provides precision vector catalog search:

- **1024D Qwen3 Embeddings**: Stores normalized 1024D vectors independently from 8D spatial projections.
- **Auto-Scaling Index**:
  - `0–2K vectors`: Exact numpy dot product.
  - `2K+ vectors`: FAISS `IndexFlatIP` (exact cosine similarity).
  - `Very large stores`: FAISS `IndexIVFFlat` (`HELIX_FAISS_MODE=ivf`).
