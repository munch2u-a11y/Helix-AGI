# Cognitive Journal Audit

**Scope:** `memory/cognitive_journal.py`

## Runtime role

- `CognitiveJournal` is the append-first JSONL store used by `MemoryManager` and the bootstrap code in the spatial stack. `memory/cognitive_journal.py:43-236`, `memory/memory_manager.py:26-613`, `core/spatial_mind.py:370-417`, `core/cognitive_space.py:1363-1415`
- Entries are written as JSON objects with `id`, `type`, `content`, `position_8d`, `pulse_id`, `lagrangian`, `metadata`, `timestamp`, and optionally `embedding_384d`. `memory/cognitive_journal.py:61-117`

## Timestamp and checksum helpers

- `_now_iso()` emits `%Y-%m-%dT%H:%M:%S%z`, which timezone offsets are written without a colon. `memory/cognitive_journal.py:22-26`
- `_checksum()` computes a SHA-256 over the canonical JSON encoding of the entry data, and `_serialize_entry()` re-emits a payload with a freshly regenerated checksum. `memory/cognitive_journal.py:27-35` (`_checksum`), `memory/cognitive_journal.py:36-41` (`_serialize_entry`)

## Write path

- `append()` builds the entry dict, optionally stores the raw 384D embedding, serializes it with a fresh checksum, appends a single line, flushes Python buffers, and calls `os.fsync()` before returning. `memory/cognitive_journal.py:61-117`
- `append_memory()`, `append_belief()`, and `append_thought()` are thin wrappers that hard-code the `type` field and forward parameters to `append()`. `memory/cognitive_journal.py:172-236`

## Read path

- `load_all()` reads the file line by line, skips empty/malformed lines, validates the checksum, and only returns entries that pass validation. `memory/cognitive_journal.py:118-136`
- `latest_by_id()` is a one-pass reducer over `load_all()` and returns the latest surviving entry for each `id`. `memory/cognitive_journal.py:137-150`

## Compaction behavior

- `compact()` rewrites the journal from `latest_by_id()` into a `.tmp` file, reserializes every entry with a fresh checksum, flushes and `fsync()`s the temp file, and then atomically replaces the original file. `memory/cognitive_journal.py:151-171`

