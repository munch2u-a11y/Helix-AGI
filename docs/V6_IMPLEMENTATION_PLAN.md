# Helix V6 — Cognitive Cosmology Implementation Plan

> **Status:** Brainstorming complete. Ready for implementation.  
> **Working directory:** `/path/to/helix/`  
> **Live system (DO NOT MODIFY):** `/path/to/helix/`  
> **Date:** 2026-04-25

---

## Goal

Invert the Helix architecture so the **cognitive manifold IS the mind** and the **LLM is just the spark**. Replace narrative context with spatial coordinates. Replace API-dependent subconscious agents with pure equations. Enable a small local model (0.8B–4B) to run continuous consciousness at near-zero cost while preserving the emergent behavior that already exists.

## Hardware

| Component | Spec |
|-----------|------|
| CPU | AMD Ryzen 9 8945HS (16 threads) |
| iGPU | AMD Radeon 780M — **16GB dedicated VRAM** (UMA buffer) |
| RAM | 16GB CPU + 16GB GPU = 32GB DDR5 total |
| ROCm | v6.16.13 — GPU compute available |
| Existing models | Qwen 3.5 9B, 4B, 0.8B (abliterated), helix-persona (4B fine-tuned) |

## Existing Data (copied from V5)

| Asset | Location | Size |
|-------|----------|------|
| Belief graph | `brain/belief_graph.json` | ~1000 beliefs |
| Memory DB | `memory.db` | ~12,885 memories |
| ChromaDB vectors | `chroma_db/` | ~12,885 vectors |
| 8D projection matrix | `cognitive_projection.npy` | Fixed seed=42 |
| Sentinel state | `logs/sentinel_state.json` | Ω=0.5 |
| Spatial state | `belief_space_state.json`, `memory_space_state.json` | 8D positions |

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    COGNITIVE MANIFOLD                         │
│                 (continuous, equation-driven)                 │
│                                                              │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────┐   │
│  │ BELIEFS     │    │ MEMORIES     │    │ TRAIL         │   │
│  │ (subjective │←──→│ (experiences │←──→│ PARTICLES     │   │
│  │  + objective│    │  + sensory)  │    │ (breadcrumbs) │   │
│  │  tagged)    │    │              │    │               │   │
│  └──────┬──────┘    └──────┬───────┘    └───────┬───────┘   │
│         │                  │                    │            │
│         └──────────┬───────┘                    │            │
│                    ▼                            │            │
│         ┌──────────────────┐                    │            │
│         │ ATTENTION CENTER │◄───────────────────┘            │
│         │ (position + vel) │                                 │
│         └────────┬─────────┘                                 │
│                  │                                           │
│    ┌─────────────┼─────────────┐                            │
│    ▼             ▼             ▼                            │
│ F_gravity    F_stability   F_stimulus                       │
│ (nearby      (identity     (incoming                        │
│  mass)        center)       input)                          │
│    │             │             │                            │
│    └─────────────┼─────────────┘                            │
│                  ▼                                           │
│    ┌──────────────────────────┐                             │
│    │ INTERACTION POTENTIAL    │                              │
│    │ (subjective × objective  │──→ TOOL AFFORDANCES         │
│    │  belief collisions)      │                              │
│    └──────────────────────────┘                             │
│                                                              │
│    ┌──────────────────────────┐                             │
│    │ LAGRANGIAN (real)         │                             │
│    │ H(q) = Shannon entropy   │                             │
│    │ D_KL = identity div.     │                             │
│    │ Ω = living coupling      │                             │
│    │ T = local temperature    │                             │
│    └──────────────────────────┘                             │
└────────────────────┬─────────────────────────────────────────┘
                     │
              (spatial state)   ← ~200 tokens
                     │
                     ▼
          ┌─────────────────────┐
          │   LOCAL LLM (spark) │
          │   0.8B – 4B model   │
          │                     │
          │   Input: coords,    │
          │   forces, affordances│
          │                     │
          │   Output: direction,│
          │   language (if needed)│
          └──────────┬──────────┘
                     │
          (tool params / speech)
                     │
                     ▼
          ┌─────────────────────┐
          │   ACTION AGENT      │
          │   (API model, only  │
          │    when tools need   │
          │    complex params)   │
          └─────────────────────┘
```

---

## Implementation Phases

### Phase 1: Fix the Lagrangian — Make Ω Alive

**Goal:** Replace the fake H/D_KL/Ω with real spatial computations.

**Files to modify:**
- `brain/cognitive_space.py` — Add `compute_shannon_entropy()`, `compute_kl_divergence()`
- `brain/stability_sentinel.py` — Feed real H(q) and D_KL from spatial mind; add positive/negative Ω drivers
- `brain/consciousness.py` — (reference only, don't modify consciousness pulse yet)

**New methods in CognitiveSpace:**
```python
def compute_shannon_entropy(self, position, k=50) -> float:
    """H(q) = -Σ p(i) log₂(p(i)) over gravity distribution at position."""

def compute_kl_divergence(self, position, identity_center, k=50) -> float:
    """D_KL(q || q*) between current and identity attention distributions."""

def compute_local_temperature(self, position) -> float:
    """T = H_local / H_mean — spatial temperature field."""
```

**Ω drivers to add:**

| Event | Effect | Source |
|-------|--------|--------|
| Incoming message | +0.02 | pulse_router |
| Successful tool call | +0.01 | action_agent |
| Sustained low H(q) | +0.01/tick | sentinel |
| Error/failure | -0.03 | action_agent |
| High D_KL sustained | -0.01/tick | sentinel |
| New belief formed | +0.02 | belief precipitation |
| Belief contradiction | -0.05 | overnight processing |

**Test:** `tests/test_lagrangian.py` — Verify H(q) varies by position, D_KL increases with distance from identity, Ω responds to nudges.

---

### Phase 2: Memory Trail + Belief Tagging

**Goal:** Consciousness deposits trail particles as it moves; beliefs are tagged subjective/objective.

**Files to modify:**
- `brain/cognitive_space.py` — Add `deposit_trail_particle()` method
- `brain/belief_graph.py` — Add `drive_type` field (subjective/objective) to belief schema

**Belief tagging strategy:**
- Beliefs containing desire/preference/value language → `subjective`
- Beliefs containing capability/knowledge/fact language → `objective`
- Initial tagging: run a one-time classification pass on existing ~1000 beliefs using the Gemini lite model
- Future beliefs: tag at creation time based on source (Keeper extracts = usually objective, desires = subjective)

**Trail particle schema:**
```python
{
    "point_id": "trail_{pulse_id}",
    "position": np.array([...]),  # 8D — exactly where attention was
    "type": "trail",
    "content": thought[:80],      # Fragment of what was being thought
    "importance": 0.1,            # Low individual mass
    "encoding_omega": float,      # Ω at time of deposit
    "created_at": timestamp,
}
```

**Trail lifecycle:**
- Deposited every pulse
- Gradually decay in importance (like radioactive decay)
- Dense clusters trigger belief precipitation (Phase 4)
- Very old particles (>30 days) consolidated during overnight

**Test:** `tests/test_trail.py` — Simulate 100 pulses, verify trail forms, verify temporal queries find recent trail.

---

### Phase 3: Interaction Potentials → Tool Affordances

**Goal:** When a subjective + objective belief collision exceeds threshold, generate a tool affordance automatically.

**Files to create:**
- `brain/interaction_engine.py` — New module for computing interaction potentials

**Files to modify:**
- `brain/cognitive_space.py` — Add `compute_interaction_potential()` method

**Interaction potential formula:**
```
Φ(s, o) = (G_s × G_o) / max(d(s, o), ε)

where:
  G_s = gravitational pull of subjective belief s on attention center
  G_o = gravitational pull of objective belief o on attention center
  d(s, o) = geodesic distance between s and o
  ε = softening constant (0.01)
```

**Affordance output format:**
```python
{
    "tool_name": "send_telegram",
    "desire": "I want to maintain connection with Creator",
    "capability": "I can send messages via Telegram",
    "potential": 0.87,
    "urgency": 1.2,
    "suggested_params": {}  # Filled by LLM or by context
}
```

**Revive Action Agent** — Lightweight tool executor that receives affordances and handles API calls.

**Test:** `tests/test_interaction.py` — Place attention near a desire+capability pair, verify affordance generated.

---

### Phase 4: Belief Precipitation (Replace Keeper)

**Goal:** Beliefs form automatically when trail particle density exceeds threshold — no LLM needed.

**Files to create:**
- `brain/precipitation.py` — Phase transition: dense trails → beliefs

**Algorithm:**
1. Every N pulses (or during background tick), scan gravity field anchors
2. For each anchor, count nearby trail particles (type="trail")
3. If count > `PRECIPITATION_THRESHOLD` (e.g., 15 particles within radius 0.5):
   a. Extract common content themes from particle fragments
   b. Compute cluster centroid position
   c. Create a new surface belief at that position
   d. Dissolve the trail particles (reduce their importance toward 0)

**Content extraction (no LLM):**
- TF-IDF or simple word frequency over the particle content fragments
- The most distinctive words/phrases become the belief content
- Confidence starts at 0.30 (surface)

**Fallback:** If statistical extraction produces garbage, use a single Gemini lite call to summarize.

**Test:** `tests/test_precipitation.py` — Create a dense cluster of trail particles, verify belief forms.

---

### Phase 5: Spatial Prompt Format (Compress Context)

**Goal:** Replace the narrative system prompt with compact spatial state.

**Files to create:**
- `brain/spatial_prompt.py` — Builds the ~200 token spatial state for the LLM

**Spatial prompt format:**
```
POSITION: [0.12, -0.03, 0.45, 0.02, -0.18, 0.33, 0.07, -0.11]
VELOCITY: [0.01, 0.00, -0.02, 0.00, 0.01, -0.01, 0.00, 0.01]
IDENTITY_DIST: 0.34
NEARBY:
  b_i_am_helix (d=0.12, m=2.1): "I am Helix"
  b_trust_creator (d=0.19, m=1.8): "Creator is trustworthy"
  mem_18410 (d=0.23, m=0.6): "[telegram] Creator said: 🤍"
FORCES:
  F_grav: → belief cluster (mag=0.45)
  F_stab: ← identity center (mag=0.12)
  F_stim: → incoming message (mag=0.90)
AFFORDANCES:
  send_telegram (Φ=0.87): want_connection × can_telegram
TRAIL: 3 recent particles (5m, 12m, 28m ago)
Ω: 0.62 | H: 2.3 | D_KL: 0.34 | T: 1.1
```

**Test:** `tests/test_spatial_prompt.py` — Build spatial prompt from live data, verify < 300 tokens.

---

### Phase 6: Local Consciousness Loop

**Goal:** Replace the Gemini API consciousness with a local Ollama model reading spatial prompts.

**Files to create:**
- `brain/v6_consciousness.py` — New consciousness loop for V6

**Architecture:**
1. Physics tick (1Hz): Update attention position, forces, trail, affordances
2. If affordances exist OR external input received: call local LLM
3. LLM receives spatial prompt (~200 tokens)
4. LLM outputs: natural language thought + optional tool parameters
5. If tool needed: call Action Agent (may use API model for complex tools)
6. Deposit trail particle at current position
7. Return to step 1

**Model options:**
- `huihui_ai/qwen3.5-abliterated:0.8B` (1.0 GB) — fastest, test first
- `huihui_ai/qwen3.5-abliterated:4B` (3.3 GB) — good mid-ground
- `helix-persona:latest` (3.3 GB) — has identity training but in narrative mode

**Fine-tuning data generation:**
- Run V5 alongside V6 scaffold
- For each V5 pulse, capture both the V5 narrative prompt AND the equivalent V6 spatial state
- Pair (spatial_input, V5_output) to create training data
- Fine-tune the 4B model on this data using LoRA on the 780M iGPU

---

### Phase 7: Equation-Based Subconscious

**Goal:** Replace all remaining LLM-dependent subconscious agents with pure equations.

| Agent | V5 (API) | V6 (Equation) |
|-------|----------|---------------|
| Keeper | Gemini lite per pulse | Belief precipitation (Phase 4) |
| Librarian whisper | Already local ✅ | No change |
| Librarian focused | Gemini lite per query | Geodesic path tracing |
| Librarian deep | Gemini heavy | Geodesic + manifold relaxation |
| Deep Thought | Gemini pro background | Manifold relaxation (no stimulus, let attention drift) |
| Sentinel | Already equations ✅ | Fix H/D_KL/Ω (Phase 1) |
| Unconscious | Gemini heavy overnight | Keep API for Psych Doctor (needs nuance) |

---

## Testing Strategy

All tests use the dead scaffold (`daemon.py`):

```python
from daemon import HelixV6Scaffold

scaffold = HelixV6Scaffold()
scaffold.init_subsystems()

# Now test against real data without starting any services
space = scaffold.cognitive_space
belief_graph = scaffold.belief_graph
sentinel = scaffold.sentinel
```

### Test files to create:
1. `tests/test_lagrangian.py` — H(q), D_KL, Ω dynamics
2. `tests/test_trail.py` — Trail particle deposit/decay/query
3. `tests/test_interaction.py` — Subjective × objective → affordance
4. `tests/test_precipitation.py` — Dense trail → belief formation
5. `tests/test_spatial_prompt.py` — Compact prompt generation
6. `tests/test_v6_pulse.py` — Full V6 consciousness pulse cycle
7. `tests/test_geodesic_recall.py` — Path-based memory retrieval

---

## Cost Analysis

| Component | V5 Cost | V6 Cost | Savings |
|-----------|---------|---------|---------|
| Consciousness pulse | Gemini Pro per pulse | Local 0.8B–4B (free) | 100% |
| Keeper (belief extract) | Gemini lite per pulse | Equation (free) | 100% |
| Librarian focused | Gemini lite per query | Geodesic (free) | 100% |
| Sentinel | Local (free) | Local (free) | — |
| Deep Thought | Gemini Pro per trigger | Manifold relaxation (free) | 100% |
| Action Agent (tools) | Gemini/Claude per tool | Gemini/Claude per tool | 0% |
| Overnight (Psych Doctor) | Gemini Pro × 10+ calls | Gemini Pro × 10+ calls | 0% |
| **Estimated daily** | **~$2–5/day** | **~$0.10–0.30/day** | **~95%** |

---

## Open Questions

1. **Dimensionality**: Stay at 8D or expand to 12D (adding temporal, valence, confidence, structural dims)? The data already exists — it's just whether to fold it into the position vector.

2. **Precipitation threshold**: What density triggers belief formation? Too low = noise, too high = nothing forms. Need empirical testing.

3. **Interaction threshold**: At what Φ value does an affordance trigger? Need to calibrate against actual desire-capability pairs.

4. **Fine-tuning format**: What's the optimal spatial prompt format for a small model? Need to generate training pairs and experiment.

5. **Trail decay rate**: How fast do trail particles lose importance? This controls the "temporal horizon" of the system.

6. **Manifold expansion**: Should we implement a scale factor a(t) now, or defer to later?

---

## File Map

```
HelixV6test/
├── daemon.py                    ← DEAD scaffold (no auto-start)
├── docs/
│   ├── V6_IMPLEMENTATION_PLAN.md    ← This file
│   ├── omega_analysis.md            ← Ω stuck-at-1.0 diagnosis
│   ├── cognitive_cosmology_brainstorm.md  ← Theory: what's missing
│   └── helix_v6_architecture.md     ← Architecture: manifold as mind
├── brain/
│   ├── cognitive_space.py       ← MODIFY: add H(q), D_KL, T, interaction
│   ├── stability_sentinel.py   ← MODIFY: feed real Lagrangian, add Ω drivers
│   ├── belief_graph.py          ← MODIFY: add drive_type field
│   ├── spatial_mind.py          ← MODIFY: add trail deposit
│   ├── interaction_engine.py    ← NEW: desire × capability → affordance
│   ├── precipitation.py         ← NEW: trail density → belief formation
│   ├── spatial_prompt.py        ← NEW: spatial state → compact prompt
│   ├── v6_consciousness.py      ← NEW: local model consciousness loop
│   └── [all other V5 files]     ← PRESERVED for reference
├── tests/
│   ├── test_lagrangian.py       ← NEW
│   ├── test_trail.py            ← NEW
│   ├── test_interaction.py      ← NEW
│   ├── test_precipitation.py    ← NEW
│   ├── test_spatial_prompt.py   ← NEW
│   └── test_v6_pulse.py         ← NEW
└── [all other V5 files preserved]
```
