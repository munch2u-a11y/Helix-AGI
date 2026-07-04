# Affect Hook Audit

**Scope:** `core/affect_hook.py`

## Runtime role

- `affect_hook.py` wires the passive Plutchik-space wave packet field (`AffectField`) into the conscious pulse loop. Each pulse, it reads the Lagrangian snapshot from the pulse context, deposits a wave packet, evolves and samples the field, and distributes the steering vector and stability sentinel Ω nudges. `core/affect_hook.py:1-16`, `core/affect_hook.py:75-148`

## Hook registration and wiring

- `register_affect_hook()` instantiates the module-level `AffectField`, binds optional `sentinel` and `spatial_mind` references, and registers the post-pulse hook callback `_affect_pulse_hook` with the runtime. `core/affect_hook.py:41-72`
- The registered hook runs after every conscious pulse in `PulseLoop` when hooks are dispatched. `core/pulse_loop.py:900-920`

## Hook execution pipeline

The callback `_affect_pulse_hook()` implements a sequential 8-step pipeline:
1. **Read Lagrangian Snapshot**: Reads `ctx.lagrangian_after` or queries the sentinel as a fallback. `core/affect_hook.py:84-95`
2. **Read Stagnation**: Reads the stagnation counter from the spatial state of the context. `core/affect_hook.py:96-99`
3. **Deposit Wave Packet**: Passes the snapshot, stagnation value, and co-retrieved belief IDs to `AffectField.deposit()`. `core/affect_hook.py:100-106`
4. **Evolve Field**: Invokes `AffectField.evolve()` to diffuse, decay, and prune packets. `core/affect_hook.py:108-110`
5. **Sample Interference**: Samples the field at the current emotional coordinates using `AffectField.sample()`, caching the results to a module-local `_last_result` reference. `core/affect_hook.py:111-115`
6. **Apply Steering Vector**: Directly sets `spatial_mind._affect_steering` to apply the emotional bias force on attention movement. `core/affect_hook.py:117-120`
7. **Nudge Sentinel Omega**: Triggers omega nudges on the sentinel when thresholds are crossed:
   - Stabilizing `affect_resonance` nudge if intensity >= `RESONANCE_INTENSITY_THRESHOLD` (0.5). `core/affect_hook.py:123-125`
   - Destabilizing `affect_boredom` nudge if diversity >= `BOREDOM_DIVERSITY_THRESHOLD` (0.4). `core/affect_hook.py:127-129`
   - Stabilizing `affect_intensity_high` nudge if intensity >= `HIGH_INTENSITY_THRESHOLD` (0.8). `core/affect_hook.py:131-133`
8. **Periodic State Save**: Saves the state to disk every `SAVE_INTERVAL` (10) pulses. `core/affect_hook.py:135-138`

## Diagnostic accessors

- `get_affect_field()` exposes the active `AffectField` instance. `core/affect_hook.py:151-153`
- `get_last_result()` returns the cached `InterferenceResult` from the most recent pulse (used by the preconscious layer to extract surfaced memory IDs). `core/affect_hook.py:156-158`
