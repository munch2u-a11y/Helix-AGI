# Memory Manager Audit

**File:** `memory/memory_manager.py`

---

### Overview

The `MemoryManager` module has been heavily refactored. Historically, it managed fragmented SQLite and ChromaDB databases. It now serves as a **compatibility wrapper** around the unified `CognitiveJournal`, while also maintaining an active connection to the `SemanticIndex` for 384D exact-match semantic search.

By mirroring the original `MemoryManager` public API, higher-level components (like native tools, preconscious injection, and the pulse loop) can continue calling `store()` and `get_recent()` without modification, while all underlying data is seamlessly routed to the append-only JSONL journal and the 384D FAISS index.

---

### Initialization (`__init__` lines 34-49)

- Accepts a `data_dir` and ensures the directory exists.
- Instantiates the `CognitiveJournal` passing the `data_dir`.
- Initializes `self._st_counter = 0`.
- Initializes `self._physics = None` (to be injected during bootstrap).

**Why:** The `_st_counter` is an in-memory counter used to emulate the auto-incrementing short-term IDs that the old SQLite database provided. This maintains backward compatibility. The `_physics` reference is required so that the `MemoryManager` can leverage the 384D semantic vector index during memory recall tool execution.

---

### Physics Injection (`set_physics` lines 50-57)

- Injects the live `PhysicsEngine` instance after both are constructed.
- Wires the memory manager to the `SemanticIndex` so the `memory_recall` tool can perform exact 384D cosine similarity searches.

---

### Primary Write (`store` lines 60-125)

```python
self.journal.append_memory(
    id=str(st_id),
    content=content,
    position_8d=position_8d or [],
    pulse_id=0,  # caller can later update if needed
    lagrangian=lagrangian_snapshot,
    metadata={
        "memory_type": memory_type,
        "source": source,
        "importance": importance,
        "tags": tags,
        "belief_ids": belief_ids,
        "created_at": now,
    },
)
```

- Accepts content, tags, lagrangian snapshots, and 8D coordinates.
- Increments `_st_counter` to generate a new `st_id`.
- Routes the write directly to `journal.append_memory`.
- **Note:** `pulse_id` is hardcoded to `0` here; if the caller needs a specific pulse ID, they must update it later.
- If an `embedding_384d` is passed in (via `SomaticScribe`), it registers it in the live `SemanticIndex` immediately for instant recall.

---

### Data Retrieval (`get_recent` lines 127-158)

- Calls `self.journal.load_all()` which reads and checksum-verifies the entire journal.
- Filters the entries to only those where `type == "memory"`.
- If `minutes_back` is provided, filters out entries older than `cutoff_dt` by performing string comparisons on the ISO-8601 `timestamp`.
- Reverses the list to return the newest entries first, capped by `limit`.
- Transforms the journal's nested dictionary schema back into the flat dictionary schema expected by the legacy API.

---

### Semantic Search (`search_semantic` lines 215-263)

- **New Functionality**: Previously a compatibility stub, this is now a fully functional semantic search hooked into the `SemanticIndex`.
- Calls `self._physics.semantic_search()` to perform an exact FAISS cosine similarity match in 384D space.
- Returns normalized metadata chunks back to the LLM's `memory_recall` tool.

---

### Mermaid Diagram – Memory Flow

```mermaid
flowchart LR
    A[Pulse Loop / Tools] -->|store()| B[MemoryManager]
    B -->|Generate st_id| C[Format Legacy Metadata]
    C -->|append_memory()| D[(CognitiveJournal)]
    C -->|Add Vector| E[(384D SemanticIndex)]
    
    A -->|get_recent()| B
    B -->|load_all()| D
    D -->|Return all entries| B
    B -->|Filter & Format| A
    
    A -->|search_semantic()| B
    B -->|semantic_search()| E
    E -->|Return top K| B
```

---

### Open Questions / Clarifications

> [!CAUTION]
> **Performance of `get_recent`:** Calling `get_recent()` invokes `journal.load_all()`, which reads and JSON-parses the entire file every time. As the journal grows, this will become an I/O bottleneck. Consider implementing an in-memory cache or an append-tail reader if `get_recent` is called frequently during the pulse loop.

> [!WARNING]
> **Loss of `st_counter` State:** The `_st_counter` is initialized to `0` on boot. Every time Helix restarts, memory IDs will reset to `1`, `2`, `3`, etc. This means `id` collisions are guaranteed across restarts. The journal handles this by treating them as the *same* memory and `compact()` will obliterate the older ones. **This is a critical bug** if short-term IDs are meant to be unique across sessions.

---

*End of Memory Manager audit.*
