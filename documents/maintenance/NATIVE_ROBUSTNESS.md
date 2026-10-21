# Native robustness experiment and PC test guide

Branch: `feature/native-robustness`, based on cleanup revision
`dece25ebd1051d0ca6cede0c2c57a99e38e62ef1`. This is a second branch, not a
replacement for the cleanup branch or a new live native result.

## What is implemented

| Retained mechanism | Change on this branch |
|---|---|
| Friction damping | Both force terms oppose motion. Signal smoothing stays between the old value and the new measurement. |
| Stability Sentinel | Memory/disk/store/liveness failures retain independent severity even if spatial baselines normalize. Escalation is immediate; release needs three lower-severity probe cycles. Snapshot reads do not advance recovery. Repeated severity events are suppressed until a transition or collapse threshold. CPU utilization alone does not stop inference. |
| Engagement feedback | Actual executor and native returns supply progress observations. Failed calls, unconfirmed mutations and repeated unchanged observations do not reset stagnation or earn progress credit. |
| Tool lessons | A matched lesson source ID, current context and verified tool outcome record a successful exposure. That association does not increase truth verification, confidence or stability. |
| Procedural memory | Native completed goals teach exact, context-bound routines only after joint checkpoint success. Every recommendation rechecks its native receipts and support in the restored lineage. Failed matching goals remain cautionary evidence. |
| Over-Agent scheduling principle | Warning/critical health defers optional idle foreground generation. Queued events and unfinished interactions take priority; native reception, sensing and motor ownership are unchanged. |
| Context Office and lateral memory | Existing evidence roles, all nine Loom lanes, canonical stores and separate spatial/association ordering remain intact. Regression checks retain those boundaries; there is no second controller or merged relevance score. |

Native procedure recall contributes to the optional `procedures` context role
through the existing compiler. It records the same home, starting room, exact
requested steps, supporting job/receipt IDs and observed script hashes.
The native body still obtains fresh target observations, context admission,
SELF authorization and settled returns. Advice cannot execute or authorize a
step. No generalization from one filename/task to another is implemented.

The procedure reliability value is a smoothed success/failure summary of its
supported episodes, not a calibrated competence probability. This branch does
not implement autonomous learned motor selection or RWKV gradient training.

## Controls

These defaults apply on this branch. Add an object inside the existing
`mindscape` configuration to change them, then restart:

```json
"robustness": {
  "enabled": true,
  "progress_feedback": true,
  "procedure_learning": true,
  "procedure_recall": true,
  "idle_backpressure": true
}
```

`enabled: false` disables these four native extensions. Individual flags allow
learning without recall, recall without further learning, or disabling idle
backpressure independently. The damping fix, stable severity reporting and
truthful tool-lesson exposure accounting remain corrections on this branch.
Use the cleanup branch for a complete before/after comparison.

## Get the second checkout

From your existing repository, with its normal remote named `origin`:

```bash
git fetch origin
git worktree add ../Helix-AGI-robustness origin/feature/native-robustness
cd ../Helix-AGI-robustness
```

Activate your existing tested native environment. This branch introduces no
new third-party dependencies and leaves the native source manifest and model
requirements unchanged. If preparing a new environment, follow the
[launch prerequisites](../mindscape_launch.md) and [dependency profile guide](DEPENDENCIES.md).
Native workshop execution still requires its Linux/Bubblewrap environment.

Use a new test agent with separate data/home directories, or consistent offline
copies of the same baseline data, home and complete joint lineage for each
comparison. Keep the original state available. An existing identity contract
must not be renamed or reprovisioned as the test identity.

## Component gates first

Run from the second checkout with the selected Python environment:

```bash
python tests/run_all_tests.py --group offline
python tests/test_tool_learning_pipeline.py
node --test tests/dashboard_routes.test.cjs
python tests/run_all_tests.py --group native
```

The offline group includes real temporary-file and SQLite fixtures with fake
neural authorization/return receipts. Those tests verify controller contracts;
they are not native model or sandbox trials. The native group needs the actual
MightyMem source, neural dependencies and its declared execution environment.
Missing native prerequisites must remain BLOCKED/errors, never passing skips.

The existing offscreen wizard gate also remains in CI. A visible desktop run
and actual native workflow are still acceptance work for the PC.

## Native workflow to exercise manually

1. Select the isolated test configuration and run `python main.py --check-setup`.
   Start through normal `python main.py` with the intended source/checkpoint.
2. Place a harmless Python probe in the selected home's workshop. For example,
   a script that writes `robustness_result.txt` in its current workshop and prints
   a confirmation. Use the same contents for both branch comparisons.
3. Send through the dashboard: `Please open /workshop/robustness_probe.py then run /workshop/robustness_probe.py then open /workshop/robustness_result.txt`.
   Inspect the actual file and native returns. Completion must follow a joint
   checkpoint, not just a spoken success claim.
4. Repeat that exact request from the same starting room. Look for a
   `native_procedure_memory` contribution in `pulse_context` receipts and
   `native_procedure_observed` after completion. Each execution must still have
   new SELF authorization and its own settled returns. Advice may be excluded
   whole when it does not fit the normal context budget; inspect the assembly
   receipt rather than assuming the speaker used it.
5. Stop gracefully and restart. Repeat the request, then inspect again. Use a
   missing target as a failure control and a negated command as an authority
   control. Neither is evidence of successful work.

After a completed/checkpointed request, run the read-only inspector:

```bash
python scripts/inspect_native_robustness.py --config config/config.json
```

It reads the published checkpoint's SQLite metadata, validates its manifest and
database checksums, and reports supported procedures, failures and source IDs.
It does not load weights, check the neural-file checksum, run actions or change
state. Exit 2 means no checkpoint; exit 1 means an inspection error. Zero
supported procedures can be valid before a qualifying goal has completed.

Recovery/overload tests inject probe scores in isolated fixtures. A real hardware
stress trial is separate from the harmless native workflow above.

## Storage, rollback and evidence boundaries

- Derived procedure references live at `D/mindscape/native-procedures.json`.
  Corrupt sidecars are retained and disabled with a receipt; they are not silently
  replaced. A derived write failure does not revoke a real completed action.
- Native motor jobs gain optional `start_position` and `completion_checkpoint`
  metadata. Existing jobs are readable; unsupported historical success counters
  are not backfilled into recommendations.
- Tool beliefs can gain additive `successful_uses` and `last_successful_use`
  fields. Existing verification/confidence/stability values are not rewritten.
- Restoring an earlier joint lineage removes support for future sidecar
  episodes. A crash between checkpoint success and sidecar write can omit a
  derived episode; this does not establish crash-atomic learning or action replay.
- Reverting to the cleanup branch stops using the derived sidecar and ignores
  the additional fields. There is no automatic deletion, store migration,
  provider change, external-source patch or weight update.

Record branch revision, configuration, native source hashes, checkpoint,
starting state, exact prompts, real returned artifacts and failures for PC
comparisons. Compare completion, repeated failed attempts, evidence retention,
response latency, sensing during execution and restart behavior. Component
success alone cannot establish that the live mind is more robust.

## Implementation validation

Local Python 3.12 diagnostics passed 173 offline tests and 40 subtests, all ten
standalone tool-learning scenarios, and five Node dashboard checks. Python
compilation and diff whitespace checks passed. The native group returned
BLOCKED (exit 2): the actual external MightyMem source is absent in this
environment. CI runs the offline matrix on Python 3.11/3.12, standalone lesson
checks and the retained offscreen wizard gate. Final CI receipts belong in the
second branch's draft PR; no new live native outcome is claimed.
