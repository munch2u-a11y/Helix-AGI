# Local model configuration

**Source review: 2026-10-17.** Model files are not supplied by this repository.
The native Mindscape composition and optional provider routes use different
loaders; a file in this directory does not automatically select a runtime.

## Native RWKV

The default Mindscape profile selects the pinned safetensors checkpoint
`RWKV/RWKV7-G1j-1.5B-20260831@2c18b29ab7fbece25ff6112281eea0fa41fcb30f`.
Configure the actual directory in `mindscape.rwkv_model` and the foreground
`local_model`/`llm_model`; include its index and all four shards.

An example model checkpoint path is
`models/rwkv7-g1j-1.5b-20260831-2c18b29` (or an external directory configured via `RWKV_MODEL_PATH`).
It is an external checkpoint location, not a portable default guaranteed to
exist on another machine. `RWKV_MODEL_PATH` participates in path discovery.

Use `requirements-mindscape.txt` in the Helix venv. The joint native bridge is
CPU-only and loads compatible MightyMem source from `mindscape.package_path`.
Foreground and auxiliary RWKV use the declared local checkpoint. Gradient
training is disabled in this adapter.

## Semantic embeddings

Helix's native 1024D semantic retrieval uses an Ollama-managed model:

```bash
ollama pull qwen3-embedding:0.6b
```

Keep Ollama running. This embedding dependency remains necessary when RWKV
provides the language stream; a separate Granite foreground is not required.

## Optional GGUF and vision models

`.gguf` files can be used by llama.cpp-backed language/micro-model adapters
through `core/gguf_manager.py`. The wizard scans `models/*.gguf`; select the
actual model rather than relying on a fixed filename. Large weight files are
excluded from version control.

Optional local vision uses `gemma3:4b` through Ollama in the vision adapters.
It is distinct from the native body's text/metadata surroundings sensor and
was disabled in the October 17 trial. Install/configure it only for an enabled
vision route.

See [launch](../documents/mindscape_launch.md) and
[architecture](../documents/architecture_current.md) for source/model parity.
