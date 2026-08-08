# Belief Detector Audit

> [!WARNING]
> **Historical code-audit snapshot.** Preserve its observations as recorded; line numbers and cross-subsystem claims may no longer match the live runtime. Use the [current architecture](../architecture_current.md) and [system manual](../../SYSTEM_MANUAL.md) for current behavior.

**Scope:** `core/belief_detector.py`

## Runtime role

- `belief_detector_hook()` is a post-pulse background classifier that looks for durable belief signals in the monologue and in expressive tool outputs, then stages matching pulses in `data/pending_beliefs.json`. `core/belief_detector.py:266-337`, `core/belief_detector.py:338-376`
- The detector is wired from `main.py` via `set_dependencies(...)` and registered as a post-pulse hook. `main.py:469-475`, `core/belief_detector.py:78-98`

## Configuration and dependencies

- Scan interval, minimum thought length, pending-file path, pending queue cap, and expressive-tool whitelist are all module-level constants. `core/belief_detector.py:49-68`
- `set_dependencies()` stores the belief store, physics engine, sentinel, and GGUF manager at module scope. The real-time detector only uses the sentinel and GGUF classifier directly; other references are for compatibility. `core/belief_detector.py:78-98`

## Classification path

- The YES/NO prompt text is declared as a module-level template. `core/belief_detector.py:101-113`
- `_has_belief_signal()` फिट्स text using `_clamp_for_classifier()` and delegates to the fast GGUF local model `fast_classifier`. If unavailable, it falls back to the auxiliary LLM client. `core/belief_detector.py:123-130` (`_clamp_for_classifier`), `core/belief_detector.py:131-178` (`_has_belief_signal`)

## Pending-tag storage

- `_read_pending()` and `_write_pending()` load and write the JSON staging file. `core/belief_detector.py:179-189` (`_read_pending`), `core/belief_detector.py:190-202` (`_write_pending`)
- `_tag_pulse()` is guarded by `_pending_lock`, enforces `MAX_PENDING`, prevents duplicate pulse registrations, and records the event context before notifying the sentinel of a new belief realization. `core/belief_detector.py:203-265`

## Hook flow

- `belief_detector_hook()` checks constraints, computes the Lagrangian stability delta, extracts expressive tool outputs from context, and dispatches the classification tasks to a daemon thread. `core/belief_detector.py:266-337`
- `_run_detection()` runs detection passes on both monologue and expressive tool outputs, saving staged tags when belief signals are confirmed. `core/belief_detector.py:338-376`
- `get_pending_count()` returns the size of the staged pending beliefs list. `core/belief_detector.py:377-380`
