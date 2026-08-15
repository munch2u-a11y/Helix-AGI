# Helix Action Path Contract

**Status:** current executable contract · **Verified:** 2026-08-15

Helix keeps its main consciousness small and provider-neutral. It does not load
the complete workflow or all tool schemas into the main context. The main
thread sees identity, current events, bounded memory, compact affect, and broad
ability descriptions. Work crosses into a separate task branch only after an
intention or user request is concrete enough to route.

```text
main consciousness (no schemas)
  -> ask one exact question, or create a durable task
  -> Codex active route: learned orchestrator + scoped focus worker
     OR local route: at most four planned outcome/evidence legs
  -> ToolExecutor: central safety and host boundary
  -> typed receipts: attempted/confirmed/error/evidence metadata
  -> verifier: read-back or observation for state changes
  -> compact result event to main consciousness
  -> procedural memory: recommend verified routes; warn on failed routes
```

## Completion and recovery

A model's prose cannot prove that an action happened. Communication is complete
only after an authoritative delivery receipt. File writes require a matching
read-back. Browser and desktop mutations require a later observation or
screenshot. Git and terminal mutations require a relevant observer step. A
failed attempt remains visible even if an unrelated read succeeds; a later
confirmed retry can recover it.

When a material input is missing, the worker emits `NEED_INPUT:` followed by
one question. Helix moves the same durable task to `WAITING_INPUT`; the answer
resumes it. When an upstream leg is unverified, dependent downstream work does
not run.

Direct requests do not depend on the model happening to say “I will.” If no
natural first-person commitment is voiced, a deterministic fallback creates an
explicitly authorized action task from an action request, or a reply-only task
from ordinary conversation. A clarification answer is consumed by the waiting
task before this fallback runs, preventing a duplicate response task.

## Context budgets

The deterministic local-orchestrated path enforces these default ceilings:

| Frame | Ceiling |
|---|---:|
| Planner task text | 300 tokens |
| Planner lessons | 150 tokens |
| Planner scoped context | 400 tokens |
| Action-plan legs | 4 |
| Prior-leg reports visible to a worker | 900 tokens |
| Each tool observation | 600 tokens |
| Final worker report | 800 tokens |

The Codex active-task path uses a durable task plus learned situational
orchestrator, adaptive focus depth, and reverse capability selection rather
than the local line planner. It is even stricter in the main thread: no tool
catalog is supplied. Each focus thread receives only the capability subset
selected for that task. Identity text is conditional there; affect appears
only for response or identity-dependent work.

## General computer interface

The browser surface returns the current title, URL, text, and short interactive
element references such as `[e1]`. A later call can click, type, select, submit,
scroll, press a key, or play referenced media, then `browse_observe` refreshes
the page and verifies state. The desktop surface can open allowlisted HTTP(S)
URLs in the visible default browser, observe that window, toggle playback, and
observe or screenshot again. This verifies the visible interaction route; it
does not claim audible playback unless a future media-status receipt confirms it.
Email, API, filesystem, program, terminal, and git work use the same receipt
boundary rather than separate model-specific success conventions.

## Codex App Server boundary

`codex_cli` starts one persistent App Server process and ephemeral thread for
main consciousness. The thread uses an empty read-only workspace; approval is
disabled and built-in Codex filesystem, shell, web, delegation, and MCP actions
are non-authoritative. Host actions are declared and validated by Helix. In
active mode the main Codex thread is thought-only, while focus sessions receive
scoped host schemas.

Helix owns the durable self contract. Codex is named as a replaceable reasoning
substrate rather than the agent's identity. The existing 8D Plutchik field is
rendered as a sub-12-word felt-orientation capsule after a field sample exists.
It may shape tone and attention, never facts, permissions, or verification.

Use either setup path:

```bash
codex login
python setup.py --non-interactive --subscription-cli codex_cli
python main.py
```

Or choose `codex_cli` and keep **Helix agent mode** checked in the graphical
Models tab. Detection performs the actual App Server initialize/thread
handshake.

## Reproducible validation

```bash
venv/bin/python tests/run_action_path_exam.py
venv/bin/python tests/run_action_path_local_smoke.py --model granite4.1:8b --json
venv/bin/python tests/run_codex_helix_smoke.py --json
```

The deterministic exam covers clarification, gather-then-email, program
write/read-back, visible browser/media routing, delivery recovery, false
completion rejection, and learning from verified versus failed routes. The
2026-08-15 run passed 7/7. The media case includes an explicit playback toggle
plus later observation; the measured maxima are 190 planner tokens, 306
initial-worker tokens, and 114 evidence tokens. The live Granite 4.1 8B
virtual-world smoke passed 3/3 in 60.46 seconds using 3,022 measured model input
tokens. The Codex smoke creates a real read-only App Server thread and tests two
turns of identity and transient continuity; it reports transport readiness and
quota/provider inference failures separately.

These are action-path integration results, not a claim that Helix is generally
more capable than Codex, ChatGPT, or Claude Code. That comparison requires a
shared end-to-end computer-task exam under matched permissions and budgets.
