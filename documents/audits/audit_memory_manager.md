# Memory Manager Audit

> [!WARNING]
> **Historical code-audit snapshot.** Preserve its observations as recorded; line numbers and cross-subsystem claims may no longer match the live runtime. Use the [current architecture](../architecture_current.md) and [system manual](../../SYSTEM_MANUAL.md) for current behavior.

**Scope:** `memory/memory_manager.py`

## Runtime role

- `MemoryManager` is the compatibility layer that higher-level code calls for memory writes and retrieval. It is journal-backed, but when a `PhysicsEngine` is wired in it also registers every memory into the live 8D manifold and 384D semantic index. `memory/memory_manager.py:26-613`, `memory/memory_manager.py:199-295` (`store`), `core/physics_engine.py:588-688` (`register_memory_entry`)

## Construction and ID handling

- The constructor creates the journal and initializes counter primitives; `_physics` remains unset until `set_physics()` is called. `memory/memory_manager.py:44-59` (`__init__`), `memory/memory_manager.py:87-96` (`set_physics`)
- `point_id()` and `journal_id()` convert between bare journal integer IDs like `123` and runtime manifold/index point IDs like `mem_123`. `memory/memory_manager.py:75-79` (`point_id`), `memory/memory_manager.py:80-86` (`journal_id`)
- `_initialize_counter()` scans existing journal memory IDs and resumes from the highest numeric one to prevent restarts from overwriting previous memories. `memory/memory_manager.py:60-74`

## Write path

- `store()` increments the counter, normalizes input tags and belief IDs, derives the pulse ID, blends target echo positions, and forwards writes to `PhysicsEngine.register_memory_entry()`. `memory/memory_manager.py:199-270`, `core/physics_engine.py:588-688`
- After registration, the journal entry persists the canonical 8D position, canonical 384D embedding, memory metadata, original attention position, and runtime point ID. `memory/memory_manager.py:271-290`
- The method returns the short-term integer ID of the saved memory. `memory/memory_manager.py:291-295`

## Retrieval path

- `_format_memory_entry()` flattens journal-level schema records back into the legacy memory dict format expected by higher-level modules. `memory/memory_manager.py:174-198`
- `get_recent()` loads the journal, filters by category, restricts results to `pulses_back` when specified, and returns newest entries first. `memory/memory_manager.py:296-327`
- `get_historical_sample()` performs timeline sampling for bootstrapping tasks. `memory/memory_manager.py:329-394`

## Semantic recall

- `search_semantic()` routes semantic query text through `PhysicsEngine.semantic_search()` (lines 655–686) and rehydrates retrieved point IDs from the latest journal state. `memory/memory_manager.py:395-474`
- `search_contextual()` retrieves candidate vectors, maps them to projected coordinates, re-ranks using 8D gravity, and refreshes point access counts. `memory/memory_manager.py:475-552`
- Somatic echo is implemented via `recall_with_somatic_echo()`, which drives sentinel omega toward the recalled memory's original `encoding_omega` value. `memory/memory_manager.py:553-595`

## Diagnostics

- `get_stats()` reports basic diagnostic counts and paths. `memory/memory_manager.py:596-613`
