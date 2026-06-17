# Scratchpad Audit

**Scope:** `core/scratchpad.py`

## Runtime role

- `Scratchpad` is a markdown-backed note buffer used for reminders and short working-memory items. It is instantiated at startup, handed to both the tool executor and the preconscious layer, and summarized into prompt context each pulse. `main.py:139-147`, `main.py:180-209`, `core/scratchpad.py:31-209`

## File model

- The store is a single file named `scratchpad.md` under the provided data directory. A missing file is initialized with `# Scratchpad`. `core/scratchpad.py:34-45`
- `_read()` and `_write()` always operate on the full file contents rather than incremental records. `core/scratchpad.py:47-58`

## Note mutations

- `add_note()` appends a markdown task-list line of the form `- [ ] (n12345) ... [due: ...] <- timestamp`, where the note ID is derived from `int(datetime.now().timestamp()) % 100000`. `core/scratchpad.py:62-83`
- `complete_note()`, `remove_note()`, and `update_note()` are regex-driven edits over the entire file, not structural markdown parsing. `core/scratchpad.py:85-139`
- `clear_completed()` removes checked items only, while `clear_all()` removes both checked and unchecked items using broader regexes. `core/scratchpad.py:141-159`

## Query and summary path

- `get_active_notes()` parses unchecked notes with a single regex and returns `id`, `content`, `due_at`, `created_at`, and `status`. `core/scratchpad.py:163-177`
- `get_due_notes()` compares each note's `due_at` string directly against `_now_iso()` and returns only overdue active notes. `core/scratchpad.py:179-183`
- `get_summary()` emits one `(REMINDER DUE: ...)` line per overdue item, then a single `(scratchpad: N active note(s): ...)` line summarizing up to three non-due notes. `core/scratchpad.py:185-209`

## Current caveats worth documenting

- Note IDs are only second-granularity modulo `100000`, so two notes created in the same second can collide. `core/scratchpad.py:71-76`
- Due-note ordering assumes `due_at` is already an ISO-like string that sorts lexicographically against `_now_iso()`. If callers write another format, `get_due_notes()` will not normalize it. `core/scratchpad.py:23-25`, `core/scratchpad.py:179-183`
