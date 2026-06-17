# Memory Manager Audit

**Scope:** `memory/memory_manager.py`

## Runtime role

- `MemoryManager` is the compatibility layer that higher-level code calls for memory writes and retrieval. It is journal-backed, but when a `PhysicsEngine` is wired in it also registers every memory into the live 8D manifold and 384D semantic index. `memory/memory_manager.py:41-63`, `memory/memory_manager.py:124-200`, `core/physics_engine.py:539-637`

## Construction and ID handling

- The constructor creates the journal, restores the short-term memory counter from existing journal entries, and keeps `_physics` unset until `set_physics()` is called. `memory/memory_manager.py:49-63`, `memory/memory_manager.py:65-77`
- `point_id()` and `journal_id()` convert between bare journal IDs like `123` and runtime manifold/index IDs like `mem_123`. `memory/memory_manager.py:79-90`
- `_initialize_counter()` fixes the old restart-collision problem by scanning existing journal memory IDs and resuming from the highest numeric one. `memory/memory_manager.py:65-77`

## Write path

- `store()` increments the counter, normalizes `tags`, `belief_ids`, and the lagrangian snapshot, derives the pulse ID from the physics engine when possible, and forwards the write through `PhysicsEngine.register_memory_entry()` when physics is wired. `memory/memory_manager.py:124-177`, `core/physics_engine.py:539-602`
- After registration, the journal append stores the canonical 8D position, canonical 384D embedding, memory metadata, the original attention position, and the runtime point ID. `memory/memory_manager.py:178-195`
- The method returns the short-term integer ID, not the runtime `mem_*` point ID. `memory/memory_manager.py:151-200`

## Retrieval path

- `_format_memory_entry()` is the normalization step that flattens journal entries back into the legacy memory dict shape used elsewhere in the repo. `memory/memory_manager.py:101-122`
- `get_recent()` loads the full journal, filters to `type == "memory"`, optionally applies a time cutoff, reverses into newest-first order, and returns formatted entries. `memory/memory_manager.py:203-225`
- `_parse_iso()` exists partly because journal timestamps may use timezone offsets without a colon, while `datetime.fromisoformat()` expects the coloned form. `memory/memory_manager.py:26-38`, `memory/cognitive_journal.py:22-25`
- `get_historical_sample()` returns all high-importance memories up to `core_cap` plus evenly spaced timeline samples from the remainder. This is the bootstrap-oriented retrieval path, not the short-term one. `memory/memory_manager.py:227-291`

## Semantic recall

- `search_semantic()` is the conscious-recall path. It requires a wired physics engine, routes the query into `PhysicsEngine.semantic_search()`, filters to memory-type hits, then rehydrates each hit from the latest journal entry when possible. `memory/memory_manager.py:293-370`, `core/physics_engine.py:606-636`
- The optional `return_embeddings` flag passes through to `PhysicsEngine.semantic_search()` and returns the normalized 384D embedding under the `embedding` key. `memory/memory_manager.py:298-312`, `memory/memory_manager.py:360-366`
- `recall_with_somatic_echo()` wraps `search_semantic()` and nudges sentinel omega toward each recalled memory's `encoding_omega`. `memory/memory_manager.py:372-413`

## Diagnostics

- `get_stats()` only reports journal-level counts and path information; it does not expose manifold or semantic-index counts. Those belong to `PhysicsEngine` and `SemanticIndex`. `memory/memory_manager.py:415-431`
