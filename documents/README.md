# Helix documentation

Start with the [sensing, action and speech guide](sensing-action-speech.md).
It explains the continuous text senses, filesystem body and transition from
private thought to ordinary speech without a generated command.

## Use the agent

| Guide | Purpose |
|---|---|
| [Project README](../README.md) | Overview and quick start |
| [Sensing, action and speech](sensing-action-speech.md) | How the engine works and what to try |
| [Setup and launch](mindscape_launch.md) | Dependencies, guided creation, CLI provisioning and startup |
| [System manual](../SYSTEM_MANUAL.md) | Operation, configuration, health and persistence |
| [Agent home](agent-home.md) | Rooms, module interfaces, sensory intake and workshop containment |

## Develop and inspect

| Guide | Purpose |
|---|---|
| [Current architecture](architecture_current.md) | Runtime ownership, memory/context/model connections and persistence |
| [Action paths](action_path.md) | Numeric body signals, authorization and completion |
| [Models](../models/README.md) | RWKV checkpoint, embeddings and optional model files |
| [Test guide](../tests/TEST_SUITE_README.md) | Implementation checks and full-product evaluation |
| [Developer examples](../examples/README.md) | Isolated API demonstrations |
| [Task cognition](task_cognition_pipeline.md) | Separate legacy focus-worker route |
| [Nursery status](nursery_status.md) | Prototype behavior and remaining integration work |

## Current support and evidence

The [October 17 live record](audits/2026-10-17-native-body-operational/README.md)
documents working movement, file opening, sandboxed Python execution and
graceful restart on CPU. A separate live control verified sensing during a
running script. Thought/speech separation and delivery routing have focused
implementation checks.

The body currently follows explicit user goals; independent learned action
selection is the next stage. Detailed receipts and evaluation scope belong
in the operational record and test guide.

## Historical audits and design work

Dated [audits](audits/) preserve their original source, successes and failures.
For current wiring, use [architecture](architecture_current.md).

- [October 10 diagnostic handoff](mindscape_diagnostics_2026-10-10.md)
- [Earlier integration plan](mindscape_implementation_plan.md)
- [Older module audit index](audits/audit_overview.md)
- [Over-Agent design](../Over_Agent_Design/README.md)
- [Creative design reflection](design_reflection.md)

## Benchmark records

These reports retain the results of their original retrieval/adapter studies:

- [LoCoMo retrieval report](locomo_benchmark_report.md)
- [Unified retrieval report](unified_retrieval_report.md)
- [Context-compiler fork comparison](context_architecture_experiments.md)
- [Benchmark reports](benchmark/)
- [Benchmark output guide](../benchmark_results/README.md)

They do not score the current native engine. A new product claim requires the
actual production composition and verified outputs; see the
[test guide](../tests/TEST_SUITE_README.md#evidence-boundary).

## Maintenance rule

Keep source wiring, operator guides and documented support in agreement.
Preserve historical evidence and distinguish it from current behavior.

## Maintenance

The [cleanup branch status](maintenance/CLEANUP_STATUS.md) records implemented
consolidation, local/CI validation and the remaining native/manual gates. The
[dependency profile guide](maintenance/DEPENDENCIES.md) explains the shared
requirements and wizard installation stages. The
[initial cleanup review](maintenance/CLEANUP_REVIEW.md) preserves its baseline
findings and proposed sequence. Frozen audits remain historical evidence.

The experimental [native robustness branch guide](maintenance/NATIVE_ROBUSTNESS.md)
explains outcome feedback, checkpoint-supported procedures, controls and PC
acceptance. Its component checks are separate from the recorded native trial.
