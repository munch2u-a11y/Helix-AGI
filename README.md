# Helix AGI

**A local Dual RWKV agent with continuous senses, a working digital body,
private thought and direct speech.**

Helix runs an ongoing loop of sensing, thinking, acting and communicating.
Its environment is a filesystem home: it can notice its surroundings, move
between rooms, open files and run Python experiments in an isolated workshop.
Private thought and outward speech have separate routes, so speaking requires
ordinary language rather than a generated `SPEAK` command or tool call.

## The sensing, action and speech engine

- **Sense the environment.** A background sensor observes the current room's
  files and folders, including names, types, sizes and changes. These text
  observations feed the persistent mind and current context.
- **Act through a digital body.** Move, inspect, open and run requests become
  numeric motor signals. The body executes the action and returns actual
  contents, output and errors to the agent.
- **Think privately, then speak directly.** A pulse can stay private or contain
  private contemplation followed by ordinary speech. Internal communication
  state and recipient routing control delivery; the model needs no action
  JSON or `[SPEAK: ...]` output.
- **Keep sensing during other work.** Filesystem observations continue during
  language generation and workshop execution. The native mind processes queued
  observations when its worker becomes available.
- **Keep a persistent home and identity.** Named rooms, personal files, memory
  and completed actions survive graceful shutdown and restart.

The native body can also select exploratory actions without a user request.
Its own clock admits the production context, advances the native mind and
returns verified observations while the language stream remains unfinished.
An [Ada trial](documents/audits/2026-10-20-autonomous-stream/verification.json)
verified an unprompted file open, learning and foreground use of the updated
weights. Target selection still uses a bootstrap adapter; coherent spontaneous
speech and general independent task competence remain unverified.

[How sensing, action and speech fit together →](documents/sensing-action-speech.md)

## TL;DR: start the selected Dual RWKV agent

For an existing configured agent, run these in separate terminals:

```bash
venv/bin/python main.py
venv/bin/python dashboard/dashboard.py --port 5050
```

Open `http://127.0.0.1:5050`. In Chat, expand **Environment and actions** to
see file contents, script output and body status alongside conversation.

For a new installation, use Python 3.11+, Linux with Bubblewrap/user namespaces,
Ollama, a compatible MightyMem source checkout and the pinned RWKV checkpoint.
The current native bridge runs on CPU.

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements-mindscape.txt
ollama pull qwen3-embedding:0.6b
./install.sh
```

Keep Ollama running. The graphical wizard guides the agent's name, archetype,
memory seed, model, main communication channel and home. Dashboard needs no
channel token. For dependency paths, command-line creation and initialization
checks, follow the [launch guide](documents/mindscape_launch.md).

## Try the body

Place a note in the named home's staging folder through Dashboard upload, or
put a Python experiment in its `workshop/`, then send a request:

```text
Please sense .
Please go to /thinking then go to /workshop.
Please open /staging/Notes.txt.
Please go to /workshop then open Example.py then run it.
```

Paths retain case; quote filenames containing spaces. `it` refers to the
explicitly opened file earlier in that request. A staged upload stays in
staging until moved into the workshop for execution.

The workshop activates its sandbox automatically. Python can write workshop
artifacts while the host source, other rooms and mind stores stay outside the
sandbox. The body checks the observed script hash before execution and returns
stdout, stderr and exit status.

## From thought to speech

The language stream can keep contemplation private, carry it into the next
pulse, and produce a plain-language reply when the communication route opens.
A thought-only pulse preserves the unfinished interaction. Delivery uses its
known recipient and channel; there is no separate model-generated “speak now”
command.

Body control runs separately. Talking about opening or running a file does
not execute it: actual movement and file operations use the motor route and
return observations that the agent can use in its response.

## The agent's home

Creation uses the name entered by the user:

```text
data/homes/<Agent Name>/
  thinking/          quiet room
  modules/           installed operational interfaces
  bedroom/closet/    personal files
  workshop/          isolated Python experiments and artifacts
  staging/           uploaded files
  intakes/           surroundings observations

data/agents/<Agent Name>/
  creation.json      identity and archetype
  beliefs/           belief stores
  memory/            journal
  spatial/           memory indexes and spatial state
  mindscape/         persistent native mind and action history
```

Archetypes seed initial preferences; starter memory depth and voice wording are
separate choices. See [agent homes](documents/agent-home.md) for room and module
behavior.

## Current support and evidence

A [live CPU run](documents/audits/2026-10-17-native-body-operational/README.md)
verified movement, real file opening, sandboxed Python execution, result
read-back and graceful restart. A separate live control verified sensing
during script execution. Thought/speech separation and delivery routing are
implemented and covered by focused checks; that body run was not a
conversation-quality benchmark.

The Chat motor route currently supports move, sense, open and run. Module/web
activation and file creation have separate handler interfaces; the optional
nursery remains a [prototype](documents/nursery_status.md).
Use **Environment and actions** for current body state. Dashboard room/module
views and staging use the selected agent home.

## Documentation

| Guide | Purpose |
|---|---|
| [Sensing, action and speech](documents/sensing-action-speech.md) | How the engine works and what to try |
| [Setup and launch](documents/mindscape_launch.md) | Dependencies, guided creation, CLI provisioning and startup |
| [System manual](SYSTEM_MANUAL.md) | Operation, configuration, health and persistence |
| [Agent home](documents/agent-home.md) | Rooms, modules, sensing and workshop containment |
| [Current architecture](documents/architecture_current.md) | Runtime ownership, memory and model connections |
| [Action paths](documents/action_path.md) | Motor signals, authorization and completion |
| [Documentation index](documents/README.md) | Developer references, status and historical records |

Model identities, retrieval lanes, configuration budgets and full receipts are
in the [architecture](documents/architecture_current.md),
[model guide](models/README.md) and
[operational record](documents/audits/2026-10-17-native-body-operational/README.md).
The verified setup includes changes in the configured MightyMem dependency;
the [launch guide](documents/mindscape_launch.md#dependencies) identifies them.

## Contributing and license

Runtime changes should update the relevant guide and include evidence for
behavioral claims. See the [test guide](tests/TEST_SUITE_README.md).

Helix-AGI is licensed under the [Apache License 2.0](LICENSE). Versions
published before the Apache 2.0 transition retain their original AGPL-3.0 terms.
