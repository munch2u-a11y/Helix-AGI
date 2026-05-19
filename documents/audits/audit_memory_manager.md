# Memory Manager Audit

**File:** `memory/memory_manager.py`

---

### Overview

The `MemoryManager` module has been heavily refactored. Historically, it managed fragmented SQLite and ChromaDB databases. It now serves as a **compatibility wrapper** around the new `CognitiveJournal`.

By mirroring the original `MemoryManager` public API, higher-level components (like tools, pre-conscious injection, and the pulse loop) can continue calling `store()` and `get_recent()` without modification, while all underlying data is seamlessly routed to the append-only JSONL journal.

---

### Initialization (`__init__` lines 34-45)

- Accepts a `data_dir` and ensures the directory exists.
- Instantiates the `CognitiveJournal` passing the `data_dir`.
- Initializes `self._st_counter = 0`.

**Why:** The `_st_counter` is an in-memory counter used to emulate the auto-incrementing short-term IDs that the old SQLite database provided. This maintains backward compatibility for systems expecting an integer return value from `store()`.

---

### Primary Write (`store` lines 48-89)

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
- **Note:** `pulse_id` is hardcoded to `0` here; if the caller needs a specific pulse ID, they must update it later (which would append a new line to the journal with the same `st_id`).

---

### Data Retrieval (`get_recent` lines 92-121)

- Calls `self.journal.load_all()` which reads and checksum-verifies the entire journal.
- Filters the entries to only those where `type == "memory"`.
- If `minutes_back` is provided, filters out entries older than `cutoff_dt` by performing string comparisons on the ISO-8601 `timestamp`.
- Reverses the list to return the newest entries first, capped by `limit`.
- Transforms the journal's nested dictionary schema back into the flat dictionary schema expected by the legacy API (`id`, `content`, `memory_type`, `source`, `importance`, `tags`, `created_at`).

---

### Compatibility Stubs (lines 124-140)

- **`search_semantic`**: Logs a warning and returns `[]`. The new journal does not provide out-of-the-box vector search. All semantic querying has been delegated to the `CognitiveSpace`'s 8D manifold.
- **`get_core_memories`**: Logs a warning and returns `[]`. Core memories are now part of the unified belief taxonomy handled elsewhere.

---

### Mermaid Diagram – Memory Flow

```mermaid
flowchart LR
    A[Pulse Loop / Tools] -->|store()| B[MemoryManager]
    B -->|Generate st_id| C[Format Legacy Metadata]
    C -->|append_memory()| D[(CognitiveJournal)]
    
    A -->|get_recent()| B
    B -->|load_all()| D
    D -->|Return all entries| B
    B -->|Filter & Format| A
```

---

### Open Questions / Clarifications

> [!CAUTION]
> **Performance of `get_recent`:** Calling `get_recent()` invokes `journal.load_all()`, which reads and JSON-parses the entire file every time. As the journal grows, this will become an I/O bottleneck. Consider implementing an in-memory cache or an append-tail reader if `get_recent` is called frequently during the pulse loop.

> [!WARNING]
> **Loss of `st_counter` State:** The `_st_counter` is initialized to `0` on boot. Every time Helix restarts, memory IDs will reset to `1`, `2`, `3`, etc. This means `id` collisions are guaranteed across restarts. The journal handles this by treating them as the *same* memory and `compact()` will obliterate the older ones. **This is a critical bug** if short-term IDs are meant to be unique across sessions.

---

*End of Memory Manager audit.*
