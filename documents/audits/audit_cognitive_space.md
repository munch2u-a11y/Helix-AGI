# Cognitive Space Audit

> [!WARNING]
> **Historical code-audit snapshot.** Preserve its observations as recorded; line numbers and cross-subsystem claims may no longer match the live runtime. Use the [current architecture](../architecture_current.md) and [system manual](../../SYSTEM_MANUAL.md) for current behavior.

**Scope:** `core/cognitive_space.py`

## Runtime role

- `CognitiveSpace` is the reusable 8D manifold implementation that backs both the belief field and the memory field inside `SpatialMind`. `core/cognitive_space.py:300-1682`, `core/spatial_mind.py:29-743`
- The file contains four distinct concerns: deterministic 8D projection (`CognitiveProjection`), the anchor-based `GravityField`, the point-store and physics methods on `CognitiveSpace`, and an `InteractionEngine` helper at the end of the file. `core/cognitive_space.py:87-173` (`CognitiveProjection`), `core/cognitive_space.py:195-299` (`GravityField`), `core/cognitive_space.py:300-1682` (`CognitiveSpace`), `core/cognitive_space.py:1683-1802` (`InteractionEngine`)

## Projection and gravity field

- `CognitiveProjection` builds a deterministic random-orthogonal matrix, supports single and batched projection, and persists the matrix to `cognitive_projection.npy`. `core/cognitive_space.py:87-173`
- `GravityField` maintains 512 fixed anchors, splats `K_SPLAT` masses onto the nearest anchors, and interpolates local potential from `K_QUERY_ANCHORS` neighbors. `core/cognitive_space.py:54-65` (constants), `core/cognitive_space.py:195-299`

## Point store and KDTree lifecycle

- `CognitiveSpace.__init__()` loads or creates the shared projection matrix, creates the gravity field, and initializes point storage plus lazy KDTree state. `core/cognitive_space.py:351-394`
- `add_point()` stores projected position, type, confidence/importance, recency metadata, and arbitrary metadata, and rebuilds the KDTree lazily after `KDTREE_REBUILD_THRESHOLD` additions. `core/cognitive_space.py:412-476`
- `update_access()`, `update_metadata()`, `remove_point()`, `get_point()`, and `get_position()` are thin state mutators/accessors around the in-memory point registry. `core/cognitive_space.py:477-519`
- `_rebuild_tree()` excludes points with `confidence <= 0.0` and points marked with `metadata.absorbed_by`, then rebuilds the KDTree from the remaining positions. `core/cognitive_space.py:1222-1265`

## Query path

- `query_nearby()` is pure nearest-neighbor lookup over the KDTree and returns `(point_id, distance)` pairs. `core/cognitive_space.py:520-547`
- `gravity_ranked_query()` first widens to `k_candidates` nearest neighbors, then re-ranks those candidates with `temperature * mass / distance^2`. `core/cognitive_space.py:548-604`
- Shannon entropy, KL divergence, and local temperature are computed from those gravity-ranked neighborhoods rather than from the raw KDTree distances. `core/cognitive_space.py:605-723`
- `invalidate_entropy_baseline()` clears the cached manifold-wide baseline so temperature recomputes after compression or major drift. `core/cognitive_space.py:724-734`

## Trail particles

- `deposit_trail_particle()` stores a synthetic `trail_*` point at the current attention position. Trail points use `type == "trail"`, `confidence == 0.0`, and carry their own pulse/time metadata. `core/cognitive_space.py:735-774`
- `decay_trail_particles()` removes trails older than `max_age_pulses`; `get_trail_particles()` exposes optional age and radius filtering. `core/cognitive_space.py:775-811` (`decay_trail_particles`), `core/cognitive_space.py:812-850` (`get_trail_particles`)

## Force integration

- `step_attention()` combines four forces: gravity, stability, stimulus, and optional affect bias, then updates velocity with damping and advances position by Euler integration. `core/cognitive_space.py:851-913`
- `compute_gravity_force()` samples up to 20 nearest points, applies a softened inverse-cube force, and clamps the total force by a density-derived limit. `core/cognitive_space.py:914-976`
- `compute_stability_force()` is a simple elastic pull toward the identity center scaled by omega. `_compute_stimulus_force()` is a unit-direction pull toward the new stimulus. `core/cognitive_space.py:977-1005` (`compute_stability_force`), `core/cognitive_space.py:1006-1025` (`_compute_stimulus_force`)

## Mass and temperature formulas

- `update_gravity_field()` recomputes the gravity field from every live point using `T * mass` as the deposited field mass. `core/cognitive_space.py:1026-1074`
- `_compute_structural_mass()` combines confidence/importance, a logarithmic reliance multiplier from `access_count + relations_count`, a short-lived recency boost, and a somatic multiplier derived from encoding omega and stability. `core/cognitive_space.py:1075-1152`
- `_compute_temperature()` uses a Lorentzian cooling profile in pulse-time, with different base temperature and tau parameters for beliefs, memories, and trails. `core/cognitive_space.py:1153-1221`

## Bootstrap, persistence, and stats

- `trace_cognitive_trail()` samples waypoint neighborhoods between two attention centers and condenses the nearest content into short flash fragments. `core/cognitive_space.py:1266-1362`
- `bootstrap_from_journal()` rehydrates points from `cognitive_journal.jsonl`, preferring stored 384D embeddings when present and falling back to the stored 8D position when not. `core/cognitive_space.py:1363-1415`
- `save_state()` and `load_state()` persist only point data; the FAISS index and gravity field are rebuilt from those points rather than serialized directly. `core/cognitive_space.py:1416-1448` (`save_state`), `core/cognitive_space.py:1449-1492` (`load_state`)
- `get_stats()` reports counts, tree status, gravity-field metrics, and aggregate mass statistics. `core/cognitive_space.py:1493-1516`

## Interaction potential and affordance helper

- `compute_interaction_potential()` now exists on `CognitiveSpace`. It inspects nearby points, prefers explicit affordance metadata (`metadata["affordance"]`, `metadata["affordances"]`, or `metadata["tool_name"]`), and otherwise falls back to conservative tool-name matching against nearby point content. `core/cognitive_space.py:1517-1682`
- `InteractionEngine.compute_affordances()` consumes those raw affordances, then applies cooldown filtering, tool-name deduplication, sentinel enrichment, and top-k truncation. `core/cognitive_space.py:1683-1802`
