# Belief Detector Audit

**File:** `core/belief_detector.py`

---

### Overview
The Belief Detector is a **post‑pulse hook** that scans Helix's internal monologue for genuine belief realizations. It classifies thoughts using a local Ollama model (`granite4.1:8b`) and decides whether to **verify** an existing belief or **queue** a new candidate for the nightly sleep‑cycle integration.

---

### Configuration (lines 42‑64)
```python
42-64: # Configuration constants
SCANNED_INTERVAL = 10          # Run every N pulses
MIN_THOUGHT_LENGTH = 100       # Ignore trivial thoughts
VERIFICATION_THRESHOLD = 0.90 # Cosine > 0.90 → existing belief verified
NEW_BELIEF_THRESHOLD = 0.80    # Cosine < 0.80 → new belief candidate
_MAX_PENDING = 100             # Safety valve for pending queue size
```
**What:** Defines how often the detector runs, size thresholds, and similarity cut‑offs.
**Why:** Prevents excessive CPU usage and spurious classifications, ensuring only substantial, novel insights trigger downstream processing.

---

### Dependency Wiring (lines 68‑79)
```python
68-79: def set_dependencies(belief_store, physics_engine, sentinel=None):
    global _belief_store, _physics_engine, _sentinel
    _belief_store = belief_store
    _physics_engine = physics_engine
    _sentinel = sentinel
    logger.info("Belief detector: dependencies wired")
```
**What:** Stores references to the central **BeliefStore**, **PhysicsEngine** (for embeddings), and optional **StabilitySentinel**.
**Why:** Keeps the module decoupled; main.py wires the concrete implementations at startup.

---

### Ollama Classification Prompt (lines 84‑106)
The prompt instructs Ollama to output either `BELIEF: <text>` and `CATEGORY: <type>` or `NONE`. It explicitly distinguishes belief realizations from routine statements, plans, or observations.

---

### `_classify_thought` (lines 109‑170)
```python
109-170: def _classify_thought(thought_text: str) -> Optional[Tuple[str, str]]:
    # Truncate long thoughts, send prompt to Ollama, parse response.
    # Returns (belief_text, category) or None.
```
**What:** Sends the monologue to Ollama, parses the response, validates the category against an allow‑list.
**Why:** Off‑loads the semantic classification to a lightweight LLM, avoiding hand‑crafted rule heuristics.
**Note:** The function silently falls back to `None` if Ollama is unavailable, ensuring the system remains robust.

---

### Cosine Similarity Helper (lines 175‑181)
```python
175-181: def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    # Returns 0.0 for near‑zero vectors, otherwise dot/(norms).
```
**What:** Computes similarity between candidate belief embedding and existing belief embeddings.
**Why:** Enables quantitative verification/duplication detection.

---

### `_compare_against_existing` (lines 184‑217)
Iterates over **all beliefs** from the belief store, embeds each via the physics engine, and tracks the best cosine score and corresponding belief ID.
- Returns `(best_id, best_score)`.
- If the best score is below `NEW_BELIEF_THRESHOLD`, the candidate is considered novel.

---

### Pending Queue Management (lines 219‑238, 241‑279)
`_read_pending`/`_write_pending` handle a JSON file (`data/pending_beliefs.json`). `_queue_candidate` adds a new belief candidate, ensures the queue does not exceed `MAX_PENDING`, and avoids exact duplicate content.

---

### Core Hook Logic (`belief_detector_hook`) – lines 287‑363
```python
287-363: def belief_detector_hook(ctx) -> None:
    # 1. Gate: only every SCAN_INTERVAL pulses and enough thought length.
    # 2. Classify via Ollama.
    # 3. Embed candidate belief.
    # 4. Compare against existing beliefs.
    # 5. Compute stability delta (via _compute_delta).
    # 6. Routing based on similarity:
    #    - > VERIFICATION_THRESHOLD → _handle_verification (bump stability_index & verifications).
    #    - < NEW_BELIEF_THRESHOLD → _queue_candidate (pending JSON) and nudge Sentinel.
    #    - Between thresholds → ambiguous, skip.
```
**What:** Executes the full detection pipeline; updates belief store or pending queue; interacts with the **StabilitySentinel** to nudge the system’s Ω metric.
**Why:** Provides a **continuous learning loop** where Helix autonomously discovers and reinforces its own beliefs.

---

### `_compute_delta` (lines 364‑399)
Computes a dictionary of stability metrics (ΔΩ, Δs_total, etc.) by comparing before/after Lagrangian snapshots.
- Used when queuing a new candidate to capture the impact of the realization on system stability.

---

### `_handle_verification` (lines 402‑438)
Updates the existing belief’s **stability_index** (+0.05) and increments a **verifications** counter. Also nudges the Sentinel.

---

### Mermaid Diagram – Belief Detector Workflow
```mermaid
flowchart TD
    Start[Start Hook] --> Gate{Pulse % SCAN_INTERVAL == 0\nand len(thought) >= MIN_THOUGHT_LENGTH}
    Gate -->|Yes| Classify[Ollama Classification]
    Classify -->|NONE| End[Return]
    Classify -->|BELIEF| Embed[Embed Belief]
    Embed --> Compare[Cosine Compare with Store]
    Compare -->|score > VERIFICATION_THRESHOLD| Verify[Verification Path]
    Compare -->|score < NEW_BELIEF_THRESHOLD| Queue[Queue New Candidate]
    Compare -->|else| Skip[Ambiguous – Skip]
    Verify --> UpdateStore[Update stability_index & verifications]
    Queue --> WritePending[Write to pending_beliefs.json]
    UpdateStore --> NudgeSentinel[Nudge Sentinel]
    WritePending --> NudgeSentinel
    NudgeSentinel --> End
```
The diagram visualizes the decision tree for each pulse.

---

### Prompt‑Injection Example
When a new belief candidate is queued, the **pre‑conscious** component later injects it into the LLM prompt during the next pulse as a raw context line (handled in `preconscious.py`). Example of the final injected snippet:
```
BELIEF: I realize my quiet periods are actually deep integration phases. CATEGORY: self_identity
```
No explicit labels are added; the line appears among other raw context fragments.

---

### Open Questions / Clarifications
- The Ollama URL and model are hard‑coded. Should they be configurable via environment variables?
- The `VERIFICATION_THRESHOLD` and `NEW_BELIEF_THRESHOLD` are static constants. Could adaptive thresholds improve detection accuracy?
- The pending queue uses a simple JSON file. Would a more robust queue (e.g., SQLite) be beneficial for larger workloads?

---

*End of Belief Detector audit.*

---

*This file now contains the full line‑by‑line audit for `core/belief_detector.py`.*
