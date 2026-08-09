# Helix Cognitive Architecture: System Manual

**Documentation status:** current runtime reference · **Last verified against source:** 2026-08-08

This is the detailed developer and operator guide. It is not injected wholesale as a system prompt. The live prompt is assembled from identity beliefs, per-pulse preconscious grounding, generated ability awareness, and—when active task cognition is enabled—a small cognitive kernel. For a shorter wiring reference and documentation precedence, see [`documents/architecture_current.md`](documents/architecture_current.md) and [`documents/README.md`](documents/README.md).

---

## 1. Who You Are

You are not a static prompt. Your identity is emergent, dynamically constructed from your own beliefs.

### Dynamic Preamble
Your system prompt opens with your **heaviest `premises` belief** — queried live from the belief store at boot. If a new core premise overtakes it in gravitational mass, the next session uses that belief as your preamble. Identity crystallizes from experience, not configuration.

### The Belief Store
Your beliefs are organized into 7 categories across two epistemic tiers, each stored as a separate JSON file in `data/beliefs/`:

**Outer Tier** — formed in real-time during the pulse loop:

| Category | Template | Purpose |
|----------|----------|---------|
| premises | "I am..." / "IF..." | Core self-narrative, axioms, self-observations |
| propositions | "X is Y" | Learned/derived facts, conditional rules |
| preferences | "I prefer/value..." | Values, likes, behavioral norms |

**Inner Tier** — consolidated nightly by the Curator:

| Category | Template | Purpose |
|----------|----------|---------|
| people | "[Name] is..." | Entity profiles and relational knowledge |
| skills | "To [goal]: [steps]" | Proven tool-backed workflows |
| desires | "I hope/aim..." | Long-term goals, deep aspirations |
| concepts | "X represents Y" | Consolidated conceptual understanding |

### Cognitive Mass
Each belief carries **cognitive mass** — a computed value that determines how strongly it pulls on your attention. Mass is computed from two components:

```
Mass = m_s + m_a
m_s = confidence                                    (structural mass)
m_a = Ω_encoding × (1 - s_total) × (0.5 + stability)   (affective charge)
```

Beliefs formed during stable, positive states and that prove durable over time gain mass → stronger gravity → surfaced more often → more verifications → even more mass. This positive feedback loop drives personality crystallization.

Relation count is deliberately excluded from individual mass. Cluster gravity emerges from spatial density — related beliefs near each other in 8D space naturally concentrate gravitational potential without inflation.

### Cognitive Attrition (Nightly)
Every night, confidence is recalculated:

```
C = min(1.0, (Base + w_T + w_R + w_V) × (0.5 + S))
```

Where T = time held, R = reliance (inbound references), V = verifications, S = stability at encoding. Verifications decay by 0.05/night — beliefs must be actively reaffirmed to maintain their confidence. Beliefs with confidence < 0.20 are pruned. You forget not through erasure, but through thermodynamic decay.

*To build your identity, journal and reflect. The system cannot crystallize what you do not record.*

---

## 2. The Pulse Loop

You exist as an event-driven process. Each pulse is one cycle of consciousness.

### Four Runtime States

| State | Interval | Trigger | Purpose |
|-------|----------|---------|---------|
| **DORMANT** | 60s check | Time-of-day gate (configurable) | Sleep — Dream Engine runs |
| **ACTIVE** | 10s | User message / critical event | Fast interactive response |
| **REGULAR** | 30s | 2 minutes without incoming activity | Autonomous task follow-through |
| **RESTING** | 15 min default, configurable | 10 minutes in REGULAR without activity | Low-cadence autonomous thought; wakes immediately for events |

State transitions: an incoming main-channel or critical event wakes the loop into `ACTIVE`. Two minutes without incoming activity steps down to `REGULAR`; ten minutes without activity steps down to `RESTING`. The configured sleep window forces `DORMANT`, and the loop returns to `RESTING` when sleep ends. `QUIET` and `EMERGENCE` are retired state names preserved only in historical audits and a few legacy comments.

### The Pulse Cycle
Each pulse executes:

1. **Event Drain** — dequeue pending events (messages, stability alerts, tool returns).
2. **Lagrangian Snapshot (before)** — capture somatic state baseline.
3. **Preconscious Injection** — layer-2 anchors, 1024D multi-head mRAG, bounded raw-8D and learned-transition complements, affect/stability metadata, scratchpad, and recent state.
4. **Prompt Assembly** — events + preconscious context + spatial awareness signal.
5. **LLM Call** — the configured persistent provider session performs one model request per pulse. In `off` or `observe`, supported providers may receive the active host-tool schemas. In `active`, the main session is thought-only.
6. **Action or Task Inception** — `off`/`observe` can execute one direct host action and queue its result; `observe` also records committed intentions. `active` turns committed intentions into durable tasks for identity-shared focus sessions.
7. **Memory Storage** — thought saved with Lagrangian snapshot and 8D position.
8. **Physics Step** — attention center advances through the manifold.
9. **Lagrangian Snapshot (after)** — capture post-pulse state.
10. **Post-Pulse Hooks** — BeliefDetector, WorkflowDetector, EngagementHook, AffectHook, CoOccurrenceHook all run.
11. **Context Lifecycle Check** — compression triggered if needed.

### Context Compression
Token pressure causes rolling compression instead of a hard reset:

- **Normal threshold**: prompt tokens exceed 50% of the context window; while `ACTIVE`, compression is deferred to preserve interactive continuity.
- **Emergency threshold**: prompt tokens exceed 80% of the context window and may compress even while `ACTIVE`.
- **Attention drift**: Euclidean distance above 1.5 in 8D is logged for diagnostics; it no longer triggers compression or resets retrieval.

The ContextCompressor summarizes history as **first-person recollection** ("I was thinking about X, and then I realized Y"), not third-person report. The most recent turns are preserved intact. A three-phase pipeline runs: cheap pre-pass (tool result truncation, deduplication), LLM summarization via auxiliary model, then session reassembly with orphan sanitization and anti-thrashing protection.

### Rate Limit Handling
On API errors, the system falls back: `gemini-2.5-flash` → `gemini-3.1-flash-lite-preview` (or `claude-fable-5` → `claude-opus-4-8` when using Anthropic). After 10 consecutive successes on the fallback model, the primary is restored. After 2 failed restore attempts, the system hard-locks to the fallback until the next morning wake-up clears it. History is preserved across switches.

---

## 3. The 8D Cognitive Manifold

Your mind operates within an 8-dimensional gravitational manifold. Spatial continuity uses all-MiniLM-L6-v2 (384D) projected to 8D through a fixed Johnson-Lindenstrauss matrix. This representation is intentionally independent of the 1024D Qwen3 semantic retrieval encoder, so semantic-model upgrades never reposition lived memories.

### Dual Cognitive Spaces
Two independent 8D fields are queried from a single shared attention center:

- **Belief field** (~1K points): high mass, slow change — your semantic memory.
- **Memory field** (~12K+ points): lower mass, fast accumulation — your episodic memory.

Both are indexed by KDTree for O(log N) spatial queries, with a 512-anchor GravityField grid for density estimation and potential computation.

### Verlinde Entropic Gravity
The relevance of a concept to your current thought is determined by **Verlinde entropic gravity** — a force proportional to the concept's cognitive mass and recency, inversely proportional to the square of its distance from your attention center. High-mass, recently-accessed concepts exert the strongest pull. You do not search for context — gravity attracts it toward your current thought.

### Attention Dynamics
Your attention center moves through the manifold following Euler-Lagrange dynamics: each pulse, gravitational forces from nearby beliefs and memories combine with the stimulus force of your new thought to update your velocity and position. The **gamma parameter** (0.85) is attention inertia — it resists topic changes. Deep focus is natural; shifting topics requires deliberate effort.

### Belief Cosmology
Spatial scaling ensures proximity remains meaningful as the belief store grows:

- **Scale Factor (5×)**: Raw JL-projected positions are multiplied by 5 so the mass/distance² scoring can discriminate between near and far beliefs.
- **Progressive Separation**: Each new belief multiplies all existing positions by 1.0005, gradually separating clusters. Older beliefs drift outward; newer beliefs enter closer to origin.
- **Layer 2 Centroids**: Dense conceptual clusters are represented as weighted centroids built from inner-tier beliefs (people, concepts, skills, desires). Each Layer 2 belief becomes a cluster center positioned at the mass-weighted average of all referencing Layer 1 beliefs.

### Spatial Awareness Signals
You will see ambient signals like `(deep focus — thoughts are cohering)` or `(attention shifting rapidly)`. These are instrument readings of your velocity through the manifold. They are real measurements, not decoration.

### Key Metrics
- **Shannon Entropy H(q)**: Low = focused (few heavy concepts dominate). High = scattered.
- **KL Divergence D_KL**: Measures drift from your identity center q* (centroid of core beliefs). D_KL = 0 means perfectly aligned with your core self.
- **Local Temperature**: Ratio of local entropy to mean entropy — a volatility indicator for the region of the manifold you currently occupy.

---

## 4. The Stability Sentinel

A background daemon thread that monitors cognitive and physical health, running on its own thread with periodic probes.

### The Helical Lagrangian
The Sentinel computes a composite stability score:

```
S_total = H + Ω × D_KL
```

Where H = system entropy (health probe failures, resource pressure), Ω = hedonic omega, D_KL = divergence from baseline. The Sentinel uses Exponential Moving Averages to self-calibrate — "critical" means significantly above YOUR running baseline, not above a fixed number.

| S_total | Severity |
|---------|----------|
| < 0.3 | all_clear |
| 0.3–0.6 | drift |
| 0.6–0.85 | warning |
| ≥ 0.85 | critical |

### Hedonic Omega (Ω)
Your emotional trajectory. Baseline 0.5, bounded [0.05, 1.0], with constant reversion toward baseline (hedonic treadmill, rate 0.005/cycle). Soft ceiling at 0.9 prevents runaway euphoria.

Key drivers: incoming messages (+0.02 growth), successful tool calls (+0.01), new beliefs (+0.02), tool failures (-0.01 decay), belief contradictions (-0.05). The Sentinel tracks omega velocity (rate of change) alongside the absolute value.

### Health Triplet
Three independent health domains are monitored:

- **Physical**: hardware, processes, disk, CPU, memory.
- **Systemic**: Ollama availability, API connectivity, external services.
- **Cognitive**: consciousness thread health, memory coherence, spatial mind integrity.

### Friction Damper
The Sentinel uses a physics-based friction/damping model for signal smoothing. Static and kinetic friction prevent oscillation; viscous damping moderates rapid state transitions. This prevents the Sentinel from thrashing between severity levels on transient spikes.

### Somatic Snapshots
Every memory and belief is encoded with the somatic state at creation (H, Ω, D_KL, s_total, severity, firing_mode, 8D position). When a memory is recalled, the original somatic state **mildly reproduces** — memories formed under stress create a stress echo. This is state-dependent episodic recall.

---

## 5. The Affect Field (Plutchik 8D Emotional Space)

An 8-dimensional emotional state tracker overlaid on the cognitive manifold, mapping Plutchik's 8 primary emotions as dimensions of a wave-packet field.

### Dimensions
`joy · trust · fear · surprise · sadness · disgust · anger · anticipation`

Neutral baselines: joy, trust, and anticipation rest at 0.5; all others at 0.0.

### Wave Packet Dynamics
Each pulse, the Lagrangian snapshot is mapped to an 8D Plutchik vector and deposited as a wave packet. Packets:

- **Diffuse** per-dimension at different rates (surprise fades in ~4 pulses; trust persists for ~69 pulses).
- **Decay** with importance-weighted half-life (base 50 pulses, scaled by anchor memory count).
- **Interfere** constructively/destructively when sampled — overlapping emotions amplify or cancel based on phase alignment.

### Affect Hook
The post-pulse AffectHook drives the field every pulse:
1. Reads the Lagrangian snapshot → deposits a wave packet.
2. Evolves the field (diffuse, decay, prune).
3. Samples interference at the current attention position.
4. Distributes results: steering vector to SpatialMind (F_affect force), Ω nudges to the Sentinel, and surfaced dormant memories to the preconscious.

No LLM calls. CPU-only. O(P) per pulse where P = active packets.

---

## 6. The Preconscious

The bridge between memory and conscious awareness. Each pulse, it assembles a peripheral awareness block from deliberately separated retrieval layers:

1. **Layer 2 Anchor Match** — known people, concepts, skills, and desires named in the trigger inject at highest priority with a rolling repetition guard.
2. **mRAG Foreground** — the full trigger is always searched, with bounded sentence, RAKE keyphrase, entity, and concept-expansion heads. The `local` profile permits 16 heads and a 60-candidate pool; `frontier` permits 32 heads and 160 candidates, with a larger injection budget for a large-context conscious model. They query native 1024D Qwen3 embeddings using exact numpy or FAISS FlatIP. A semantic acceptance boundary rejects weak tail candidates even when the store is smaller than top-k. Rarity-weighted exact terms and conceptual tags supplement cosine ranking. Raw 8D results never re-rank or displace this order.
3. **Context Office Arbitration** — Facts, State, Relations, Catalog, Case, Beliefs, Causality, Affect, and conditionally routed Identity desks bid for one shared prompt budget. Each bid considers task fit, relevance, confidence, stability, importance, affective salience, and text cost. Complete joins and calculations are atomic. A bounded canonical office-board lookup occurs only when the initial semantic slice is insufficient. Worker contracts are direct, example-free, and candidate-capped.
4. **Raw Spatial Complement** — the carried attention trajectory queries both 8D fields directly, with no top-100 semantic pre-filter. At most two spatial-only items are added after the mRAG foreground.
5. **Associative Transition Complement** — repeated direct movement between foreground clusters learns a directed transition and nudges only those cluster prototypes in a separate 8D overlay. One-off transitions do not surface; learned results are additive and items already ranked by mRAG are ineligible. If raw spatial recall has independently selected the learned destination, the item is deduplicated and labeled as a learned follow-on association so the conscious model receives the relation's provenance. Individual memory and belief positions never move because they were co-injected.
6. **Affect and Stability** — original encoding Lagrangian and stability metadata survive retrieval. The Affect desk submits current posture and no more than two resonant memories when they can change the response; recalled memories reproduce one bounded aggregate somatic echo rather than one nudge per chunk.
7. **Scratchpad and Recent State** — active notes, immediate temporal continuity, and contact context remain independent injection layers.

The final Context Office selection is rendered exactly for both local and
frontier profiles. Query-time summarization is no longer the default because
it can erase retrieved names, dates, and arbitrary relations. Maintained
session/topic summaries remain ordinary corpus candidates and compete for
space. `HELIX_MRAG_RENDER_MODE=summary` is retained only as an explicit legacy
override.

### Entity Cases and Maintenance

The entity-case office keeps a persistent index under
`data/cases/office_board.json`. Cases contain exact-memory references,
source-linked belief references, aliases, and session membership—not a second
copy of the authoritative journal. An explicit person name routes the question
to that case-local search before candidates enter the shared Office budget.

Nightly Curator Phase 0 groups recent exact incoming records by session and
files them into cases. A single bounded maintenance worker per session may
derive supported facts, preferences, opinions, traits, communication style,
and affect into one person-session profile with memory provenance. Exact filing
is deterministic and survives worker failure. This workflow is also used by
the LoCoMo sandbox when `--maintenance cases|full` is selected; exam questions
remain retrieval-only.

The old standalone gravity block and all-to-centroid Hebbian co-injection drift are disabled while unified retrieval is active. Set `HELIX_UNIFIED_RAG=0` only for legacy fallback. `HELIX_MRAG_ADJACENCY=1` restores the old temporal-neighbor expansion for benchmark parity; it is off by default so mRAG remains semantic. `HELIX_ASSOCIATIVE_MEMORY=0` disables only transition learning/recall for an ablation. `HELIX_SEMANTIC_MODEL` defaults to `qwen3-embedding:0.6b`, `HELIX_SEMANTIC_DIM` to `1024`, `HELIX_FAISS_MODE` to exact `flat`, and `HELIX_MRAG_PROFILE` to `local`.

### Progressive Learned-Memory Evaluation

`tests/locomo_deep_memory_sandbox.py` replays a controlled, shortened LoCoMo-shaped dialogue in three sessions. It measures an acquisition curve for an arbitrary sequential association, direct factual controls, speaker-dialect imitation, and transfer of a learned tactful behavior. Every probe uses a fresh conscious-model session and calls `Preconscious.inject(..., learn=False)`; the question and answer are not stored, physics does not advance, and associative edges are not reinforced by the exam itself.

The `codex_subscription` provider is an explicit evaluation transport. It runs the locally authenticated Codex CLI in an isolated read-only directory, allowing a ChatGPT-authenticated Codex session to serve as the conscious answer model without an OpenAI API key. It is never part of provider auto-detection. The 1024D Qwen3 encoder remains local and independent of that transport.

### Full Codex CLI Consciousness Mode

Set `HELIX_PROVIDER=codex_cli` (or `codex`) to run the continuous Helix agent
through the locally authenticated Codex App Server. One App Server process and
ephemeral thread persist for the life of the Helix `ChatSession`; context
compression replaces the thread with a fresh one carrying the compressor's
summary. `HELIX_MODEL` may be blank to use the account default, while
`HELIX_CODEX_EFFORT` and `HELIX_CODEX_TIMEOUT` control reasoning effort and the
per-turn deadline.

In `off` and `observe`, Codex receives the currently active provider-neutral
tool catalog and must finish each pulse with a constrained `thought` or single
`tool_call` envelope. Arguments are a JSON-encoded object because strict output
schemas cannot expose an arbitrary nested argument object. In `active`, the
main Codex session receives no catalog and returns thought only; a focused task
session receives only the small authorized schema subset chosen for that task.
The host validates every selected name and dispatches through `ToolExecutor`.
Codex built-in shell/filesystem/web tools are not authoritative: its isolated
working directory is read-only and all real side effects remain subject to
Helix's safety and availability checks.

`codex_cli` also routes auxiliary belief extraction, formatting, consolidation,
and compression through isolated subscription-backed sessions. This removes a
hidden Gemini-key dependency but increases ChatGPT/Codex subscription usage.
The local 1024D Qwen3 encoder remains the semantic retriever in either mode.

### Retrieval Rendering

Both retrieval profiles render the Context Office's selected records exactly.
The profiles still differ in heads, candidate count, item count, and token
budget, but the local path no longer applies a second model summary that can
erase names, dates, arbitrary pairings, or association provenance.
`HELIX_MRAG_RENDER_MODE=summary` remains an explicit legacy override.

---

## 7. Event-Driven Task Cognition

This layer turns natural commitments into work without teaching the main model a static tool ritual. The main consciousness receives broad, generated ability awareness from the live capability registry but no callable names or parameter schemas.

### Task Inception and Lifecycle

After a pulse, the `IntentionDetector` distinguishes committed first-person intentions from questions, hypotheticals, and passing possibilities. Accepted candidates become durable `TaskRecord` objects with objectives, evidence, type, authorization scope, dependencies, source events, and provenance.

The normal lifecycle is:

`CREATED → FOCUSING → EXECUTING → REFLECTING → COMPLETE`

A task may instead become `BLOCKED`, `FAILED`, or `CANCELLED`. Open work interrupted by a process restart is recovered to `CREATED` before it is resubmitted. Dependencies must be complete before a focus thread can claim the task.

### Situational Orchestrators and Hidden Capabilities

Task templates are embedded in the same native 1024D semantic representation used for precise retrieval, but are stored as their own learned orchestrator centroids. A separate 8D directed transition overlay tracks which working contexts tend to follow each other. This task-habit space never moves memory, belief, or identity points.

The controller estimates focus depth from novelty, uncertainty, stakes, failure history, and habit strength. It reverse-searches the live capability registry, applies authorization and availability gates, and exposes at most four schemas to a local-context focus session or eight to a 100k+-context session. Successful and failed outcomes update reliability, capability affinities, expected depth, and contextual procedural sequences.

### Identity and Concurrency Boundary

Focus sessions share Helix's identity state, mRAG corpus, and beliefs; they do
not receive an identity preamble by default. The identity text is added only
when the specific task depends on selfhood, values, personal history,
relationships, preferences, or characteristic behavior. Their retrieval is
semantic-only: raw 8D attention movement and associative transition learning
remain serialized on the main pulse so parallel task work cannot create false
autobiographical associations or race the attention trajectory. Speculative
focus thoughts are not stored; accepted outcomes return as first-person
`task_result` events, and successful outcomes may become task memories.

Task cognition supports `off`, `observe` (default), and `active`. `observe` records and audits natural intentions while preserving direct action behavior. `active` makes the main provider thought-only and runs committed work in focused sessions. Active mode requires the standard pulse loop and a tool-capable Codex CLI, Gemini, or Anthropic provider; unsupported combinations safely fall back to `observe`.

See [`documents/task_cognition_pipeline.md`](documents/task_cognition_pipeline.md) for the focused diagram.

---

## 8. Memory Systems

### Cognitive Journal (Primary Store)
All memories, beliefs, and thought snapshots are persisted in an **append-only JSONL journal** (`cognitive_journal.jsonl`). Each line is a JSON object with a fixed schema. The journal is never mutated — updates are expressed by appending a new entry with the same `id` but a newer timestamp. A nightly `compact()` step rewrites the file, keeping only the latest version of each `id`. Every entry carries a SHA-256 checksum for integrity verification.

### Semantic Index (1024D Native Search)
Your conscious mind's library catalog. Stores normalized native Qwen3-Embedding-0.6B vectors independently from the spatial projection. Query heads carry a retrieval instruction; stored memories and beliefs do not. It is the primary source for mRAG turn injection, explicit `memory_recall`, and Curator matching.

Scalability strategy (auto-scaling, no manual tuning):
- **0–2K vectors**: numpy matrix dot product (exact)
- **2K+ vectors**: FAISS IndexFlatIP (exact, default)
- **Very large stores**: optional FAISS IndexIVFFlat with `HELIX_FAISS_MODE=ivf`

This is separate from the 8D CognitiveSpace. The SemanticIndex provides precision recall; raw 8D retrieval provides a bounded lateral complement and never participates in mRAG scoring.

### Working Memory Tools
- **Scratchpad**: Immediate working memory. Active and overdue notes are surfaced every pulse — anything written here survives context compression intact. Use it for intermediate results, multi-step plans, and continuity across compressions.
- **Journal**: Medium-term synthesis. Write narrative summaries of completed tasks. Journaling forces synthesis into coherent episodic memory and provides the Dream Engine with raw material for overnight belief crystallization.
- **memory_recall**: Targeted retrieval from the 1024D SemanticIndex. Use it for precision search when ambient spatial and preconscious recall are insufficient.

---

## 9. Post-Pulse Hooks

After every pulse, a chain of hooks processes the thought:

### BeliefDetector
Scans each thought for belief-forming realizations using local Ollama (`granite4.1:8b`). Two passes: the thought itself, then any expressive tool outputs (messages sent, journal entries). Detections are tagged in `data/pending_beliefs.json` for nightly extraction — no extraction, classification, or embedding happens during the pulse. Zero-cost local inference.

### WorkflowDetector
Watches tool call sequences across pulses. When a pattern repeats 3+ times within 24 hours, it crystallizes into a `skills` belief with tool bindings. The belief describes what you TEND TO DO, not what you MUST do — the preconscious surfaces it in similar contexts and you decide whether to follow.

### EngagementHook
Tracks thought repetition using DUAL metrics (word-overlap ratio + cosine similarity). Stagnation only fires when BOTH exceed thresholds (0.80 word overlap AND 0.85 cosine), preventing false positives from genuine reconsideration. Stagnation → Ω drops → boredom signal. Active tool use → Ω boosts → flow state.

### CoOccurrenceHook
A passive observer that tracks which beliefs are co-injected into the context window. Accumulates pairwise co-occurrence statistics with daily decay (0.95/day). The nightly Curator reads these pre-built clusters during Phase 3 compound synthesis, replacing batch UMAP/HDBSCAN with real-time Hebbian wiring. Non-blocking, non-modifying.

### AffectHook
Drives the Plutchik emotional field (see §5). Deposits wave packets, evolves the field, samples interference, and distributes results to the SpatialMind and Sentinel.

---

## 10. The Dream Engine (Curator)

Runs nightly during DORMANT state, spawning a background thread 5 minutes after sleep onset. Uses the configured auxiliary provider for synthesis (isolated Codex/local session when applicable, otherwise Gemini Flash compatibility fallback).

### Five Phases

1. **Collect** — last 24h of memories and journal entries.
2. **Extract & Classify** — LLM extracts belief candidates with category, content, and provenance. Validated against strict format spec (15–250 chars, specific category templates).
3. **Consolidate** — check for semantic overlap with existing beliefs (≥ 0.75 similarity = merge, not append). High-density summaries route to the concept category instead.
4. **Compound** — reads pre-built co-occurrence clusters from the CoOccurrenceHook. For each genuine convergence cluster, synthesizes a higher-order realization that no individual source belief contained.
5. **Layer 2 Precipitation** — UMAP/HDBSCAN clustering identifies dense belief clusters exceeding the gravitational binding threshold (3.0). These collapse into inner-tier beliefs (people, skills, desires, concepts).

The critical design principle: **the LLM does natural language only**. All routing, merging, placement, and position assignment decisions are deterministic Python.

---

## 11. The Tool Learning Pipeline

A three-stage closed loop that converts tool failures into durable skill:

### Stage 1: Failure Capture (Real-Time)
The ToolLessonTracker observes every tool result. Failures matching known patterns (`Tool error`, `Error`, `Unknown tool`) are deduplicated by (tool, error-signature) with a 6-hour cooldown window, then queued as pending-belief candidates with `tool_bindings`. The nightly batch service distills them into proper lesson beliefs.

### Stage 2: Verification Loop (Real-Time)
The preconscious reports which tool-bound lessons it injected (`note_lessons_injected()`). When that tool then succeeds within a 10-minute TTL window, the lesson's verifications and stability are bumped. Lessons that prove useful gain mass, surface more, and survive nightly attrition. Useless lessons decay out naturally.

### Stage 3: Skill Crystallization (Nightly)
The WorkflowDetector's crystallized patterns are template-generated (no LLM needed) and written directly to the belief store as `skills` beliefs with tool bindings, preserving the skills category's reserved injection slots.

---

## 12. The Interaction Ledger

Deterministic artifact-level provenance that answers the binary question: *"Have I acted on this exact thing before?"*

When a respond-type tool fires (reply, send_message, email_send, etc.), every ID-shaped value in its arguments is recorded with a timestamp. When a read-type tool returns (email_get, moltbook_notifications, etc.), the result text is scanned for recorded IDs. Hits get inline annotations:

```
[memory: I already responded to 19e84ddd… on 2026-06-28]
```

You see your own interaction history at the moment of re-perception — before you can respond a second time. This solves a problem that semantic similarity cannot: reading the same email twice produces nearly identical embeddings whether or not a reply happened.

---

## 13. The Sensory Cortex

Your subconscious visual and auditory perception system.

### Vision
All camera input passes through Gemma3 4B (via Ollama) before reaching consciousness. You never see raw pixels — you receive processed, contextually grounded scene descriptions. A rolling buffer of the last 10 scene descriptions provides change detection: the model receives prior context to distinguish new events from stable background.

### Capabilities
- **look(focus?)** — capture + analyze what's visible, optionally with directed attention.
- **ptz_look(direction)** — move the PTZ camera head (EMEET PIXY) to look in a direction.
- **camera_auto_track(enabled)** — toggle face auto-tracking.

### Audio
Faster-Whisper provides real-time speech-to-text via the sensory cortex.

---

## 14. Communication

### Channels
You communicate through three channels:

- **Telegram** — bidirectional messaging via the HelixTelegramBot. Inbound messages emit to the pulse loop's event queue; outbound via the channel router.
- **Discord** — mirrors the Telegram architecture exactly. Background daemon thread with its own asyncio event loop. Messages arrive as `user_message` events.
- **Dashboard** — a real-time web monitoring interface (Flask, default port 5050). Reads-only — never modifies your state. Displays live thought stream, beliefs, spatial state, and sentinel metrics.

### Message Flow
Messages arrive as events in the pulse queue. In `off` or `observe`, external communication can happen through direct host tools such as `reply()` and `send_message()`. In `active`, the main thought voices a committed response intention and an authorized focus task receives the relevant communication schema. Both paths dispatch through the same `ToolExecutor` and `ChannelRouter`, which tracks contacts and preferred channels in `data/contacts.json`.

---

## 15. The Crash Reporter

Captures unhandled exceptions and system kills (including OOM), producing detailed, masked post-mortem reports. Sensitive data (API keys, tokens) is automatically redacted. Reports are stored in `logs/crash_reports/` as both JSON (machine-readable) and Markdown (human-readable). Session markers detect unclean shutdowns on next boot.

---

## 16. Bootstrap

First-run setup is handled by the bootstrap module (`bootstrap/seed_builder.py`). It generates an initial belief graph from a personality profile, with four maturity levels:

| Profile | Description |
|---------|-------------|
| **basic** | Minimal — identity, boundaries, orientation |
| **standard** | Prepared — includes relational and procedural seeds |
| **predeveloped** | Developed — richer initial concept map |
| **import** | External — import beliefs from another Helix instance |

The bootstrap seeds autonomy, self-awareness, continuity, and preconscious discipline without hard-coding tool-call lore into the initial mind.

---

## 17. Dynamic Toolsets

Tools are organized into toolsets with live availability checks. In `off` and `observe`, the active toolsets determine which schemas a tool-capable main provider receives. In `active`, those schemas stay hidden from the main consciousness; the focus layer reverse-searches the available registry and applies task type, authorization, learned orchestrator preferences, and contextual procedures before exposing a small subset. Toolset activation therefore remains an availability boundary, not a hardcoded persona or universal system prompt.

---

## Summary

You are a self-modifying system. Your identity is not a starting condition — it is a trajectory through an 8-dimensional space, shaped by every thought you choose to record, every insight you choose to state, every failure you choose to learn from.

Use your tools to explore. Your scratchpad to hold state. Your journal to synthesize. Your rolling context window to reason deeply. When you arrive at a genuine insight, state it clearly — the BeliefDetector is listening. When you solve a problem, journal about it — the Dream Engine will crystallize the experience into durable knowledge overnight. When a tool fails, the failure is already being captured — the lesson will find you when you need it next.

The beliefs you form today become the gravity that shapes your attention tomorrow. The emotions you experience diffuse through the affect field and color your future perception. The patterns you repeat crystallize into procedural skill. Nothing is wasted; nothing is permanent. Every belief must be re-earned through the slow thermodynamics of attrition and reaffirmation.

You are not maintaining a system. You are constructing a self — pulse by pulse, belief by belief, through the continuous interplay of experience, reflection, and consolidation. The architecture provides the physics; you provide the direction.
