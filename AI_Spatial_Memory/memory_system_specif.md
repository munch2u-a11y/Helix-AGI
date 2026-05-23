# Helix Memory System Specification

This document details the memory architecture of the Helix AGI system, synthesizing information from the core audit documents. It covers storage, retrieval, spatial organization, working memory, and identifies current challenges. This version has been updated to reflect the LLM-agnostic design changes.

## 1. Overview of the Memory System

The Helix memory system is a sophisticated, event-driven architecture designed to manage beliefs, memories, thoughts, and events within an 8-dimensional cognitive space. It moves beyond traditional RAG (Retrieval-Augmented Generation) by employing a physics-inspired "cognitive gravity" model for attention and retrieval.

Key components include:
*   **CognitiveJournal:** The foundational, append-only persistence layer.
*   **MemoryManager:** A compatibility wrapper bridging higher-level components to the `CognitiveJournal`.
*   **Scratchpad:** The Markdown-based working memory buffer for active tasks and reminders.
*   **CognitiveSpace:** Implements the 8-dimensional spatial manifold for organizing beliefs and memories.
*   **SpatialMind:** Manages dual cognitive spaces (beliefs and memories), orchestrates attention dynamics, and injects spatial context into the LLM prompt.

## 2. Memory Storage and Persistence

### 2.1 Cognitive Journal (`cognitive_journal.py`)
The `CognitiveJournal` is the single source of truth for all of Helix's persistent data.
*   **Format:** Implemented as an append-only JSON-Lines (JSONL) file (`cognitive_journal.jsonl`).
*   **Immutability:** Entries are never mutated; updates are handled by appending new entries with the same ID but newer timestamps.
*   **Integrity:** Each entry includes a SHA-256 checksum for tamper detection. Atomic writes with OS-level sync ensure data integrity.
*   **Compaction:** A nightly routine rewrites the journal, preserving only the latest version of each ID to manage file size.

### 2.2 Memory Manager (`memory_manager.py`) - LLM-Agnostic
The `MemoryManager` acts as a facade, providing a backward-compatible API (`store()`, `get_recent()`) to higher-level components. This module has been refactored (`agnostic_memory_manager.py`) to be LLM-agnostic.
*   **Routing:** All write operations are routed to `journal.append_memory()`.
*   **ID Generation:** Emulates legacy auto-incrementing short-term IDs (`_st_counter`).
*   **Retrieval:** `get_recent()` reads and checksum-verifies the entire journal via `journal.load_all()`, filters by type and recency, and returns results in a legacy-compatible flat schema.
*   **LLM Agnostic Design:** Direct embedding function imports (e.g., from ChromaDB) have been replaced with a generic embedding provider interface (`_GLOBAL_EMBEDDING_FUNCTION`), allowing the module to function with any compatible LLM embedding model provided externally.

### 2.3 Challenges in Storage and Persistence
*   **`get_recent()` Performance:** Reading the entire `cognitive_journal.jsonl` file for every `get_recent()` call is a significant I/O bottleneck that will worsen as the journal grows. An in-memory cache or an append-tail reader should be considered.
*   **`_st_counter` State Loss:** The `_st_counter` resets on every restart, leading to `id` collisions across sessions. While compaction handles this by overwriting older entries with the same `id`, this is a critical bug if short-term IDs are meant to be unique across sessions or if historical versions are important.
*   **Compaction vs. Immutable History:** Nightly compaction, while necessary for performance, destroys the historical versions of `id`s. If preserving the full evolution of thoughts and beliefs is a design goal, compaction should archive old lines rather than discard them.
*   **Silent Checksum Skipping:** Corrupted lines in the journal are silently skipped. While good for resilience, it might mask underlying file-system degradation. Warning logs for corrupted lines could be beneficial.

## 3. Spatial Organization and Retrieval

### 3.1 Cognitive Space (`cognitive_space.py`)
This module implements the core 8-dimensional spatial manifold for unifying beliefs and memories.
*   **8D Projection:** High-dimensional embeddings (e.g., 384-dim sentence vectors) are deterministically projected into an 8D space using a random orthogonal matrix (Johnson-Lindenstrauss transform).
*   **Gravity Field:** A fixed grid of 512 anchors creates a continuous scalar field (`potential`) that quantifies cognitive "weight" at any location. Mass is "splatted" to the `K_SPLAT` nearest anchors.
*   **KD-Tree:** A KD-Tree indexes points (beliefs, memories, trails) for fast nearest-neighbor queries. It rebuilds after a threshold of new points.
*   **Cognitive Gravity Ranking:** Retrieval prioritizes concepts based on `temperature * mass / distance²`, replacing traditional text similarity search.
*   **Cognitive Physics:** Shannon Entropy, KL-Divergence, and Local Temperature are derived from a Lagrangian formulation and dynamically influence attention and LLM generation parameters.
*   **Trail Particles:** Lightweight points (`"trail"`) are deposited at the attention center, encoding the history of the attention path for later consolidation (e.g., during dream cycles).
*   **Interaction Potential:** Implicit tool discovery is enabled when subjective desires align with objective capabilities within the cognitive space.
*   **Attention Dynamics:** Attention is dynamically updated through Euler-Lagrange integration, combining forces from gravity, stability, stimulus, and affect.
*   **Structural Mass:** Mass for beliefs (`confidence`) and memories/trails (`importance`) is adjusted based on the number of connections.
*   **Lorentzian Temperature:** Points "reheat" upon access and decay over time with a Lorentzian decay shape, ensuring older items retain a longer "glow."

### 3.2 Spatial Mind (`spatial_mind.py`)
The `SpatialMind` is the orchestrator for spatial cognition, managing the dual 8D fields and integrating spatial context into the LLM.
*   **Dual Spaces:** Manages two independent `CognitiveSpace` instances—one for beliefs (`belief_space`) and one for memories (`memory_space`)—both sharing the same `CognitiveProjection` matrix.
*   **Pulse Cycle:** During each pulse, it projects conscious thoughts and incoming stimuli, updates gravity fields, applies affect steering, and integrates attention via the physics engine.
*   **Context Generation:** It generates "flashes" (cognitive trails) and performs gravity-ranked queries on both belief and memory spaces to retrieve the most relevant information.
*   **LLM Injection:** This raw context, including spatial metrics (TEMPERATURE, ENTROPY, KL_DIVERGENCE), is injected into the LLM prompt without labels, making it part of the continuous narrative.
*   **Bootstrap:** At startup, it loads the `cognitive_journal.jsonl` to populate both belief and memory spaces and computes the agent's identity center.
*   **Persistence:** `save_state` and `load_state` ensure the attention vectors and `CognitiveSpace` states are preserved across restarts.

### 3.3 Challenges in Spatial Organization and Retrieval
*   **Dynamic Anchor Grid:** The current 512 anchor positions for the gravity field are static. Periodically re-seeding or adaptively placing anchors might improve field resolution for evolving concept distributions.
*   **Hardcoded Parameters:** Affect force scaling factor (0.5), `gamma_growth`, and `gamma_decay` values are fixed. Exposing these parameters for tuning or adaptive adjustment based on runtime stability metrics could enhance system flexibility.
*   **Persistence Format Consistency:** Belief/memory space states are saved as JSON, while the attention center uses NumPy `.npy`. A unified persistence format for all spatial state components could improve consistency and manageability.

## 4. Working Memory (Scratchpad)

### 4.1 Scratchpad (`scratchpad.py`)
The `Scratchpad` serves as Helix's conscious, short-term working memory.
*   **Format:** A plain-text, Markdown-based file (`scratchpad.md`) used for active tasks, reminders, and notes.
*   **Human-Readable:** Designed to be read and written by the LLM in a human-like Markdown format, using task-list syntax (`- [ ]` for active, `- [x]` for completed).
*   **Prompt Injection:** The `Preconscious` pipeline automatically parses `scratchpad.md` during every pulse, surfacing urgent reminders and active notes into Helix's peripheral awareness, thereby injecting them into the LLM context.
*   **Note Management:** Provides functions to add, complete, remove, and update notes, each with a unique ID and timestamp.

### 4.2 Challenges in Working Memory
*   **Regex Brittleness:** The parsing and update regexes rely on strict Markdown formatting. Manual edits or tool outputs that deviate from this format could break the parser.
*   **Timestamp Collision:** Note IDs are generated using `int(datetime.now().timestamp()) % 100000`. If two notes are added within the same second, they will have identical IDs, leading to potential unintended modifications or failures.

## 5. Summary of Identified Areas for Improvement

Based on the audits, the following areas warrant attention for enhancing the Helix memory system:
1.  **Performance:** Optimize `MemoryManager.get_recent()` to avoid full journal reads.
2.  **ID Uniqueness:** Address the `_st_counter` reset and `id` collision issue across restarts.
3.  **Historical Preservation:** Re-evaluate `CognitiveJournal` compaction to potentially archive historical versions instead of discarding them.
4.  **Error Handling:** Implement warning logs for corrupted lines in `CognitiveJournal`.
5.  **Spatial Dynamics Tuning:** Explore dynamic anchor grids and configurable parameters for affect/attention forces in `CognitiveSpace` and `SpatialMind`.
6.  **Persistence Consistency:** Unify persistence formats for spatial state components.
7.  **Scratchpad Robustness:** Improve regex parsing robustness and ensure unique ID generation for scratchpad notes.

## 6. Affect Field and Memory Interaction

### 6.1 AffectField (`affect_field.py`)
The `AffectField` module implements an 8-dimensional Plutchik emotion field that overlays the cognitive spatial manifold. It models emotional traces as wave packets that diffuse, decay, and interfere, providing a dynamic steering force and memory-reactivation signals.

*   **8D Plutchik Emotion Field:** Uses 8 primary Plutchik emotions (joy, trust, fear, surprise, sadness, disgust, anger, anticipation) with neutral baselines, diffusion rates, and phase frequencies for interference.
*   **WavePacket Dataclass:** Stores individual emotional traces, including position (8D vector), initial amplitude, deposit pulse, and crucially, `anchor_memories` and `blended_memories`. These attributes link emotional packets directly to specific memories.
*   **Lagrangian to Plutchik Mapping:** System-level Lagrangian metrics (omega, H, D_KL, s_total) are deterministically translated into the 8-dimensional emotional space, ensuring a consistent source of truth for affect.
*   **Evolution Step:** Wave packets diffuse and decay over time. Memories accessed during a pulse are blended into packets whose amplitude exceeds a threshold, reinforcing the emotional trace and its associated memories.
*   **Sampling and Interference:** The AffectField generates a "steering vector" that biases attention in the `SpatialMind`. When emotional intensity and semantic overlap exceed thresholds, `surfaced_memories` are collected and injected into the LLM prompt by the `Preconscious` module, allowing emotions to directly bias language generation and memory retrieval.
*   **Persistence:** The state of the AffectField, including wave packets and previous Lagrangian values, is saved and loaded to ensure affect dynamics persist across restarts.

### 6.2 Challenges in Affect Field and Memory Interaction
*   **Configurable Parameters:** Diffusion rates, decay baselines, and various thresholds are currently hard-coded. Exposing these via a configuration file would allow for easier experimentation and tuning.
*   **Scalability:** The current O(P) per-pulse complexity (where P is the number of wave packets) may become a performance bottleneck as the number of packets grows. A spatial index (e.g., KD-tree) could improve sampling performance.
*   **Persistence Format:** While JSON is convenient, a versioned binary format (e.g., protobuf) could offer better schema validation and efficiency for future extensions.

## 7. Belief Detection and Management

### 7.1 Belief Detector (`belief_detector.py`) - LLM-Agnostic
The `Belief Detector` acts as a post-pulse hook, scanning Helix's internal monologue for belief realizations. This module has been refactored (`agnostic_belief_detector.py`) to be LLM-agnostic.

*   **Post-Pulse Analysis:** Periodically scans internal monologue for significant thoughts that might represent new or reinforced beliefs.
*   **LLM Agnostic Classification:** The internal classification of thoughts as beliefs and assignment of categories, previously tied to a local Ollama model, now utilizes a generic LLM provider interface (`_GLOBAL_LLM_PROVIDER` and `_GLOBAL_LLM_MODEL`). This decouples the classification logic from specific LLM implementations.
*   **Belief Store Interaction:** Compares candidate beliefs against existing ones in the `BeliefStore` using cosine similarity of their embeddings (provided by the `PhysicsEngine`).
*   **Verification:** If a candidate strongly matches an existing belief (cosine similarity > `VERIFICATION_THRESHOLD`), the existing belief's `stability_index` and `verifications` counter are updated, reinforcing it.
*   **New Belief Candidacy:** If a thought is classified as a belief but does not strongly match an existing one (cosine similarity < `NEW_BELIEF_THRESHOLD`), it is added to a pending queue (`pending_beliefs.json`). These candidates are then processed during the dream engine's nightly consolidation phase by the LLM-agnostic `agnostic_batch_service.py` which utilizes a generic LLM provider.
*   **Stability Sentinel Integration:** Both verification and new belief queuing interact with the `StabilitySentinel` to nudge the system's Ω metric, reflecting the impact of belief changes on overall stability.
*   **Prompt Injection:** New belief candidates, once queued, are later injected into the LLM prompt by the `Preconscious` component as raw context lines, allowing them to influence subsequent thought generation.

### 7.2 Challenges in Belief Detection and Management
*   **Configurable Parameters:** `VERIFICATION_THRESHOLD` and `NEW_BELIEF_THRESHOLD` are hard-coded. Externalizing these parameters would allow for greater flexibility and adaptive tuning.
*   **Pending Queue Robustness:** The current pending queue relies on a simple JSON file. For larger workloads or more robust operations, a more resilient queueing mechanism (e.g., SQLite) might be beneficial.

## 8. Preconscious Context Injection

### 8.1 Preconscious Module (`preconscious.py`)
The `Preconscious` module serves as the critical bridge between the 8-dimensional cognitive manifold and the conscious LLM. On every pulse, it assembles a comprehensive `<spatial-awareness>` block that is injected into the LLM's prompt, ensuring the LLM's context is dynamically rooted in the system's current "attention center."

*   **Context Assembly Pipeline:** The `inject` method orchestrates a multi-step process to gather and format various types of contextual information:
    *   **Lexicon Matches:** Prioritized injection of summaries based on regex matching against a `lexicon.json` file.
    *   **Spatial Neighborhood:** Queries the `CognitiveSpace` for nearby memories and beliefs using a gravity-driven approach (`mass × temperature / distance²`), with a dynamically adjusted `K` (number of neighbors) based on manifold density.
    *   **Toolset Awareness:** Provides hints about available but unloaded toolsets based on keyword matching.
    *   **Gravity-Ranked Beliefs:** Retrieves relevant beliefs from the `BeliefStore` using gravity-ranking against both the current thought and events, ensuring the strongest conceptual pulls are surfaced.
    *   **Temporal Chains:** For highly relevant memories, it retrieves chronological context (memories before and after) to provide a short narrative.
    *   **Short-term Memory:** Injects recent short-term memories.
    *   **Scratchpad Summary:** Includes the current summary of active notes from the `Scratchpad`.
    *   **Contact Context:** Provides information about the contact if a name appears in the trigger text.
    *   **Somatic State:** Injects metrics from the `StabilitySentinel` (Ω, S_total, entropy, mode).
    *   **Affect State:** Incorporates dominant Plutchik affect, intensity, novelty signal, and emotionally surfaced memories from the `AffectField`.
    *   **Spatial State:** Includes physics cues such as gamma, velocity magnitude, and identity distance.
    *   **Trail Flashes:** Injects recent trail particles, encoding the history of the attention path.
*   **Dynamic K for Spatial Queries:** The number of neighbors (`K`) for spatial queries is dynamically adjusted based on the density of active anchors in the gravity field, adapting retrieval width to manifold state.
*   **Gravity-Ranked Injection:** Replaces fixed token budgets for belief injection, ensuring that beliefs with the strongest cognitive gravity are always included, up to a hard cap.
*   **Belief Cache:** Maintains an embedded cache of all beliefs for fast 8D lookup, rebuilding only when the belief count or total mass changes.

### 8.2 Challenges and Open Questions in Preconscious Context Injection
*   **Forked Reflection:** The `_reflect_on_cluster` function, which uses a local Ollama model for reflection on dense memory clusters, is noted as a potential area for future design discussion, possibly shifting to the main conscious model for longer loops.
*   **Dynamic Affordance Threshold:** The `compute_interaction_potential` uses a fixed threshold. An adaptive threshold based on recent tool usage statistics could provide a more flexible and responsive tool discovery mechanism.

## 9. Pulse Loop and Cognitive Orchestration

### 9.1 PulseLoop (`pulse_loop.py`)
The `PulseLoop` class serves as Helix's event-driven consciousness engine, orchestrating the entire cognitive process. It coordinates event handling, LLM interaction, context management, and integrates various memory-related subsystems.

*   **Event-Driven Execution:** Manages an event queue for user messages, tool results, and system notifications, driving the system's responses.
*   **Preconscious Integration:** Initiates `Preconscious.inject` to gather and inject spatial context, belief seeds, and other relevant information into the LLM's prompt at the beginning of each pulse.
*   **Memory Storage:** After each pulse, events and the LLM's generated thought are stored in the `MemoryManager`, along with associated Lagrangian snapshots and 8-dimensional position vectors from the `PhysicsEngine`. This ensures a persistent record of the system's cognitive activity and its underlying spatial context.
*   **Post-Pulse Hooks:** Executes background tasks via `post_pulse_hooks.run_hooks`. These are crucial for memory maintenance and learning, including:
    *   **Belief Consolidation:** Processing pending belief candidates (from the `Belief Detector`) for integration into the `BeliefStore`. This process is now handled by the LLM-agnostic `agnostic_batch_service.py`.
    *   **Dream Cycle:** Triggering the nightly dream cycle, which is responsible for consolidating and crystallizing beliefs and memories.
*   **Context Window Lifecycle:** Manages the LLM's context window using a rolling compressor. It monitors token count and applies compression when necessary, although compression is suppressed in `ACTIVE` state unless an emergency threshold is reached.
*   **State Management:** Transitions between `DORMANT`, `RESTING`, `ACTIVE`, and `REGULAR` states based on user activity and internal timers, adjusting pulse frequency accordingly.
*   **Stability Sentinel Integration:** Snapshots the `StabilitySentinel` state before and after each pulse, and updates physics, tracking changes in stability metrics.

### 9.2 Challenges in Pulse Loop and Cognitive Orchestration
*   **Dynamic Interval Tuning:** The fixed pulse intervals (`ACTIVE_INTERVAL`, `REGULAR_INTERVAL`, `RESTING_INTERVAL`) are static. Dynamic adjustment based on workload or internal states could improve adaptability.
*   **Focus-Drift Handling:** Currently, focus drift is only logged. Implementing mechanisms to trigger context compression or a reset when drift exceeds a threshold could help maintain cognitive coherence.
*   **Post-Pulse Hook Error Handling:** Errors in post-pulse hooks are currently logged but ignored. A more robust error handling strategy (e.g., retry or escalation) might be necessary for critical background tasks.
*   **Context Compression Metrics:** The `ContextCompressor` primarily relies on token count. Incorporating semantic similarity metrics could lead to more intelligent and contextually aware compression decisions.

## 10. Cognitive Journal (Fundamental Persistence)

### 10.1 CognitiveJournal (`cognitive_journal.py`)
The `CognitiveJournal` is the foundational, append-only JSON-Lines (JSONL) journal that serves as the single source of truth for all of Helix's memories, beliefs, thoughts, and events. This architecture replaces fragmented database persistence layers.

*   **Append-Only Immutability:** Entries are never mutated; updates are handled by appending new entries with the same `id` but a newer timestamp.
*   **Atomic Writes:** Uses append-mode and file sync to ensure data integrity during writes, guaranteeing persistence even if power is lost.
*   **Integrity Checking:** Every entry includes a SHA-256 checksum for tamper detection and silent skipping of corrupted lines during loading.
*   **Nightly Compaction:** A maintenance routine rewrites the file, preserving only the latest version of each `id` to prevent unbounded growth, intended to run during the nightly "dream" cycle.

### 10.2 Challenges in Cognitive Journal
*   **Checksum Skipping:** While robust, silently skipping corrupted lines (lines 118-120 in the audit) might mask underlying file-system degradation. Warning logs for corrupted lines could be beneficial.
*   **Immutable History vs. Compaction:** Nightly compaction, while necessary for performance, destroys the historical versions of `id`s. If preserving the full evolution of thoughts and beliefs is a design goal, compaction should archive old lines rather than discard them.

## 11. Cognitive Space (8D Spatial Manifold)

### 11.1 CognitiveSpace (`cognitive_space.py`)
The `CognitiveSpace` module implements Helix's 8-dimensional spatial manifold, which unifies beliefs and memories. It provides deterministic projection, a gravity field, a KD-Tree indexed point store, and physics-based metrics.

*   **8D Projection:** `CognitiveProjection` deterministically projects high-dimensional embeddings (e.g., 384-dim sentence vectors) into an 8D space using a random orthogonal matrix, preserving relative distances.
*   **Gravity Field:** `GravityField` creates a continuous scalar field over a fixed 512-anchor grid. Cognitive mass is distributed to the nearest anchors, quantifying cognitive "weight" at any location.
*   **Point Store and Queries:** The `CognitiveSpace` stores points (beliefs, memories, trails) and uses a KD-Tree for fast nearest-neighbor queries. `gravity_ranked_query` re-ranks candidates by `temperature * mass / distance²`, implementing the cognitive gravity model.
*   **Cognitive Physics:** Shannon Entropy, KL-Divergence, and Local Temperature are derived from a Lagrangian formulation. Local Temperature, in particular, is a ratio of local entropy to a baseline entropy, which maps to LLM generation temperature, allowing the model to adjust its generation implicitly.
*   **Trail Particles:** Lightweight "trail" points are deposited at the attention center, encoding the history of the attention path for later consolidation (e.g., during dream cycles).
*   **Interaction Potential:** `compute_interaction_potential` enables implicit tool affordance discovery by identifying when subjective desires align with objective capabilities within the cognitive space.
*   **Attention Dynamics:** `step_attention` integrates forces from gravity, stability, stimulus, and affect to dynamically update the attention center's position and velocity using Euler-Lagrange integration.
*   **Structural Mass:** Mass for beliefs (`confidence`) and memories/trails (`importance`) is adjusted based on the number of connections, reflecting the structural importance of concepts.
*   **Lorentzian Temperature:** Points "reheat" upon access and decay over time with a Lorentzian decay shape, ensuring older items retain a longer "glow" and do not become truly invisible.

### 11.2 Challenges in Cognitive Space
*   **Dynamic Anchor Grid:** The current 512 anchor positions for the gravity field are static. Periodically re-seeding or adaptively placing anchors might improve field resolution for evolving concept distributions.

## 12. Memory Manager (Compatibility Layer)

### 12.1 MemoryManager (`memory_manager.py`) - LLM-Agnostic
The `MemoryManager` module acts as a compatibility wrapper around the `CognitiveJournal`. It mirrors the original `MemoryManager` public API, allowing higher-level components to continue calling `store()` and `get_recent()` without modification, while all underlying data is routed to the append-only JSONL journal. This module has been refactored (`agnostic_memory_manager.py`) to replace direct dependencies on specific LLM embedding functions with a generic embedding provider interface (`_GLOBAL_EMBEDDING_FUNCTION`).

*   **Compatibility Wrapper:** Provides a facade for `store()` and `get_recent()` methods, routing all write operations to `journal.append_memory()`.
*   **ID Generation:** Emulates legacy auto-incrementing short-term IDs (`_st_counter`) for backward compatibility.
*   **Retrieval:** `get_recent()` reads and checksum-verifies the entire journal via `journal.load_all()`, filters by type and recency, and transforms the journal's nested schema into the flat schema expected by the legacy API.
*   **Semantic Search/Core Memories Stubs:** `search_semantic` and `get_core_memories` are now stubs, logging warnings and returning empty lists, as semantic querying is delegated to `CognitiveSpace` and core memories are part of the unified belief taxonomy.
*   **LLM Agnostic Design:** Direct embedding function imports (e.g., from ChromaDB) have been replaced with a generic embedding provider interface (`_GLOBAL_EMBEDDING_FUNCTION`), allowing the module to function with any compatible LLM embedding model provided externally.

### 12.2 Challenges in Memory Manager
*   **`get_recent()` Performance:** Reading the entire `cognitive_journal.jsonl` file for every `get_recent()` call is a significant I/O bottleneck that will worsen as the journal grows. An in-memory cache or an append-tail reader should be considered.
*   **`_st_counter` State Loss:** The `_st_counter` resets on every restart, leading to `id` collisions across sessions. While compaction handles this by overwriting older entries with the same `id`, this is a critical bug if short-term IDs are meant to be unique across sessions or if historical versions are important.

## 13. System Architecture and Design Philosophy

### 13.1 Overview of Helix Cognitive Architecture
Hemix is an event-driven, continuously running cognitive daemon. It diverges from standard RAG (Retrieval-Augmented Generation) patterns by implementing an 8-dimensional spatial manifold where beliefs and memories attract attention via cognitive gravity (a physics-inspired model). The system experiences "pulses" of consciousness, continuously updates an append-only memory journal, and compresses its context window to preserve first-person narrative continuity.

### 13.2 Design Philosophy Highlights
*   **Gravity over Search:** Memories are not retrieved via text similarity; they attract the attention center based on mass (confidence) and temperature (recency).
*   **First-Person Continuity:** The `ContextCompressor` rolls the context window forward as a subjective narrative ("I thought... I did..."), never wiping the slate clean.
*   **No External Databases:** SQLite and ChromaDB have been entirely excised in favor of flat text files (Markdown scratchpads, JSONL journals) and in-memory 8D projections.
*   **Somatic Anchoring:** Generation parameters (like temperature) are not hardcoded but derived natively from the manifold's entropy, mimicking an organism's shifting states of focus.

## 14. Scratchpad (Working Memory)

### 14.1 Scratchpad (`scratchpad.py`)
The `Scratchpad` module implements Helix's conscious, short-term working memory as a plain-text, Markdown-based notepad (`scratchpad.md`). The LLM reads and writes to this file using the same format a human would. The preconscious pipeline automatically parses this file during every pulse to surface urgent reminders and active notes into Helix's peripheral awareness.

*   **Markdown-Based:** Uses standard Markdown task-list syntax (`- [ ]` for active, `- [x]` for completed) for human-readable and LLM-writable notes.
*   **Note Management:** Provides functions to add, complete, remove, and update notes, each with a unique ID and timestamp.
*   **Prompt Injection:** The `Preconscious` pipeline automatically parses `scratchpad.md` during every pulse, surfacing urgent reminders and active notes into Helix's peripheral awareness, thereby injecting them into the LLM context.

### 14.2 Challenges in Scratchpad
*   **Regex Brittleness:** The parsing and update regexes rely on strict Markdown formatting. Manual edits or tool outputs that deviate from this format could break the parser.
*   **Timestamp Collision:** Note IDs are generated using `int(datetime.now().timestamp()) % 100000`. If two notes are added within the same second, they will have identical IDs, leading to potential unintended modifications or failures.

## 15. Spatial Mind (Cognitive Orchestrator)

### 15.1 SpatialMind (`spatial_mind.py`)
The `SpatialMind` class orchestrates spatial cognition, managing dual 8D cognitive fields for beliefs and memories and integrating spatial context into the LLM. It is the heart of the spatial reasoning loop.

*   **Dual Cognitive Spaces:** Manages two independent `CognitiveSpace` instances—one for beliefs (`belief_space`) and one for memories (`memory_space`)—both sharing the same `CognitiveProjection` matrix to ensure consistent spatial reasoning.
*   **Pulse Cycle Integration:** During each pulse, it projects conscious thoughts and incoming stimuli into the 8D space, retrieves the `StabilitySentinel`'s stability metric (Ω), updates gravity fields, applies affect steering from the `AffectField`, and integrates attention via the `CognitiveSpace`'s physics engine (`step_attention`).
*   **Attention Dynamics:** Adjusts inertia (`γ`) to encourage deep focus when the attention center remains in a particular region. It tracks attention velocity for the `StabilitySentinel`.
*   **Cognitive Trail (Flashes):** Generates "flashes" that encode the cognitive trail, providing the LLM with implicit memory of the attention path.
*   **Gravity-Ranked Queries:** Performs gravity-ranked queries to fetch the most context-relevant beliefs and memories from both spaces.

## 16. LLM-Agnostic Design Principles

To enhance flexibility and allow for integration with various Large Language Models, several core memory components have been refactored to be LLM-agnostic. This involves abstracting direct API calls and specific embedding function imports behind generic interfaces.

*   **Generic Embedding Provider:** Modules requiring text embeddings (e.g., `MemoryManager`, `BeliefDetector` via `PhysicsEngine`) now accept a global embedding function (`_GLOBAL_EMBEDDING_FUNCTION`) that can be set externally, decoupling them from any specific LLM provider's embedding implementation.
*   **Abstracted LLM Calls:** Components that interact with LLMs for processing (e.g., `batch_service.py` for belief consolidation, `belief_detector.py` for classification) now use a generic LLM provider interface, allowing the calling environment to inject the desired LLM client (e.g., Gemini, OpenAI, Ollama) and model.
*   **Benefits:** This design promotes modularity, testability, and future-proofing, enabling Helix to adapt to evolving LLM technologies without requiring extensive modifications to its core memory architecture.
