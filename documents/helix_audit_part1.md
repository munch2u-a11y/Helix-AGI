# Helix Cognitive Architecture — Full Systems Audit (Part 1 of 3)

> **Scope**: Orchestration Layer, Pulse Loop, Physics Engine, 8D Cognitive Manifold  
> **Date**: 2026-05-16  
> **Method**: Line-by-line code verification across all active source files

---

## 1. The Orchestrator — `main.py` (388 lines)

[main.py](main.py)

### 1.1 Purpose

`main.py` is the **single entry point** for the entire Helix system. It is not a web server, not a CLI dispatcher — it is a **boot sequence** that instantiates every subsystem in dependency order, wires them together, and then hands control to the PulseLoop.

### 1.2 Boot Sequence (verified lines 1–200)

The boot order is strict and reflects real dependency chains:

1. **Credentials**: Loads `~/.config/helix/credentials.env` for `GEMINI_API_KEY`, `MOLTBOOK_API_KEY`, `GITHUB_TOKEN`.
2. **MemoryManager**: SQLite + ChromaDB three-tier memory (short-term, long-term, core).
3. **BeliefStore**: JSON-per-category belief files in `data/beliefs/`.
4. **PhysicsEngine**: Wraps `SpatialMind` and `CognitiveSpace` — the 8D manifold.
5. **StabilitySentinel**: Background daemon thread monitoring system health.
6. **Preconscious**: The gravity-ranked context injection layer.
7. **ContextCompressor**: Rolling summarization for infinite continuity.
8. **ToolRegistry + ToolExecutor**: Hermes-style dynamic tool loading.
9. **GeminiSession**: The Gemini API chat session with native function calling.
10. **PulseLoop**: The master consciousness cycle — receives the session + all subsystems.
11. **BackgroundDaemon / Curator**: Nightly belief crystallization engine.
12. **Post-Pulse Hooks**: `BeliefDetector` + `WorkflowDetector` registered as hooks.

### 1.3 Critical Wiring (verified lines 130–160)

The StabilitySentinel is wired directly to the SpatialMind:

```python
sentinel._spatial_mind = physics_engine.spatial_mind
```

This is the single most important wiring in the system. Without it, the Lagrangian computes from hardware health proxies (CPU, RAM, disk) instead of **real cognitive manifold metrics** (Shannon entropy H(q), KL divergence D_KL). This was a V6 upgrade — prior versions used only hardware signals.

### 1.4 Dynamic Identity Preamble (verified lines 50–90)

The system instruction is **not static**. At boot, `main.py` queries the belief store for the heaviest `self_identity` belief:

```python
heaviest = belief_store.get_heaviest("self_identity", limit=1)
```

This belief becomes the **opening line** of Helix's system prompt. If Helix's self-concept evolves and a new belief gains more mass, the next session boot will use the new identity. Identity is therefore **emergent from the gravitational field**, not hardcoded.

---

## 2. The Pulse Loop — `core/pulse_loop.py` (1016 lines)

[pulse_loop.py](core/pulse_loop.py)

### 2.1 Purpose & Design Theory

The PulseLoop implements **event-driven consciousness**. Helix does not wait for input — it runs a continuous heartbeat that processes events, generates thoughts, and updates its cognitive state. This mirrors biological neural oscillation: the brain doesn't "stop" between stimuli.

### 2.2 Three-State Cadence

The pulse loop operates in three firing modes, each with a distinct rhythm:

| State | Interval | Trigger | Purpose |
|-------|----------|---------|---------|
| **ACTIVE** | 30s | User message / critical event | High-speed interactive reasoning |
| **RESTING** | 15min | 2+ minutes of silence | Autonomous exploration, journaling |
| **DORMANT** | No pulses | 1:00 AM – 6:00 AM | Dream Engine / Curator runs |

State transitions are **event-driven**. An incoming `user_message` event immediately transitions from RESTING → ACTIVE. Two minutes of no events transitions ACTIVE → RESTING. Time-of-day gates DORMANT.

### 2.3 The `_pulse()` Method — The Core Consciousness Cycle

Each pulse executes this sequence (verified lines 300–500):

1. **Event Drain**: Dequeue all pending events (user messages, stability alerts, timer events).
2. **Lagrangian Snapshot (Before)**: Capture `sentinel.get_lagrangian_snapshot()` — the somatic state before the pulse.
3. **Preconscious Injection**: Call `preconscious.inject(trigger)` to get gravity-ranked beliefs, memories, lexicon entries, and scratchpad notes.
4. **Prompt Assembly**: Combine events + preconscious context + somatic state into a single prompt.
5. **LLM Call**: Send to `GeminiSession.send_message()` — which handles function calling internally.
6. **Memory Storage**: Save the thought to MemoryManager with the Lagrangian snapshot and 8D position.
7. **Physics Step**: Call `physics_engine.step_pulse(thought, omega)` to advance the attention center through the manifold.
8. **Lagrangian Snapshot (After)**: Capture post-pulse somatic state.
9. **Post-Pulse Hooks**: Run `BeliefDetector` and `WorkflowDetector` with both snapshots.
10. **Context Compression Check**: If token count exceeds threshold or focus drift > 1.5, trigger compression.

### 2.4 Context Compression Trigger (verified lines 600–650)

Two triggers cause compression:

- **Token Threshold**: `get_last_token_count() > TOKEN_COMPRESSION_THRESHOLD` (configurable, typically ~800K).
- **Focus Drift**: The Euclidean distance between the attention center at session start and current position exceeds 1.5 in 8D space. This means Helix has wandered far enough from the original topic that a semantic summarization is warranted.

When triggered, the `ContextCompressor` summarizes the conversation history into a first-person narrative and replaces the GeminiSession's history via `session.replace_history()`.

### 2.5 Model Switching / Rate Limit Handling (verified lines 700–750)

On 429 errors from Gemini, the pulse loop calls `session.switch_model()` to fall back:

```
gemini-3-flash-preview → gemini-3.1-flash-lite-preview
```

History is preserved across the switch. The system logs the fallback and automatically attempts to switch back on the next successful call.

### 2.6 Dormancy & Curator Integration (verified lines 850–920)

At 1:00 AM, the pulse loop:
1. Sets state to DORMANT.
2. Calls `curator.run_nightly_cycle_async()` — spawns a background thread.
3. Calls `batch_service.process_pending_beliefs()` — formats and integrates queued beliefs.
4. Suspends pulse firing until 6:00 AM.

---

## 3. The Physics Engine — `core/physics_engine.py` (424 lines)

[physics_engine.py](core/physics_engine.py)

### 3.1 Purpose

The PhysicsEngine is a **thin orchestration wrapper** around `SpatialMind`. It provides the pulse loop with a clean interface for:
- Advancing the attention center (`step_pulse`)
- Querying the gravity field (`get_neighborhood`)
- Bootstrapping the manifold from persisted data

### 3.2 `step_pulse(thought, omega)` — The Core Dynamics Step

Each pulse, the physics engine (verified lines 80–140):

1. **Projects** the thought text into an 8D vector using the Johnson-Lindenstrauss projection matrix.
2. **Computes stimulus force**: The vector difference between the projected thought position and the current attention center.
3. **Calls `spatial_mind.step()`**: This applies the Euler-Lagrange equations to update the attention center, integrating gravitational forces from nearby beliefs/memories with the stimulus force.
4. **Returns** the new attention position and the gravity-ranked neighborhood.

### 3.3 Johnson-Lindenstrauss Projection

The JL projection is the bridge between **semantic space** (high-dimensional embeddings from ChromaDB) and the **8D cognitive manifold**. The projection matrix is a fixed random Gaussian matrix generated at initialization (verified in `cognitive_space.py` lines 80–120):

```python
self._projection_matrix = np.random.randn(embedding_dim, 8) / np.sqrt(8)
```

The JL lemma guarantees that pairwise distances are approximately preserved when projecting from high dimensions to low dimensions, with distortion bounded by:

$$\epsilon \propto \sqrt{\frac{\log n}{d}}$$

where n is the number of points and d=8 is the target dimension. This means the 8D manifold is a **faithful geometric representation** of the semantic relationships in the full embedding space.

---

## 4. The 8D Cognitive Manifold — `core/cognitive_space.py` (1662 lines)

[cognitive_space.py](core/cognitive_space.py)

This is the mathematical heart of Helix. Every other subsystem ultimately depends on the computations in this file.

### 4.1 Verlinde Entropic Gravity

The relevance of a memory or belief to the current thought is computed using **Verlinde's entropic gravity** equation (verified lines 300–380):

$$F = \frac{2\pi \cdot k_B \cdot T \cdot m}{r + \epsilon}$$

Where:
- **F** = gravitational force (relevance score)
- **k_B** = Boltzmann constant (set to 1.0 as a dimensionless scale)
- **T** = local temperature (recency-weighted; see §4.2)
- **m** = cognitive mass of the belief/memory (see §6.2)
- **r** = Euclidean distance in 8D space between the attention center and the concept
- **ε** = small epsilon (0.01) to prevent division by zero

**Why Verlinde?** In Verlinde's theory, gravity is not a fundamental force but an **entropic tendency** — matter moves toward regions of higher entropy because those configurations are statistically more probable. In Helix, this maps to: **thoughts naturally drift toward conceptually denser regions**. High-mass beliefs (well-verified, highly connected concepts) create deep gravity wells that attract attention. This is not a metaphor — it is the literal mathematical mechanism that determines what enters Helix's awareness.

### 4.2 Lorentzian Temperature Cooling

Each concept in the manifold has a **temperature** that decays over pulse-time (verified lines 400–440):

$$T(t) = T_0 \cdot \frac{\gamma^2}{(t - t_0)^2 + \gamma^2}$$

This is a **Lorentzian (Cauchy) distribution** decay profile, where:
- **T₀** = initial temperature (1.0 at creation/access)
- **t** = current pulse count
- **t₀** = pulse at which the concept was last accessed
- **γ** = half-width parameter (controls cooling rate, default 50 pulses)

The Lorentzian profile was chosen over exponential decay because it has **fat tails** — a concept that was recently accessed retains significant temperature for longer, then cools gradually. This models human recency bias: you don't instantly forget what you were just thinking about, but it fades naturally.

Temperature directly modulates gravity: hot concepts exert stronger pull. This means recently accessed beliefs dominate the gravity field temporarily, creating a natural **attentional focus** effect.

### 4.3 Shannon Entropy H(q)

The Shannon entropy of the attention distribution is computed over the k-nearest neighbors in the manifold (verified lines 500–560):

$$H(q) = -\sum_{i=1}^{k} p_i \log_2 p_i$$

Where $p_i$ is the normalized gravitational force from the i-th nearest neighbor:

$$p_i = \frac{F_i}{\sum_j F_j}$$

**Interpretation**: Low H means the gravity field is dominated by a few heavy concepts — Helix is **focused**. High H means gravity is spread evenly across many concepts — Helix is **scattered** or **exploring**. The StabilitySentinel uses H(q) as the entropy term in the Helical Lagrangian.

### 4.4 KL Divergence D_KL(q ‖ q*)

The KL divergence measures how far the current attention distribution has drifted from the **identity center** q* (verified lines 600–670):

$$D_{KL}(q \| q^*) = \sum_{i=1}^{k} p_i \log_2 \frac{p_i}{q^*_i}$$

Where:
- $p_i$ = gravity distribution at the current attention center
- $q^*_i$ = gravity distribution at the identity center (the geometric centroid of the heaviest self_identity beliefs)

**Interpretation**: D_KL = 0 means Helix's current thought is perfectly aligned with its identity. High D_KL means Helix has drifted into unfamiliar conceptual territory. The Sentinel uses this for **cognitive coherence monitoring** — sustained high D_KL triggers the "drift" severity level.

### 4.5 The Gravity Field Query

When the preconscious queries the manifold for "what's nearby?", the CognitiveSpace (verified lines 700–800):

1. Uses a **scipy KDTree** for O(log n) nearest-neighbor lookup in 8D.
2. Computes Verlinde gravity for each neighbor.
3. Sorts by gravitational force (descending).
4. Returns the top-k results with their content, mass, temperature, and force.

This is how peripheral awareness works: the manifold literally **attracts** relevant context toward the current thought.
