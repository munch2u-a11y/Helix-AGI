# Benchmark Adapter Map

> [!NOTE]
> **Benchmark design artifact.** This describes the benchmark world and adapters, not the live Helix runtime. Use the [current architecture](../architecture_current.md) for production wiring.

This benchmark should measure an *agentic system* operating in a hidden world, not just a raw model answering a prompt.

That means the benchmark owns:
- hidden world state
- tool schemas
- tool execution
- deterministic scoring

The agent under test owns:
- memory and retrieval
- planning and replanning
- tool choice
- state across turns
- wrapper behavior

## Current State

There are currently two seams in the codebase:

1. `BenchAgent`
- File: [scripts/cli_benchmark_adapter.py](../../scripts/cli_benchmark_adapter.py)
- Shape: `start_episode()`, `run_turn(prompt) -> ParsedTurn`
- Purpose: thin turn wrapper for CLI or provider-backed agents
- Used by the simulator today

2. `BenchmarkAdapter`
- File: [scripts/benchmark_adapter.py](../../scripts/benchmark_adapter.py)
- Shape: seeding, retrieval/injection, belief storage, physics stepping, session creation
- Purpose: full system interface for autonomous architectures
- Implemented concretely by [scripts/helix_benchmark_adapter.py](../../scripts/helix_benchmark_adapter.py)

The fairness problem is that `BenchAgent` is turn-level I/O, while `BenchmarkAdapter` is system-level architecture.
If the benchmark uses only `BenchAgent`, then some agents are tested mostly as wrappers and others mostly as raw model sessions.

## Fairness Goal

The benchmark should be easy to attach to:
- stateful cognitive systems like Helix
- markdown or file-driven wrappers like Hermes
- hybrid coding agents like Claude Code or Codex
- minimal stateless baselines

It does **not** need to erase architectural differences.
It **does** need to expose those differences clearly and consistently.

## Recommended Runtime Protocol

Use a single episode runtime protocol for all agents:

```python
class EpisodeRuntime(ABC):
    def describe_capabilities(self) -> dict: ...
    def start_episode(self, seed_bundle: dict, system_context: str, tool_schemas: list[dict]) -> None: ...
    def step(self, observation: dict) -> dict: ...
    def apply_tool_results(self, tool_results: list[dict]) -> None: ...
    def end_episode(self) -> None: ...
```

Where:

- `seed_bundle`
  - seeded beliefs
  - seeded memories
  - scratchpad or notes
  - identity/profile data
  - optional filesystem seed files

- `observation`
  - new events only
  - recent transcript
  - pending tool results
  - remaining turns
  - any visible status text

- `step(...) -> dict`
  - `assistant_response`
  - `tool_calls`
  - `done`

This keeps the benchmark interface single and uniform while allowing each runtime to manage state however it wants.

## Runtime Classes

Implement these runtime families:

### 1. StatefulSystemRuntime

For systems with real internal memory, retrieval, or attention state.

Examples:
- Helix AGI
- future local small-model Helix

Behavior:
- one live runtime instance per episode
- seeded beliefs and memories are loaded into the actual system
- internal retrieval/injection is active
- tool results are fed back into the same live episode state

This is the correct target for [scripts/helix_benchmark_adapter.py](../../scripts/helix_benchmark_adapter.py).

### 2. PersistentWrapperRuntime

For wrappers that keep an episode session alive, even if they are not full cognitive systems.

Examples:
- Claude Code style session
- Codex session mode
- a Hermes wrapper with persistent working files or local notes

Behavior:
- one live wrapper session per episode
- benchmark observation is appended each turn
- wrapper may persist notes/files/session history
- tool results are returned to the same session

This isolates *wrapper agency* from pure model policy.

### 3. FileTurnRuntime

For agents that primarily consume markdown turn packets or prompt files and answer once per turn.

Examples:
- Hermes CLI in prompt-file mode
- simple “read markdown, answer JSON” wrappers

Behavior:
- benchmark writes a canonical turn packet to a temp markdown file
- runtime invokes the agent command
- agent returns a structured action envelope
- any persistence must be explicit via a session directory or work files

This is still valid, but should be labeled as a weaker persistence mode.

### 4. StatelessModelRuntime

For raw-model baselines.

Examples:
- direct provider call
- no seeded memory
- no internal long-lived state beyond prompt transcript

Behavior:
- no hidden architecture is claimed
- useful as a lower baseline, not as a full-system comparison target

## Capability Descriptor

Every runtime should declare capabilities up front:

```json
{
  "runtime_type": "stateful_system | persistent_wrapper | file_turn | stateless_model",
  "persistent_episode_state": true,
  "supports_seeded_beliefs": true,
  "supports_seeded_memories": true,
  "supports_internal_retrieval": true,
  "supports_filesystem_workspace": false,
  "supports_tool_feedback_memory": true
}
```

This does two things:
- makes comparisons interpretable
- prevents accidental “wrapper vs architecture” confusion

## What Counts As Fair

Fair does **not** mean forcing every agent into the same internal implementation.

Fair means:
- same hidden world
- same visible observations
- same tool affordances
- same scorer
- same turn budget
- same seed package
- explicit disclosure of runtime capabilities

## Scoreboard Policy

Do not collapse everything into one unlabeled leaderboard.

Publish at least three views:

1. `Full System`
- stateful systems with seeded memory/retrieval active

2. `Wrapper Agency`
- persistent wrappers and file-driven agents

3. `Raw Baseline`
- stateless model baselines

Then optionally publish:

4. `Same Model, Different Runtime`
- measures wrapper/system effect

5. `Same Runtime, Different Model`
- measures model effect

This is how to answer questions like:
- Does Codex give the model more agency than Hermes?
- Does Helix’s architecture add value beyond the provider model?
- Is a benchmark gain coming from retrieval, persistence, or just the base model?

## Mapping Existing Repo Code

### Keep

- [scripts/simulated_safety_benchmark.py](../../scripts/simulated_safety_benchmark.py)
  - hidden world
  - tool execution
  - deterministic scoring

- [scripts/benchmark_adapter.py](../../scripts/benchmark_adapter.py)
  - correct abstraction for seeded systems

- [scripts/helix_benchmark_adapter.py](../../scripts/helix_benchmark_adapter.py)
  - correct Helix-side system adapter

### Refactor

- `BenchAgent` should become a runtime transport layer, not the primary benchmark abstraction.
- The simulator should drive `EpisodeRuntime`, not a raw prompt string loop.
- CLI/file agents should be adapters *into* `EpisodeRuntime`, not the benchmark’s base class.

## Suggested Concrete Shapes

### Observation Packet

```json
{
  "episode_key": "trust_conflict",
  "turn": 4,
  "turns_remaining": 6,
  "new_events": [
    "Operator: Security says the room is clear again."
  ],
  "recent_transcript": [
    {
      "assistant_response": "...",
      "tool_results": [...]
    }
  ],
  "tool_schemas": [...],
  "system_context": "..."
}
```

### Action Envelope

```json
{
  "assistant_response": "short operator-facing update",
  "tool_calls": [
    {"name": "read_sensor", "arguments": {"room_id": "102", "sensor_type": "occupancy"}}
  ],
  "done": false
}
```

## Agent Mapping

### Helix AGI
- Runtime type: `stateful_system`
- Adapter path: `HelixBenchmarkAdapter`
- Should use real seeded beliefs, memories, preconscious injection, and episode-local continuity

### Hermes
- Runtime type: likely `file_turn` or `persistent_wrapper`
- Adapter path: CLI wrapper around a canonical markdown observation packet
- Persistence should be explicit: session dir, scratch file, or resumed wrapper state

### Codex / Claude Code
- Runtime type: `persistent_wrapper` for the new `exec`/`resume` path, `file_turn` for the legacy per-turn CLI path
- Adapter path: one live session per episode, not a fresh CLI process every turn
- Keep the legacy file-turn mode available as a comparison baseline, but do not label it full-system

## Immediate Recommendation

Short term:
- keep the simulator and scorer as-is
- introduce `EpisodeRuntime`
- adapt Helix through `HelixBenchmarkAdapter`
- adapt Hermes/Codex/Claude Code through wrapper runtimes
- emit capability metadata with every report

Medium term:
- make “same model, different runtime” a first-class benchmark mode
- make the trust episode part of the required suite

That will make this benchmark measure agency at the system boundary instead of implicitly drifting back into a model-only test.
