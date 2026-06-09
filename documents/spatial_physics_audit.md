# Spatial Physics Audit — What's Real vs. What's Fluff

## TL;DR

The system has **a solid core**: KDTree-indexed spatial queries, a working gravity ranking formula, attention movement with inertia, and a functional temperature-based recency decay. Wrapped around that core is **a lot of physics cosplay** — Verlinde citations, Lagrangian comments, Hubble expansion, Shannon entropy, KL divergence — most of which either doesn't do what the names claim, or is computed but never read.

---

## File-by-File Breakdown

### 1. [cognitive_space.py](file:///home/nemo/Helix/core/cognitive_space.py) — The Engine Room

This is where 90% of the real work lives. ~1527 lines.

#### ✅ REAL — Does actual work

| Component | Lines | What it does | Verdict |
|---|---|---|---|
| **CognitiveProjection** | 60-158 | JL random projection: 384D → 8D via QR-orthogonalized matrix. Deterministic, distance-preserving. | **Solid.** Standard dimensionality reduction. The 8D positions are real and meaningful. |
| **KDTree spatial index** | 445-471, 1111-1151 | O(log N) nearest-neighbor queries via scipy.spatial.KDTree. Rebuilt lazily after 100 insertions. | **Solid.** This is the actual retrieval engine. |
| **`gravity_ranked_query()`** | 473-511 | Gets K nearest neighbors, re-ranks by `T × mass / d²`. | **This is the gravity formula. It works.** Temperature × mass / distance² is a sensible relevance score. Calling it "Verlinde entropic gravity" is a metaphor — it's just a weighted relevance formula. |
| **`_compute_structural_mass()`** | 1028-1054 | Returns `confidence` for beliefs, `importance` for memories. | **Real but trivial.** It's just `max(0.01, c)`. The 20-line docstring about "holographic bits" and "N holographic screens" is pure metaphor — it returns a single float. |
| **`_compute_temperature()`** | 1056-1107 | Lorentzian cooling: `T₀ / (1 + (pulse_age/τ)²)`. Different T₀ and τ for beliefs vs memories vs trails. Floor of 0.05. | **Real and important.** This is how recency decay works. The Lorentzian profile (vs exponential) means old things cool gradually rather than falling off a cliff. The "phase states" (gas/liquid/solid/plasma) in the docstring are pure metaphor — nothing reads those labels. |
| **`step_attention()`** | 812-873 | Euler integration: `v = γv + dt·ΣF`, `x = x + dt·v`. Three forces summed. | **Real.** This is how the attention center moves. The math is just `velocity += force; position += velocity` — a basic physics sim. The Euler-Lagrange framing in the comments is misleading (see below). |
| **`compute_gravity_force()`** | 875-928 | Sum of `T×m×direction/d³` for K=20 nearest points. Clamped. | **Real.** Pulls attention toward massive nearby concepts. The "Verlinde" label is metaphor. |
| **`compute_stability_force()`** | 930-957 | `-omega × (position - identity_center)` — Hooke's Law spring. | **Real.** Pulls attention back toward core beliefs. Omega from the Sentinel scales the spring constant. Simple and effective. |
| **`_compute_stimulus_force()`** | 959-975 | Unit vector toward stimulus, scaled by strength. | **Real.** Pulls attention toward new thoughts/input. |
| **`trace_cognitive_trail()`** | 1155-1206 | LERP between prev and current attention, query nearest point at each waypoint, condense to phrase fragment. | **Real.** Produces the `⟪flash⟫` fragments. Functional but could be simpler — it's basically "sample some points along the attention path." |
| **`_condense()`** | 1208-1248 | Strip preamble, take first clause, lowercase. | **Real.** Simple string processing for trail fragments. |
| **`decay_trail_particles()`** | 670-706 | Prunes trail particles older than `max_age_pulses` (default 200). | **Real.** Called during context compression to limit KDTree growth. |

#### ⚠️ REAL BUT OVERBUILT — Works, but more complex than needed

| Component | Lines | Issue |
|---|---|---|
| **GravityField (512-anchor grid)** | 165-299 | Splats mass onto 512 random anchor points, computes "potential" at arbitrary positions via inverse-distance interpolation. **In practice, `potential_at()` was only called by `gradient_at()`** (which has been deleted). The anchor grid's `density` array feeds `update_gravity_field()` but the actual ranking uses direct point-to-point gravity, not the field. The entire GravityField class is ~135 lines that could be deleted without changing behavior. |
| **`deposit_trail_particle()`** | 658-696 | Adds trail points to the KDTree. Cleaned up periodically via `decay_trail_particles()`. | **Real.** Works as intended, with pruning now active. |

#### 🎭 METAPHORICAL — Physics language, but the math doesn't match

| Component | Lines | Claim vs. Reality |
|---|---|---|
| **"Verlinde entropic gravity"** (comments at 1014-1026) | — | The comment claims `F = T × ΔS / Δx` from Verlinde 2011. The actual code does `gravity = T × mass / d²`. This is just a weighted score. It has nothing to do with holographic screens, entropic information, or the second law of thermodynamics. The mapping is: "temperature" = recency, "mass" = confidence, "gravity" = relevance score. Perfectly fine as a relevance formula — just not Verlinde gravity. |
| **"Euler-Lagrange equation"** (comments at 513-526) | — | The comment claims the system derives from `δ∫(H(q) + λ D_KL(q‖q*))dt = 0`. The actual code is `v += dt × F; x += dt × v` — forward Euler integration of Newton's second law. No Lagrangian is constructed. No variational calculus is performed. No functional is minimized. The forces are defined directly, not derived from a Lagrangian. |
| **"Shannon entropy H(q)"** (528-555) | — | The code correctly computes Shannon entropy of the gravity distribution at a point. This is called in normal operation by the background `StabilitySentinel` thread to calculate manifold entropy. |
| **"KL divergence"** (557-610) | — | Correctly computes KL divergence between gravity distributions at two positions. This is called in normal operation by the background `StabilitySentinel` thread to track identity drift. |
| **"Local temperature"** (612-654) | — | Computes `H_local / H_mean` — ratio of local entropy to baseline. This is called in normal operation by the background `StabilitySentinel` thread to continuously modulate generation parameters. |
| **"Phase states"** (docstring at 1069-1075) | — | "Gas", "liquid", "solid", "plasma" labels in the temperature docstring. Nothing reads or uses these labels. They're just comments. |

#### 💀 DEAD CODE — Computed but never consumed

| Component | Lines | Status |
|---|---|---|
| **`invalidate_entropy_baseline()`** | 647-654 | **Real.** Called during context compression in the pulse loop. |
| **`GravityField.potential_at()`** | 259-278 | Only defined in cognitive_space.py, never called. |

---

### 2. [spatial_mind.py](file:///home/nemo/Helix/core/spatial_mind.py) — The Orchestrator

~725 lines. Wraps two CognitiveSpace instances (belief + memory) with a shared attention center.

#### ✅ REAL

| Component | What it does |
|---|---|
| **Dual spaces with shared projection** (63-74) | Belief and memory spaces share the same projection matrix so positions are comparable. Correct design. |
| **Attention center + velocity + gamma** (77-89) | Position, velocity, damping. Real state that persists across pulses. |
| **`pulse()` method** (150-274) | The main pulse loop integration. Calls stimulus determination, force stepping, gamma update, trail tracing, gravity queries, formatting. **This is the actual heartbeat.** |
| **Gamma adaptation** (234-239) | Gamma grows when displacement is small (sustained focus), decays on large shifts. Simple, effective. |
| **`_format()`** (319-370) | Formats beliefs as bullets with confidence, memories as plain text, flashes as `⟪⟫` markers. No-frills output. |
| **Wake flash system** (107-110, 337-341, 656-722) | Loads overnight dream trail, sets attention to last position, injects wake fragments on first pulse. Real and functional. |
| **Identity center computation** (422-447) | Centroid of "core" beliefs, or fallback to all-belief centroid. Used as the stability spring anchor. |
| **CCI (Cognitive Coherence Index)** (499-571) | Composite of gravity density, gamma, identity drift. Self-calibrating EMA baselines. **Real and consumed by Sentinel.** |
| **`_affect_steering` force** (216-221) | Incorporates Plutchik emotional steering bias vector to attract/steer attention based on affect. **Real and set dynamically by `affect_hook`.** |

#### ⚠️ ISSUES

| Component | Issue |
|---|---|
| **`_get_query_depth()` always returns (10, 8, 5)** (304-315) | The docstring says it was "Sentinel-modulated" but it's hardcoded. This means the trail always traces 5 waypoints, regardless of cognitive state. The whole function is 12 lines that could be 1 line. |

---

### 3. [physics_engine.py](file:///home/nemo/Helix/core/physics_engine.py) — The Wrapper

~645 lines. Thin delegation layer over SpatialMind.

#### ✅ REAL

| Component | What it does |
|---|---|
| **`step_pulse()`** (150-235) | Embeds thought, delegates to SpatialMind.pulse(), deposits trail particles, extracts flashes. |
| **`query_neighborhood()`** (257-332) | Queries both spaces, merges, sorts by gravity. Primary interface for preconscious. |
| **`get_spatial_state()`** (239-253) | Returns pulse count, gamma, velocity, identity distance, flash list. Consumed by preconscious. |
| **SemanticIndex** (70-76) | Separate 384D index for conscious recall tools. Real, different purpose. |

#### ⚠️ ISSUES

| Component | Issue |
|---|---|
| **`_OmegaProxy` mock** (189-193) | Creates a fake sentinel object to pass omega. Fragile pattern. Should just pass omega as a parameter. |
| **Duplicate `embed_text()` and `_get_embedder()`** | Both PhysicsEngine and SpatialMind have identical implementations. Should share one. |

---

### 4. [belief_cosmology.py](file:///home/nemo/Helix/core/belief_cosmology.py) — Expansion Engine

~435 lines.

#### ✅ REAL

| Component | What it does |
|---|---|
| **`SCALE_FACTOR = 5.0`** (58) | Multiplies raw JL positions so gravity formula can discriminate. Well-justified with empirical data in the docstring. |
| **`compute_position()`** (71-88) | `JL_project × 5.0`. One line of real work. |
| **`GalaxyCenter` / `GalaxyMap`** (144-435) | Clusters beliefs by their nearest Layer 2 term, computes mass-weighted centroids. Used by preconscious for cluster-aware retrieval. **Real and functional.** |

#### ⚠️ QUESTIONABLE

| Component | Issue |
|---|---|
| **Hubble Expansion** (60-128) | `(1 + 0.0005)^delta` — positions inflate as more beliefs are created. The idea is sound: older beliefs drift outward, creating separation. **But is `get_expanded_position()` actually called during queries?** If positions are stored once at creation and never re-expanded at query time, the expansion is meaningless. Need to verify this is wired in. |

---

## Summary Verdict

### What's Load-Bearing (Don't Touch)

```
CognitiveProjection (384D → 8D via QR-JL)
KDTree spatial index (O(log N) queries)
gravity_ranked_query() → T × mass / d²
_compute_structural_mass() → confidence/importance
_compute_recency_temperature() → Lorentzian recency decay in pulse-time
compute_shannon_entropy() → called by StabilitySentinel
compute_kl_divergence() → called by StabilitySentinel
compute_local_temperature() → called by StabilitySentinel
step_attention() → v += F; x += v with 3 forces
Gamma adaptation (focus inertia)
Identity center (stability spring anchor)
SCALE_FACTOR = 5.0 (spreads positions)
GalaxyMap (cluster-aware retrieval)
decay_trail_particles() (prunes old trail particles)
invalidate_entropy_baseline() (resets baseline on context compression)
```

### What's Decoration (Could Delete, Nothing Breaks)

```
GravityField (512-anchor grid) — never queried
potential_at() — never called
All "Verlinde" and "Euler-Lagrange" comments — pure metaphor
Phase state labels (gas/liquid/solid/plasma) — never read
```

### What Was Broken (Fixed)

> [!NOTE]
> **Hubble expansion**: `apply_hubble_expansion()` has been implemented and wired into `add_point` and state loading. Base positions and creation epochs are now correctly persisted, ensuring older beliefs expand outward dynamically.

> [!NOTE]
> **Duplicate temperature concepts**: The internal Lorentzian recency decay helper has been renamed to `_compute_recency_temperature()`, separating its name clearly from the Shannon-entropy-based `compute_local_temperature()` used by the Stability Sentinel.
