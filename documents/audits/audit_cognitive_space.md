# Cognitive Space Audit

**Scope:** `core/cognitive_space.py`

## Runtime role

- `CognitiveSpace` is the reusable 8D manifold implementation that backs both the belief field and the memory field inside `SpatialMind`. `core/cognitive_space.py:300-388`, `core/spatial_mind.py:58-70`
- The file contains four distinct concerns: deterministic 8D projection (`CognitiveProjection`), the anchor-based `GravityField`, the point-store and physics methods on `CognitiveSpace`, and an `InteractionEngine` helper at the end of the file. `core/cognitive_space.py:75-173`, `core/cognitive_space.py:180-294`, `core/cognitive_space.py:300-1615`, `core/cognitive_space.py:1637-1755`

## Projection and gravity field

- `CognitiveProjection` builds a deterministic random-orthogonal matrix, supports single and batched projection, and persists the matrix to `cognitive_projection.npy`. `core/cognitive_space.py:75-173`
- `GravityField` maintains 512 fixed anchors, splats `K_SPLAT` masses onto the nearest anchors, and interpolates local potential from `K_QUERY_ANCHORS` neighbors. `core/cognitive_space.py:61-67`, `core/cognitive_space.py:180-294`

## Point store and KDTree lifecycle

- `CognitiveSpace.__init__()` loads or creates the shared projection matrix, creates the gravity field, and initializes point storage plus lazy KDTree state. `core/cognitive_space.py:346-388`
- `add_point()` stores projected position, type, confidence/importance, recency metadata, and arbitrary metadata, and rebuilds the KDTree lazily after `KDTREE_REBUILD_THRESHOLD` additions. `core/cognitive_space.py:407-469`
- `update_access()`, `update_metadata()`, `remove_point()`, `get_point()`, and `get_position()` are thin state mutators/accessors around the in-memory point registry. `core/cognitive_space.py:470-499`
- `_rebuild_tree()` excludes points with `confidence <= 0.0` and points marked with `metadata.absorbed_by`, then rebuilds the KDTree from the remaining positions. `core/cognitive_space.py:1176-1217`

## Query path

- `query_nearby()` is pure nearest-neighbor lookup over the KDTree and returns `(point_id, distance)` pairs. `core/cognitive_space.py:507-533`
- `gravity_ranked_query()` first widens to `k_candidates` nearest neighbors, then re-ranks those candidates with `temperature * mass / distance^2`. `core/cognitive_space.py:535-574`
- Shannon entropy, KL divergence, and local temperature are computed from those gravity-ranked neighborhoods rather than from the raw KDTree distances. `core/cognitive_space.py:591-708`
- `invalidate_entropy_baseline()` clears the cached manifold-wide baseline so temperature recomputes after compression or major drift. `core/cognitive_space.py:710-717`

## Trail particles

- `deposit_trail_particle()` stores a synthetic `trail_*` point at the current attention position. Trail points use `type == "trail"`, `confidence == 0.0`, and carry their own pulse/time metadata. `core/cognitive_space.py:721-760`
- `decay_trail_particles()` removes trails older than `max_age_pulses`; `get_trail_particles()` exposes optional age and radius filtering. `core/cognitive_space.py:761-832`

## Force integration

- `step_attention()` combines four forces: gravity, stability, stimulus, and optional affect bias, then updates velocity with damping and advances position by Euler integration. `core/cognitive_space.py:837-899`
- `compute_gravity_force()` samples up to 20 nearest points, applies a softened inverse-cube force, and clamps the total force by a density-derived limit. `core/cognitive_space.py:900-960`
- `compute_stability_force()` is a simple elastic pull toward the identity center scaled by omega. `_compute_stimulus_force()` is a unit-direction pull toward the new stimulus. `core/cognitive_space.py:962-1007`

## Mass and temperature formulas

- `update_gravity_field()` recomputes the gravity field from every live point using `T * mass` as the deposited field mass. `core/cognitive_space.py:1011-1045`
- `_compute_structural_mass()` combines confidence/importance, a logarithmic reliance multiplier from `access_count + relations_count`, a short-lived recency boost, and a somatic multiplier derived from encoding omega and stability. `core/cognitive_space.py:1060-1119`
- `_compute_temperature()` uses a Lorentzian cooling profile in pulse-time, with different base temperature and tau parameters for beliefs, memories, and trails. `core/cognitive_space.py:1121-1172`

## Bootstrap, persistence, and stats

- `trace_cognitive_trail()` samples waypoint neighborhoods between two attention centers and condenses the nearest content into short flash fragments. `core/cognitive_space.py:1220-1313`
- `bootstrap_from_journal()` rehydrates points from `cognitive_journal.jsonl`, preferring stored 384D embeddings when present and falling back to the stored 8D position when not. `core/cognitive_space.py:1317-1366`
- `save_state()` and `load_state()` persist only point data; the FAISS index and gravity field are rebuilt from those points rather than serialized directly. `core/cognitive_space.py:1370-1444`
- `get_stats()` reports counts, tree status, gravity-field metrics, and aggregate mass statistics. `core/cognitive_space.py:1447-1469`

## Interaction potential and affordance helper

- `compute_interaction_potential()` now exists on `CognitiveSpace`. It inspects nearby points, prefers explicit affordance metadata (`metadata["affordance"]`, `metadata["affordances"]`, or `metadata["tool_name"]`), and otherwise falls back to conservative tool-name matching against nearby point content. `core/cognitive_space.py:1471-1615`
- `InteractionEngine.compute_affordances()` consumes those raw affordances, then applies cooldown filtering, tool-name deduplication, sentinel enrichment, and top-k truncation. `core/cognitive_space.py:1637-1755`
