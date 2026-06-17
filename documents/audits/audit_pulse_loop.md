# Pulse Loop Audit

**Scope:** `core/pulse_loop.py`

## Runtime role

- `PulseLoop` owns the consciousness thread, event queue, LLM session, cadence state, context-compression policy, and post-pulse hook dispatch. `core/pulse_loop.py:54-59`, `core/pulse_loop.py:86-236`, `core/pulse_loop.py:495-657`
- The live state machine uses `DORMANT`, `RESTING`, `ACTIVE`, and `REGULAR`. The module header still mentions older names (`QUIET`, `EMERGENCE`), but those names are not what the runtime executes. `core/pulse_loop.py:20-25`, `core/pulse_loop.py:151-159`, `core/pulse_loop.py:495-657`

## State, timers, and provider-dependent thresholds

- Base cadence and timeout constants live at class scope: `ACTIVE_INTERVAL`, `REGULAR_INTERVAL`, `RESTING_INTERVAL`, `DORMANT_CHECK`, `ACTIVE_TIMEOUT`, `REGULAR_TIMEOUT`, `FOCUS_DRIFT_THRESHOLD`, `TOKEN_WARNING_STEP`, and `DREAM_DELAY_SECONDS`. `core/pulse_loop.py:61-84`
- `__init__()` rewrites cadence for local providers (`ollama`, `llama_cpp`) and configures `ContextCompressor` thresholds differently for local vs API-backed sessions. `core/pulse_loop.py:126-138`, `core/pulse_loop.py:188-207`
- Sleep hours and default toolsets come from `config/config.json`; `core` is forced into the active toolset even if the config omits it. `core/pulse_loop.py:399-474`

## Construction and owned state

- The constructor stores references to memory, belief, physics, preconscious, scratchpad, tool execution, channel routing, sentinel, and sensory cortex. It also creates the journal directory, event queue, thread control primitives, and rolling counters for tokens, tools, and idle/nightly work. `core/pulse_loop.py:86-236`
- `preconscious._active_toolsets` is set to the same mutable set instance held by the pulse loop, so toolset-aware hints read the live toolset state rather than a copy. `core/pulse_loop.py:209-218`

## Lifecycle and event ingress

- `start()` launches the daemon thread and chooses `RESTING` or `DORMANT` based on the current sleep window. `core/pulse_loop.py:270-280`
- `stop()` stops the loop by clearing `_running`, waking the waiter, and forcing `DORMANT`. `core/pulse_loop.py:282-287`
- `wake()` promotes `DORMANT` or `RESTING` to `ACTIVE`, resets the idle-consolidation guard, and sets the wake event. `core/pulse_loop.py:309-320`
- `emit()` converts structured events to natural-language strings, enqueues them, updates timing fields, wakes the loop on user messages, and nudges the sentinel for inbound messages. `core/pulse_loop.py:323-344`
- `_translate_event()` currently special-cases `user_message`, `tool_result`, `schedule_trigger`, and `system`, with a generic fallback for anything else. `core/pulse_loop.py:345-378`

## Main loop

- `_main_loop()` enforces the configured sleep window, starts the nightly dream cycle after `DREAM_DELAY_SECONDS`, clears rate-limit parking on morning wake, runs one pulse per interval, checks context lifecycle, performs state transitions, and spawns a consolidation pass after two idle hours in `RESTING`. `core/pulse_loop.py:495-657`
- Rate-limit parking is not just a one-pulse fallback. `_rate_limited` forces the fallback model on every loop until the next wake from `DORMANT` clears it. `core/pulse_loop.py:560-609`
- The `REGULAR -> RESTING` transition is skipped for local providers; local runs stay on the faster cadence. `core/pulse_loop.py:624-629`

## Context lifecycle

- `_check_context_lifecycle()` no longer resets sessions on focus drift. Drift is only logged; compression is token-driven. `core/pulse_loop.py:658-699`
- `_compress_context()` replaces the old hard reset path with `ContextCompressor.compress()`, `replace_history()`, lexicon-blacklist reset, entropy-baseline invalidation, and trail-particle pruning in both spaces. `core/pulse_loop.py:700-758`
- `_reset_session()` still exists, but it is used only for explicit reset-tool requests, not normal context maintenance. `core/pulse_loop.py:289-307`, `core/pulse_loop.py:1023-1031`

## Pulse body

- `_pulse()` increments the pulse counter, snapshots sentinel state before the pulse, drains queued events, requests a preconscious injection and cluster centroid, optionally appends sensory-cortex output, builds the pulse message, sends it to the chat session, and handles 429 fallback logic. `core/pulse_loop.py:761-899`
- Tool results returned by the chat session are re-emitted as `tool_result` events for the next pulse rather than being injected into the same pulse. `core/pulse_loop.py:900-910`
- Tool-call logging feeds `Preconscious.record_tool_usage()` and updates `_recent_tool_counts`; three tool calls across the last three pulses are enough to treat the loop as active work and bump `RESTING` back to `REGULAR`. `core/pulse_loop.py:917-943`
- Input events and the final thought are stored through `MemoryManager.store()` with lagrangian snapshot, 8D attention position, 384D embedding, tags, and pulse ID. `core/pulse_loop.py:948-999`
- Spatial dynamics are advanced through `physics.step_pulse(...)`, and post-pulse hooks receive a `PostPulseHookContext` snapshot built from the pulse output, tool calls, spatial state, and before/after lagrangian data. `core/pulse_loop.py:1001-1065`

## Session and tool orchestration

- `_ensure_session()` creates a provider session only once, builds the system instruction from beliefs, and loads tool declarations when the provider type is `gemini`. `core/pulse_loop.py:1106-1169`
- `_build_system_instruction()` uses premise, preference, and proposition beliefs to build the durable identity prompt; per-pulse retrieved context is handled separately by the preconscious layer. `core/pulse_loop.py:1170-1286`
- `_send_pulse()` supports dynamic toolset rebuilds and generation-parameter updates when the session object exposes those capabilities. `core/pulse_loop.py:1317-1369`
- `_parse_output()` is intentionally empty. The legacy text-tag action path is kept only as a compatibility placeholder. `core/pulse_loop.py:1373-1380`

## Current caveats worth documenting

- The file still contains `_load_all_tools()`, but the live session path builds tool declarations from the registry or static declaration helpers instead of using that flat text export. `core/pulse_loop.py:1120-1146`, `core/pulse_loop.py:1288-1315`
- The `journal_dir` constructor argument is used only to create a directory; the pulse loop does not otherwise write a separate journal there. Memory persistence happens through `MemoryManager`. `core/pulse_loop.py:140-143`, `core/pulse_loop.py:948-999`
