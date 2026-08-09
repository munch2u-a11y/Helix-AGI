# Helix Technical Documentation

**Documentation status:** current index · **Last verified against source:** 2026-08-09

Helix documentation is divided by purpose. This distinction matters because
the repository retains old audits and benchmark reports to preserve design
history and measured results.

## Current References

These documents describe the live system on the current branch:

| Document | Use it for |
|---|---|
| [Project README](../README.md) | Installation, configuration, features, and operator entry points |
| [Current Architecture](architecture_current.md) | Canonical runtime wiring, retrieval lanes, task cognition, providers, and persistence |
| [System Manual](../SYSTEM_MANUAL.md) | Detailed subsystem behavior and operating model |
| [Task Cognition Pipeline](task_cognition_pipeline.md) | Focused diagram and lifecycle for event-driven task cognition |
| [Context Architecture Fork Comparison](context_architecture_experiments.md) | Same-exam hybrid compiler versus canonical Context Office results and tradeoffs |
| [Test Suite Guide](../tests/TEST_SUITE_README.md) | Test organization and execution |

When current documents disagree, use this precedence:

1. Executable source and tests.
2. `documents/architecture_current.md`.
3. `SYSTEM_MANUAL.md`.
4. `README.md`.

Please fix the lower-precedence document when a discrepancy is found.

## Historical Code Audits

Files under [`documents/audits/`](audits/) and the three
[`helix_audit_part*.md`](helix_audit_part1.md) reports are source-level
snapshots of earlier implementations. They are useful for rationale and design
history, but their line numbers, model names, dimensions, state names, and
runtime paths are not current contracts.

The older preconscious and pulse deep dives now live in `documents/audits/`:

- [`preconscious_memory_audit.md`](audits/preconscious_memory_audit.md)
- [`preconscious_refactor_audit.md`](audits/preconscious_refactor_audit.md)
- [`pulse_workflow_audit.md`](audits/pulse_workflow_audit.md)

## Benchmark Records

Benchmark reports record the exact implementation and settings that were
evaluated at the report date. Values such as `384D` in an old result remain
correct for that run; they do not describe today's 1024D semantic index.

- [`locomo_benchmark_report.md`](locomo_benchmark_report.md) — older LoCoMo retrieval run.
- [`unified_retrieval_report.md`](unified_retrieval_report.md) — unified-retrieval baseline run.
- [`benchmark/`](benchmark/) — benchmark design and individual run reports.
- `benchmark_results/` at the repository root — generated run artifacts.

Do not silently rewrite measured configurations in historical results. Run a
new benchmark and add a new dated report instead.

## Maintenance Rule

Any change to pulse states, retrieval ordering, embedding dimensions, provider
behavior, persistence formats, or task cognition must update
`architecture_current.md` and the affected current guide in the same commit.
Historical documents should receive a status note, not a retroactive rewrite.
