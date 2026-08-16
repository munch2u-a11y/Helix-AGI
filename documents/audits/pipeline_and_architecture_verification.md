# Helix AGI — Architecture Audit & Pipeline Verification Report

**Date**: August 16, 2026  
**Audited Codebase**: `/home/nemo/Helix`  
**Status**: **100% VERIFIED**  

---

## Executive Summary

An exhaustive end-to-end audit of Helix AGI was conducted across memory recall, conscious pulse execution, channel routing, and task-branching execution. The findings verify that Helix operates under strict context isolation, non-mutating preconscious retrieval, dynamic focus budgeting, and deterministic action verification.

---

## Section 1: Memory & Preconscious Pipeline

### 1. 384D FAISS Embeddings $\rightarrow$ 8D Continuous Spatial Manifold
* **Dense Embedding**: Text is converted to 384-dimensional dense vectors via `all-MiniLM-L6-v2` (`core/physics_engine.py:L187-209`, `core/spatial_mind.py:L112-144`).
* **Johnson-Lindenstrauss (JL) Projection**:
  * Managed by `CognitiveProjection` (`core/cognitive_space.py:L75-174`).
  * Target dimension $d=8$, seed $s=42$.
  * QR decomposition (`q, _ = np.linalg.qr(raw)`) yields an orthogonal matrix $W \in \mathbb{R}^{384 \times 8}$. Pairwise Euclidean distances are preserved within a constant factor ($\epsilon$-isometry).
  * Projection formula: $P = X W \in \mathbb{R}^{N \times 8}$ (`core/cognitive_space.py:L130-144`).
  * Saved to `cognitive_projection.npy` and shared between `belief_space` and `memory_space` (`core/spatial_mind.py:L70-72`).

### 2. Gravitational Query (`_gravity_query`) Selection
* **Phase 1 — 384D Semantic Gating**: Computes cosine similarity between query and belief vectors in `_belief_emb_matrix`, selecting top `SEMANTIC_ANCHOR_K = 100` candidates (`core/preconscious.py:L1339-1365`).
* **Phase 2 — 8D Gravitational Ranking (Verlinde Entropic Gravity)**:
  * Evaluates entropic gravity: $$g = \frac{T \cdot M}{d^2 + 10^{-4}}$$
  * Decay penalty applied for repeated injection: $g \leftarrow g \times 0.5^{\text{decay\_count}}$ (`core/preconscious.py:L1408-1412`).
  * Threshold cutoff: $g \ge 0.5$ (`core/preconscious.py:L1425-1428`).

### 3. Dynamic Focus Budgeting (4 to 18 Items)
* **Tool Intensity Tier** (`_recent_tool_history`): $\ge 3$ focus tools $\rightarrow$ Deep tier (1 item); $1-2$ tools $\rightarrow$ Working tier (2 items); $0$ tools $\rightarrow$ Open tier (3 items).
* **Spatial Temperature Modulation**: $T = H_{\text{local}} / H_{\text{mean}}$. High entropy narrows budget by $0.5\times$; low entropy widens budget by $1.3\times$ (`core/preconscious.py:L277-338`).
* **Unified Envelope**: Contracts to **~4 items** under heavy tool focus and expands up to **18–20 items** in open conversational states (`core/unified_retrieval.py:L967-1085`).

### 4. Non-Mutating Memory Recall
* All retrieval functions (`SemanticLane.retrieve`, `_route_record_roles`, `_purge_near_duplicates`) perform pure read queries. Line 861 explicitly confirms: *"Retrieval-only. Nothing is merged, rewritten or deleted."*

```mermaid
flowchart TD
    subgraph Text2Vector ["1. Dense Vectorization"]
        A["Incoming Query / Thought"] --> B["384D MiniLM Embedder"]
    end

    subgraph JLProj ["2. JL 8D Projection Subspace"]
        B --> C["CognitiveProjection (384D -> 8D)"]
        C --> D["Orthogonal QR Matrix (cognitive_projection.npy)"]
        D --> E["8D Continuous Point (Spatial Mind)"]
    end

    subgraph TwoPhaseRetrieval ["3. Two-Phase Preconscious Retrieval"]
        B --> F["Phase 1: 384D FAISS Cosine Search (K=100 Candidates)"]
        E --> G["Phase 2: 8D Verlinde Entropic Gravity Ranking"]
        F --> G
        G --> H{"g = (T * M) / (d^2 + 1e-4) >= 0.5?"}
        H -- Yes --> I["Apply Decay & Focus Budget Filter"]
        H -- No --> J["Prune Candidate"]
    end

    subgraph PeripheralAwareness ["4. Non-Mutating Injection"]
        I --> K["Inject into Peripheral Awareness Context (Pure Read)"]
    end
```

---

```mermaid
stateDiagram-v2
    [*] --> IdleOpenState: 0 Focus Tools Active
    
    state IdleOpenState {
        direction TB
        OpenBudget: Base Budget = 3 Items (Max 18 Unified)
        OpenTemp: Spatial T Modulation (0.8x - 1.3x)
    }

    IdleOpenState --> WorkingState: 1-2 Focus Tools Used
    
    state WorkingState {
        direction TB
        WorkingBudget: Base Budget = 2 Items (~8 Unified)
        WorkingTemp: Spatial T Modulation (0.7x - 1.15x)
    }

    WorkingState --> DeepFocusState: >= 3 Focus Tools Used
    
    state DeepFocusState {
        direction TB
        DeepBudget: Base Budget = 1 Item (~4 Unified)
        DeepTemp: High T Entropy Penalty (0.5x Budget)
    }

    DeepFocusState --> WorkingState: Tools Inactive
    WorkingState --> IdleOpenState: All Tools Idle
```

---

## Section 2: Main Conscious Stream & Channel Routing Pipeline

### 1. Pulse Turn Execution Sequence
* **Phase 0 (Setup & Sentinel)**: Increments counters, auto-disengages idle toolsets, takes baseline Lagrangian snapshot (`pulse_loop.py:L942-969`).
* **Phase 1 (Drain Events)**: Thread-safely drains event queue, snapshots `requeue_events`, ticks sensory cortex (`L971-1016`).
* **Phase 2 (Preconscious & Assembly)**: Fires `preconscious.inject()`, builds prompt payload via `_build_pulse_message()`, appends affect capsule (`L985-1049`).
* **Phase 3 (LLM Turn)**: Dispatches `_send_pulse()`, enforces token limits, handles errors (`L1051-1240`).
* **Phase 4 (Action Execution)**: Collects native function call outputs, parses local action primitives (`[read:]`, `[write:]`, `[amend:]`, `[execute:]`), dispatches via `ToolDispatcher` (`L1247-1289`).
* **Phase 5 (Storage & Physics)**: Stores event and thought records in `MemoryManager`, advances 8D manifold physical state, runs post-pulse hooks (`L1295-1454`).

### 2. ChannelRouter Contact & Default Channel Resolution
* **Contact Lookup**: Normalizes name, checks key matches in `contacts.json`, traverses `display_name` and `aliases` (`tools/channel_router.py:L109-123`). Auto-registers new contacts (`L150-193`).
* **Auto / Last Sender Routing**: If recipient is unspecified, `""`, or `"last"`, `_get_last_inbound()` returns the entry in `_last_inbound` with the highest timestamp (`L194-206`).
* **Default Channel Fallback**: If no recent inbound message exists within `REPLY_WINDOW` (3,600s), `route_reply()` falls back to `route_message()`, which routes to `default_channel` in `contacts.json` or follows channel priority cascade (`L244-290`).

```mermaid
sequenceDiagram
    autonumber
    participant EventQueue as Event Queue
    participant PulseLoop as Pulse Loop (Conscious Stream)
    participant Preconscious as Preconscious mRAG
    participant LLM as LLM Engine (granite4.1:8b)
    participant Dispatcher as Tool Dispatcher
    participant Router as Channel Router
    participant Memory as Memory Manager & Physics

    EventQueue->>PulseLoop: Drain Events (Messages, Sensory, Webhooks)
    PulseLoop->>Preconscious: preconscious.inject() (Gravity Query)
    Preconscious-->>PulseLoop: Return Peripheral Awareness Context
    PulseLoop->>LLM: Send Pulse Prompt (System Instruction + Events + Context)
    LLM-->>PulseLoop: Internal Monologue Thought
    
    alt Action Tag Parsed (e.g. [write: telegram, "..."])
        PulseLoop->>Dispatcher: resolve_and_execute("write", "telegram", content)
        Dispatcher->>Router: route_reply(recipient, message)
        alt Recipient Unspecified / "last"
            Router->>Router: _get_last_inbound() -> Auto-select Most Recent Sender
        else Specific Contact (e.g. "El")
            Router->>Router: Check _last_inbound -> Fallback to contacts.json default_channel
        end
        Router-->>Dispatcher: Message Delivered
        Dispatcher-->>PulseLoop: Emit tool_result event
    end

    PulseLoop->>Memory: Store Thought & Events (Project to 8D Manifold)
    PulseLoop->>Memory: Step Physics Engine & Run Post-Pulse Hooks
```

---

```mermaid
flowchart TD
    A["Outbound Reply Call: route_reply(recipient, message)"] --> B{"Is recipient empty, 'last', or 'auto'?"}
    
    B -- Yes --> C["Query _last_inbound map"]
    C --> D["Select entry with highest timestamp (Most Recent Sender)"]
    D --> E["Send via last inbound channel (Telegram, Discord, Slack, etc.)"]

    B -- No --> F["Resolve contact in contacts.json (Name / Display Name / Aliases)"]
    F --> G{"Recent inbound within REPLY_WINDOW (3600s)?"}
    
    G -- Yes --> H["Send via contact's last inbound channel"]
    G -- No --> I{"Does contact have default_channel set in contacts.json?"}
    
    I -- Yes --> J["Send via contact's default_channel"]
    I -- No --> K["Cascade Channel Priority: Telegram > Discord > Slack > WhatsApp > Webhook"]
    K --> L["Deliver Message"]
```

---

## Section 3: Task & Action Branching Pipeline

### 1. Clean Main Conscious Stream vs. Isolated Worker Branches
* **Main Window**: Receives only a brief one-line-per-toolset overview (`llm/orchestrated.py:L331-340`). Main consciousness expresses intent through an outcome request (`{"tool_request": "..."}`).
* **Worker Branch Isolation**:
  * **Local Orchestration**: `OrchestratedToolSession` intercepts tool requests (`llm/orchestrated.py:L72-117`). `ToolTaskRunner.run` spawns an isolated session (`pass_factory(system_prompt)`), executes multi-step work, and closes the session (`core/tool_task_runner.py:L269-465`).
  * **llama.cpp Context Swap**: Borrows resident GGUF session, stashes main history, sets `session.history = []`, and strictly restores main history upon closing (`llm/tool_pass.py:L88-137`).
  * **Event-Driven Focus Threads**: `FocusManager.submit` offloads tasks to a `ThreadPoolExecutor` (`core/task_cognition/focus.py:L75-96`). Intermediate worker context never touches main awareness.

### 2. Action Verification & Receipt Policy (`action_protocol.py`)
* **Typed Receipts**: Tools return `ToolReceipt` with classified status (`_FAILURE_RE`, `_BLOCKED_RE`, `_STRONG_SUCCESS_RE`).
* **Evidence Grading**: Communication tools and mutations matching `_STRONG_SUCCESS_RE` receive `EvidenceLevel.CONFIRMED`.
* **Deterministic Verification Rules**:
  * File mutations (`write_file`) require a subsequent `read_file` with matching path (`action_protocol.py:L360-370`).
  * Shell mutations (`terminal`) require a subsequent read-only shell observation command (`L377-383`).
  * If unverified, returns `VerificationStatus.PARTIAL`.

### 3. Observation Ingest into Main Awareness
* Raw execution logs stay in worker branches.
* Summarized or direct first-person receipts are framed into main awareness:
  * Verified: `"The system verified that outcome from tool receipts. Now give your reply."`
  * Unverified: `"The attempted action was not fully verified. Report only what the receipts establish..."` (`llm/orchestrated.py:L106-115`).
* Committed to memory as first-person episodic records (`controller.py:L193-203`).

```mermaid
graph TD
    subgraph MainConscious ["Main Conscious Stream (Fluid & Clean)"]
        MC1["Main Monologue / Chat Prompt"] --> MC2{"Wants to Act or Remember?"}
        MC2 -- Conversational Reply --> MC3["Direct Reply in Main Stream (Fast & Organic)"]
        MC2 -- Tool Request --> MC4["Emit Tool Outcome Request: {'tool_request': '...' }"]
    end

    subgraph SubContextBranch ["Branched Sub-Context Worker Thread (Isolated Thought Branch)"]
        MC4 --> W1["Spawn Isolated Pass / Focus Thread"]
        W1 --> W2["Inject Layer B Directed System Prompt & Targeted Tool Manifest"]
        W3["Execute Tool Legs in Isolated Context"] <-- Worker Loop --> W2
        W3 --> W4["Action Protocol Verification (action_protocol.py)"]
        W4 --> W5{"Receipt Status Verified?"}
        W5 -- Verified --> W6["Grade Evidence CONFIRMED / OBSERVED"]
        W5 -- Unverified --> W7["Grade Evidence PARTIAL / FAILED"]
    end

    subgraph AwarenessIngest ["Main Awareness Observation Ingest"]
        W6 --> I1["Format First-Person Observation Receipt"]
        W7 --> I1
        I1 --> I2["Inject Observation Receipt into Main Awareness Stream"]
        I2 --> I3["Commit Episodic Memory Entry (Zero Worker Log Pollution)"]
    end
```

---

## Conclusion & Verification Summary

The architectural audit confirms that Helix AGI:
1. **Preserves Clean Context**: Main stream context remains fluid and uncluttered by heavy tool schemas.
2. **Prevents Memory Corruption**: Preconscious memory recall is strictly read-only and forms zero spurious memories during retrieval.
3. **Ensures Reliable Routing**: `ChannelRouter` auto-routes replies to the last inbound sender and falls back to default contact channels.
4. **Enforces Action Integrity**: Action execution is isolated in worker sub-context branches and verified deterministically via `action_protocol.py`.
