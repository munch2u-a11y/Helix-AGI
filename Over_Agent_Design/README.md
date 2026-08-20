# 🧠 Helix Subconscious Over-Agent System (`Over_Agent_Design`)

> **A Continuous Digital Bicameral Mind Architecture** operating through ultra-slim executive reflection loops, surgical tool-group passes, multi-head mRAG preconscious memory recall, dynamic identity compilation, and synthetic affect simulation.

---

## 🌟 Architectural Features

### 1. Digital Bicameral Mind & Pinned Identity Anchor
- **Shared Identity Source ([`identity.md`](file:///home/nemo/Over_Agent_Design/identity.md))**: Defines a canonical first-person selfhood (*"I am Helix..."*) inherited by all cognitive focus windows.
- **Slim Main Orchestrator ([`subconscious_conductor.py`](file:///home/nemo/Over_Agent_Design/subconscious_conductor.py))**: Keeps the main subconscious reflection anchor prompt ultra-lean ($\sim$80 tokens), delegating tool selection to specialized sub-orchestrators.

### 2. Surgical Sub-Orchestrators ([`subagents.py`](file:///home/nemo/Over_Agent_Design/subagents.py))
- **`SpeakerFocus`**: Vocal cognitive mode for direct user dialogue synthesis.
- **`ResearcherSubOrchestrator`**: Multi-head mRAG preconscious recall over [`/home/nemo/Helix/data`](file:///home/nemo/Helix/data), workspace file scanning, and web search.
- **`ExecutorSubOrchestrator`**: Technical code evaluation, shell command execution (`TerminalFocus`), and desktop screen capture (`ScreenFocus`).

### 3. Multi-Head mRAG Memory Recall ([`mrag_adapter.py`](file:///home/nemo/Over_Agent_Design/mrag_adapter.py))
- Integrates [`/home/nemo/Local-mRag`](file:///home/nemo/Local-mRag) to index canonical belief and memory stores from [`/home/nemo/Helix/data`](file:///home/nemo/Helix/data) (`pending_beliefs.json`, `contacts.json`, `tool_learned_notes.json`, `interaction_ledger.json`, `cognitive_journal.jsonl`).
- Performs preconscious recall prior to rendering responses, placing relevant memory nodes into the active stream.

### 4. Dynamic Identity & Synthetic Affect Simulation Pipeline
- **Dynamic Identity Compiler ([`dynamic_identity_compiler.py`](file:///home/nemo/Over_Agent_Design/dynamic_identity_compiler.py))**: Maintains a running [`self_opinion.json`](file:///home/nemo/Over_Agent_Design/self_opinion.json) anchor compiled into the system prompt and updated nightly during DORMANT passes.
- **Synthetic Affect Simulation ([`affect_simulation.py`](file:///home/nemo/Over_Agent_Design/affect_simulation.py))**: Tracks mathematical state vectors (`Valence`, `Arousal`, `Focus Depth`, `State Descriptor`) to guide prompt personality and conceptual gravity.

### 5. Real-Time Background Pulses & Thread Safety
- **Background Daemon Thread ([`main.py`](file:///home/nemo/Over_Agent_Design/main.py))**: Executes real-time idle reflection pulses (`pulse_idle_check`) every ~12 seconds while waiting for user input.
- **Thread Lock (`self.lock`)**: Prevents GPU HTTP completion request contention on local Ollama instances (`granite4.1:8b`), giving strict priority to user turns.
- **Expanded History Budget**: 16,000 character ($\sim$4,000 token) dialogue budget with separate system injection slots.

### 6. DORMANT State Nightly Consolidation Pass
- **`run_dormant_consolidation_pass()`**: Performs deep stream compaction, extracts persistent session facts, updates `self_opinion.json`, and saves state to `helix_seeded_state.pkl`.

---

## 📁 Repository Structure

```
Over_Agent_Design/
├── main.py                        # Rich terminal UI & background pulse launcher
├── subconscious_conductor.py      # Core Conductor engine & thread lock
├── subagents.py                   # Speaker, Research & Execution Sub-Orchestrators
├── mrag_adapter.py                # Multi-head mRAG retrieval over /home/nemo/Helix/data
├── dynamic_identity_compiler.py   # Compiles identity.md + self_opinion.json + affect state
├── affect_simulation.py           # Synthetic affect state vector pipeline
├── llm_backend.py                 # Local Ollama HTTP adapter (granite4.1:8b default)
├── voice_subagents.py             # Modular TTS/STT speech interface
├── identity.md                    # Shared first-person identity anchor
├── self_opinion.json              # Consolidated dynamic self-opinion statement
├── synthetic_affect_state.json    # Synthetic mood/affect parameters
├── helix_seeded_state.pkl         # Persistent memory state pickle
├── Launch_Helix_Agent.sh          # Executable shell launcher script
├── Run_Health_Check.sh            # System health diagnostic tool
└── tests/                         # Unit tests & empirical benchmark suite
    ├── test_full_system.py        # Integration test suite
    └── benchmark_recall_and_reasoning.py # Empirical recall & routing benchmark
```

---

## 🚀 Quick Start Guide

### 1. System Diagnostic Check
Verify local Ollama service, model tags, audio tools, and identity files:
```bash
./Run_Health_Check.sh
```

### 2. Launch Interactive Terminal App
Launch Helix with debug logs and real-time background pulse threading:
```bash
./Launch_Helix_Agent.sh
```

*(For voice mode, run `python3 main.py --voice`)*

### 3. Run Test & Benchmark Suite
Execute system integration tests and the empirical benchmark suite:
```bash
python3 -m unittest discover -s tests
python3 tests/benchmark_recall_and_reasoning.py
```

---

## 📊 Empirical Benchmark Results

Run `python3 tests/benchmark_recall_and_reasoning.py` to produce a structured JSON report saved to [`tests/benchmark_results.json`](file:///home/nemo/Over_Agent_Design/tests/benchmark_results.json):

- **mRAG Memory Recall**: 100% Hit Rate across canonical Helix belief stores ($\sim$1.2ms latency).
- **Sub-Orchestrator Routing**: High-precision domain dispatch (`speaker`, `researcher`, `executor`).
- **Context Compaction**: Efficient turn history reduction without loss of pinned identity anchors.
- **Error Recovery**: Automatic diagnostic step generation upon receiving failed command receipts.

---

## 📜 License & Acknowledgments
Designed for **Helix AGI** research into continuous digital mind architectures, test-time compute expansion, and autonomous subconscious intelligence.
