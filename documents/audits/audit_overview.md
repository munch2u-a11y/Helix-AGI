# Helix Technical Audit Overview

These audits are maintained against the live runtime wiring in `main.py`, the core runtime under `core/`, and persistence/search modules under `memory/`.

## Runtime shape

- Startup wires `MemoryManager`, `BeliefStore`, `Scratchpad`, `PhysicsEngine`, `Preconscious`, `PulseLoop`, and the post-pulse hooks in `setup_helix()`. `main.py:133-230`, `main.py:325-364`
- The spatial stack is split between a wrapper (`PhysicsEngine`), a dual-space controller (`SpatialMind`), and the underlying 8D manifold (`CognitiveSpace`). `core/physics_engine.py:56-90`, `core/physics_engine.py:162-248`, `core/spatial_mind.py:48-109`, `core/cognitive_space.py:300-388`
- Persistence is append-first: memories are journaled to `CognitiveJournal`, registered into the live 8D manifold through `PhysicsEngine.register_memory_entry()`, and added to the 384D `SemanticIndex` for conscious recall. `memory/memory_manager.py:124-200`, `core/physics_engine.py:539-637`, `memory/cognitive_journal.py:61-116`, `memory/semantic_index.py:108-225`
- Pulse-time behavior is centered on `PulseLoop._main_loop()` and `PulseLoop._pulse()`, with preconscious recall, LLM/tool orchestration, memory writes, spatial updates, and post-pulse hooks all happening from there. `core/pulse_loop.py:495-657`, `core/pulse_loop.py:761-1065`

## Audit index

### Core loop

- [Pulse Loop Audit](audit_pulse_loop.md) - thread lifecycle, event queue, cadence state, rate-limit parking, context compression, and post-pulse dispatch. `core/pulse_loop.py:54-1398`
- [Preconscious Audit](audit_preconscious.md) - layered context assembly, Layer 2 anchors, spatial neighborhood recall, gravity-ranked belief injection, and dashboard-side injection snapshots. `core/preconscious.py:43-1640`

### Spatial stack

- [Spatial Mind Audit](audit_spatial_mind.md) - dual `CognitiveSpace` ownership, attention state, wake flashes, identity center, and persistence. `core/spatial_mind.py:29-730`
- [Cognitive Space Audit](audit_cognitive_space.md) - 8D projection, KDTree-backed point store, gravity field, entropy and temperature metrics, trail particles, force integration, and affordance inference. `core/cognitive_space.py:75-1755`

### Affect and post-pulse analysis

- [Affect Field Audit](audit_affect_field.md) - Plutchik-space wave packets, interference sampling, surfaced-memory reactivation, and persisted affect state. `core/affect_field.py:100-722`
- [Belief Detector Audit](audit_belief_detector.md) - post-pulse belief-signal classification, pending tag writes, and sentinel nudges. `core/belief_detector.py:77-355`

### Persistence and recall

- [Cognitive Journal Audit](audit_cognitive_journal.md) - append, checksum verification, load, and compaction behavior. `memory/cognitive_journal.py:19-241`
- [Memory Manager Audit](audit_memory_manager.md) - compatibility API, journal-backed writes, recent/history retrieval, semantic recall, and somatic echo. `memory/memory_manager.py:41-431`
- [Semantic Index Audit](audit_semantic_index.md) - normalized 384D vector storage, numpy search, FAISS upgrade path, and persistence. `memory/semantic_index.py:47-512`
- [Scratchpad Audit](audit_scratchpad.md) - markdown note storage, regex-based edits, due-note parsing, and preconscious summary generation. `core/scratchpad.py:31-209`

## Important boundary notes

- `PhysicsEngine` and `affect_hook` are part of the runtime path but do not yet have standalone audit files in this directory. Their behavior is referenced where it materially affects the audited modules. `core/physics_engine.py:38-759`, `core/affect_hook.py:41-158`
- Several module header docstrings are older than the implementation. The detailed audits below cite the executable code paths rather than the prose headers. Examples: `core/pulse_loop.py:1-25`, `core/preconscious.py:1-26`, `memory/semantic_index.py:13-19`
