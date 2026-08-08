# Physics Engine Audit

> [!WARNING]
> **Historical code-audit snapshot.** Preserve its observations as recorded; line numbers and cross-subsystem claims may no longer match the live runtime. Use the [current architecture](../architecture_current.md) and [system manual](../../SYSTEM_MANUAL.md) for current behavior.

**Scope:** `core/physics_engine.py`

## Runtime role

- `PhysicsEngine` acts as the primary orchestrator for all spatial and semantic updates. It aggregates two separate systems: the 8D dual-space manifold controller (`SpatialMind`) and the 384D semantic search index (`SemanticIndex`). `core/physics_engine.py:38-814`
- During each pulse, `PulseLoop` invokes `PhysicsEngine.step_pulse()` to process thoughts and updates spatial coordinates, which in turn delegates to `SpatialMind.pulse()`. `core/physics_engine.py:210-298`, `core/pulse_loop.py:810-1237`

## Construction and initialization

- The constructor initializes `SpatialMind` and `SemanticIndex`, restoring saved attention/coherence parameters if a data directory is provided. `core/physics_engine.py:56-98`
- Getter/setter properties bridge access to active attention coordinates, velocities, and tracking factors (such as gamma) in `SpatialMind`. `core/physics_engine.py:99-121`

## Vector operations

- `embed_text()` yields a 384-dimensional vector utilizing the shared MiniLM embedder, returning a zero vector on failure rather than crashing. `core/physics_engine.py:179-190`
- `embed_and_project()` embeds text and projects the 384D vector directly into the 8D manifold. `core/physics_engine.py:191-196`
- Static converters `memory_point_id()` and `memory_journal_id()` convert between memory identifiers (like `123`) and point identifiers (like `mem_123`). `core/physics_engine.py:197-209`

## Pulse movement

- `step_pulse()` captures the current sentinel `omega` value using a local `_OmegaProxy` wrapper (lines 249–298) and delegates spatial updates to `SpatialMind.pulse()`. It returns a formatted spatial context block. `core/physics_engine.py:210-298`
- `get_spatial_state()` compiles diagnostic metrics, including current attention coordinates, coherence, and recent trajectory logs. `core/physics_engine.py:299-316`

## Neighbor and temporal queries

- `query_neighborhood()` runs gravity-ranked queries across both belief and memory manifolds to find nearby nodes and clusters. `core/physics_engine.py:317-392`
- `query_temporal_chain()` fetches historical memory sequences to reconstruct chronological context. `core/physics_engine.py:393-423`

## Manifold synchronization

- Internal helpers `_register_point()` and `_remove_point()` update points in both the 8D space and the 384D index. `core/physics_engine.py:424-470`, `core/physics_engine.py:471-487`
- Point management methods: `add_belief_point()` (`488–506`), `add_memory_point()` (`507–524`), `remove_belief_point()` (`525–528`), and `remove_memory_point()` (`529–532`).
- `sync_belief_record()` merges revised beliefs (e.g. from the Curator or consolidation loops) and updates coordinates in the spatial spaces. `core/physics_engine.py:533-587`
- `register_memory_entry()` embeds new memories and maps their positions based on recent attention trajectory vectors. `core/physics_engine.py:588-654`

## Semantic search and bootstrap

- `semantic_search()` uses the `SemanticIndex` to perform direct 384D searches (with optional category constraints and result count caps). `core/physics_engine.py:655-686`
- `bootstrap_from_stores()` handles initial startup hydration by processing existing SQLite beliefs and journals, mapping or projecting their initial coordinate states. `core/physics_engine.py:689-799`
- Serialization is finalized on shutdown via `save_all()`, which persists the 8D manifold state and 384D index. `core/physics_engine.py:808-814`
