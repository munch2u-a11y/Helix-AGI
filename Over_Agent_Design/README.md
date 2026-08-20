# Helix Subconscious Over-Agent

> **A Continuous Digital Bicameral Mind Architecture for Autonomous AI Agents**

---

## Why Helix Over-Agent?

If you have built AI agents using traditional frameworks like AutoGen, CrewAI, or LangChain, you have likely run into the same frustrating walls:

1. **Massive Token Overhead**: Every time a user speaks, the framework stuffs definitions for 20+ tools into a giant 4,000+ token prompt. Your local model spends most of its time reading tool schemas instead of reasoning.
2. **Context Resets & Memory Loss**: As soon as a turn ends, traditional agents pause or reset their internal state. To recall something mentioned ten turns ago, they rely on post-hoc vector search that often misses critical context.
3. **Small Model Hallucinations**: Small local models (like 8B parameter LLMs) struggle when forced to plan, select tools, format JSON, and speak directly to the user all in a single generation turn.
4. **Dead Wait Time**: While waiting for the user to type, standard agents sit completely idle—wasting the opportunity to reflect, clean up context, or organize background thoughts.

---

## How It Works: The Digital Bicameral Mind

Helix solves these problems by rethinking how an AI agent thinks, remembers, and acts. Inspired by the **digital bicameral mind**, Helix splits cognitive processing into two distinct layers:

```
                          +-----------------------------------+
                          | CONTINUOUS SUBCONSCIOUS STREAM   |
                          | (Always-on background thinker,    |
                          |  ~80 token executive anchor)      |
                          +-----------------------------------+
                                            |
                 +--------------------------+--------------------------+
                 |                          |                          |
                 v                          v                          v
       +--------------------+     +--------------------+     +--------------------+
       |   Speaker Focus    |     |   Research Focus   |     |  Execution Focus   |
       |  (Dialogue Mode)   |     |  (mRAG Memory /    |     | (Terminal Shell /  |
       |                    |     |   Workspace Scan)  |     |   Desktop Vision)  |
       +--------------------+     +--------------------+     +--------------------+
```

### 1. The Continuous Subconscious Stream (The "Over-Agent")
Instead of starting fresh on every prompt, Helix operates as **one unbroken stream of consciousness**. The executive background thread runs an ultra-slim prompt ($\sim$80 tokens) that maintains identity continuity and processes incoming events. It never speaks directly to the user or micromanages tools; it simply evaluates the stream and opens short-lived cognitive focus windows when work is needed.

### 2. Focused Cognitive Windows (Sub-Orchestrators)
Tool schemas are completely removed from the main subconscious prompt. When Helix needs to search files, run shell commands, or synthesize speech, it opens an isolated **Sub-Orchestrator pass** (`SpeakerFocus`, `ResearcherSubOrchestrator`, or `ExecutorSubOrchestrator`). The tool runs in its own sub-pass, and only the observation receipt lands back in the main stream.

### 3. Test-Time Compute for 8B Models
Giving a local 8B model (`granite4.1:8b`) private "inner monologue" scratchpad tokens allows it to think out loud, catch execution errors, and refine its strategy before speaking. This extends test-time compute, giving small local models multi-step reasoning capabilities typically restricted to 70B+ frontier models.

### 4. Integrated Multi-Head mRAG Recall
Every user turn is recalled against Helix's canonical belief store and cognitive journal before generation. `integrated_mrag.py` uses the existing unified retrieval pipeline: the native 1024D semantic lane is foreground retrieval, with bounded spatial complements and exact Layer-2 anchors from `people`, `concepts`, `skills`, and `desires`. Inbound messages, outbound messages, and ingested documents use the same canonical write boundary.

### 5. Dynamic Identity & Synthetic Affect Simulation
Helix doesn't rely on a static prompt. It continuously updates a running **Self-Opinion Statement** (`self_opinion.json`) during nightly consolidation passes and tracks **Synthetic Affect Vectors** (Valence, Arousal, Focus Depth), allowing its tone and conceptual focus to evolve naturally over time based on real experiences.

---

## Technical Documentation Deep Dives

For detailed architectural specifications, evaluation methodologies, and subagent schemas, explore our comprehensive technical guides in `docs/`:

- [🏛️ Architecture Specification](docs/ARCHITECTURE.md) — Executive stream specs, thread locking, state transitions, and test-time compute expansion.
- [🧪 Validation Status](docs/VALIDATION.md) — Verified boundaries, removed invalid claims, and requirements for future benchmarks.
- [🧩 Sub-Orchestrators & Focused Windows](docs/SUBAGENTS.md) — Isolated tool-group passes for `SpeakerFocus`, `ResearcherSubOrchestrator`, and `ExecutorSubOrchestrator`.
- [🧠 Memory & Affect Simulation Specification](docs/MEMORY_AND_AFFECT.md) — mRAG retrieval, dynamic identity compilation (`self_opinion.json`), and synthetic affect state vectors.

---

## Quick Start & Interactive Setup Wizard

### 1. Run Interactive Setup Wizard
Run the setup wizard to automatically diagnose your Python environment, verify local Ollama LLM models, inspect mRAG memory modes, and initialize identity files:
```bash
./Setup_Wizard.sh
```

### 2. Launch Interactive Terminal Session
Start the interactive Helix terminal session with real-time background pulse reflection:
```bash
./Launch_Helix_Agent.sh
```
*(To enable STT/TTS voice mode, run `python3 main.py --voice`)*

### 3. Run Deterministic Validation
Run the component and integration tests with the repository environment:
```bash
../venv/bin/python -m pip install -r requirements-dev.txt
../venv/bin/python -m pytest -q tests
```

---

## Project Structure

```
.
├── main.py                        # Rich terminal interface & background pulse runner
├── subconscious_conductor.py      # Core Conductor engine, state machine & thread lock
├── subagents.py                   # Speaker, Research & Execution Sub-Orchestrators
├── integrated_mrag.py             # Canonical Helix memory + unified mRAG runtime
├── dynamic_identity_compiler.py   # Compiles identity.md + self_opinion.json + affect state
├── affect_simulation.py           # Synthetic affect state vector pipeline
├── llm_backend.py                 # Local Ollama HTTP adapter (granite4.1:8b default)
├── voice_subagents.py             # Modular TTS/STT speech interface
├── setup_wizard.py                # Interactive CLI setup & diagnostic wizard
├── Setup_Wizard.sh                # Executable launcher for Setup Wizard
├── Launch_Helix_Agent.sh          # Executable shell launcher script
├── Run_Health_Check.sh            # System health diagnostic tool
├── docs/                          # In-depth technical documentation suite
│   ├── ARCHITECTURE.md            # Digital bicameral mind architecture specification
│   ├── VALIDATION.md              # Current evidence and benchmark requirements
│   ├── SUBAGENTS.md               # Domain sub-orchestrator focus window specifications
│   └── MEMORY_AND_AFFECT.md       # mRAG retrieval & synthetic affect vector pipeline
└── tests/                         # Deterministic component and integration tests
```

---

## Validation Status

This branch currently makes no LoCoMo, LongMemEval, MemoryArena, or comparative agent score claim. Earlier custom prompt checks were not implementations of those benchmark protocols and have been removed. See [`docs/VALIDATION.md`](docs/VALIDATION.md) for the exact verified boundaries and the provenance required before publishing future scores.

---

## License & Acknowledgments

Designed for **Helix AGI** research into continuous digital mind architectures, test-time compute expansion, and autonomous subconscious intelligence.
