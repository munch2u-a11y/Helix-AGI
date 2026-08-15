# Helix Technical Documentation

**Documentation status:** current index · **Last verified against source:** 2026-08-15

Helix documentation is divided by purpose. This distinction matters because the repository retains historical audits and benchmark reports to preserve design history and measured results.

## Current References

These documents describe the live system on the current branch (`feature/typed-memory-retrieval`):

| Document | Use it for |
|---|---|
| [Project README](../README.md) | Installation, configuration, features, and operator entry points |
| [Current Architecture](architecture_current.md) | Canonical runtime wiring, retrieval lanes, Action Path, task cognition, providers, and persistence |
| [System Manual](../SYSTEM_MANUAL.md) | Detailed subsystem behavior and operating reference |
| [Action Path Contract](action_path.md) | ActionLeg planning, context budgets, state verifiers, computer interface, and smoke harnesses |
| [Task Cognition Pipeline](task_cognition_pipeline.md) | Event-driven task diagram, focus arbitration, and lifecycle |
| [Context Architecture Fork Comparison](context_architecture_experiments.md) | Same-exam hybrid compiler versus canonical Context Office results |
| [Test Suite Guide](../tests/TEST_SUITE_README.md) | Test organization and execution |

When current documents disagree, use this precedence:

1. Executable source and tests.
2. `documents/architecture_current.md`.
3. `SYSTEM_MANUAL.md`.
4. `README.md`.

Please fix the lower-precedence document when a discrepancy is found.

## Technical Code Audits

Detailed module-by-module technical audits are maintained under [`documents/audits/`](audits/):

- [`audit_overview.md`](audits/audit_overview.md) — Main architecture map and module index.
- [`audit_action_planner.md`](audits/audit_action_planner.md) [NEW] — Action Path, 4-leg plan limits, clarification questions (`NEED_INPUT:`), and tool orchestrators.
- [`audit_task_cognition.md`](audits/audit_task_cognition.md) [NEW] — Inception intent detection, focus worker arbitration, and procedural memory.
- [`audit_record_envelope.md`](audits/audit_record_envelope.md) [NEW] — Provider-free `RecordEnvelope` memory decorators, evidence assertions, and typed retrieval lanes.
- [`audit_pulse_loop.md`](audits/audit_pulse_loop.md) — Pulse loop state machine, event queue, and cadence.
- [`audit_preconscious.md`](audits/audit_preconscious.md) — Preconscious context assembly and evidence injection.
- [`preconscious_memory_audit.md`](audits/preconscious_memory_audit.md) & [`preconscious_refactor_audit.md`](audits/preconscious_refactor_audit.md) — Preconscious design history.

## Benchmark Records

Benchmark reports record the exact implementation and settings evaluated at the report date:

- [`locomo_benchmark_report.md`](locomo_benchmark_report.md) — LoCoMo retrieval run.
- [`unified_retrieval_report.md`](unified_retrieval_report.md) — Unified retrieval baseline run.
- [`benchmark/`](benchmark/) — Benchmark design and run reports.

## Maintenance Rule

Any change to pulse states, retrieval ordering, embedding dimensions, provider behavior, persistence formats, action paths, or task cognition must update `architecture_current.md` and the affected current guide in the same commit.
