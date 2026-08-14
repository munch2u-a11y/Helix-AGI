# Helix Technical Audit Overview & Subsystem Map

**Documentation Status:** Current Audit Index & Architecture Map · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

This audit collection provides line-by-line source audits for every core subsystem in Helix.

---

## Live System Architecture Map

- **System Boot & Initializer**: [`main.py`](file:///home/nemo/_mrag_composite_test/main.py#L30-L150) initializes [`MemoryManager`](file:///home/nemo/_mrag_composite_test/memory/memory_manager.py#L30-L90), [`BeliefStore`](file:///home/nemo/_mrag_composite_test/memory/belief_store.py#L40-L110), [`PhysicsEngine`](file:///home/nemo/_mrag_composite_test/core/physics_engine.py#L40-L130), [`Preconscious`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L100-L200), [`ToolExecutor`](file:///home/nemo/_mrag_composite_test/tools/tool_executor.py#L30-L110), and [`PulseLoop`](file:///home/nemo/_mrag_composite_test/core/pulse_loop.py#L120-L280).
- **Dual-Space Spatial Mind & Entropic Physics**: Wrapped by [`PhysicsEngine`](file:///home/nemo/_mrag_composite_test/core/physics_engine.py#L40-L130), coordinated by [`SpatialMind`](file:///home/nemo/_mrag_composite_test/core/spatial_mind.py#L40-L110), and projected into 8D continuous space by [`CognitiveSpace`](file:///home/nemo/_mrag_composite_test/core/cognitive_space.py#L30-L120).
- **Journal Persistence & 1024D Semantic Search**: Journaled to [`cognitive_journal.jsonl`](file:///home/nemo/_mrag_composite_test/memory/cognitive_journal.py), indexed in 1024D native [`SemanticIndex`](file:///home/nemo/_mrag_composite_test/memory/semantic_index.py#L40-L120), and anchored in 8D spatial fields via [`register_memory_entry()`](file:///home/nemo/_mrag_composite_test/core/physics_engine.py#L580-L640).
- **Pulse Engine Execution**: [`PulseLoop._pulse()`](file:///home/nemo/_mrag_composite_test/core/pulse_loop.py#L810-L1230) controls event ingestion, preconscious context retrieval, conscious LLM execution, function calls, spatial attention updates, and post-pulse hooks.

---

## Subsystem Audit Index

### 1. Core Loop & Retrieval Architecture
- [Pulse Loop Audit](audit_pulse_loop.md) — Thread lifecycle, state machine, rate limits, context compression, and post-pulse hook dispatch ([`core/pulse_loop.py`](file:///home/nemo/_mrag_composite_test/core/pulse_loop.py#L120-L1400)).
- [Preconscious Injection Audit](audit_preconscious.md) — Layered context assembly, 1024D mRAG, 8D Spatial complements, multi-hop traversal (`retrieve_multihop`), and organic tone (`format_personal_opinions`) ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L100-L2450)).

### 2. Spatial & Physics Stack
- [Physics Engine Audit](audit_physics_engine.md) — Dual-space coordination, text embeddings, neighborhood queries, and temporal chaining ([`core/physics_engine.py`](file:///home/nemo/_mrag_composite_test/core/physics_engine.py#L40-L810)).
- [Spatial Mind Audit](audit_spatial_mind.md) — Attention trajectory, 8D dual-space ownership, identity center, and state persistence ([`core/spatial_mind.py`](file:///home/nemo/_mrag_composite_test/core/spatial_mind.py#L30-L750)).
- [Cognitive Space Audit](audit_cognitive_space.md) — 8D JL projection matrix, KD-Tree point store, entropic gravity field, and local temperature ([`core/cognitive_space.py`](file:///home/nemo/_mrag_composite_test/core/cognitive_space.py#L30-L1800)).

### 3. Affect & Post-Pulse Hooks
- [Affect Field Audit](audit_affect_field.md) — Plutchik 8D emotional wave packets, interference sampling, and memory reactivation ([`core/affect_field.py`](file:///home/nemo/_mrag_composite_test/core/affect_field.py#L30-L730)).
- [Affect Hook Audit](audit_affect_hook.md) — Post-pulse affect reads, Lagrangian snapshot updates, and Sentinel Ω nudges ([`core/affect_hook.py`](file:///home/nemo/_mrag_composite_test/core/affect_hook.py#L20-L160)).
- [Belief Detector Audit](audit_belief_detector.md) — Post-pulse realization scanning and pending belief tagging ([`core/belief_detector.py`](file:///home/nemo/_mrag_composite_test/core/belief_detector.py#L40-L380)).

### 4. Persistence & Database Stack
- [Cognitive Journal Audit](audit_cognitive_journal.md) — Append-only JSONL storage, SHA-256 checksums, and compaction ([`memory/cognitive_journal.py`](file:///home/nemo/_mrag_composite_test/memory/cognitive_journal.py#L20-L240)).
- [Belief Store Audit](audit_belief_store.md) — Database schema, 7 categories, 2 tiers, and stability-based confidence adjustments ([`memory/belief_store.py`](file:///home/nemo/_mrag_composite_test/memory/belief_store.py#L40-L1420)).
- [Memory Manager Audit](audit_memory_manager.md) — Compatibility API, journal-backed writes, and somatic echoes ([`memory/memory_manager.py`](file:///home/nemo/_mrag_composite_test/memory/memory_manager.py#L20-L610)).
- [Semantic Index Audit](audit_semantic_index.md) — 1024D native vector storage, numpy dot product, and FAISS FlatIP upgrade ([`memory/semantic_index.py`](file:///home/nemo/_mrag_composite_test/memory/semantic_index.py#L40-L510)).
- [Scratchpad Audit](audit_scratchpad.md) — Working memory markdown notes, regex edits, and due-note parsing ([`memory/scratchpad.py`](file:///home/nemo/_mrag_composite_test/memory/scratchpad.py#L30-L280)).

### 5. Dynamic Tooling & Agent UI Canvas
- [Tool System & Learning Audit](audit_tool_learning.md) — Hermes dynamic registry, 30s TTL caching, Agent UI Canvas (`render_ui_canvas`), and `ToolLessonTracker` failure capture ([`tools/tool_registry.py`](file:///home/nemo/_mrag_composite_test/tools/tool_registry.py#L30-L260), [`tools/ui_canvas_tool.py`](file:///home/nemo/_mrag_composite_test/tools/ui_canvas_tool.py#L25-L95), [`core/tool_lesson_tracker.py`](file:///home/nemo/_mrag_composite_test/core/tool_lesson_tracker.py#L20-L90)).
