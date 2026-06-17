# Cognitive Journal Audit

**Scope:** `memory/cognitive_journal.py`

## Runtime role

- `CognitiveJournal` is the append-first JSONL store used by `MemoryManager` and the bootstrap code in the spatial stack. `memory/cognitive_journal.py:43-56`, `memory/memory_manager.py:49-63`, `core/spatial_mind.py:381-415`, `core/cognitive_space.py:1317-1366`
- Entries are written as JSON objects with `id`, `type`, `content`, `position_8d`, `pulse_id`, `lagrangian`, `metadata`, `timestamp`, and optionally `embedding_384d`. `memory/cognitive_journal.py:61-111`

## Timestamp and checksum helpers

- `_now_iso()` emits `%Y-%m-%dT%H:%M:%S%z`, which means timezone offsets are written without a colon. `memory/cognitive_journal.py:22-25`
- `_checksum()` computes a SHA-256 over the canonical JSON encoding of the entry data, and `_serialize_entry()` re-emits a payload with a freshly regenerated checksum. `memory/cognitive_journal.py:27-40`

## Write path

- `append()` builds the entry dict, optionally stores the raw 384D embedding, serializes it with a fresh checksum, appends a single line, flushes Python buffers, and calls `os.fsync()` before returning. `memory/cognitive_journal.py:61-116`
- `append_memory()`, `append_belief()`, and `append_thought()` are thin wrappers that hard-code the `type` field and forward the rest of the parameters to `append()`. `memory/cognitive_journal.py:171-235`

## Read path

- `load_all()` reads the file line by line, skips empty or malformed lines, removes the `checksum` field from each decoded object, recomputes the checksum, and only returns entries that pass validation. Returned entries do not include the checksum field anymore. `memory/cognitive_journal.py:118-135`
- `latest_by_id()` is a one-pass reducer over `load_all()` and returns the latest surviving entry for each `id`. `memory/cognitive_journal.py:137-146`

## Compaction behavior

- `compact()` rewrites the journal from `latest_by_id()` into a `.tmp` file, reserializes every entry with a fresh checksum, flushes and `fsync()`s the temp file, and then atomically replaces the original file. `memory/cognitive_journal.py:151-167`
