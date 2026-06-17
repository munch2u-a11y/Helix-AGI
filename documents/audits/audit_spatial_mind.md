# Spatial Mind Audit

**Scope:** `core/spatial_mind.py`

## Runtime role

- `SpatialMind` owns the live attention state and two separate `CognitiveSpace` instances: one belief field and one memory field. Both spaces share the same projection matrix so the same 384D embedding lands in the same 8D region in each space. `core/spatial_mind.py:48-70`
- The pulse loop does not call `SpatialMind` directly. Runtime movement is routed through `PhysicsEngine.step_pulse()`, which embeds text, forwards the optional cluster centroid, and then delegates into `SpatialMind.pulse()`. `core/physics_engine.py:162-248`, `core/spatial_mind.py:146-270`

## Construction and persisted state

- The constructor initializes both spaces, shared attention center, previous center, velocity, gamma bounds and growth/decay rates, identity center, persistence paths, lazy embedder, and one-shot wake flashes. It also restores persisted attention state immediately. `core/spatial_mind.py:48-109`
- `save_state()` persists both spaces plus `attention_center.npy`, velocity, previous center, and gamma. `load_state()` restores those files and recomputes the identity center. `core/spatial_mind.py:582-623`

## Embedding path

- `_get_embedder()` and `embed_text()` use ChromaDB's `DefaultEmbeddingFunction`, which resolves to the same all-MiniLM-L6-v2 family used elsewhere in the repo. On failure, `embed_text()` returns a zero vector instead of raising. `core/spatial_mind.py:111-142`
- `pulse_from_text()` is just a convenience wrapper that embeds text and forwards to `pulse()`. `core/spatial_mind.py:272-296`

## Attention update path

- `pulse()` chooses the stimulus position from either the preconscious cluster centroid or the projected thought embedding, optionally blends in an incoming embedding, reads omega from the wired sentinel when present, updates both gravity fields, and delegates the force integration step to `belief_space.step_attention()`. `core/spatial_mind.py:146-228`
- Affect steering is optional and is applied only when `_affect_steering` has already been set by the affect hook. `core/spatial_mind.py:209-228`, `core/affect_hook.py:117-120`
- After the movement step, `pulse()` updates gamma based on displacement, tracks attention velocity, traces flash fragments across the previous and current centers, queries both spaces for gravity-ranked neighbors, and then updates the stored attention state. `core/spatial_mind.py:230-270`
- `_get_query_depth()` is currently hard-coded to `(10, 8, 5)` rather than being severity-dependent. `core/spatial_mind.py:300-311`

## Output formatting

- `_format()` emits at most three kinds of output in order: one-shot wake flashes, per-pulse trail flashes, then raw nearby beliefs and memories. It does not add explanatory headers to the returned context block. `core/spatial_mind.py:315-366`
- Beliefs are rendered as `-content [confidence]` style bullet lines, while memories are emitted as raw content strings. `core/spatial_mind.py:344-365`

## Bootstrap and identity center

- `bootstrap()` loads the cognitive journal directly, rehydrates points that already have stored 8D positions, and then recomputes the identity center. `core/spatial_mind.py:370-416`
- `_compute_identity_center()` prefers core beliefs (`weight == "core"` or `confidence >= 0.85`), then deep beliefs, then the centroid of all beliefs. `core/spatial_mind.py:422-453`
- `add_belief()` refreshes the identity center immediately after inserting a point; `add_memory()` does not. `core/spatial_mind.py:462-480`

## Diagnostics

- `get_spatial_health()` exposes counts, gravity-field maxima, active-anchor counts, attention velocity, and the current 8D center for the sentinel. `core/spatial_mind.py:483-500`
- `get_cognitive_coherence()` computes a bounded coherence score from average nearby belief gravity, normalized gamma, and distance from the identity center using self-calibrating EMA baselines. `core/spatial_mind.py:506-578`
- `get_stats()` reports combined belief/memory-space stats plus attention-level state such as gamma and queued wake flashes. `core/spatial_mind.py:650-662`

## Wake-up behavior

- `load_overnight_trail()` can restore the final overnight position, clear velocity, reset gamma to its minimum, queue wake flashes for the first conscious pulse, and archive the consumed trail file by renaming it with a `.loaded.json` suffix. `core/spatial_mind.py:666-730`
