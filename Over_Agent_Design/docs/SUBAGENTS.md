# 🧩 Sub-Orchestrators & Focused Cognitive Windows (`subagents.py`)

> **Surgical Domain Tool-Group Passes in the Digital Bicameral Mind Architecture.**

---

## 1. Sub-Orchestrator Design Philosophy

In conventional multi-agent frameworks, an LLM agent must carry definitions for all available tools (web search, shell execution, database query, voice synthesis, code editing) inside its system prompt on every single turn. This produces massive context bloat ($\sim$3,000–5,000+ tokens) and degrades LLM reasoning.

The **Helix Subconscious Over-Agent Architecture** solves this by enforcing **Bicameral Focus Window Isolation**:

- The **Main Subconscious Conductor** sees only 3 high-level cognitive domains:
  1. `"speaker"`: Dialogue synthesis mode.
  2. `"researcher"`: Information gathering & memory recall mode.
  3. `"executor"`: Technical task execution mode.
- Tool schemas and tool selection logic are encapsulated inside domain sub-orchestrators (`subagents.py`).
- Tool execution receipts land in the continuous event stream as `Observation` events, which the conductor ingests on subsequent turns.

---

## 2. Focused Cognitive Window Modules

### 2.1 Vocal Mode — `SpeakerFocus`
- **Role**: Synthesizes direct user dialogue responses.
- **Context Handling**: Receives identity principles (`identity.md`), dynamic self-opinion anchor (`self_opinion.json`), synthetic affect vector (`synthetic_affect_state.json`), user prompt, and recent stream observations.
- **Output**: Clean, natural dialogue for terminal screen display or TTS audio playback.

### 2.2 Research Mode — `ResearcherSubOrchestrator`
- **Role**: Executes mRAG preconscious memory retrieval, workspace file scanning, or web searches.
- **Integrated Tools**:
  - `HelixMRAGAdapter`: Queries canonical belief stores (`pending_beliefs.json`, `contacts.json`, `tool_learned_notes.json`, `interaction_ledger.json`, `cognitive_journal.jsonl`).
  - `WorkspaceScanner`: Scans local directory file structures.
  - `WebSearcher`: Fetches live web pages.
- **Output**: Formatted `Observation (Research Sub-Orchestrator): ...` receipt appended to `self.event_stream`.

### 2.3 Execution Mode — `ExecutorSubOrchestrator`
- **Role**: Executes technical operations, terminal commands, or vision capture.
- **Integrated Tools**:
  - `TerminalFocus`: Executes bash CLI commands.
  - `ScreenFocus`: Captures desktop display screenshots for vision evaluation.
  - `CodeEngine`: Reviews code snippets and structural logic.
- **Output**: Formatted `Observation (Execution Sub-Orchestrator): ...` receipt appended to `self.event_stream`.

---

## 3. Preconscious Subagent Execution Sequence

```
+-----------------------------------------------------------------------------------+
|                        PRECONSCIOUS SUBAGENT EXECUTION LOOP                       |
|                                                                                   |
|   1. User Prompt: "Search for memory beliefs about joshua..."                      |
|   2. Conductor Intent Routing -> Classifies Intent as 'researcher'                 |
|   3. Sub-Orchestrator Pass -> Executes ResearcherSubOrchestrator(query)           |
|   4. mRAG Adapter -> Recalls 1,572 chars of belief nodes from data store          |
|   5. Receipt Ingestion -> Appends Observation to self.event_stream                 |
|   6. Dialogue Synthesis -> SpeakerFocus reads observation and generates answer     |
+-----------------------------------------------------------------------------------+
```
