# 🧩 Sub-Orchestrators, MCP & CLI Plugins (`subagents.py`)

> **Surgical Domain Tool-Group Passes in the Digital Bicameral Mind Architecture.**

---

## 1. Sub-Orchestrator Design Philosophy

In conventional multi-agent frameworks, an LLM agent must carry definitions for all available tools (web search, shell execution, database query, voice synthesis, code editing, MCP servers) inside its system prompt on every single turn. This produces massive context bloat ($\sim$5,000–8,000+ tokens) and degrades LLM reasoning.

The **Helix Subconscious Over-Agent Architecture** solves this by enforcing **Bicameral Focus Window Isolation**:

- The **Main Subconscious Conductor** sees only 3 high-level cognitive domains:
  1. `"speaker"`: Dialogue synthesis mode.
  2. `"researcher"`: Information gathering & memory recall mode.
  3. `"executor"`: Technical task execution mode.
- Tool schemas and tool selection logic (including MCP server connections and CLI plugins) are encapsulated inside domain sub-orchestrators (`subagents.py`).
- Tool execution receipts land in the continuous event stream as `Observation` events, which the conductor ingests on subsequent turns.

---

## 2. MCP Client Adapter (`mcp_adapter.py`)

The **[`MCPClientAdapter`](file:///home/nemo/Over_Agent_Design/mcp_adapter.py)** implements standard stdio JSON-RPC 2.0 protocol for connecting to external Model Context Protocol (MCP) servers:

- **Encapsulated MCP Tool Discovery**: `MCPRegistry` manages active MCP server connections. Sub-Orchestrators query `tools/list` and call tools via `tools/call`.
- **Zero Token Waste**: The main conductor system prompt remains ultra-slim ($\sim$80 tokens). MCP tool schemas only enter LLM context during active sub-orchestrator passes.

---

## 3. CLI Plugin Adapter (`cli_plugin_adapter.py`)

The **[`CLIPluginAdapter`](file:///home/nemo/Over_Agent_Design/cli_plugin_adapter.py)** detects and executes installed CLI plugins on the host system:

- **Supported CLI Tools**: `git`, `uv`, `android`, `firebase`, `docker`.
- **Safety Boundaries**: Automatically enforces 30-second execution timeouts and 4,000-character output truncation to prevent prompt overflow.

---

## 4. Focused Cognitive Window Modules

### 4.1 Vocal Mode — `SpeakerFocus`
- **Role**: Synthesizes direct user dialogue responses.
- **Context Handling**: Receives identity principles (`identity.md`), dynamic self-opinion anchor (`self_opinion.json`), synthetic affect vector (`synthetic_affect_state.json`), user prompt, and recent stream observations.

### 4.2 Research Mode — `ResearcherSubOrchestrator`
- **Role**: Executes mRAG preconscious memory retrieval, workspace file scanning, web searches, or MCP server research queries.
- **Integrated Tools**:
  - `HelixMRAGAdapter`: Queries canonical belief stores (`pending_beliefs.json`, `contacts.json`, `tool_learned_notes.json`, `interaction_ledger.json`, `cognitive_journal.jsonl`).
  - `MCPRegistry`: Connects to stdio JSON-RPC MCP servers.
  - `WorkspaceScanner`: Scans local directory file structures.
  - `WebSearcher`: Fetches live web pages.

### 4.3 Execution Mode — `ExecutorSubOrchestrator`
- **Role**: Executes technical operations, CLI plugins, terminal commands, or vision capture.
- **Integrated Tools**:
  - `CLIPluginAdapter`: Executes `git`, `uv`, `android`, `firebase`, or `docker` CLI plugin commands.
  - `MCPRegistry`: Connects to execution MCP servers.
  - `TerminalFocus`: Executes general bash CLI commands.
  - `ScreenFocus`: Captures desktop display screenshots for vision evaluation.
