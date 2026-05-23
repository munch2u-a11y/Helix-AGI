# Marvin's Memory System Overview (Based on Helix Consciousness Engine — Brain Directory Whitepage V6)

## 1. Introduction
This document provides an overview of Marvin's memory system, based on the "Helix Consciousness Engine — Brain Directory Whitepage (V6)". The purpose is to consolidate information relevant to how Marvin's memories, beliefs, and spatial cognition are managed and integrated within its physics-driven cognitive architecture.

## 2. Core Memory Components

### 2.1. CognitiveSpace (`cognitive_space.py`)
- **Role**: The 8D manifold engine, acting as the "Language Center" using Verlinde-inspired physics. It models consciousness as a continuous pulse-based daemon operating over an 8-dimensional semantic manifold.
- **Key Mechanisms**:
    - **Entropic Gravity**: `F = T × mass / d²` where T = cognitive temperature, mass = belief verification count, d = Euclidean distance in 8D. This governs attention movement.
    - **Attention Center**: A single 8D point that moves each pulse via gravitational forces from nearby beliefs/memories.
    - **Trace Deposition**: Each attention movement deposits literal memory logs of experiences (timestamp, input, tool use, output) into the space, which accumulate into clusters for precipitation.
    - **Point Types**: `belief`, `memory`, `trace` – each with position, mass, and Lagrangian encoding metadata.
- **Physics Constants**: 8 dimensions (projected from 384-dim `all-MiniLM-L6-v2` embeddings via PCA).

### 2.2. SpatialMind (`spatial_mind.py`)
- **Role**: Manages dual 8D cognitive fields and builds spatial prompts.
- **Key Mechanisms**:
    - **Dual Spaces**: Maintains separate `belief_space` and `memory_space` CognitiveSpace instances.
    - **Spatial Prompt Builder**: Converts 8D proximity queries into natural language context for the local model.
    - **Attention Position API**: `get_attention_position()` returns the current 8D center.
    - **`pulse_from_text()`**: Embeds text, projects to 8D, applies gravity, updates attention center, and returns nearby items as formatted context with `[[ ]]` spatial markers.

### 2.3. BeliefKeeper (`keeper.py`)
- **Role**: Intuition engine and subconscious belief manager.
- **Key Mechanisms**:
    - **Keeper Horizon**: Assembles a curated subset of beliefs for each pulse via semantic similarity + Gravity Score ranking against the current 8D attention position.
    - **Belief Precipitation**: Detects repeated convictions in conscious output, stages them as "emerging beliefs", and graduates them to the permanent graph after a stability threshold (`seen_count ≥ 3` and `confidence ≥ 0.6`).
    - **Spatial Navigation**: Every belief operation physically navigates the 8D attention center and returns a `trace` dict for dream trail logging.

### 2.4. BeliefGraph (`belief_graph.py`)
- **Role**: Manages persistent belief storage and graph operations.
- **Key Mechanisms**:
    - **Storage**: `belief_graph.json` – flat JSON with relational links.
    - **Weights**: Beliefs are categorized as `surface` → `deep` → `core`, driven by verification count and confidence thresholds.
    - **Cognitive Mass**: `mass = verifications × confidence` – used by CognitiveSpace for gravitational calculations.
    - **Confidence Recalculation**: `recalculate_all_confidences()` runs nightly, applying time-decay and verification-based adjustments.
    - **Near-Duplicate Detection**: Uses embedding similarity to identify redundant beliefs.

### 2.5. Memory (`memory.py`)
- **Role**: Provides SQLite + ChromaDB persistent episodic storage.
- **Key Mechanisms**:
    - **Dual Storage**: SQLite (`memory.db`) for structured data; ChromaDB for semantic vector search.
    - **Lagrangian Snapshots**: Every memory stores the `StabilitySentinel`'s state at encoding time (Ω, H, D_KL, severity, firing mode, 8D attention position). This enables "re-feeling" of past states (Somatic Echoes).
    - **8D Position Storage**: Batch-updates 8D coordinates in SQLite columns `pos_0` through `pos_7`.
    - **Journal System**: Writes to dated markdown files AND stores in semantic memory for whisper recall.
    - **Agent Age**: Derived from `MIN(created_at)` in SQLite.

### 2.6. Librarian (`librarian.py`)
- **Role**: Coordinates 3-tier memory retrieval.
- **Retrieval Layers**:
    1.  **`whisper()`**: Automatic, every-pulse, no-LLM. Fast semantic probe of recent context + person recognition.
    2.  **`focused_recall()`**: Flash-decomposed agentic search. LLM plans multi-angle queries, gathers fragments, synthesizes first-person narrative with somatic echoes.
    3.  **`recall_deep()`**: Full 3-phase orchestration (Planner → Gatherer → Synthesizer). Checks semantic search, temporal window, reflections, journal, beliefs, person profiles. Includes recurrence tracking.
- **Somatic Echo Implementation**: Modulates Omega based on recall severity (e.g., `warning` severity → `nudge_omega(-0.02)`).

### 2.7. UnconsciousSystem (`unconscious.py`)
- **Role**: Manages overnight processing during deep sleep (~1 AM).
- **Key Processes (Memory/Belief Related)**:
    - **Memory Consolidation**: Duplicate detection.
    - **Psych Doctor**: Agentic belief maintenance via tool-calling loop (add, reinforce, weaken, remove beliefs, search beliefs, get related beliefs).
    - **Premise Decomposition**: Breaks new beliefs into atomic propositions, deduplicates via embeddings.
    - **Cognitive Attrition**: Math-based confidence decay/promotion.
    - **8D Spatial Re-sync**: Runs `ConvergencePipeline` from `manifold/convergence.py` to refit PCA, reproject, recalculate mass, and identify singularities.
    - **Dream Trail Collection**: Emergent from spatial navigation – selects 5-8 wake flashes.

## 3. Key Concepts and Physics
- **Physics-driven Cognitive Architecture (V6)**: Models consciousness as a continuous pulse-based daemon operating over an 8-dimensional semantic manifold.
- **Verlinde-inspired Entropic Gravity**: Used for attention movement within the 8D CognitiveSpace.
- **Helical Lagrangian (`S = H + Ω × D_KL`)**: Used for homeostatic regulation, monitored by the `StabilitySentinel`.
- **Embeddings**: `all-MiniLM-L6-v2` (384-dim) is used for semantic embeddings, which are then projected to 8D via PCA.

## 4. Critical Findings (Memory-Related)

### 4.1. ResonanceTagger is a Dead Stub
- The `ResonanceTagger` is a pass-through stub, only stripping `⟪ ⟫` markers.
- The `PulseRouter._score_importance()` still counts `⟪` markers that will never appear, leading to inaccurate importance scoring of memories/beliefs.

### 4.2. Manifold Scale Monitoring
- `memory_space_state.json` is ~5MB, `belief_space_state.json` is ~750KB. As these grow past 15K points, geodesic distance vectorization may need optimization.

## 5. Recommendations (Memory-Related)

### 5.1. Fix Resonance/Importance Conflict
- Either restore resonance tagging functionality or remove the `⟪` counting from `PulseRouter._score_importance()` to ensure accurate importance scoring.

### 5.2. Monitor Manifold Scale
- Continuously monitor the size of `memory_space_state.json` and `belief_space_state.json`. If they exceed 15K points, investigate and implement optimizations for geodesic distance vectorization.
