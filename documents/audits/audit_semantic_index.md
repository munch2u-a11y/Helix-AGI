# Semantic Index Audit

**Scope:** `memory/semantic_index.py`

## Runtime role

- `SemanticIndex` is the explicit 384D cosine-similarity index used for conscious recall and some bootstrap/rebuild paths. It is separate from the ambient 8D spatial retrieval path. `memory/semantic_index.py:47-67`, `core/physics_engine.py:70-76`, `core/physics_engine.py:606-636`
- The prose comments at the top still talk about a `5K` switch point, but the live threshold is `_DEFAULT_FAISS_THRESHOLD = 2000`. Use the constant, not the older header prose, as the authoritative value. `memory/semantic_index.py:13-19`, `memory/semantic_index.py:37-45`

## Storage model

- The index stores ordered IDs, an `(N, dim)` float32 embedding matrix, metadata per ID, and an ID-to-row map for O(1) lookup. `memory/semantic_index.py:69-100`
- `add()` L2-normalizes every embedding, upserts in place when an ID already exists, and marks the FAISS side dirty for later rebuild. `memory/semantic_index.py:108-181`
- `remove()` deletes the row, rebuilds the ID map, and invalidates the FAISS index so it can be rebuilt later. `memory/semantic_index.py:226-252`

## Search routing

- `search()` normalizes the query, routes filtered searches through numpy every time, and only uses FAISS for unfiltered queries when a FAISS index exists and the vector count is at or above the threshold. `memory/semantic_index.py:182-225`
- `_numpy_search()` is exact brute-force matrix multiplication over normalized vectors and uses `np.argpartition()` for top-k extraction. `memory/semantic_index.py:264-315`
- `_faiss_search()` uses an IVF index with inner-product scoring, sets `nprobe` to `sqrt(nlist)` when possible, and falls back to numpy if the FAISS call fails. `memory/semantic_index.py:316-360`

## FAISS lifecycle

- `_rebuild_faiss_index()` refuses to train until both FAISS is available and the vector count is at least `min(_IVF_TRAINING_MIN, faiss_threshold)`. `memory/semantic_index.py:362-401`
- The number of IVF centroids is `sqrt(N)` clamped to `[_MIN_IVF_CENTROIDS, _MAX_IVF_CENTROIDS]`. `memory/semantic_index.py:379-390`
- The index is rebuilt on ingest when either the FAISS index does not exist yet or enough new additions have accumulated (`max(100, count // 20)`). `memory/semantic_index.py:165-180`

## Persistence and diagnostics

- `save()` persists `embeddings.npy`, `ids.json`, and `metadata.json` under a directory; it does not serialize the FAISS index itself. `memory/semantic_index.py:404-434`
- `load()` restores those files, validates row counts and dimensionality, rebuilds the ID map, and optionally rebuilds FAISS afterward. `memory/semantic_index.py:435-495`
- `get_stats()` reports vector count, dimensionality, active search strategy, FAISS availability, dirty flag, and raw embedding memory footprint. `memory/semantic_index.py:498-512`
