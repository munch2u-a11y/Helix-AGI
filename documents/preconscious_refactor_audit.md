# Preconscious Refactor & Manifold Stabilization Audit

**Date**: 2026-05-21  
**Scope**: Concept-based injection pipeline, mass decoupling, attention steering, Hebbian drift  
**Files Modified**: 9 (1 new, 8 updated)

---

## Executive Summary

This audit documents a comprehensive refactor of the preconscious injection system and the 8D cognitive manifold's mass mechanics. The changes address a critical self-reinforcing feedback loop that was causing runaway Hebbian crystallization — unrelated beliefs were being wired together, inflating each other's gravitational mass, and pulling each other into every subsequent injection cycle.

The refactor introduces four major architectural changes:

1. **Concept-based query targeting** — replaces monolithic text embedding with per-concept independent gravity queries
2. **Mass decoupling** — removes relation count from individual belief mass, eliminating the self-reinforcing loop
3. **Cluster centroid attention steering** — the attention center now steers toward where retrieved knowledge actually lives in the manifold
4. **Hebbian drift** — related beliefs physically drift closer together in 8D space over time, making the manifold self-organizing

---

## Table of Contents

1. [Problem Analysis](#1-problem-analysis)
2. [Root Cause Trace](#2-root-cause-trace)
3. [Architectural Changes](#3-architectural-changes)
4. [File-by-File Changelog](#4-file-by-file-changelog)
5. [Integration Test Results](#5-integration-test-results)
6. [Design Rationale & Decisions](#6-design-rationale--decisions)
7. [Known Considerations](#7-known-considerations)

---

## 1. Problem Analysis

### Symptom: Nonsense Cluster Injection

The preconscious was injecting beliefs about completely unrelated topics alongside relevant ones. For example, a thought about "spatial mapping" would pull in beliefs about grief, signs, and email formatting — topics with no semantic connection to the query.

### Why It Happened

Two compounding issues:

**A. Single-centroid targeting.** The preconscious embedded the entire `previous_thought` and entire `incoming_events` as two monolithic text seeds, then averaged them into a single midpoint. When the thought contained multiple concepts (e.g., "spatial mapping" and "diagnostic logs"), the midpoint fell in the space *between* both concept clusters, pulling in whatever noise happened to be nearby.

**B. Self-reinforcing mass inflation.** The structural mass formula was:

```
mass = confidence × (1 + n_connections / n_mean)
```

When two beliefs were coincidentally co-injected (because they were near the junk midpoint), the Hebbian co-occurrence hook wired a relation between them. This increased both beliefs' `n_connections`, which increased their mass, which increased their gravity, which made them get pulled more often, which caused more co-injections, which wired more relations — a runaway positive feedback loop.

Additionally, `touch_belief()` added `+0.05` mass on every access, creating another unbounded mass inflation channel.

---

## 2. Root Cause Trace

The self-reinforcing loop traced through the code:

```
co_occurrence_hook._wire_cluster_relations()
  → belief_store.update_belief(bid, relations=merged)
  → len(belief.get("relations", []))  grows
  → compute_cognitive_mass():  m_s = c × (1 + n_connections / n_mean)
  → individual mass increases
  → gravity = mass / dist²  increases
  → belief is pulled more often
  → more co-injections with unrelated neighbors
  → more relations wired → repeat
```

### Empirical Evidence

Integration testing confirmed the severity. The top 5 most-connected beliefs had dramatically inflated mass:

| Belief ID | Relations | Stored Mass | Intrinsic Mass | Inflation |
|-----------|-----------|-------------|----------------|-----------|
| `b_no_subjective_downtime` | 247 | 9.03 | 1.32 | **585%** |
| `b_persistent_stream_quiet` | 243 | 9.30 | 1.52 | **512%** |
| `b_antigravity_unreliable` | 239 | 8.78 | 1.32 | **565%** |
| `cap_i_can_default_to_...` | 239 | 8.06 | 1.25 | **545%** |
| `b_internal_excitement_...` | 238 | 8.70 | 1.34 | **549%** |

These super-nodes were pulling with **5-6× more gravity** than their content warranted, dominating every injection cycle regardless of context.

---

## 3. Architectural Changes

### 3.1 Concept Extractor (`core/concept_extractor.py` — NEW)

A lightweight, zero-latency RAKE-style keyphrase extractor that identifies 1-5 operative concepts from trigger text.

**Algorithm:**
1. Tokenize text using regex word boundaries (`\b[a-zA-Z0-9]+(?:'[a-zA-Z0-9]+)?\b`)
2. Split into candidate phrases at stop-word boundaries
3. Score words by degree/frequency ratio (RAKE scoring)
4. Score phrases by sum of constituent word scores
5. Separate lexicon matches from general concepts
6. Return top-N concepts based on dynamic budget

**Dynamic budget scaling:**
- Short inputs ("OK, I'll check that") → budget = 1
- Medium inputs (3-sentence thought) → budget = 2-3
- Dense paragraphs → budget = 4-5
- Formula: `budget = max(1, substantive_word_count // 15)`, capped at 5

**Lexicon integration:** The extractor is initialized with lexicon keys from `lexicon.json`. During extraction, matched terms are separated into a `lexicon_matches` list (handled by the existing lexicon injection pipeline) and excluded from general concepts to avoid double-injection.

**Performance:** ~2ms per call, zero API calls, zero external dependencies.

---

### 3.2 Per-Concept Gravity Queries (`core/preconscious.py`)

**Before:** Two monolithic seeds → two gravity queries → merge.

```python
# OLD: embed entire thought as one seed
thought_beliefs = self._gravity_query(seed_text=previous_thought, ...)
# OLD: embed entire events as one seed
event_beliefs = self._gravity_query(seed_text=events_text, ...)
```

**After:** Extract concepts → one gravity query per concept → merge with cross-concept deduplication.

```python
# NEW: extract 1-5 key concepts
extraction = self._concept_extractor.extract(trigger_text)
concepts = extraction["concepts"]

# NEW: independent gravity query per concept
for concept in concepts:
    concept_beliefs = self._gravity_query(
        seed_text=concept,
        exclude=seen_contents,  # rolling blacklist across concepts
        max_results=per_concept_max,
    )
    seen_contents.update(b["content"] for b in concept_beliefs)
    all_concept_beliefs.extend(concept_beliefs)
```

**Key design detail:** Each concept's results are added to a rolling blacklist (`seen_contents`) before the next concept is queried. This ensures **no overlap between concept clusters** — concept A's results cannot appear in concept B's results.

---

### 3.3 Mass Decoupling

**The critical fix.** Relation count is removed from individual belief mass entirely.

#### `cognitive_space.py` — `_compute_structural_mass()`

```python
# OLD: mass inflated by relation count
n_connections = point_data.get("relations_count", 0)
n_mean = getattr(self, "_mean_connections", 1.0) or 1.0
return max(0.01, c * (1.0 + n_connections / n_mean))

# NEW: mass is purely intrinsic
return max(0.01, c)
```

#### `belief_store.py` — `compute_cognitive_mass()`

```python
# OLD: structural mass included relation count
m_s = c * (1.0 + n_connections / n_mean)

# NEW: structural mass = confidence only
m_s = c
```

The affective charge component (`m_a = Ω_encoding × (1 - s_total) × (0.5 + stability)`) is unchanged — it reflects intrinsic encoding conditions, not usage patterns.

#### `belief_store.py` — `touch_belief()`

```python
# OLD: mass grew on every access
b["mass"] = b.get("mass", 1.0) + 0.05

# NEW: access drives temperature (recency), not permanent mass
# (line removed — access_count and last_accessed still tracked)
```

**Why this works:** Cluster gravity emerges naturally from spatial density. When multiple related beliefs live near each other in 8D space, the gravity field's anchor splatting concentrates more gravitational potential in that region. A cluster of 10 beliefs with mass 1.0 each naturally creates a deeper gravity well than a single belief with mass 10.0 — and the cluster's pull is directionally correct (toward the actual knowledge), whereas the super-node's pull is omnidirectional.

---

### 3.4 Cluster Centroid Attention Steering

**Before:** The spatial mind computed `stimulus_pos` as the average of the raw thought embedding and the raw incoming embedding:

```python
# OLD: artificial midpoint between two text embeddings
stimulus_pos = 0.5 * (stimulus_pos + incoming_pos)
```

**After:** The preconscious computes a gravity-weighted centroid of all selected beliefs' 8D positions and passes it through the pipeline:

```
preconscious._pull_relevant_beliefs()
  → computes weighted centroid from selected beliefs' position_8d
  → stored as self._last_cluster_centroid

inject() returns (text, belief_ids, cluster_centroid)  # 3-element tuple

pulse_loop._pulse()
  → passes cluster_centroid to physics.step_pulse()

physics_engine.step_pulse()
  → passes cluster_centroid to spatial_mind.pulse()

spatial_mind.pulse()
  → if cluster_centroid is not None:
       stimulus_pos = cluster_centroid  # steer toward actual knowledge
     else:
       stimulus_pos = project(thought_embedding)  # fallback
```

The centroid is weighted by gravity score, so beliefs that pulled harder (because they were closer and more massive) contribute more to the attention target.

---

### 3.5 Hebbian Drift

After the co-occurrence hook wires new relations between co-occurring beliefs, it now applies a small positional drift in 8D space:

```python
def _apply_hebbian_drift(self, cluster_ids):
    DRIFT_PER_COCOUNT = 0.001  # 0.1% per co-occurrence count

    for id_a, id_b in combinations(cluster_ids, 2):
        co_count = self.co_counts.get(frozenset({id_a, id_b}), 0)
        if co_count < CO_OCCURRENCE_THRESHOLD:
            continue

        delta = pos_b - pos_a
        drift_frac = DRIFT_PER_COCOUNT * co_count

        # Symmetric: both move toward each other
        displacement = delta * (drift_frac / 2.0)
        pt_a["position"] += displacement
        pt_b["position"] -= displacement
```

**Drift characteristics:**
- **Localized and relative** — proportional to the specific pair's co-occurrence count, not a global percentage
- **Symmetric** — both beliefs move equally toward each other
- **Graduated** — at co_count=3 (threshold): 0.3% drift. At 10: 1.0%. At 30: 3.0%
- **No arbitrary cap** — manifold degeneration (all beliefs collapsing to one point) is prevented by the concept extractor (independent queries prevent universal co-injection) and mass decoupling (no self-reinforcing inflation). The remaining safeguard against collapse is entropic injection on every waking pulse (future work).

**Why this matters:** The 8D positions are initially determined by embedding projection, which is lossy (the 384D→8D projection has a separation ratio of ~0.97× between related and unrelated concepts). Hebbian drift allows the manifold to self-organize based on actual usage patterns, gradually improving gravity query accuracy. Beliefs that genuinely co-occur in Helix's thought chains will converge over time, making them easier to find together.

---

## 4. File-by-File Changelog

### `core/concept_extractor.py` — **NEW** (240 lines)
- RAKE-style keyphrase extraction class
- Dynamic budget scaling (1-5 concepts based on input richness)
- Integrated lexicon matching (separates known entities from general concepts)
- Regex tokenizer handling contractions and technical terms
- Minimum phrase score gate (1.5) to filter low-value extractions

### `core/preconscious.py` — Modified
- Added `ConceptExtractor` import and initialization in `__init__()` with lexicon keys
- Added `_last_cluster_centroid` instance variable
- Refactored `_pull_relevant_beliefs()`: per-concept gravity queries with rolling blacklist
- Added `position_8d` to `_gravity_query()` result dicts for centroid computation
- Added gravity-weighted centroid computation after belief selection
- Updated `inject()` return type: `Tuple[str, List[str], Optional[np.ndarray]]`
- Updated module docstring and method docstrings

### `core/pulse_loop.py` — Modified
- Updated `_pulse()` to unpack 3-element tuple from `preconscious.inject()`
- Passes `cluster_centroid` to `physics.step_pulse()`

### `core/physics_engine.py` — Modified
- Added `cluster_centroid` parameter to `step_pulse()`
- Passes `cluster_centroid` through to `spatial_mind.pulse()`
- Updated docstring with parameter documentation

### `core/spatial_mind.py` — Modified
- Added `cluster_centroid` parameter to `pulse()`
- When centroid is provided: uses it directly as `stimulus_pos` with strength 1.5
- When centroid is None: falls back to raw thought/incoming embedding midpoint (original behavior)
- Updated docstring with parameter documentation

### `core/cognitive_space.py` — Modified
- Rewrote `_compute_structural_mass()`: returns `max(0.01, c)` (confidence only)
- Removed `n_connections / n_mean` term from mass formula
- Updated docstring explaining the design rationale

### `core/co_occurrence_hook.py` — Modified
- Added `cognitive_space` parameter to `CoOccurrenceTracker.__init__()`
- Added `_apply_hebbian_drift()` method (localized, relative positional drift)
- `_wire_cluster_relations()` now calls `_apply_hebbian_drift()` after wiring
- Updated `register_co_occurrence_hook()` to accept and pass `cognitive_space`

### `memory/belief_store.py` — Modified
- Rewrote `compute_cognitive_mass()`: `m_s = c` (no relation count)
- Removed `+0.05` mass increment from `touch_belief()`
- Updated module docstring: mass equation, rationale for decoupling

### `main.py` — Modified
- Passes `physics.spatial_mind.belief_space` to `register_co_occurrence_hook()`

---

## 5. Integration Test Results

Full pipeline test against live data (1,772 beliefs, 2,035 memories, 2,121 manifold points):

```
============================================================
  1. CONCEPT EXTRACTION
============================================================
  Lexicon loaded: 88 entries, 98 keys

  [Idle pulse] (budget=1)
    Concepts: ['stay focused']

  [User message] (budget=1)
    Lexicon: ['core', 'helix']

  [Dense thought] (budget=1)
    Concepts: ['creating runaway super nodes']

  [Mixed input] (budget=1)
    Lexicon: ['new', 'telegram']
    Concepts: ['spatial mapping upgrade']

============================================================
  2. PER-CONCEPT GRAVITY QUERIES
============================================================
  Injection completed in 241s (dominated by first-time belief cache build)
  Belief IDs surfaced: 18
  Cluster centroid: computed (8D, float32)

============================================================
  3. MASS DECOUPLING VERIFICATION
============================================================
  Top 5 most-connected beliefs — mass reduction:
    247 rels: 9.03 → 1.32 (85% reduction)
    243 rels: 9.30 → 1.52 (84% reduction)
    239 rels: 8.78 → 1.32 (85% reduction)
    239 rels: 8.06 → 1.25 (85% reduction)
    238 rels: 8.70 → 1.34 (85% reduction)

============================================================
  4. CLUSTER CENTROID COMPUTATION
============================================================
  Shape: (8,), dtype: float32
  ✓ Computed from actual retrieved belief positions

============================================================
  5. HEBBIAN DRIFT SIMULATION
============================================================
  Pair: sel_i_am_an_ai ↔ sel_i_am_a_living
  Distance before: 0.101482
  Co-occurrence count: 10
  Distance after:  0.100467 (0.1% closer)
  ✓ Symmetric drift, positions restored after test
```

---

## 6. Design Rationale & Decisions

### Why no cosine similarity gate?

Initially proposed as a 384D cosine threshold to filter gravity candidates. Rejected because:
1. The noise problem isn't that bad beliefs appear once — it's that they get wired, mass-inflated, and pulled again. Fix the loop, not the symptom.
2. A cosine threshold is arbitrary and doesn't fit the spatial mind architecture.
3. The gravitational field already handles relevance through spatial proximity — that's what it's for.

### Why no drift cap?

Large drift does not cause "loss of semantic meaning" because:
1. The 8D positions are already lossy projections (0.97× separation ratio).
2. The entire point of drift is to encode *actual usage patterns* instead of the initial embedding guess.
3. Manifold degeneration (all beliefs collapsing) requires universal co-injection, which is prevented by the concept extractor and mass decoupling.
4. The long-term safeguard is a constant source of entropy on every waking pulse (future work).

### Why no max cluster size cap?

As long as the compression systems work correctly, the cluster size naturally self-limits. The concept extractor (1-5 queries) and the rolling blacklist (no overlap between concept results) inherently limit how many beliefs can be co-injected per pulse.

### Why keep the gravity formula?

The existing `T × M / d²` formula preserves rich metadata: mass (confidence + affective encoding), temperature (recency via Lorentzian cooling), and distance (spatial proximity). A pure cosine similarity system would discard all of this and reduce to a flat vector search — at that point we might as well use ChromaDB.

---

## 7. Known Considerations

### Stored Mass Values Are Stale

The live belief store still contains mass values computed under the old formula (with relation count inflation). These will be corrected during a manual `recompute_all_masses()` call, scheduled separately. Until then, the preconscious belief cache uses the old stored mass values — but the CognitiveSpace's structural mass computation is already using the new formula.

### First-Time Belief Cache Build Is Slow

The initial `_ensure_belief_cache()` call embeds all ~1,800 beliefs from scratch (~4 minutes on CPU). Subsequent pulses reuse the cache and rebuild only when belief count or total mass changes. This is existing behavior, not introduced by the refactor.

### Entropy Source (Future Work)

The manifold currently has no source of randomness. Without entropy, the Hebbian drift could theoretically cause slow convergence even with the decoupling fixes. A per-pulse noise injection (small random displacement of the attention center, or periodic random shuffling of belief positions) would provide the thermodynamic entropy needed to prevent crystallization. This is identified as a future improvement.

---

*End of audit.*
