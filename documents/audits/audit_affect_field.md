# Affect Field Audit

**Scope:** `core/affect_field.py`

## Runtime role

- `AffectField` stores emotional traces as 8D Plutchik-space wave packets. Packets diffuse, decay, interfere at sample time, and can surface memory IDs when multiple resonant packets overlap with co-retrieved memories. `core/affect_field.py:258-722`
- The field itself is passive. Runtime distribution into `SpatialMind` and the sentinel happens in `core/affect_hook.py`, which deposits a packet every pulse, evolves the field, samples it, then forwards the steering vector and omega nudges. `core/affect_hook.py:41-137`

## Constants and dimensional layout

- The eight dimensions are `joy`, `trust`, `fear`, `surprise`, `sadness`, `disgust`, `anger`, and `anticipation`, with non-zero neutral baselines for `joy`, `trust`, and `anticipation`. `core/affect_field.py:42-52`
- Diffusion rates, phase frequencies, decay parameters, sampling thresholds, and hard caps are fixed at module scope. `core/affect_field.py:54-89`

## WavePacket state and evolution

- `WavePacket` stores the Plutchik position, deposit pulse, anchor memories, blended memories, sigma, and the current amplitude. `core/affect_field.py:100-121`
- `intensity` measures average deviation from the neutral baselines; `importance` scales with anchored-memory count. `core/affect_field.py:140-156`
- `evolve()` expands sigma per dimension and decays amplitude with a halflife derived from both emotional intensity and anchor-memory importance. `core/affect_field.py:162-176`
- `spatial_contribution()` evaluates an anisotropic Gaussian contribution at a sample point, and `is_alive()` prunes any packet whose amplitude falls below `PRUNE_THRESHOLD`. `core/affect_field.py:181-200`

## Deposit path

- `deposit()` converts a lagrangian snapshot into an 8D position, updates the previous snapshot cache, computes intensity from deviation from neutral, creates a `WavePacket`, appends it, and enforces the `MAX_PACKETS` cap by dropping low-amplitude packets. `core/affect_field.py:297-353`
- `_lagrangian_to_plutchik()` derives the eight emotional coordinates from omega, entropy, KL divergence, total instability, local temperature, and the delta between the previous and current lagrangian snapshot. `core/affect_field.py:355-424`
- Current implementation note: `amplitude = max(0.1, intensity)` happens before `if amplitude < 0.05`, so the low-intensity early return is effectively dead code. `core/affect_field.py:325-335`

## Evolution and sampling

- `evolve()` increments the pulse counter, clears the summary cache, evolves every packet, blends in newly accessed memory IDs when the packet is still strong enough, and then drops packets below the prune threshold. `core/affect_field.py:428-450`
- `sample()` defaults to sampling at the current affect summary, computes phase-coherent interference, builds the steering vector, checks memory-overlap strength, and returns an `InterferenceResult` with field intensity, surfaced memories, dominant affect, and the novelty/diversity signal. `core/affect_field.py:453-523`
- `_compute_semantic_overlap()` requires at least two contributing packets that overlap with the current co-retrieved memories before surfacing dormant memories. `core/affect_field.py:541-568`

## Summary and persistence

- `_compute_affect_summary()` caches weighted averages for all eight dimensions plus total amplitude and dominant affect for the current pulse. `core/affect_field.py:572-630`
- `_cognitive_diversity_signal()` is a boredom-style novelty score derived from mild disgust plus low anticipation. `core/affect_field.py:632-646`
- `save_state()` persists `current_pulse`, previous lagrangian values, stagnation counter, and the full packet list to `data/affect_field.json`; `_load_state()` restores the same structure. `core/affect_field.py:672-713`
- `to_dict()` is the thin external serialization surface used by dashboards or tools. `core/affect_field.py:714-722`
