# Helix-AGI: careful cleanup and consolidation review

Review date: October 17, 2026
Repository: [munch2u-a11y/Helix-AGI](https://github.com/munch2u-a11y/Helix-AGI)
Reviewed revision: [a43492e68c0e7413eca71cd34814c15910cc314e](https://github.com/munch2u-a11y/Helix-AGI/commit/a43492e68c0e7413eca71cd34814c15910cc314e)

## Assessment

Helix would benefit from consolidation, but a large directory reshuffle would be a poor first change. The main risks are inconsistent configuration and path ownership, incomplete reproducibility of the native dependency, and a validation baseline that does not consistently cover the current composition.

There is an identifiable production architecture worth preserving: main.py constructs PulseLoop; Mindscape supplies serialized native state and motor execution; canonical Helix stores remain separate from their native projections; the foreground language route does not authorize body actions. The current documentation already distinguishes these responsibilities and marks historical and prototype work. Cleanup should reinforce those boundaries.

My recommendation is a series of small pull requests: establish trustworthy checks, make the dependency reproducible, consolidate configuration and paths, then extract demonstrably shared code. Defer retirement of alternate implementations until their consumers and behavior contracts are established.

This was a read-only repository evaluation. No source file, branch, tag, issue, pull request, repository setting, or remote history was changed. Checks ran in a fresh local checkout; no agent, model inference, channel delivery, installation script, or benchmark session was launched.

## What was inspected

The review covered the tracked-file inventory, Git history and branch state, current operator and architecture guides, launch/setup code, composition resolution, native/body/context boundaries, dashboard home paths, curated test runner, representative tests, exact duplicate files and function bodies, and the split between runtime, prototypes, experiments, and dated evidence.

This is a repository-maintenance assessment, not a complete behavioral certification or a line-by-line audit of every module.

| Inventory at the reviewed revision | Observed value |
|---|---:|
| Tracked files | 1,322 |
| Total tracked file bytes | 75,391,988, approximately 71.9 MiB |
| Python files, including frozen audit source | 628 |
| Python files outside documents/audits/ | 338 |
| test_*.py modules | 96: 88 in root tests, 7 in Over-Agent, 1 in the plugin |
| documents/audits/ | 853 files; 54,966,628 bytes, approximately 73% of tracked bytes |
| Python source snapshots under audits | 290 files |
| Over_Agent_Design/ | 58 files; 13,151,891 bytes |
| Exact duplicate-content groups, files larger than 100 bytes | 135 groups; 143 extra copies; 2,783,411 duplicate bytes |
| GitHub Actions runs returned | 0 |
| Open pull requests / open issues / releases returned | 0 / 0 / 0 |

Most exact file duplication is between live source and frozen audit snapshots. This is evidence retention, not proof of redundant live implementations. The duplicate byte total is only about 3.7% of tracked bytes; deleting “duplicate code” would not account for most repository size.

The feature/subconscious-overagent-bicameral branch is an ancestor of main: the local comparison reports main 19 commits ahead, feature branch 0 commits ahead. A v2.0.0 tag exists; there are no GitHub release objects in the returned list. No branch or tag should be removed as an automatic cleanup step.

## Architecture boundaries to preserve

| Area | Current role | Cleanup treatment |
|---|---|---|
| main.py, core/pulse_loop.py, core/mindscape.py | Production composition, cadence, native ownership, lifecycle | Preserve public entry points; extract internals incrementally |
| core/native_motor.py, core/mindscape_workspace.py | User-goal admission, native execution, observed returns and containment | Preserve authorization, order, hashes, receipts and checkpoint-before-completion rules |
| memory/, core/unified_retrieval.py, core/context_office.py | Canonical memory and distinct evidence/retrieval routes | Share interfaces where useful; preserve lane-specific meaning, ordering and provenance |
| MightyMem habitus_ai/context_loom dependency | Native neural/graph state and Loom implementation | Pin and verify the actual tested dependency source |
| llm/providers/ and composition=helix paths | Provider adapters and retained alternate composition | Keep explicit configuration and compatibility; do not fold into native dispatch |
| core/nursery/ | Separate developmental prototype | Label and test separately; do not make it a required startup stage |
| Over_Agent_Design/ | Separate design/prototype runtime | Preserve as a distinct prototype pending usage/consumer review |
| desktop_widget/ and dashboard/ | Current presentation and operator interfaces | Preserve widget as a presentation client of the dashboard |
| plugins/helix-agent-lab/ | Independently packaged evaluation tool | Retain its package boundary and explicit evaluation scope |
| documents/audits/ | Dated source, patches, failures and operational receipts | Treat as immutable historical evidence |

The 8D spatial/association paths, semantic retrieval, Context Office desks, native graph/cortex, and nine Loom lanes are not interchangeable duplicates. Consolidating their scores or reducing them to one retrieval implementation would be an architectural change requiring its own evaluation.

Likewise, private thought, outward speech, explicit body goals, actual action returns, and historical assistant statements must retain different roles. Cleanup must not make old model text into execution authority or verified evidence.

## Findings and recommended disposition

### 1. Validation currently cannot serve as a reliable cleanup gate — high priority

The curated runner lists 24 scripts and selects the first 18 for --quick. It does not include test_native_motor.py, test_agent_home.py, test_dual_rwkv_defaults.py, test_health_check.py, or test_pulse_context.py. The test guide explicitly documents native diagnostics separately, but a green “quick” run would still be insufficient evidence for a native runtime refactor.

There is no root pyproject.toml or pytest configuration, and no tracked GitHub Actions workflow was found. Tests mix unittest modules, standalone runners, pytest-style functions, simulators, and live/model experiments. Some root tests also use different dependency assumptions.

Concrete mismatch: tests/test_health_check.py imports Check, collect_checks, and exit_code; scripts/run_health_check.py exposes none of them. The test module fails to import.

The health script itself printed a dependency FAIL in this environment, then printed “HELIX IS READY TO LAUNCH” and exited with code 0. It also checks generic credentials and legacy data/projection paths rather than the full selected native composition. That makes it unsuitable as a machine gate.

Recommended action:

- Define explicit offline, dependency-integration, prototype, and live-product test groups.
- Make the offline group discover all applicable maintained tests; ensure additions are included or explicitly classified.
- Repair health reporting and its documented/tested API; required failures must produce a nonzero status.
- Check the selected configuration, native source, models, embedding service, and sandbox requirements in a separate native preflight.
- Classify missing prerequisites as blocked, with the actual failed prerequisite.
- Preserve existing failures in a baseline ledger. Do not relax behavior assertions merely to make cleanup appear green.

### 2. Native dependency reproducibility is incomplete — high priority

The launch guide openly records that the tested MightyMem checkout includes local gestation-seed and cancellation changes, and that a clean Helix checkout alone does not supply them. The operational audit preserves a native-dependency.patch and source hashes, which are valuable.

However, setup still relies on selecting a compatible external directory rather than a single reproducible tested dependency installation. Most Python dependencies are lower bounds; only Transformers is exactly pinned in requirements-mindscape.txt. That file includes the broad requirements.txt, so optional GUI, audio, cloud and local inference packages remain coupled in the installation.

Recommended action:

- Record an exact tested MightyMem revision plus every required patch and resulting file hash, or publish a dependency commit containing those changes.
- Retain patch provenance: the operational record says its patch includes pre-existing edits.
- Add a read-only compatibility probe for the exact interfaces Helix uses, not just file presence.
- Produce a tested Linux/CPU dependency lock or constraints file with documented Python/platform scope.
- Split optional dependency groups only after removing eager imports that make them mandatory.
- Keep the original install route during transition.

Do not quietly import frozen audit source to make missing native tests pass. That would test a different composition.

### 3. Dependency/model selection has multiple owners — high priority

core/mindscape_config.py already resolves MIGHTYMEM_PATH, RWKV_MODEL_PATH, configured paths, and explicit source activation. main.py separately contains RWKV path fallback logic.

More seriously, core/bicameral_rwkv.py previously prepended a literal MightyMem host path to sys.path before importing habitus_ai.rwkv7_language. That competes with the declared activation path. Depending on import order and whether that directory exists, it can influence which dependency package is selected; this review did not reproduce a wrong-source import on the original host.

tests/test_path_agnosticism.py passed here, but its scan excludes both core/mindscape_config.py and core/bicameral_rwkv.py. Its success therefore does not substantiate the broader “all paths” message.

Recommended action:

- Make one resolved composition object authoritative for dependency and checkpoint paths.
- Remove competing import-path mutation after adding source-identity checks.
- Pass the selected backend or source contract explicitly where practical.
- Exercise custom dependency paths and poisoned alternative import locations in an isolated subprocess.
- Extend path checks to active runtime files, with documented exceptions for historical evidence.

### 4. Agent creation and home-path resolution diverge — high priority

The GUI calls provision_creation; setup.py does not. The launch guide explicitly documents the resulting missing creation.json on the CLI path and provides a manual provisioning workaround. This is a concrete consolidation opportunity around an existing helper.

Dashboard upload staging uses the configured mindscape.home, while room/module code still uses DATA_DIR/agent_home. Its room lookup also probes older paths. Current joint checkpoints are selected through LATEST.json and generation directories; the legacy room probe looks for joint/mind.sqlite. The native body API is separate, so this does not prove the body itself uses the wrong room. It does show that different dashboard surfaces can describe or modify different homes.

Recommended action:

- Resolve one selected agent's home, state directory, creation manifest, and latest checkpoint.
- Reuse that read-only resolution in dashboard views and APIs.
- Route CLI and wizard provisioning through the same identity-preserving service.
- Support old configurations through an explicit migration/compatibility path.
- Never choose an agent by the first glob result.
- Do not move an existing home or regenerate an identity as a side effect of resolving paths.

### 5. Composition settings and environment precedence need one policy — medium/high priority

resolve() forces task_cognition_mode=off for native Mindscape. TaskCognitionController subsequently gives HELIX_TASK_COGNITION precedence over the passed mode. With RWKV, an active request is downgraded to observe, rather than permitted to execute as an active tool-capable focus controller. Thus this is a conflicting-mode/configuration problem, not evidence that this environment produces unauthorized native motor execution.

The current architecture guide already warns operators about the override.

Recommended action: resolve precedence once, publish the effective composition, and reject incompatible native-mode overrides before controllers or stores are created. Retain the documented override behavior for supported legacy configurations until explicitly migrated.

### 6. There are real shared-code candidates — lower initial risk

AST comparison found identical function bodies outside audit snapshots:

| Candidate | Evidence | Proposed treatment |
|---|---|---|
| comms/*_bot.py and webhook_channel.py | Same _chunk_message body across five channel classes | Shared pure chunking helper; retain channel defaults and wrapper methods |
| brain/sensory_cortex.py and vision_cortex.py | Shared camera discovery, model readiness, PTZ, context/journal routines | Extract narrow camera/journal support; keep both lifecycle/role classes |
| desktop_widget/overlay.py and Over_Agent_Design/desktop_overlay.py | Shared geometry and several bridge/window methods | Extract pure geometry first only if prototype remains maintained |
| core/batch_service.py and belief_detector.py | Same _read_pending / _write_pending bodies | Consider one queue-storage owner after checking locking and retry semantics |
| wizard/models_tab.py and pages/credentials.py | Same credential loading routine | Shared credential reader; preserve precedence and secret handling |
| main.py and mindscape_config.py | Repeated RWKV discovery policy | One model/path resolution contract |
| Several providers | Some matching history/parameter/format helpers | Extract only demonstrably provider-neutral behavior after contract tests |

Identical code is a candidate, not an automatic instruction to introduce a shared base class. Camera ownership, provider histories, cancellation and transport-specific behavior can differ even when selected methods match.

The current channel chunker stops after five chunks. A behavior-preserving extraction must retain that behavior initially; deciding how to handle longer messages is a separate functional change.

### 7. Large classes have useful extraction seams — medium/high refactor risk

| File | Lines | Suggested first seam |
|---|---:|---|
| core/preconscious.py | 2,820 | Candidate selection/rendering adapters with typed contributions; preserve lane policies |
| core/pulse_loop.py | 2,496 | Recipient/delivery snapshot handling or context preparation, one seam at a time |
| tools/tool_executor.py | 2,425 | Domain handler registration behind the current executor facade |
| core/cognitive_space.py | 1,801 | Separate persistence/configuration helpers from mathematical behavior only after targeted review |
| memory/belief_store.py | 1,413 | Preserve schema/IDs; review store boundaries before extraction |
| main.py | 833 | setup_helix, lines 185–655, mixes construction and runtime services |
| core/mindscape.py | 950 | Preserve single native owner and checkpoint sequencing during any extraction |

File length is a maintenance signal, not evidence that behavior should be removed. A giant rename-only PR would obscure import, resource-path, receipt and persistence regressions.

### 8. Audit and prototype material should be made easier to navigate — low behavior risk if retained

The current documentation index already identifies historical material. Strengthen it with a concise “current / alternate / prototype / frozen evidence” ownership map and explicit test commands.

Keep dated audit folders byte-for-byte unchanged in the initial cleanup. Some preserve failed attempts, dependency changes and uncommitted source that cannot be reconstructed by pointing at a clean Git commit.

If size later warrants archive relocation, require a complete file manifest, hashes, durable artifact location, verified retrieval, preserved licensing and working links before removing working-tree copies. Do not rewrite Git history. Moving files in a new commit would not shrink existing Git history anyway.

## Verification performed in this review

| Check | Result and interpretation |
|---|---|
| Parse every tracked Python file with ast.parse | 628 parsed; no syntax errors. Includes frozen snapshots, not only live source. |
| bash -n for every tracked shell file | 26 passed syntax validation; scripts were not executed. |
| Sampled unittest command below | 47 reported items: 33 passed, 5 failures, 8 errors, 1 skipped. One error is a failed-module loader item. |
| Native motor and home modules | Both failed import because habitus_ai is absent; native cases did not execute. |
| Standalone path-agnosticism check | Passed, with the scan-coverage limitation above. |
| Health script | Printed missing dependency FAIL and readiness message; process status 0. |
| Git status after checks | Clean tracked working tree. |

Sampled command:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_dual_rwkv_defaults \
  tests.test_fresh_clone_cognizance \
  tests.test_health_check \
  tests.test_pulse_context \
  tests.test_context_focus \
  tests.test_memory_record_envelope
```

Failure classification:

- Four assertion failures concern section-title wording/punctuation in PulseContext rendering.
- A fifth expects “not external evidence” inside a recalled thought's text. Current code retains that evidence in the typed contribution, but ordinary text rendering omits the explicit phrase. Decide and test the intended model-visible provenance contract before calling this merely an outdated test.
- One import error is the missing health-check API.
- One setup case requires the absent external MightyMem source.
- Six errors come from importing Preconscious/PulseLoop through an eager torch import in LocalSummarizer.
- One case was skipped by its own prerequisite logic.

The environment has Python 3.12.14, NumPy, SciPy, PyYAML and packaging, but lacks the native source, Torch/Transformers, Flask and several declared dependencies. I did not install the full stack or download model weights. No live-product claim follows from these checks.

The repository's preserved October 17 record reports 72 focused checks and a real body workflow. Those are historical receipts, not checks rerun during this review, and not general recall/coherence/development scores.

## Proposed pull-request sequence

Each item is a separately reviewable change. Rebase the plan against the latest main before implementation; this report is pinned to a43492e.

| Order | Scope | Acceptance gate | Rollback |
|---|---|---|---|
| 0 | Record the baseline, dependency receipts, effective configuration and known failures; produce an ownership/test-group manifest | Every maintained route has an owner and an explicit test/blocked status; audit hashes recorded | Documentation/manifest revert only |
| 1 | Repair health-check contract and exit codes; classify and wire offline/native/prototype/live test groups; add CI for genuinely offline checks | Required failures cannot report ready; new tests cannot silently fall outside the gate; existing failures classified, not hidden | Revert validation-only PR |
| 2 | Pin/reconstruct the tested MightyMem dependency and provide scoped Python constraints; add compatibility preflight | Clean environment can reproduce the selected source and required API capabilities, or fails before creating state | Previous dependency lock and explicit source path |
| 3 | Consolidate resolved composition/model paths and environment precedence | Custom paths work, wrong-source imports are rejected, native settings remain native, legacy profiles still load | Previous resolver plus unchanged saved configuration |
| 4 | Share creation/provisioning and home/checkpoint path resolution across CLI, wizard and dashboard | New identities get matching manifests; existing identities unchanged; dashboard upload/body/room/module paths agree; latest checkpoint selected correctly | Revert service changes; no automatic data move |
| 5 | Extract pure channel chunking and credential-reader helpers in separate small PRs | Exact transport defaults, outputs and precedence preserved; no live delivery | Revert helper and wrappers |
| 6 | Extract camera/journal or pending-queue support, one concern per PR | Mocked hardware/provider checks and persistence/concurrency contracts pass; no duplicated resource ownership | Revert extraction without changing stored formats |
| 7 | Split executor registration, startup construction, then context/delivery internals, one seam per PR | Same public imports, tool schemas, state/receipt shapes, lifecycle and selected behavior; native smoke for native-touching changes | Revert each extraction independently |
| 8 | Improve docs/evidence navigation; evaluate prototype retirement or archive relocation separately | References and hashes verified; consumers accounted for; compatibility decision recorded | Restore original paths/links |
| 9 | Consider root packaging/namespace migration only if still useful | Installation, assets, entry points, dynamic imports, plugin package and all supported profiles validated | Compatibility shims and prior installation route |

Proposed new shared modules, if implemented, should have specific ownership such as runtime_paths, resolved composition, message_chunks, or camera support. Avoid a general-purpose utils module and avoid forcing every provider or action path into one base class.

A root packaging change needs particular care: setup.py is currently an interactive application setup script, not conventional package metadata. Do not add a build configuration that accidentally invokes it as an installer.

## Required preservation and rollback gates

Before changes that could touch persistent state, take a consistent backup of the selected home, canonical journal/beliefs/indexes, creation manifest and native joint checkpoint lineage. Use a stopped process or a supported snapshot/SQLite backup mechanism; copying a live database file alone is not sufficient. Keep a manifest of hashes and restore instructions. Protect credentials separately and never commit them.

Refactors should preserve stored schemas. If a schema migration is genuinely required, make it a distinct change with a version, dry run, idempotency and tested restore path. Do not “clean” learned memory, graph records, recurrent state, unfinished goals, identity or historical audit outputs.

For native-touching changes, use an isolated disposable agent and verify:

1. Existing identity, archetype, home position and canonical records survive restart.
2. Move, sense, open and sandboxed run produce matching real returns.
3. Case-sensitive/quoted paths, multiple targets and bound pronouns retain their current contract.
4. Negated/ambiguous requests and file/retrieval text do not become authorized user goals.
5. Changed script hashes, wrong-target returns and checkpoint failures cannot produce completed goals.
6. Sensing continues while foreground/workshop work occupies other paths; native state writes retain one owner.
7. Private thought remains private, recipient snapshots remain tied to the originating generation, and delayed replies retain the intended route.
8. Complete context admission, provenance, tokenizer accounting and all configured retrieval lanes remain intact.
9. Graceful cancellation/restart and the documented interrupted-goal behavior remain intact.
10. No new cloud fallback or optional channel activation occurs.

These are operational invariants, not requests to assert exact output prose. Run live checks only in the intended environment with the actual selected dependency/model and record their composition. Keep structural cleanup separate from attempts to improve model quality or autonomy.

## Recommended first implementation scope

Start with orders 0–1: a reliable baseline and truthful health/test entry points. Then orders 2–4 address the highest-value consolidation: the dependency source, selected composition, identity provisioning, and paths.

The first cleanup PR should not delete prototypes, relocate audits, change memory math, alter model defaults, merge retrieval lanes, rewrite the action controller, or migrate existing agent data. Those changes have different evidence requirements and should be reviewed independently.

## Primary source references

All links below are pinned to the reviewed revision.

- [Current architecture](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/documents/architecture_current.md)
- [Launch/dependency and CLI provisioning guide](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/documents/mindscape_launch.md)
- [Test guide](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/tests/TEST_SUITE_README.md)
- [Curated runner](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/tests/run_all_tests.py)
- [Health checker](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/scripts/run_health_check.py) and [its tests](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/tests/test_health_check.py)
- [Composition resolution](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/core/mindscape_config.py) and [bicameral import bootstrap](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/core/bicameral_rwkv.py)
- [Dashboard path handling](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/dashboard/dashboard.py)
- [CLI setup](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/setup.py), [creation service](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/core/agent_creation.py), and [wizard](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/wizard/app.py)
- [Context rendering/provenance](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/core/pulse_context.py)
- [Task controller precedence](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/core/task_cognition/controller.py)
- [Recorded native workflow and dependency-patch provenance](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/documents/audits/2026-10-17-native-body-operational/README.md)
- [Over-Agent scope](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/Over_Agent_Design/README.md)
- [Plugin package and evaluation boundary](https://github.com/munch2u-a11y/Helix-AGI/blob/a43492e68c0e7413eca71cd34814c15910cc314e/plugins/helix-agent-lab/README.md)
