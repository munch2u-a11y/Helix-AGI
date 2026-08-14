# Preconscious Injection Audit

**Status:** Current Runtime Audit · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

**Scope:** [`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py)

---

## 1. Runtime Role & Injection Assembly

The `Preconscious` engine ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L100-L200)) assembles per-pulse prompt annotations woven into Helix's conscious prompt stream:

- **Layer 2 Anchor Match**: Priority term-matched lookup for people, concepts, skills, and desires ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L470-L482)).
- **Unified Retrieval Pipeline**: Integrates 1024D native mRAG semantic recall with bounded 8D spatial complements ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L1880-L1950)).
- **Gravity-Guided Multi-Hop Traversal (`retrieve_multihop`)**: Automatically triggered on multi-question or relational triggers ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L1910-L1930)).
- **Organic Tone Induction (`Personal Opinions:`)**: Converts affectively salient memories into a 1st-person subjective block ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L2418-L2428)).
- **Context Office Desks**: Facts, State, Relations, Catalog, Case, Beliefs, Causality, Affect, and Identity desks ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L1880-L1950)).
- **Scratchpad Working Memory & Temporal State**: Active notes, recent memories, and contact context ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L540-L560)).

---

## 2. Construction & Cached State

The constructor ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L100-L200)):
- Stores references to `beliefs`, `memory`, `physics`, `scratchpad`, `channel_router`, and `sentinel`.
- Shares active toolset sets and rolling tool usage history (`_recent_tool_history`).
- Initializes `_concept_blacklist`, `_memory_blacklist`, `_tool_belief_blacklist`, and `_injection_gravity_decay`.
- Loads Layer 2 anchors into `_lexicon_lookup` ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L145-L160)).
- Initializes `UnifiedRetrieval` when `HELIX_UNIFIED_RAG=1` ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L180-L200)).

---

## 3. Unified Selection & Multi-Hop Traversal

In `_unified_select()` ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L1880-L1950)):
1. Checks if the trigger string contains multi-step / multi-question structure.
2. If multi-step, invokes `self._unified.retrieve_multihop(query=trigger_text, ...)`, which traverses 8D gravity basins around Hop 1 evidence to perform Hop 2 retrieval ([`core/unified_retrieval.py`](file:///home/nemo/_mrag_composite_test/core/unified_retrieval.py#L300-L365)).
3. Otherwise, calls `self._unified.retrieve()`, combining 1024D mRAG foreground with bounded 8D spatial complements (`UNIFIED_COMPLEMENT_CAP = 2`).

---

## 4. Selection Rendering & Tone Induction

In `_render_selection()` ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L2242-L2430)):
1. Accumulates selected items up to the dynamic token budget.
2. Formats item role tags (`STATE DESK`, `RELATIONS DESK`, `CATALOG DESK`, `BELIEFS DESK`).
3. Invokes `self._unified.format_personal_opinions(rendered_selection)` to append a formatted `Personal Opinions:` block.
4. Updates injection gravity decay (`_injection_gravity_decay`) and calculates the 8D weighted cluster centroid (`_last_cluster_centroid`).
5. Writes diagnostic snapshot to `data/spatial/spatial_injection.json` ([`core/preconscious.py`](file:///home/nemo/_mrag_composite_test/core/preconscious.py#L2002-L2099)).
