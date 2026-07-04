# Pulse Loop Audit

**Scope:** `core/pulse_loop.py`

## Runtime role

- `PulseLoop` owns the consciousness thread, event queue, LLM session, cadence state, context-compression policy, and post-pulse hook dispatch. `core/pulse_loop.py:54-1737`, `core/pulse_loop.py:87-241`, `core/pulse_loop.py:469-630`
- The live state machine uses `DORMANT`, `RESTING`, `ACTIVE`, and `REGULAR`. The module docstring still mentions older design notes, but those are not what the runtime executes. `core/pulse_loop.py:1-25`, `core/pulse_loop.py:138-139`, `core/pulse_loop.py:469-630`

## State, timers, and provider-dependent thresholds

- Base cadence and timeout constants live at class scope: `ACTIVE_INTERVAL`, `REGULAR_INTERVAL`, `RESTING_INTERVAL`, `DORMANT_CHECK`, `ACTIVE_TIMEOUT`, `REGULAR_TIMEOUT`, `FOCUS_DRIFT_THRESHOLD`, `TOKEN_WARNING_STEP`, and `DREAM_DELAY_SECONDS`. `core/pulse_loop.py:61-85`
- `__init__()` configures the `ContextCompressor` thresholds based on `ProviderConfig` (e.g., context window size) for local vs API-backed sessions. `core/pulse_loop.py:175-184`
- Sleep hours and default toolsets come from `config/config.json` via load helpers; the pulse loop normalizes active toolsets against live registry state. `core/pulse_loop.py:186-200`, `core/pulse_loop.py:382-468`

## Construction and owned state

- The constructor stores references to memory, belief, physics, preconscious, scratchpad, tool execution, channel routing, sentinel, and sensory cortex. It also initializes the event queue, thread control primitives, and tracking variables. `core/pulse_loop.py:87-241`
- `preconscious._active_toolsets` is set to the same mutable set instance held by the pulse loop (`_active_toolsets`), so toolset-aware hints read the live toolset state rather than a copy. `core/pulse_loop.py:201-203`

## Lifecycle and event ingress

- `start()` launches the main loop thread and chooses `RESTING` or `DORMANT` based on the sleep window. `core/pulse_loop.py:248-259`
- `stop()` stops the loop by clearing `_running`, waking the waiter, and forcing `DORMANT`. `core/pulse_loop.py:260-266`
- `wake()` promotes `DORMANT` or `RESTING` to `ACTIVE`, resets consolidation tracking, and triggers the wake event. `core/pulse_loop.py:291-304`
- `emit()` converts structured events to strings via `_translate_event()`, enqueues them, updates timing fields, wakes the loop on user messages, and nudges the sentinel. `core/pulse_loop.py:305-326`
- `_translate_event()` handles `user_message`, `tool_result`, `schedule_trigger`, and `system`, with generic fallbacks. `core/pulse_loop.py:327-361`

## Main loop

- `_main_loop()` enforces the configured sleep window, starts the nightly dream cycle after `DREAM_DELAY_SECONDS`, clears rate-limit parking on morning wake, runs one pulse per interval, checks context lifecycle, and triggers consolidation/idle behaviors. `core/pulse_loop.py:469-630`
- Rate-limit parking is checked each cycle: if `_rate_limited` is set, a fallback provider is used. `core/pulse_loop.py:535-585`
- The `REGULAR -> RESTING` transition is skipped for local providers; local runs stay on the faster cadence. `core/pulse_loop.py:595-602`

## Context lifecycle

- `_check_context_lifecycle()` monitors session token counts and schedules drift/warning alerts. Drift is logged, while compression is token-driven. `core/pulse_loop.py:631-672`
- `_compress_context()` delegates to `ContextCompressor.compress()`, updates the chat history, resets the preconscious lexicon blacklist, invalidates baseline entropy, and prunes trail particles. `core/pulse_loop.py:673-731`
- `_reset_session()` clears chat sessions, reset histories, and restarts the provider chat. `core/pulse_loop.py:267-279`

## Pulse body

- `_pulse()` increments the pulse counter, snapshots sentinel state, drains events, gets preconscious injection (annotations, ambient, surfaced IDs, centroid), builds the pulse message, sends it, and parses output. `core/pulse_loop.py:810-1238`
- Tool results returned by the chat session are re-emitted as `tool_result` events for the next pulse. `core/pulse_loop.py:928-936`
- Tool-call logging feeds `Preconscious.record_tool_usage()` and tracks tool usage over the last five pulses to adjust active cadence. `core/pulse_loop.py:942-972`
- Monologue thoughts and input events are persisted via `MemoryManager.store()` along with Plutchik coordinates, spatial centroids, and semantic embeddings. `core/pulse_loop.py:978-1110`
- Spatial dynamics are advanced via `physics.step_pulse()`, and post-pulse hooks receive a `PostPulseHookContext` snapshot. `core/pulse_loop.py:1111-1237`

## Session and tool orchestration

- `_ensure_session()` instantiates a provider chat session, constructs the system instructions from beliefs, and binds tool schemas. `core/pulse_loop.py:1285-1348`
- `_build_system_instruction()` aggregates premise, preference, and proposition beliefs to assemble the core agent identity prompt. `core/pulse_loop.py:1349-1576`
- `_send_pulse()` sends the assembled message to the LLM and manages toolsets or model parameters. `core/pulse_loop.py:1606-1661`
- `_parse_output()` handles compatibility placeholders for older text tag actions. `core/pulse_loop.py:1662-1722`

## Caveats and structure

- `_load_all_tools()` is present but live sessions build tool declarations from the registry or static definitions. `core/pulse_loop.py:1577-1605`
- The `journal_dir` constructor argument is used to initialize the directory; pulse-time memory writes flow to `MemoryManager`. `core/pulse_loop.py:127-129`, `core/pulse_loop.py:978-1110`

