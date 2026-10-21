# Mindscape setup and launch

**Source review: 2026-10-17 · Current native route: `main.py → setup_helix →
PulseLoop`, with independent receptive, sensory and motor loops.**

Start the continuous sensing, action and speech engine through the normal
Helix entry point. The default Mindscape configuration combines a persistent
RWKV/Habitus mind with a local RWKV language stream. The body follows explicit
user goals through numeric motor signals; thought can remain private and
outward speech is ordinary prose.

See [sensing, action and speech](sensing-action-speech.md) for what to try, or
[architecture](architecture_current.md) for implementation wiring.

## Dependencies

- Python 3.11+ and the checkout's `venv`.
- Linux with Bubblewrap (`bwrap`) and permitted user/network/process namespaces
  for workshop execution. There is no unsandboxed fallback.
- A compatible, explicitly selected MightyMem source containing both
  `habitus_ai` and `context_loom`.
- The pinned `RWKV/RWKV7-G1j-1.5B-20260831` checkpoint directory, including
  its index and all four safetensors shards. The verified revision is
  `2c18b29ab7fbece25ff6112281eea0fa41fcb30f`.
- Running Ollama with `qwen3-embedding:0.6b` for Helix's 1024D semantic lane.

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements-mindscape.txt
ollama pull qwen3-embedding:0.6b
```

`requirements-mindscape.txt` pins Transformers 5.17.0; the checkpoint requires
its cache API. The joint bridge is CPU-only. It uses the configured MightyMem
source, not a replacement `context_loom` package from pip. Paths can be supplied
through setup or defaults discovered using `MIGHTYMEM_PATH` and
`RWKV_MODEL_PATH`.

The October 17 run verified with an external `MightyMem` directory (configured via `MIGHTYMEM_PATH`), including local gestation-seed
support and cooperative cancellation changes in `habitus_ai/continual_rwkv.py`.
Its dependency patch and source hashes are in the
[operational audit](audits/2026-10-17-native-body-operational/README.md).
A clean Helix checkout alone does not supply those external source changes.
Verify a reconstructed dependency against the exact recorded file hashes with:

```bash
python scripts/verify_native_dependency.py --package-path /absolute/path/to/MightyMem
```

This read-only comparison includes recorded dirty-source bytes. It does not
apply the patch, load weights, or certify a newer dependency. A mismatch returns
nonzero; preserve pre-existing dependency edits and use a separate checkout when
reconstructing the recorded revision. No new fully locked native environment is
claimed by this cleanup.


## Guided creation

Run `./install.sh` for the PyQt6 wizard. The launcher installs a lighter UI
profile first; the wizard installs the chosen composition before bootstrap.
Select native Mindscape for RWKV/Ollama, or Helix for the separate hosted/CLI
provider composition. See [dependency profiles](maintenance/DEPENDENCIES.md)
for installation scope and limits.

For Mindscape, choose an agent name, creator,
archetype, starter memory depth/voice, local RWKV model and MightyMem paths,
primary communication channel, credentials, tools and schedule.

The wizard provisions:

- `data/homes/<Agent Name>/`: rooms, built-in module descriptors and identity.
- `data/agents/<Agent Name>/`: creation manifest and canonical memory directories.
- `config/config.json`: selected runtime and paths.
- `~/.config/helix/credentials.env`: private channel/provider credentials.

Dashboard needs no channel token. External channels must be enabled and supplied
with their own credentials. Archetypes seed native preferences; they do not
train model weights or certify competence. The nursery prototype is not offered
as an integrated startup stage.

## Command-line creation

The explicit Mindscape CLI route uses the same identity provisioning service as
the wizard. It validates the selected home and existing identity, writes
`creation.json`, and seeds only missing bootstrap files. It does not gestate
neural state until native startup.

For a **new, unused** example name and data/home directories, replace the model
and dependency paths with your actual directories:

```bash
venv/bin/python setup.py --non-interactive --composition mindscape \
  --composition-only --provider rwkv \
  --mightymem-path /absolute/path/to/MightyMem \
  --rwkv-model /absolute/path/to/rwkv7-g1j-1.5b-20260831-2c18b29 \
  --agent-name Example --creator-name User --archetype curious \
  --primary-channel dashboard --data-dir data/agents/Example \
  --agent-home data/homes/Example

```

Run commands from the Helix root. Explicit Mindscape composition defaults to
RWKV; Ollama remains selectable with `--provider ollama --model <name>`. Hosted
providers require the separate Helix composition. The configuration-only route
still provisions the selected identity, seeds missing bootstrap files and
updates provider/model/channel environment selections; it is not read-only.
It preserves other credential values.

For an existing agent, avoid recreating identity. Review its saved paths and
start it directly. `--resume-only` makes missing native checkpoints an error.
The creation contract refuses a changed identity/archetype over existing state.
`mindscape.workspace` is a legacy path; the body uses `mindscape.home`.

## Launch and inspect

```bash
# Initialization check: touches the actual selected stores and checkpoint.
venv/bin/python main.py --check-setup
# Continuous production runtime; uses saved data_dir.
venv/bin/python main.py
```

In another terminal:

```bash
venv/bin/python dashboard/dashboard.py --port 5050
```

The GUI launcher can manage the dashboard process. Plain `main.py` polls the
dashboard message bridge but does not start its HTTP server.

Open Dashboard Chat and expand **Environment and actions**. File staging uses
the configured `mindscape.home/staging`; a staged file remains there until
moved. Put a Python experiment in `workshop/` before asking it to run.

```text
Please go to /workshop then open Example.py then run it.
Please open /staging/Notes.txt.
Please sense .
```

Converse normally for speech. A private thinking pulse can continue into a
later reply without generating a `SPEAK` command or action JSON.

The Chat body route supports move/sense/open/run. Additional module handlers
are covered in the [home guide](agent-home.md). For current body state, use
`GET /api/motor` or **Environment and actions**. Room status, staging and
Module Studio resolve the same configured home. Room position reads the selected
`LATEST.json` checkpoint in read-only mode; it never chooses an agent by folder
order. Restart the dashboard after changing the selected agent configuration.

## State, limits and shutdown

Let `D` be the configured `data_dir`.

| Artifact | Purpose |
|---|---|
| `D/creation.json` | Identity, archetype, seed and native gestation status |
| `D/mindscape/composition-manifest.json` | Sources, models, lanes and boundaries |
| `D/mindscape/receipts.jsonl` | Actual intake, context admission, actions, returns and checkpoints |
| `D/mindscape/motor-state.json` | Public body state and per-goal receipts |
| `D/mindscape/foreground-health.json` | Language status/failure |
| `D/mindscape/joint/LATEST.json` | Selected joint neural/graph-memory checkpoint |
| `D/mindscape/joint/events.jsonl` | Native lineage and restore events |
| `mindscape.home/intakes/` | Raw changed filesystem observations |

First startup gestates native state and admits the initial home observation;
restart resumes its joint checkpoint. Historical Helix records are projected
with source/version/evidence labels rather than replayed as new feedback.
RWKV gradient training is disabled. Loom is a derived projection.

`local_context_window` is a configured assembled-input budget (8192 in the
verified profile), not RWKV's physical recurrent capacity. Whole input is counted
with the selected tokenizer; mandatory overflow fails explicitly. There is no
RWKV generated-output cap, motor action-count cap or workshop timeout.
`mindscape.sensory_interval_seconds` is the observation cadence, default 1.0.

A successful goal requires all matching returns and a joint checkpoint before
public completion. Stop with Ctrl-C or SIGTERM for cooperative generation,
native-chunk and sandbox cancellation plus the shutdown checkpoint. A running
sandbox interrupted by shutdown is not marked successful. Keep the selected
home, canonical stores and joint lineage together when backing up the agent.
Crash recovery and exactly-once replay of every intermediate action remain
unestablished.

## Verification scope

`--check-setup` validates initialization and synchronizes actual state. Start
normally afterward to use the continuous channels/body loops.

The [October 17 live record](audits/2026-10-17-native-body-operational/README.md)
documents a normal launch, graceful restart and working movement, file opening
and isolated execution. Thought/speech separation and routing have focused
implementation checks. Detailed scope and historical trials are linked from
that record and the [test guide](../tests/TEST_SUITE_README.md).
