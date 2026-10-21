# Helix Test Suite

**Documentation status:** diagnostic test guide · **Reviewed:** 2026-10-17

Use the repository virtual environment for every command. Some retrieval tests
mock the semantic encoder; end-to-end semantic runs require local Ollama with
`qwen3-embedding:0.6b` available.

## Explicit maintenance test groups

For the lightweight offline gate (no weights, services, channel credentials or hardware):

```bash
python -m pip install -r requirements-dev.txt
python tests/run_all_tests.py --list-groups
python tests/run_all_tests.py --group offline
```

The checked-in `test_groups.json` accounts for every `test_*.py` module under
`tests/`, `Over_Agent_Design/` and `plugins/`; a new unclassified module fails
this gate. Frozen audit snapshots are intentionally excluded. The offline group
is a maintenance smoke gate, not all root regressions or a product evaluation.
The `integration` group retains broader regressions and known baseline drift;
`native` requires the real external MightyMem source and neural dependencies;
`prototype` and `plugin` have separate dependencies and composition boundaries.
Review live tests before using `--group live --allow-live`.

Missing native source returns **BLOCKED**, exit 2, before tests import. Other
missing requirements surface as test errors rather than silent passing skips.
The existing ungrouped runner and `--quick` retain their historical curated
script lists; they are not substitutes for the native or offline groups.

The read-only installation preflight is `python scripts/run_health_check.py`
(or add `--json` for machine output). Required failures return nonzero; passing
this offline check does not establish live service availability or launch success.

## Wizard and dashboard UI checks

The offline group includes selected-data canvas, module API and desktop-widget
bridge checks. File-writing fixtures use temporary directories. The dashboard
request functions are exercised separately with Node (no npm install):

```bash
node --test tests/dashboard_routes.test.cjs
```

For the offscreen wizard regression gate used in CI:

```bash
python -m pip install -r requirements-dev.txt -r requirements-wizard.txt
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_wizard_routes.py tests/test_agent_creation.py::WizardCreationDiagnostics
```

Linux also needs Qt system libraries such as libEGL, OpenGL and xkbcommon; CI
installs them explicitly. These are mocked/offscreen implementation diagnostics,
not a visible-desktop, full-installer or live-provider certification.

## Evidence boundary

Unit, fixture, provider, simulator and retrieval-only checks are implementation
diagnostics. They do not evaluate the current native Mindscape product, even
when they use real model weights. `--check-setup` proves initialization only.
A helper that seeds temporary stores and calls `BicameralRWKVSession` directly
does not traverse the production runtime; putting recall facts in the prompt
does not test durable recall.

For a product claim, record the exact revision and dirty tree, entry point,
configuration, models/checkpoints, stores/indexes, retrieval/reasoning lanes,
compiler, tools, hardware, output path and outcome/grader. Audit inherited
limits before launching. Each case must prove:

`real ingestion → persistent memory/state → all production retrieval/reasoning
lanes → production context compiler → declared model → real answer/action path
→ official scorer or independently verified outcome`

The [October 17 native-body record](../documents/audits/2026-10-17-native-body-operational/README.md)
contains such a composition/receipt chain for its stated movement/open/run and
restart workflow. Its recorded 72 focused implementation checks are separate;
neither the workflow nor those checks provide a coherence, recall or growth
score.

## Native-body implementation diagnostics

```bash
venv/bin/python -m unittest tests.test_native_motor \
  tests.test_agent_home tests.test_dual_rwkv_defaults
```

These exercise request recognition, per-target obligations, checkpoint gating,
local auxiliary routing, lifecycle cancellation, sensory persistence and
workshop containment. They use isolated fixtures where appropriate; they are
not a new full-product trial. Older subconscious-motor tests target retained
helper APIs, not the production speech decoder. Nursery tests exercise the
[separate prototype](../documents/nursery_status.md), not integrated development.

## Other diagnostic commands

Run the repository's curated quick suite:

```bash
venv/bin/python tests/run_all_tests.py --quick
```

Run the runner's broader curated list, including simulators and load/stress scripts
(the list is not the full current product composition):

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

`run_all_tests.py` retains an inherited five-minute limit per listed script;
that limit is not a justified native-product boundary. Raw discovery also
includes legacy contracts and requires their dependencies. The commands have
different coverage and neither establishes release readiness or full-product
performance.

## Current Architecture Coverage

| Area | Primary tests |
|---|---|
| Native goal policy and body lifecycle | `test_native_motor.py`, `test_agent_home.py`, `test_dual_rwkv_defaults.py` |
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

## Legacy action-path diagnostics

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

## Historical memory-adapter experiments

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
`scripted` ingestion isolates retrieval behavior; `connector` performs a
conscious replay inside that adapter. Neither mode establishes parity with the
current production Mindscape composition. Exam turns are retrieval-only and do not
teach the system.

## LongMemEval-S adapter diagnostic

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
same-reader adapter study with RAGOffice. Reader backend and model are locked into
the resume manifest.

## RAGOffice same-exam adapter diagnostic

`ragoffice_parity_sandbox.py` executes RAGOffice's current 110-item generator,
freezes the resulting 100 answerable questions plus ten negative controls, and
ingests the exact 220 source turns into one isolated Helix mind. It uses
RAGOffice's answer prompt, local Granite reader, accepted-answer alternatives,
required-span rules, and refusal scoring. The snapshot hash, RAGOffice commit,
and dirty source paths are recorded before the run.

```bash
venv/bin/python tests/ragoffice_parity_sandbox.py \
  --ragoffice-root /path/to/RAGOffice \
  --model granite4.1:8b \
  --context-office on \
  --resume
```

Use `--context-office off` with a different output directory for the semantic
advisor ablation. `--question-ids q_1,q_11,q_50,n_7` performs a cheap targeted
audit without changing the frozen exam or indexing scope.

This keeps the exam and reader fixed within the isolated adapter study.
It does not establish current Mindscape product parity: the normal entry point,
native state, all Loom lanes and production context/model route are not proven
by this harness. Preserve its numbers as diagnostic provenance, not current
product comparisons. LongMemEval and this synthetic suite are also different
exams and cannot be compared as equivalent scores.

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

## Experimental native robustness checks

The offline group covers `test_stability_policy.py`, `test_progress_feedback.py`
and `test_native_robustness.py`, plus the retained Context Office diagnostics.
They use injected probe scores, temporary files/SQLite and explicitly fake neural
receipts. The standalone `python tests/test_tool_learning_pipeline.py` script
checks failure capture and successful-exposure accounting with real temporary
belief stores; successful use does not verify a lesson's truth.

The [second-branch guide](../documents/maintenance/NATIVE_ROBUSTNESS.md) provides
controls, a read-only checkpoint inspector and the native PC acceptance workflow.
