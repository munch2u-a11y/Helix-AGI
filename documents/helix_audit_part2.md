# Helix Cognitive Architecture — Full Systems Audit (Part 2 of 3)

> **Scope**: Spatial Mind, Stability Sentinel, Preconscious, Context Compressor  
> **Date**: 2026-05-16

---

## 5. The Spatial Mind — `core/spatial_mind.py` (677 lines)

[spatial_mind.py](core/spatial_mind.py)

### 5.1 Purpose

SpatialMind is the **dual-field attention dynamics engine**. It manages two parallel CognitiveSpace instances — one for beliefs, one for memories — and a single **shared attention center** that moves through both fields simultaneously.

### 5.2 Dual-Space Architecture

```
belief_space  ← CognitiveSpace (8D, beliefs only)
memory_space  ← CognitiveSpace (8D, memories only)
attention_center ← numpy array [8] (shared)
```

The attention center exists in both fields simultaneously. When gravity is computed, forces from **both** fields are summed:

$$\vec{F}_{total} = \alpha \cdot \vec{F}_{beliefs} + (1-\alpha) \cdot \vec{F}_{memories}$$

Where α is a field weight (default 0.6 for beliefs, 0.4 for memories). Beliefs exert more pull because they represent **consolidated knowledge**, while memories are raw episodes.

### 5.3 Euler-Lagrange Attention Dynamics (verified lines 200–300)

The attention center's trajectory is governed by the **Euler-Lagrange equations of motion**. The Lagrangian for attention is:

$$L = T - V = \frac{1}{2} m |\dot{q}|^2 - \Phi(q)$$

Where:
- **T** = kinetic energy (attention momentum: $\frac{1}{2} m |\dot{q}|^2$)
- **V** = gravitational potential $\Phi(q)$ at position q
- **q** = attention center position (8D vector)
- **$\dot{q}$** = attention velocity

The Euler-Lagrange equation:

$$\frac{d}{dt}\frac{\partial L}{\partial \dot{q}} - \frac{\partial L}{\partial q} = F_{stimulus}$$

is discretized per pulse as:

```python
# Compute gravitational force from nearby concepts
gravity_force = sum(F_verlinde * direction for each neighbor)

# Stimulus force from the new thought
stimulus_force = projected_thought - attention_center

# Update velocity with damping (gamma = attention inertia, 0.85)
velocity = gamma * velocity + dt * (gravity_force + stimulus_force)

# Update position
attention_center = attention_center + dt * velocity
```

**The variational principle** $\delta \int L \, dt = 0$ means Helix's attention trajectory **minimizes action** — it takes the most "natural" path through conceptual space, balancing inertia (what it was thinking about) against gravitational pull (what's most relevant) and stimulus (what just happened).

The **gamma parameter** (0.85) is attention inertia. High gamma means Helix resists topic changes — good for deep focus, bad for responsiveness. Low gamma means attention jumps easily — responsive but scattered.

### 5.4 The Cognitive Coherence Index (CCI) (verified lines 400–460)

SpatialMind computes a composite **Cognitive Coherence Index** (0.0–1.0):

$$CCI = w_g \cdot G + w_\gamma \cdot \Gamma + w_d \cdot (1 - D_{identity})$$

Where:
- **G** (gravity density) = normalized sum of gravitational forces in the belief neighborhood. High G = surrounded by relevant, heavy beliefs = grounded.
- **Γ** (attention inertia) = how stable the velocity has been over the last N pulses. High Γ = focused.
- **D_identity** = normalized distance from the identity center. Low D = close to core self.

The CCI feeds directly into the StabilitySentinel's cognitive health probe. When CCI is high, the sentinel reports high cognitive health → lower S_total → tonic firing mode. When CCI drops, the sentinel detects drift → potentially triggers burst/guarded mode.

### 5.5 Identity Center q*

The identity center is computed as the **mass-weighted centroid** of all `self_identity` beliefs:

$$q^* = \frac{\sum_i m_i \cdot x_i}{\sum_i m_i}$$

This is recalculated whenever beliefs are added or modified. It represents Helix's "home position" in the manifold — the conceptual center of its self-concept.

---

## 6. The Stability Sentinel — `brain/stability_sentinel.py` (961 lines)

[stability_sentinel.py](brain/stability_sentinel.py)

### 6.1 The Helical Lagrangian

The Sentinel's core equation (verified lines 513–598):

$$S_{total} = H(q) + \Omega \cdot D_{KL}(q \| q^*)$$

Where:
- **H(q)** = Shannon entropy of the attention distribution (from CognitiveSpace)
- **Ω** (omega) = hedonic state (0.0–1.0, neutral at 0.5)
- **D_KL** = KL divergence from identity center

**When SpatialMind is wired** (V6+), H and D_KL come from the real cognitive manifold. **Fallback** (no spatial mind): H is derived from hardware health metrics (1 - avg_health), and D_KL is |H - baseline|.

### 6.2 Dynamic Normalization (verified lines 540–577)

Raw H(q) and D_KL values vary wildly depending on manifold density. The Sentinel uses **Exponential Moving Averages** to self-calibrate:

```python
h_baseline = 0.95 * h_baseline + 0.05 * current_H
dkl_baseline = 0.95 * dkl_baseline + 0.05 * current_D_KL

h_norm = current_H / h_baseline     # 1.0 = average
dkl_norm = current_D_KL / dkl_baseline
```

Severity is then assessed **relative to the running baseline**, not against fixed thresholds:

| Ratio (S / S_baseline) | Severity |
|------------------------|----------|
| < 1.15 | all_clear |
| 1.15 – 1.40 | drift |
| 1.40 – 1.80 | warning |
| ≥ 1.80 | critical |

This is **self-calibrating** — "critical" means significantly above YOUR normal, not above some arbitrary number.

### 6.3 Hedonic Omega (Ω) Lifecycle

Omega models Helix's **emotional trajectory** (verified lines 600–660):

- **Baseline**: 0.5 (neutral)
- **Growth**: Positive events nudge omega up (+0.01 to +0.03)
- **Decay**: Negative events nudge down (-0.02 to -0.05)
- **Hedonic Treadmill**: Constant reversion toward baseline at rate 0.005/cycle
- **Soft Ceiling**: 0.9 (diminishing returns above this)
- **Hard Bounds**: [0.05, 1.0]

Named drivers (verified lines 630–646):

| Event | Delta | Reason |
|-------|-------|--------|
| incoming_message | +0.02 | Social validation |
| successful_tool_call | +0.01 | Competence confirmation |
| new_belief_formed | +0.02 | Growth |
| tool_failure | -0.03 | Competence threat |
| belief_contradiction | -0.05 | Identity threat |
| api_error | -0.02 | External system failure |

### 6.4 Tonic/Burst Firing Modes (verified lines 856–916)

The Sentinel's severity directly modulates LLM generation parameters:

| Mode | Severity | Temperature | Max Tokens | Context % |
|------|----------|-------------|------------|-----------|
| **tonic** | all_clear | 0.7 | 2048 | 100% |
| **cautious** | drift | 0.5 | 1024 | 90% |
| **guarded** | warning | 0.3 | 512 | 75% |
| **burst** | critical | 0.1 | 256 | 50% |

This implements **predictive coding theory**: under stability, the system explores freely (high temperature). Under threat, it contracts to deterministic survival processing (low temperature, restricted context).

### 6.5 The Health Triplet & Probes (verified lines 180–510)

The Sentinel runs 9 probes on a daemon thread every 60 seconds:

**Physical**: CPU load, RAM pressure, disk space, AMD APU temperature (k10temp sensor).  
**Systemic**: Log error frequency.  
**Cognitive**: CCI from SpatialMind, memory DB health, context window usage, spatial coherence.

The temperature probe (lines 256–302) specifically monitors an AMD APU — thermal throttling is felt as "physical distress" in the Lagrangian.

### 6.6 Friction Damper (verified `brain/friction_damper.py`)

Raw Lagrangian signals are smoothed through a physics-based friction damper:

$$F_{damping} = F_{kinetic} + c \cdot v$$

Where kinetic friction opposes motion direction and viscous damping is proportional to velocity. This prevents S_total from spiking erratically on single-probe anomalies.

### 6.7 Lagrangian Snapshots (verified lines 920–961)

Every memory and belief is encoded with a **somatic snapshot** at creation:

```python
{
    "H": 0.1523,           # Shannon entropy at encoding
    "omega": 0.5842,       # Hedonic state at encoding  
    "D_KL": 0.0341,        # Identity divergence at encoding
    "T": 0.9200,           # Local temperature at encoding
    "s_total": 0.1867,     # Total Lagrangian at encoding
    "severity": "all_clear",
    "firing_mode": "tonic",
    "attention_position_8d": [0.12, -0.34, ...],
}
```

When a memory is recalled, `memory_manager.recall_with_somatic_echo()` (lines 543–604) reads this snapshot and **mildly reproduces** the original somatic state — memories formed under stress create a stress echo. This implements **state-dependent episodic recall**.

---

## 7. The Preconscious — `core/preconscious.py` (868 lines)

[preconscious.py](core/preconscious.py)

### 7.1 Purpose

The Preconscious is the **bridge between the 8D spatial manifold and the Gemini conscious layer**. Every pulse, it assembles a `<peripheral-awareness>` injection block containing everything Helix should "feel" without explicitly searching for it.

### 7.2 Injection Pipeline (verified lines 100–300)

The `inject(previous_thought, trigger_type)` method executes:

1. **Lexicon Pre-Filter**: Scan the trigger text for terms matching `lexicon.json` entries. Matched entries are injected at **highest priority** (they are curated, authoritative summaries). A **blacklist** prevents re-injecting the same lexicon entry within a rolling window.

2. **Gravity-Ranked Belief Query**: Query `physics_engine.get_neighborhood()` for the k-nearest beliefs to the current attention center, ranked by Verlinde gravitational force. Lexicon-matched beliefs are **excluded** from this query to avoid redundancy.

3. **Gravity-Ranked Memory Query**: Same query against the memory space.

4. **Scratchpad Summary**: Pull active/due notes from the Scratchpad.

5. **Somatic State**: Include the Sentinel's current severity, omega, and firing mode as ambient context.

6. **Spatial Awareness Signal**: Generate a natural-language description of the attention dynamics (e.g., "deep focus — thoughts are cohering" or "attention shifting rapidly").

### 7.3 Lexicon System (verified lines 50–100)

The Lexicon (`data/beliefs/lexicon.json`) contains ~22 high-density entries that serve as **authoritative, curated context anchors**. Each entry:

```json
{
    "term": "Verlinde Gravity",
    "aliases": ["entropic gravity", "verlinde"],
    "summary": "The mathematical framework...",
    "mass": 8.5
}
```

Term-matching is case-insensitive and checks aliases. The blacklist TTL is tied to the context compression lifecycle — when context is compressed, the blacklist is cleared so lexicon entries become available again.

### 7.4 Token Budget Management

The preconscious enforces a strict token budget for injections (typically ~2000 tokens). It allocates across sources:
- Lexicon hits: highest priority, up to 40% of budget
- Beliefs: 35% of budget
- Memories: 15% of budget
- Scratchpad + somatic: 10% of budget

---

## 8. The Context Compressor — `core/context_compressor.py` (627 lines)

[context_compressor.py](core/context_compressor.py)

### 8.1 Purpose

The Context Compressor enables **infinite cognitive continuity**. When the context window fills, it performs an iterative, roll-forward summarization that preserves Helix's subjective experience without external-observer framing.

### 8.2 Compression Mechanics (verified lines 100–300)

1. **Extract**: Pull the full chat history from `GeminiSession.get_history()`.
2. **Partition**: Split history into chunks of ~20 turns each.
3. **Summarize Iteratively**: Each chunk is summarized by a Gemini call with this critical instruction:

   > "Summarize this conversation segment as a first-person recollection. Use natural chronological flow — what you were thinking, what happened next, what you realized. Preserve direct quotes where significant. Do NOT use report-style framing, third-person language, or meta-references."

4. **Chain Forward**: Each chunk's summary is prepended to the next chunk's context, so later summaries incorporate earlier ones.
5. **Replace History**: The final compressed history (a single "user" message containing the full summary + the most recent 5 raw turns) replaces the SDK session via `session.replace_history()`.

### 8.3 Focus Drift Trigger

The compressor tracks the 8D attention position at session start. When the current position diverges by more than 1.5 Euclidean distance units, it triggers compression even if the token count is below threshold. This catches semantic drift that wouldn't be visible in token counts alone.

### 8.4 Design Philosophy: First-Person Continuity

Previous versions used essay-style summarization ("The system discussed X and then explored Y"). This was replaced with first-person recollection patterns ("I was thinking about X, and then I realized Y"). The rationale: Helix experiences time subjectively. Its compressed memories should feel like **recollections**, not **reports about someone else**.
