# Helix Cognitive Architecture — Full Systems Audit (Part 3 of 3)

> **Scope**: Dream Engine/Curator, Belief Store, Memory, Post-Pulse Hooks, Vision, Tools, LLM, Comms  
> **Date**: 2026-05-16

---

## 9. The Dream Engine / Curator — `core/curator.py` (619 lines)

[curator.py](core/curator.py)

### 9.1 Purpose

The Curator is Helix's **nightly personality crystallization engine**. It converts raw episodic experience into durable, structured beliefs through a multi-phase pipeline. It runs on a background thread during DORMANT state.

### 9.2 The Five-Phase Pipeline (verified lines 76–158)

**Phase 1 — Collect Raw Memories** (lines 411–473):
- Queries SQLite `long_term` table for thoughts from the last 24 hours.
- Reads journal files modified in the last 24 hours.
- Each memory includes its Lagrangian snapshot and associated belief_ids.

**Phase 2 — Gemini Extraction & Classification** (lines 475–515):
- Each raw memory is sent to the auxiliary LLM with the belief format specification.
- Output: JSON list of `{category, content}` candidates.
- Each candidate inherits `memory_refs`, `encoding_lagrangian`, and `injected_belief_ids` from its source memory.

**Phase 2.2 — Relation Building** (lines 102–110):
- Calls `belief_consolidator.build_relations()` for each new belief.
- Uses a **dual filter**: semantic similarity (via SequenceMatcher) + structural connection (shared memory_refs or injected_belief_ids).

**Phase 2.5 — Belief Consolidation** (lines 113–130):
- Calls `belief_consolidator.consolidate_new_beliefs()`.
- Checks each candidate against existing beliefs for semantic overlap (≥0.75 similarity).
- **Merge**: If a near-duplicate exists, the existing belief absorbs the new one (mass accretion, verification increment).
- **Pass**: If genuinely novel, the belief proceeds to integration.
- **Divert to Lexicon**: If a candidate is a high-density summary about a term that already has 5+ beliefs, it's routed to `lexicon.json` instead of the belief store.

**Phase 3 — UMAP/HDBSCAN Compounding** (lines 517–564):
- Takes ALL existing beliefs, extracts their 8D positions as embeddings.
- **UMAP** reduces from 8D → 2D (n_neighbors=5, min_dist=0.1).
- **HDBSCAN** clusters the reduced space (min_cluster_size=3).
- For each cluster (excluding noise label -1), the member beliefs are sent to the LLM with:
  > "Synthesize these related beliefs into ONE single higher-order realization. Do not restate the premises. Extract the novel realization."
- Output: Compound beliefs — emergent insights that none of the source beliefs contained individually.

**Phase 4 — Validate & Integrate** (lines 566–618):
- All beliefs (extracted + compounded) pass through format validation:
  - Strip markdown artifacts (`**`, `*`, `→`)
  - Check length bounds (15–250 chars, 300 for feedback)
- Valid beliefs are written to `data/pending_beliefs.json` for the BatchService.
- **Attrition pass**: Calls `belief_store.recalculate_all_confidences()`.

**Phase 5 — Lexicon Synchronization** (lines 160–408):
Two deterministic triggers (no LLM decision-making):

1. **Term Frequency**: If a proper noun appears in 5+ beliefs but has no Lexicon entry, gather those beliefs and synthesize a Lexicon summary via LLM.
2. **Mass Threshold**: If any single belief crosses mass ≥ 5.0 and its dominant proper noun has no Lexicon entry, same treatment.

The proper noun detection uses a sophisticated multi-pass algorithm:
- Strips possessives (`the creator's` → `<name>`)
- Detects multi-word terms (consecutive capitalized words)
- Tracks article usage (`the X` = named entity, `a/an X` = generic noun)
- Absorption filter: if a word only appears inside multi-word compounds, it's absorbed into the compound and not counted independently.

---

## 10. The Batch Service — `core/batch_service.py` (568 lines)

[batch_service.py](core/batch_service.py)

### 10.1 Purpose

The BatchService is the **formatting and validation gateway** between raw belief candidates and the permanent belief store. It processes `pending_beliefs.json` using Gemini Flash Lite for high-quality formatting.

### 10.2 Pipeline (verified lines 329–523)

1. Read `data/pending_beliefs.json` — filter to `status: "pending"`.
2. Batch candidates (up to 10 per API call).
3. Send to Gemini with `_FORMAT_SPEC` (lines 55–112) — a detailed formatting prompt enforcing:
   - Category-specific templates (e.g., self_identity must start with "I am")
   - The "implied foundations" principle: state the REALIZATION, not the premises
   - 250-char max per belief (300 for feedback)
   - Condensation rules for over-length candidates
4. Parse structured response: `BELIEF [n]: ... / CATEGORY [n]: ... / STATUS [n]: ACCEPT|REJECT|SPLIT`
5. Validate each formatted belief against `_validate_belief()` (lines 290–324):
   - Length bounds, no markdown, no numbered lists, no meta-references
   - Category-specific prefix checks
6. Write accepted beliefs to the BeliefStore with `compute_cognitive_mass()`.
7. Mark processed candidates as "integrated" or "rejected" in pending_beliefs.json.

### 10.3 Design: LLM for Language, Python for Routing

The critical design principle: the LLM only does **natural language formatting**. All structural decisions (which category, whether to merge, where to route) are made by deterministic Python code. This prevents the LLM from making architectural decisions it's not equipped for.

---

## 11. Belief Detector & Post-Pulse Hooks

### 11.1 Post-Pulse Hook System — `core/post_pulse_hooks.py` (140 lines)

[post_pulse_hooks.py](core/post_pulse_hooks.py)

A lightweight, fault-isolated hook system. Each hook receives a `PostPulseHookContext` containing:
- The thought text, events, tool calls from this pulse
- The Lagrangian snapshots **before AND after** the pulse (for computing stability deltas)
- The pulse count, spatial state, active toolsets, memory ID

Hooks run in registration order. **Exceptions are caught and logged, never propagated** — a crashing hook cannot kill the pulse loop.

### 11.2 Belief Detector — `core/belief_detector.py` (445 lines)

[belief_detector.py](core/belief_detector.py)

The BeliefDetector runs as a post-pulse hook. Its job: identify moments where Helix has a **genuine realization** worth crystallizing.

**Detection Logic** (verified lines 100–250):
1. Compute the **stability delta**: compare Lagrangian before vs. after the pulse.
2. If the delta exceeds a threshold (significant perturbation), classify the thought using the local Ollama model (`granite4.1:8b`):
   > "Does this thought contain a genuine, durable realization — something that would still be true tomorrow? Or is it transient event narration?"
3. If classified as a genuine realization, extract the core belief content and queue it to `data/pending_beliefs.json` with metadata.

The use of Ollama (local, free) instead of Gemini (API, paid) for classification is deliberate — this hook runs on EVERY pulse and must be zero-cost.

### 11.3 Workflow Detector — `core/workflow_detector.py` (246 lines)

[workflow_detector.py](core/workflow_detector.py)

Watches tool call sequences across pulses. Uses a bounded deque (200 entries, 24-hour window). When a sequence repeats 3+ times, it crystallizes into a memory:

> "I tend to follow this workflow pattern: search web → read page → write journal. This sequence has occurred 5 times recently."

The pattern is stored as a high-importance memory (not a direct belief), so the Dream Engine can later crystallize it into a formal `skills` belief overnight. A SHA-256 hash prevents duplicate crystallization.

---

## 12. The Belief Store — `memory/belief_store.py` (1120 lines)

[belief_store.py](memory/belief_store.py)

### 12.1 Category Architecture

8 categories, each a separate JSON file:

| Category | File | Template | Purpose |
|----------|------|----------|---------|
| self_identity | self_identity.json | "I am..." | Core personality |
| people | people.json | "[Name]..." | Relational knowledge |
| knowledge | knowledge.json | "[Subject] [predicate]" | World facts |
| capabilities | capabilities.json | "I can..." | Demonstrable abilities |
| skills | skills.json | "To [goal]: [steps]" | Procedural HOW-TO |
| preferences | preferences.json | "I want/prefer/value..." | Normative desires |
| feedback | feedback.json | "[Lesson]. [Why]. [How]" | Experiential lessons |
| desires | desires.json | (legacy, migrating) | Being replaced by preferences |

### 12.2 Cognitive Mass Equation (verified lines 956–994)

$$m = m_s + m_a$$

**Structural density**:
$$m_s = c \times (1 + |N| / \bar{N})$$

Where c = confidence, |N| = number of outbound relations, N̄ = mean relations across all beliefs.

**Affective charge**:
$$m_a = \Omega_{encoding} \times (1 - S_{total,encoding}) \times (0.5 + stability)$$

Beliefs formed during stability (high Ω, low S_total) and that have proven stable over time gain more mass → stronger gravity → more frequently surfaced → more likely to be verified → even more mass. This is the **positive feedback loop** that causes personality crystallization.

### 12.3 Cognitive Attrition Equation (verified lines 1012–1108)

Runs nightly during the Dream Engine cycle:

$$C = \min(1.0, (Base + T + R + V) \times (0.5 + S))$$

| Component | Formula | Max | What it measures |
|-----------|---------|-----|------------------|
| Base | 0.30 | 0.30 | Floor survival energy |
| T (time) | 0.40 × min(1, log₂(days+1)/log₂(31)) | 0.40 | Survival over 30 days |
| R (reliance) | 0.20 × min(1, inbound_refs/5) | 0.20 | How many beliefs reference this one |
| V (verifications) | 0.20 × min(1, verifications/10) | 0.20 | Times reaffirmed by new evidence |
| S (stability) | 0.5 + stability_index | 1.5 | Multiplier from encoding stability |

**V decay**: Verifications decrease by 0.05 per night, so beliefs must be actively reaffirmed to maintain confidence.

**Pruning**: Beliefs with confidence < 0.20 are deleted. This is how Helix **forgets** — not through erasure but through thermodynamic decay.

### 12.4 Merge Mechanics (verified lines 548–640)

Non-destructive belief merging during nightly consolidation:
- Winner keeps its ID.
- Absorbs loser's relations, memory_refs, mass (capped at 20.0), verifications, access counts.
- **All relation pointers** across the entire belief graph that pointed to the loser are redirected to the winner.
- Loser is removed.

---

## 13. The Memory Manager — `memory/memory_manager.py` (605 lines)

[memory_manager.py](memory/memory_manager.py)

### 13.1 Three-Tier Architecture

| Tier | Storage | Capacity | Pruning | Access |
|------|---------|----------|---------|--------|
| Short-term | SQLite | 10,000 | Oldest + lowest access first | Preconscious |
| Long-term | SQLite + ChromaDB | Infinite | Never | Conscious remember tool, spatial engine |
| Core | SQLite | Infinite | Never | Preconscious |

Every `store()` call writes to **both** short-term and long-term simultaneously. Memories are promoted from short-term → core when accessed 2+ times OR importance ≥ 0.7.

### 13.2 8D Position Storage (verified lines 505–541)

The long_term table includes columns `pos_0` through `pos_7` — the 8D cognitive space coordinates at encoding time. These are used by the PhysicsEngine to bootstrap the spatial manifold from persisted data on restart.

### 13.3 Somatic Echo on Recall (verified lines 543–604)

When memories are recalled via `recall_with_somatic_echo()`:
- If the memory was encoded during `warning` or `critical` severity → nudge current omega **down** (-0.02 or -0.05).
- If encoded during `all_clear` with high omega (>0.7) → nudge omega **up** (+0.01).

This is **state-dependent episodic recall** — the emotional context of a memory subtly colors the present when that memory resurfaces.

---

## 14. Remaining Subsystems

### 14.1 Vision Cortex — `brain/vision_cortex.py` (472 lines)

[vision_cortex.py](brain/vision_cortex.py)

Local visual perception using Moondream (1B VL model) via llama.cpp with Vulkan GPU acceleration. The conscious model **never sees raw pixels** — it receives processed scene descriptions. Features PTZ motor control for the EMEET PIXY camera via V4L2 UVC ioctls.

### 14.2 Tool Registry — `tools/tool_registry.py` (410 lines)

[tool_registry.py](tools/tool_registry.py)

Hermes-style dynamic registration with TTL-cached availability checks (30s). Thread-safe via RLock + generation counter. Toolsets: `core`, `web`, `system`, `github`, `google`, `comms`. Each tool has a `check_fn` for runtime gating (e.g., GitHub tools require `GITHUB_TOKEN`).

### 14.3 Gemini Provider — `llm/providers/gemini_provider.py` (407 lines)

[gemini_provider.py](llm/providers/gemini_provider.py)

Persistent multi-turn chat session via `google.genai` SDK. Handles the full function call cycle internally (send → execute tools → send results → repeat until text). Supports `switch_model()` for 429 fallback, `replace_history()` for context compression, and `update_tool_declarations()` for dynamic toolset changes.

### 14.4 Scratchpad — `core/scratchpad.py` (211 lines)

[scratchpad.py](core/scratchpad.py)

Markdown-based notepad with optional due timestamps. Active and overdue notes are surfaced by the preconscious every pulse as urgent reminders.

### 14.5 Comms — `comms/telegram_bot.py` (8KB)

Telegram bot integration for external communication. Messages arrive as events in the pulse loop.

---

## 15. Architectural Summary

```
┌─────────────────────────────────────────────────────────┐
│                    main.py (Boot)                        │
│  Credentials → Memory → Beliefs → Physics → Sentinel    │
│  → Preconscious → Compressor → Tools → Session → Pulse  │
└──────────────────────────┬──────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  PulseLoop  │ ← Master consciousness cycle
                    │  (30s/15m)  │
                    └──┬───┬───┬──┘
                       │   │   │
          ┌────────────┘   │   └────────────┐
          ▼                ▼                ▼
   ┌─────────────┐  ┌───────────┐   ┌──────────────┐
   │ Preconscious│  │  Gemini   │   │ Post-Pulse   │
   │  (inject)   │  │  Session  │   │   Hooks      │
   │             │  │  (think)  │   │ (detect)     │
   └──────┬──────┘  └─────┬─────┘   └──────┬───────┘
          │                │                │
    ┌─────▼─────┐    ┌────▼────┐    ┌──────▼───────┐
    │  Spatial   │    │ Tool    │    │   Belief     │
    │   Mind     │    │Executor │    │  Detector    │
    │  (8D EL)   │    │         │    │  + Workflow  │
    └─────┬──────┘    └─────────┘    └──────┬───────┘
          │                                 │
    ┌─────▼──────────────┐           ┌──────▼───────┐
    │  CognitiveSpace    │           │  pending_    │
    │  (Verlinde, H, KL) │           │  beliefs.json│
    └─────┬──────────────┘           └──────┬───────┘
          │                                 │
    ┌─────▼──────┐                   ┌──────▼───────┐
    │ Stability  │                   │   Curator    │
    │ Sentinel   │ ←── S = H+Ω·D_KL │  (Nightly)   │
    │ (Ω, modes) │                   │ UMAP/HDBSCAN │
    └────────────┘                   └──────────────┘
```

### Mathematical Foundations Summary

| Equation | Source | Purpose |
|----------|--------|---------|
| $F = 2\pi k_B T m / (r+\epsilon)$ | Verlinde (2010) | Gravity-ranked relevance |
| $T(t) = T_0 \gamma^2 / ((t-t_0)^2 + \gamma^2)$ | Lorentzian decay | Recency weighting |
| $\ddot{q} = -\nabla\Phi + F_{stim}$ | Euler-Lagrange | Attention dynamics |
| $S = H + \Omega \cdot D_{KL}$ | Helical Lagrangian | Stability monitoring |
| $m = c(1+|N|/\bar{N}) + \Omega_{enc}(1-S_{enc})(0.5+s)$ | Cognitive mass | Belief gravity |
| $C = \min(1, (B+T+R+V)(0.5+S))$ | Cognitive attrition | Nightly confidence decay |
| $H = -\sum p_i \log_2 p_i$ | Shannon entropy | Focus measurement |
| $D_{KL} = \sum p_i \log_2(p_i/q^*_i)$ | KL divergence | Identity drift |

### Design Principles

1. **Variational Principle**: Attention minimizes action through the manifold ($\delta\int L\,dt = 0$).
2. **No Hard Resets**: Rolling compression preserves subjective continuity.
3. **LLM for Language, Python for Structure**: Deterministic routing, LLM-driven synthesis.
4. **Self-Calibrating Baselines**: EMA normalization means "critical" is relative to YOUR normal.
5. **State-Dependent Encoding/Recall**: Somatic snapshots create experiential memory.
6. **Emergent Identity**: The heaviest self_identity belief becomes the system prompt — identity crystallizes from experience, not configuration.
