# 🧠 Memory & Affect Simulation Specification

> **Multi-Head mRAG Preconscious Retrieval, Dynamic Identity Compilation, and Synthetic Affect State Vector Pipelines.**

---

## 1. Multi-Head mRAG Adapter (`mrag_adapter.py`)

The **Helix mRAG Adapter** connects the local mRAG retrieval engine (`/home/nemo/Local-mRag`) to canonical Helix memory stores (`/home/nemo/Helix/data`).

### Indexed Data Stores:
- `pending_beliefs.json` (Real-time active beliefs)
- `contacts.json` (Entity profiles and user relationship records)
- `tool_learned_notes.json` (Operational tool habits and efficiencies)
- `interaction_ledger.json` (Conversation history ledger)
- `cognitive_journal.jsonl` (Subconscious journal logs)
- `data/beliefs/*` & `data/memory/*` (Subdirectories containing domain memory nodes)

### Preconscious Retrieval Workflow:
1. When a research pass is triggered, `HelixMRAGAdapter.retrieve_mrag_context(query)` extracts query keywords.
2. Keyword matching and semantic vector heads scan the belief corpus for matching items.
3. Top matching items are formatted into a `--- mRAG RECALLED HELIX MEMORIES ---` observation receipt.
4. The receipt is injected into `self.event_stream` **before** the dialogue synthesis pass.

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
