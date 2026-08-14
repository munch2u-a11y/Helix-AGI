# Helix Cognitive Architecture: System Manual

**Documentation Status:** Current Runtime Reference · **Last Verified Against Source:** 2026-08-14

This is the canonical system manual for developers, operators, and AI pairing sessions. It specifies the live architecture contracts implemented across [`core/`](core/), [`llm/`](llm/), [`tools/`](tools/), [`memory/`](memory/), [`dashboard/`](dashboard/), and [`tests/`](tests/).

For architecture summaries and file link maps, see [`documents/architecture_current.md`](documents/architecture_current.md) and [`documents/README.md`](documents/README.md).

---

## 1. Identity & Belief Store

Helix's identity is dynamically constructed from its own belief graph rather than a static prompt file.

### Dynamic Preamble & Boot Sequence
Your system prompt opens with your **heaviest `premises` belief** — queried live from the belief store at boot ([`memory/belief_store.py`](memory/belief_store.py#L40-L100)). If a new core premise overtakes it in cognitive mass during consolidation, subsequent sessions use that updated belief as the identity preamble.

### The 7 Belief Categories
Beliefs are organized across two epistemic tiers and stored as JSON files in `data/beliefs/`:

**Outer Tier** (formed in real-time during pulse loop execution):
| Category | Template | Canonical Role |
|---|---|---|
| `premises` | "I am..." / "IF..." | Core self-narrative, operational axioms, self-observations |
| `propositions` | "X is Y" | Learned facts, derived rules, domain knowledge |
| `preferences` | "I prefer/value..." | Values, behavioral norms, interaction styles |

**Inner Tier** (consolidated nightly by the Dream Engine / Curator):
| Category | Template | Canonical Role |
|---|---|---|
| `people` | "[Name] is..." | Entity profiles and multi-person relational knowledge |
| `skills` | "To [goal]: [steps]" | Proven tool-backed procedural workflows & verified lessons |
| `desires` | "I hope/aim..." | Long-term goals and cognitive aspirations |
| `concepts` | "X represents Y" | Consolidated higher-order conceptual understanding |

### Cognitive Mass Formula
Each belief carries **cognitive mass** ($m$), determining its gravitational pull on attention:
\[m = m_s + m_a\]
\[m_s = \text{confidence}\]
\[m_a = \Omega_{\text{encoding}} \times (1 - s_{\text{total}}) \times (0.5 + \text{stability})\]

### Cognitive Attrition & Thermodynamic Decay
Nightly consolidation recalculates belief confidence:
\[C = \min\left(1.0, (\text{Base} + w_T + w_R + w_V) \times (0.5 + S)\right)\]
Verifications decay by $0.05/\text{night}$. Beliefs with confidence $C < 0.20$ are pruned.

---

## 2. The Pulse Loop & Context Office Architecture

Helix operates as an event-driven cognitive pulse loop ([`core/pulse_loop.py`](core/pulse_loop.py#L120-L280)).

### Runtime States
| State | Cadence | Trigger Condition | Primary Purpose |
|---|---|---|---|
| **DORMANT** | 60s check | Configured active hours window | Sleep — Dream Engine consolidation runs |
| **ACTIVE** | 10s | User message / active conversation | Fast interactive turn processing |
| **REGULAR** | 30s | 2 minutes without incoming events | Autonomous task execution |
| **RESTING** | 15m default | 10 minutes in REGULAR without activity | Low-power autonomous reflection |

### Context Office & Unified Retrieval Pipeline
Every awake pulse executes context assembly through `ContextOffice` ([`core/preconscious.py`](core/preconscious.py#L1880-L1950) & [`core/unified_retrieval.py`](core/unified_retrieval.py#L200-L380)):

1. **Front Desk Categorization**: Incoming events (direct messages, emails, tool returns, sensory readings) are parsed into typed front desks.
2. **Parallel Retrieval Lanes**:
   - **1024D Semantic mRAG (Qwen3-Embedding-0.6B)**: Multi-head foreground vector recall over past sessions, beliefs, and documents.
   - **Bounded 8D Spatial Complements**: Lateral gravity-ranked complements (max 1–2 items) that add non-displacing associative context.
   - **Gravity-Guided Multi-Hop Traversal (`retrieve_multihop`)**: Automatically traverses 8D gravity basins around Hop 1 evidence to resolve multi-step queries.
   - **Organic Tone Induction (`Personal Opinions:`)**: Converts affectively salient memories into a 1st-person subjective block via `format_personal_opinions()`.
3. **Shared Bid Arbitration**: Specialist desks (Facts, State, Relations, Catalog, Case, Beliefs, Causality, Affect, Identity) bid for context allocation based on utility, confidence, and token budget.
4. **Conscious Execution**: The compiled capsule is injected into the conscious LLM prompt (Codex CLI, Gemini, Anthropic, Ollama), driving function calls or direct responses.

---

## 3. The 8D Cognitive Manifold & Entropic Gravity

Spatial continuity uses 384D embeddings projected to an 8D continuous space via a fixed Johnson-Lindenstrauss matrix ([`core/cognitive_space.py`](core/cognitive_space.py#L30-L120) & [`core/spatial_mind.py`](core/spatial_mind.py#L50-L140)).

### Verlinde Entropic Gravity
Gravitational potential $F_g$ exerted on attention:
\[F_g = \frac{T \cdot m}{d^2 + \epsilon}\]
Where $T$ is spatial temperature, $m$ is cognitive mass, $d$ is 8D Euclidean distance, and $\epsilon = 10^{-4}$.

### Multi-Hop Traversal (`retrieve_multihop`)
For complex multi-step queries, `retrieve_multihop()` identifies Hop 1 evidence, extracts 8D gravity-basin keywords (`SpatialMind.get_gravity_basin_keywords()`), and executes directed Hop 2 queries to pull required procedural context before execution ([`core/unified_retrieval.py`](core/unified_retrieval.py#L300-L365)).

---

## 4. Stability Sentinel & Somatic State

The `StabilitySentinel` background thread ([`core/somatic_sentinel.py`](core/somatic_sentinel.py#L40-L150)) monitors cognitive and physical health:

### Helical Lagrangian & Hedonic Omega ($\Omega$)
\[S_{\text{total}} = H + \Omega \cdot D_{\text{KL}}\]
- $H$: System entropy (probe failures, hardware pressure).
- $\Omega$: Hedonic state (baseline $0.5$, bounded $[0.05, 1.0]$).
- $D_{\text{KL}}$: KL divergence from core identity baseline.

---

## 5. Affect Field (Plutchik 8D Emotional Space)

An 8D emotional state tracker overlaid on the manifold ([`core/affect_field.py`](core/affect_field.py#L30-L120)):
`joy · trust · fear · surprise · sadness · disgust · anger · anticipation`

Emotional wave packets diffuse, decay, and interfere constructively/destructively to modulate spatial attention forces and surface resonant memories.

---

## 6. Dynamic Hermes Tool Registry & Dynamic UI Canvas

Tool execution is governed by the central dynamic Hermes registry ([`tools/tool_registry.py`](tools/tool_registry.py#L30-L110)).

### Hermes Dynamic Tool Gating
- Tools are registered with runtime availability checks (`check_fn`) and TTL caching (30s).
- Unloaded or unauthorized tools are hidden from the model's context window.

### Dynamic Agent-Controlled UI Canvas (`render_ui_canvas`)
Helix can dynamically control and update the user's active Web Dashboard view using `render_ui_canvas` ([`tools/ui_canvas_tool.py`](tools/ui_canvas_tool.py#L25-L95)):
- `markdown`: Rich formatted reports and documents.
- `image`: Generated diagrams, charts, and media assets.
- `browser`: Embedded external web pages and live URLs.
- `terminal`: Execution logs and sandbox terminal streams.
- `card`: Display big hero emphasis cards.

### Tool Lesson Tracker & Procedural Learning
Every tool failure is captured by `ToolLessonTracker` ([`core/tool_lesson_tracker.py`](core/tool_lesson_tracker.py#L20-L90)). Lessons are deduplicated and queued for nightly Curator consolidation ($G=2.5$), crystallizing into `skills` beliefs with tool bindings for future sessions.

---

## 7. Communication & UI Web Dashboard

- **Web Dashboard (`localhost:5050`)**: Real-time web chat, thought stream monitor, spatial manifold inspector, and live **Agent Canvas 🎨** tab ([`dashboard/dashboard.py`](dashboard/dashboard.py#L420-L535)).
- **Telegram & Discord**: Optional bidirectional channels via `HelixTelegramBot` and `HelixDiscordBot`.

---

## 8. One-Command Launchers & Test Suites

Helix provides 1-click launcher shell scripts at the repository root:

- **Launch Agent**: `./Launch\ Helix\ Agent.sh` (or `venv/bin/python main.py`)
- **Setup Wizard**: `./Helix\ Setup\ Wizard.sh` (or `venv/bin/python -m wizard`)
- **Health Check Diagnostic**: `./Run\ Health\ Check.sh` (or `venv/bin/python scripts/run_health_check.py`)
- **Interactive Benchmark Suite Runner**: `./Run\ Benchmarks.sh` (or `venv/bin/python tests/run_all_benchmarks.py`)

### Automated Benchmark Suites
1. `tests/test_mrag_ablation_bench.py` — Non-LLM 100-question A/B retrieval ablation.
2. `tests/test_helix_early_memories.py` — Early Helix memory grounding & organic tone.
3. `tests/test_agent_adaptation_bench.py` — Constraint adaptation & skill acquisition.
4. `tests/test_live_agent_pulse_simulation.py` — Multi-pulse live conversation simulation.
5. `tests/test_autonomous_pulse_chain.py` — Autonomous monologue stream & 8D attractor navigation.
6. `tests/test_longform_agentic_memory_bench.py` — Long-form agentic memory, proactive initiative, and opinion defense.
