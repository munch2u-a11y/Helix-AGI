# Belief Detector Audit

**Scope:** `core/belief_detector.py`

## Runtime role

- `belief_detector_hook()` is a post-pulse background classifier that looks for durable belief signals in the internal monologue and in expressive tool outputs, then stages matching pulses in `data/pending_beliefs.json`. `core/belief_detector.py:242-349`
- The detector is wired from `main.py` via `set_dependencies(...)` and `register_hook(...)`. `main.py:332-338`, `core/belief_detector.py:77-89`

## Configuration and dependencies

- Scan interval, minimum thought length, pending-file path, pending queue cap, and expressive-tool whitelist are all module-level constants. `core/belief_detector.py:48-67`
- `set_dependencies()` stores the belief store, physics engine, sentinel, and GGUF manager at module scope. The real-time detector only uses the sentinel and classifier path directly; the other references are kept for broader lifecycle compatibility. `core/belief_detector.py:71-89`

## Classification path

- `_has_belief_signal()` builds a strict YES/NO prompt and returns early on very short text. `core/belief_detector.py:94-113`
- Preferred path is `_gguf_manager.generate(alias="fast_classifier", ..., grammar_string='root ::= "YES" | "NO"')`. If that model is not wired, the detector falls back to `core.auxiliary_llm.get_auxiliary_client()`. It does not call Ollama directly in this module anymore. `core/belief_detector.py:114-150`

## Pending-tag storage

- `_read_pending()` and `_write_pending()` read and rewrite the entire JSON staging file. `core/belief_detector.py:155-172`
- `_tag_pulse()` is guarded by `_pending_lock`, enforces `MAX_PENDING`, suppresses duplicate `(memory_id, source)` tags, stores the thought text, tool-output text, lagrangian delta, injected belief IDs, and detection timestamp, then nudges sentinel omega through `new_belief_formed`. `core/belief_detector.py:175-238`

## Hook flow

- `belief_detector_hook()` gates on `SCAN_INTERVAL` and `MIN_THOUGHT_LENGTH`, snapshots the mutable hook context, computes an `encoding_delta` from `lagrangian_before` and `lagrangian_after`, extracts expressive tool outputs from the tool-call list, and dispatches the actual classification work to a daemon thread. `core/belief_detector.py:242-311`
- `_run_detection()` performs two passes: one on the monologue, one on the aggregated expressive tool output. Each positive pass writes its own staged tag with a distinct `source` value. `core/belief_detector.py:314-349`
- `get_pending_count()` is only a thin diagnostic helper over `_read_pending()`. `core/belief_detector.py:353-355`
