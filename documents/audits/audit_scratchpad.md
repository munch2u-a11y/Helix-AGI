# Scratchpad Audit

**Scope:** `core/scratchpad.py`

## Runtime role

- `Scratchpad` is a markdown-backed note buffer used for reminders and short working-memory items. It is instantiated at startup, handed to both the tool executor and the preconscious layer, and summarized into prompt context each pulse. `main.py:155` (instantiation), `main.py:226` (preconscious injection), `core/scratchpad.py:31-282`

## File model

- The store is a single file named `scratchpad.md` under the provided directory. A missing file is initialized with `# Scratchpad`. `core/scratchpad.py:34-46` (`__init__` and `_write_initial`)
- `_read()` and `_write()` always operate on the full file contents rather than incremental records. `core/scratchpad.py:47-60`

## Note mutations

- `_check_postponed()` scans postponed notes and auto-reactivates them if their postpone time has elapsed. `core/scratchpad.py:61-93`
- `add_note()` appends a markdown task-list line of the form `- [ ] (n12345) ... [due: ...] <- timestamp` or `- [P] (n12345) ... [postponed_until: ...]`, where the note ID is derived from `int(datetime.now().timestamp()) % 100000`. `core/scratchpad.py:94-119`
- `complete_note()`, `remove_note()`, and `update_note()` are regex-driven edits over the entire file. `core/scratchpad.py:120-139` (`complete_note`), `core/scratchpad.py:140-156` (`remove_note`), `core/scratchpad.py:157-212` (`update_note`)
- `clear_completed()` removes checked items only, while `clear_all()` removes both checked and unchecked items. `core/scratchpad.py:213-222` (`clear_completed`), `core/scratchpad.py:223-234` (`clear_all`)

## Query and summary path

- `get_active_notes()` parses unchecked task lines (excluding postponed ones whose date has not passed) and returns a list of dictionaries with note properties. `core/scratchpad.py:235-250`
- `get_due_notes()` compares each note's `due_at` string lexicographically against `_now_iso()` and returns only overdue active notes. `core/scratchpad.py:251-256`
- `get_summary()` emits one `(REMINDER DUE: ...)` line per overdue item, then a single `(scratchpad: N active note(s): ...)` line summarizing up to three non-due notes. `core/scratchpad.py:257-281`

## Current caveats worth documenting

- Note IDs are second-granularity modulo `100000`, so two notes created in the same second will collide. `core/scratchpad.py:105`
- Due-note ordering assumes `due_at` is an ISO-like string that sorts lexicographically against `_now_iso()`. If callers write another format, sorting will not be correct. `core/scratchpad.py:23-26` (`_now_iso`), `core/scratchpad.py:251-256`

