# Helix Test Suite

**Documentation status:** current test guide · **Last verified against source:** 2026-08-15

Use the repository virtual environment for every command. Some retrieval tests
mock the semantic encoder; end-to-end semantic runs require local Ollama with
`qwen3-embedding:0.6b` available.

## Recommended Commands

Run the repository's curated quick suite:

```bash
venv/bin/python tests/run_all_tests.py --quick
```

Run its curated full suite, including simulators and load/stress scripts:

```bash
venv/bin/python tests/run_all_tests.py
```

Audit every discoverable unit and integration module, including retained
legacy tests that are not part of the curated green gate:

```bash
venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Run one test module:

```bash
venv/bin/python tests/test_task_cognition.py
venv/bin/python tests/run_all_tests.py --script test_task_cognition.py
```

`run_all_tests.py` is the maintained subprocess gate with a five-minute limit
per listed script. Raw `unittest` discovery is the broadest dependency-free
audit, but it also includes legacy contract tests that are not currently in
the curated runner and may expose known migration debt. Do not treat those two
commands as equivalent coverage or release criteria.

## Current Architecture Coverage

| Area | Primary tests |
|---|---|
| Native semantic representation | `test_semantic_encoder.py` |
| Multi-head full/sentence/RAKE retrieval | `test_mrag_semantic_lane.py` |
| mRAG-primary lane separation | `test_unified_retrieval.py` |
| Directed non-semantic associations | `test_associative_transitions.py` |
| Progressive learned-memory benchmark | `test_deep_memory_benchmark.py` |
| Sandboxed LongMemEval ingestion, selection, and review artifacts | `test_longmemeval_sandbox.py` |
| Exact RAGOffice exam parity and scoring | `test_ragoffice_parity_sandbox.py` |
| Codex App Server provider and host tools | `test_codex_cli_provider.py` |
| Clarify-plan-act-verify action contract | `test_action_protocol.py`, `test_action_planner.py`, `test_action_path_exam.py` |
| Provider-neutral identity and affect capsule | `test_self_state.py` |
| Codex one-switch setup | `test_codex_agent_setup.py` |
| Event-driven tasks, orchestrators, focus, and procedures | `test_task_cognition.py` |
| Preconscious context assembly | `test_preconscious_injection.py` |
| Maintained session/subject/topic/relation logs and canonical-ID deduplication | `test_case_memory_office.py` |
| Typed source-aware Office capsules and stateless speaker boundary | `test_office_runtime.py` |
| Belief and memory behavior | `test_belief_operations.py`, `test_emc2_retrieval.py` |
| Tool dispatch and learned tools | `test_tool_executor.py`, `test_tool_learning_pipeline.py`, `test_tool_factory.py` |
| Channels and dashboard | `test_channel_router.py`, `test_dashboard_*.py` |
| Safety and runtime integrity | `test_simulated_safety_benchmark.py`, `test_runtime_integrity.py` |

The current architecture and documentation precedence are defined in
[`documents/architecture_current.md`](../documents/architecture_current.md)
and [`documents/README.md`](../documents/README.md).

## Action-Path Smokes

The deterministic exam has no external side effects:

```bash
venv/bin/python tests/run_action_path_exam.py
```

The local-model smoke uses a virtual tool world, so it exercises real model
planning without changing host files or accounts:

```bash
venv/bin/python tests/run_action_path_local_smoke.py \
  --model granite4.1:8b --json
```

The Codex smoke creates a real authenticated App Server thread, but keeps its
workspace read-only, disables network and approvals, and exposes no host tools:

```bash
venv/bin/python tests/run_codex_helix_smoke.py --json
```

It distinguishes a successful App Server handshake from model inference. A
subscription usage limit therefore reports `transport_ready: true` with an
inference blocker instead of being misreported as a wiring failure.

## Progressive Deep-Memory Evaluation

First validate the fixture and checkpoint assembly without calling a conscious
model:

```bash
venv/bin/python tests/locomo_deep_memory_sandbox.py --dry-run
```

Then run fresh checkpoint exams through a locally authenticated Codex client:

```bash
venv/bin/python tests/locomo_deep_memory_sandbox.py \
  --backend codex-subscription \
  --retrieval-profile frontier \
  --ingest-mode scripted
```

Use `--association-memory on` and `off` for the transition-memory ablation.
`scripted` ingestion isolates retrieval behavior; `connector` performs the
costlier end-to-end conscious replay. Exam turns are retrieval-only and do not
teach the system.

## LongMemEval-S Development Evaluation

`longmemeval_sandbox.py` indexes cleaned LongMemEval histories into a fresh
temporary Helix runtime for each question and answers through the ordinary
preconscious mRAG injection. Its 100-question ceiling is enforced by the CLI.
The default sample is proportional across question type and abstention status,
using a recorded seed rather than the category-skewed first 100 rows.
History ingestion records direct session-cluster transitions when the
associative lane is enabled; exam questions use `learn=False`.

```bash
venv/bin/python tests/longmemeval_sandbox.py \
  --dataset /path/to/longmemeval_s_cleaned.json \
  --dry-run
```

The run is resumable and saves a manual review page per answer. Automated
exact match, token overlap, and evidence-session recall remain diagnostics;
the review pages preserve the gold evidence and actual injected context.
Use `--backend ollama --model granite4.1:8b` for a subscription-free run or a
same-reader comparison with RAGOffice. Reader backend and model are locked into
the resume manifest.

## RAGOffice Exact-Exam Parity

`ragoffice_parity_sandbox.py` executes RAGOffice's current 110-item generator,
freezes the resulting 100 answerable questions plus ten negative controls, and
ingests the exact 220 source turns into one isolated Helix mind. It uses
RAGOffice's answer prompt, local Granite reader, accepted-answer alternatives,
required-span rules, and refusal scoring. The snapshot hash, RAGOffice commit,
and dirty source paths are recorded before the run.

```bash
venv/bin/python tests/ragoffice_parity_sandbox.py \
  --ragoffice-root /home/nemo/RAGOffice \
  --model granite4.1:8b \
  --context-office on \
  --resume
```

Use `--context-office off` with a different output directory for the semantic
advisor ablation. `--question-ids q_1,q_11,q_50,n_7` performs a cheap targeted
audit without changing the frozen exam or indexing scope.

This is the appropriate same-exam comparison. LongMemEval remains the broader,
much longer natural-dialogue evaluation rather than a directly comparable
replacement for RAGOffice's synthetic suite.

## Test Classes

- `test_*.py` files are unit or integration regressions. The curated runner
  defines the maintained gate; raw discovery also includes retained legacy
  contracts and is useful for migration-debt audits.
- `simulate_*.py`, `stress_test_pulse.py`, and `load_test.py` exercise model or
  performance behavior outside the ordinary unit-test contract.
- `*_sandbox.py` and `*_benchmark.py` scripts are explicit experiments. Read
  their CLI help and output location before running them.
- Generated reports belong in `benchmark_results/`; dated reports describe the
  evaluated build and are not current architecture references.

No fixed throughput, latency, or pass-rate numbers are promised here. Those
figures depend on hardware, store size, provider, local model availability, and
the exact commit, so performance claims belong in dated benchmark reports.
