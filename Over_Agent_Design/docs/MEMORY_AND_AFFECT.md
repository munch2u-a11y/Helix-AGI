# 🧠 Memory & Affect Simulation Specification

> **Helix Preconscious Retrieval, Dynamic Identity Compilation, and Synthetic Affect State Vector Pipelines.**

---

## 1. Integrated Helix Recall (`integrated_mrag.py`)

The Over-Agent uses Helix's in-repository memory implementation directly. There is no second cache and no copied feature-branch runtime.

### Canonical stores
- `data/memory/cognitive_journal.jsonl`: append-only Layer-0 memories, including inbound/outbound messages and document chunks.
- `data/beliefs/*.json`: outer beliefs plus Layer-2 `people`, `concepts`, `skills`, and `desires` anchors.
- `data/spatial/semantic_index*`: the semantic index supplied by the containing Helix revision.

### Preconscious Retrieval Workflow:
1. `SubconsciousConductor.process_user_event()` calls `HelixMRAGRuntime.recall_context()` before generation.
2. On original `main`, the in-folder bridge queries Helix's 384D semantic index and prepends bounded exact Layer-2 term/alias matches.
3. On revisions that provide `core.unified_retrieval`, the runtime selects that native multi-head mRAG implementation automatically.
4. The compact result grounds the current executive and speaker calls, then inbound and outbound text are persisted through `MemoryManager`.

Original `main` predates structured record envelopes. In that compatibility mode, record kind, direction, epistemic role, and evidence scopes are preserved as `record:*` tags on the canonical journal entry. No parent-repository file is modified by this subproject.

---

## 2. Dynamic Identity Compiler (`dynamic_identity_compiler.py`)

Rather than relying on a static hardcoded system prompt, Helix uses a **Dynamic Identity Compiler** that constructs system prompt anchors on every turn by combining three layers:

```
+-----------------------------------------------------------------------------------+
|                        DYNAMIC IDENTITY SYSTEM PROMPT ANCHOR                      |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | Layer 1: Baseline Identity (identity.md)                                    |  |
|  | - Shared First-Person Selfhood ("I am Helix...")                              |  |
|  | - Error Learning & Failure Adaptation Principles                            |  |
|  +-----------------------------------------------------------------------------+  |
|  | Layer 2: Dynamic Self-Opinion Statement (self_opinion.json)                  |  |
|  | - Running 1-sentence consolidated perspective updated during DORMANT passes  |  |
|  +-----------------------------------------------------------------------------+  |
|  | Layer 3: Synthetic Affect Vector (synthetic_affect_state.json)               |  |
|  | - Live parameter injection: [Valence, Arousal, Focus Depth, State Label]      |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 3. Synthetic Affect Simulation Pipeline (`affect_simulation.py`)

The **Synthetic Affect Pipeline** tracks mathematical state vectors to modulate prompt personality and conceptual gravity:

### State Vector Parameters:
- **`Valence`** (Range: -1.0 to +1.0): Tracks positive vs. diagnostic interaction sentiment.
- **`Arousal`** (Range: 0.0 to 1.0): Tracks calm vs. active compute energy.
- **`Focus Depth`** (Range: 0.0 to 1.0): Tracks diffuse vs. deep analytical concentration.
- **`State Label`**: Derived synthetic descriptor (e.g., `"Deeply Focused & Analytical"`, `"Calm & Receptive"`, `"Reflective & Diagnostic"`).

### Dynamic Update Protocol:
- During active turns, `update_affect()` adjusts state parameters based on interaction sentiment and task complexity.
- State is persisted to `synthetic_affect_state.json` and injected into the prompt anchor:
  `[Synthetic Affect Vector]: Deeply Focused & Analytical | Valence: +0.50 | Arousal: 0.40 | Focus Depth: 0.80`

---

## 4. DORMANT State Nightly Consolidation Pass

During extended periods of inactivity or nightly maintenance, `run_dormant_consolidation_pass()` executes:
1. **Dialogue Compaction**: Prunes raw turn logs into 1-line summary notes (`compacted_memories`).
2. **Self-Opinion Update**: Evaluates recent session learnings and generates a fresh 1-sentence self-opinion statement saved to `self_opinion.json`.
3. **Pickle State Persistence**: Saves consolidated stream state to `helix_seeded_state.pkl`.
