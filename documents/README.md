# Helix Technical Documentation Index

**Documentation Status:** Current & Verified · **Last Verified Against Source:** 2026-08-14

Helix documentation is structured by subsystem and operational purpose. This index defines authoritative system references, subsystem audits, and benchmark evaluation records.

---

## Authoritative System References

These documents describe the canonical live runtime on the `main` branch:

| Document | Purpose & Scope |
|---|---|
| [Repository README](../README.md) | Installation, Quick Start, 1-Click Launchers, Architecture Overview, and UX Features |
| [Current Architecture](architecture_current.md) | Canonical runtime wiring, 1024D mRAG, 8D Spatial Manifold, Context Office, and Persistence |
| [System Manual](../SYSTEM_MANUAL.md) | Comprehensive subsystem reference, pulse loop mechanics, and operating contracts |
| [Task Cognition Pipeline](task_cognition_pipeline.md) | Diagram and lifecycle for event-driven task cognition and tool execution |
| [MCP Agent Lab Integration](mcp_agent_lab.md) | Model Context Protocol integration for Codex, Claude Code, and Gemini CLIs |
| [Context Architecture Experiments](context_architecture_experiments.md) | Same-exam hybrid compiler versus canonical Context Office benchmark comparison |

### Documentation Precedence
When documentation disagrees, resolve discrepancies in the following order:
1. **Executable Source & Unit Tests** (`core/`, `llm/`, `tools/`, `memory/`, `tests/`)
2. [`documents/architecture_current.md`](architecture_current.md)
3. [`SYSTEM_MANUAL.md`](../SYSTEM_MANUAL.md)
4. [`README.md`](../README.md)

---

## Subsystem Audits & Module Maps

Detailed line-by-line audits for every core module in Helix are located in [`documents/audits/`](audits/):

| Audit Document | Module Covered | Canonical Source File |
|---|---|---|
| [Overview & Module Index](audits/audit_overview.md) | Full system map and subsystem directory | [`main.py`](../main.py) |
| [Preconscious Injection](audits/audit_preconscious.md) | mRAG 1024D + 8D Spatial + Multi-Hop + Opinions | [`core/preconscious.py`](../core/preconscious.py) |
| [Pulse Loop Engine](audits/audit_pulse_loop.md) | State machine, pulse cycle, and event queues | [`core/pulse_loop.py`](../core/pulse_loop.py) |
| [Tool System & Learning](audits/audit_tool_learning.md) | Hermes Dynamic Registry, UI Canvas, Lessons | [`tools/tool_registry.py`](../tools/tool_registry.py), [`tools/ui_canvas_tool.py`](../tools/ui_canvas_tool.py) |
| [Cognitive Space](audits/audit_cognitive_space.md) | 8D Manifold, JL Projection, KD-Tree | [`core/cognitive_space.py`](../core/cognitive_space.py) |
| [Physics Engine](audits/audit_physics_engine.md) | Euler-Lagrange spatial dynamics, gravity queries | [`core/physics_engine.py`](../core/physics_engine.py) |
| [Spatial Mind](audits/audit_spatial_mind.md) | Dual-space coordinate system & state persistence | [`core/spatial_mind.py`](../core/spatial_mind.py) |
| [Affect Field](audits/audit_affect_field.md) | Plutchik emotional wave packet interference | [`core/affect_field.py`](../core/affect_field.py) |
| [Affect Hook](audits/audit_affect_hook.md) | Post-pulse affect reads & sentinel Ω nudges | [`core/affect_hook.py`](../core/affect_hook.py) |
| [Belief Detector](audits/audit_belief_detector.md) | Real-time belief extraction via Lagrangian deltas | [`core/belief_detector.py`](../core/belief_detector.py) |
| [Belief Store](audits/audit_belief_store.md) | Database layer, normalized schemas, and mass | [`memory/belief_store.py`](../memory/belief_store.py) |
| [Memory Manager](audits/audit_memory_manager.md) | Unified JSONL journal & 384D FAISS index | [`memory/memory_manager.py`](../memory/memory_manager.py) |
| [Semantic Index](audits/audit_semantic_index.md) | Vector storage, numpy search, FAISS upgrade | [`memory/semantic_index.py`](../memory/semantic_index.py) |
| [Scratchpad](audits/audit_scratchpad.md) | Markdown working memory & postponement locks | [`memory/scratchpad.py`](../memory/scratchpad.py) |
| [Cognitive Journal](audits/audit_cognitive_journal.md) | Append-only JSONL event sourcing | [`memory/cognitive_journal.py`](../memory/cognitive_journal.py) |

---

## Benchmark Evaluation Suites

Automated and interactive benchmark suites located in [`tests/`](../tests/):

1. **Non-LLM 100-Question A/B Retrieval Ablation** ([`test_mrag_ablation_bench.py`](../tests/test_mrag_ablation_bench.py))
2. **Early Helix Memory Grounding & Tone Evaluation** ([`test_helix_early_memories.py`](../tests/test_helix_early_memories.py))
3. **Agent Adaptation & Skill Acquisition Benchmark** ([`test_agent_adaptation_bench.py`](../tests/test_agent_adaptation_bench.py))
4. **Multi-Pulse Live Agent Simulation** ([`test_live_agent_pulse_simulation.py`](../tests/test_live_agent_pulse_simulation.py))
5. **Autonomous Internal Monologue Stream** ([`test_autonomous_pulse_chain.py`](../tests/test_autonomous_pulse_chain.py))
6. **Long-Form Agentic Memory & Opinion Defense** ([`test_longform_agentic_memory_bench.py`](../tests/test_longform_agentic_memory_bench.py))
7. **Unified Benchmark Runner** ([`run_all_benchmarks.py`](../tests/run_all_benchmarks.py) / [`Run Benchmarks.sh`](../Run%20Benchmarks.sh))

---

## Maintenance Rule

Any change to pulse states, retrieval ordering, embedding dimensions, provider interfaces, tool declarations, or persistence formats must update [`architecture_current.md`](architecture_current.md) and [`SYSTEM_MANUAL.md`](../SYSTEM_MANUAL.md) in the same commit.
