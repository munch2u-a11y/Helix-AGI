# Helix Technical Audit Overview

> [!WARNING]
> **Historical code-audit collection.** These files preserve earlier source-level snapshots; line numbers, dimensions, provider behavior, and cross-subsystem claims may no longer match the live runtime. Use the [current architecture](../architecture_current.md) and [system manual](../../SYSTEM_MANUAL.md) for current behavior.

These audits were written against the runtime wiring in `main.py`, the core runtime under `core/`, and persistence/search modules under `memory/` at their respective audit dates.

## Runtime shape

- Startup wires `MemoryManager`, `BeliefStore`, `Scratchpad`, `PhysicsEngine`, `Preconscious`, `PulseLoop`, and the post-pulse hooks in `setup_helix()`. `main.py:126-505`
- The spatial stack is split between a wrapper (`PhysicsEngine`), a dual-space controller (`SpatialMind`), and the underlying 8D manifold (`CognitiveSpace`). `core/physics_engine.py:56-98` (`__init__`), `core/physics_engine.py:210-298` (`step_pulse`), `core/spatial_mind.py:48-109` (`__init__`), `core/cognitive_space.py:351-394` (`__init__`)
- Persistence is append-first: memories are journaled to `CognitiveJournal`, registered into the live 8D manifold through `PhysicsEngine.register_memory_entry()`, and added to the 384D `SemanticIndex` for conscious recall. `memory/memory_manager.py:199-295` (`store`), `core/physics_engine.py:588-688` (`register_memory_entry`), `memory/cognitive_journal.py:61-117` (`append`), `memory/semantic_index.py:108-225` (add and search)
- Pulse-time behavior is centered on `PulseLoop._main_loop()` and `PulseLoop._pulse()`, with preconscious recall, LLM/tool orchestration, memory writes, spatial updates, and post-pulse hooks all happening from there. `core/pulse_loop.py:544-747` (`_main_loop`), `core/pulse_loop.py:810-1237` (`_pulse`)

## Audit index

### Core loop and orchestration

- [Pulse Loop Audit](audit_pulse_loop.md) - thread lifecycle, event queue, cadence state, rate-limit parking, context compression, and post-pulse dispatch. `core/pulse_loop.py:54-1737`
- [Preconscious Audit](audit_preconscious.md) - layered context assembly, Layer 2 anchors, spatial neighborhood recall, gravity-ranked belief injection, and dashboard-side injection snapshots. `core/preconscious.py:46-2140`

### Spatial and physics stack

- [Physics Engine Audit](audit_physics_engine.md) - dual-space coordination, text embeddings, neighborhood/temporal queries, and boot hydration. `core/physics_engine.py:38-814`
- [Spatial Mind Audit](audit_spatial_mind.md) - dual `CognitiveSpace` ownership, attention state, wake flashes, identity center, and persistence. `core/spatial_mind.py:29-743`
- [Cognitive Space Audit](audit_cognitive_space.md) - 8D projection, KDTree-backed point store, gravity field, entropy and temperature metrics, trail particles, force integration, and affordance inference. `core/cognitive_space.py:87-1802`

### Affect and post-pulse analysis

- [Affect Field Audit](audit_affect_field.md) - Plutchik-space wave packets, interference sampling, surfaced-memory reactivation, and persisted affect state. `core/affect_field.py:101-727`
- [Affect Hook Audit](audit_affect_hook.md) - post-pulse hook integration, Lagrangian snapshot read, and stability sentinel Ω nudges. `core/affect_hook.py:41-159`
- [Belief Detector Audit](audit_belief_detector.md) - post-pulse belief-signal classification, pending tag writes, and sentinel nudges. `core/belief_detector.py:78-380`

### Persistence and database layer

- [Cognitive Journal Audit](audit_cognitive_journal.md) - append, checksum verification, load, and compaction behavior. `memory/cognitive_journal.py:22-236`
- [Belief Store Audit](audit_belief_store.md) - database layer, normalized schemas, category I/O, and stability-based confidence adjustments. `memory/belief_store.py:108-1420`
- [Memory Manager Audit](audit_memory_manager.md) - compatibility API, journal-backed writes, recent/history retrieval, semantic recall, and somatic echo. `memory/memory_manager.py:21-613`
- [Semantic Index Audit](audit_semantic_index.md) - normalized 384D vector storage, numpy search, FAISS upgrade path, and persistence. `memory/semantic_index.py:47-513`
- [Scratchpad Audit](audit_scratchpad.md) - markdown note storage, regex-based edits, due-note parsing, and preconscious summary generation. `core/scratchpad.py:31-282`

### Dynamic tool learning

- [Tool Learning Audit](audit_tool_learning.md) - tool failure capture, nightly note compilation, success verification, and crystallized workflow skills. `core/tool_lesson_tracker.py:76-346`, `core/curator.py:324-396`, `tools/tool_registry.py:209-259`

## Important boundary notes

- Several module header docstrings are older than the implementation. The detailed audits cite the executable code paths rather than the prose headers. Examples: `core/pulse_loop.py:1-25`, `core/preconscious.py:1-26`, `memory/semantic_index.py:13-19`
