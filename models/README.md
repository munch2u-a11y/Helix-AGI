# Local GGUF Models

**Documentation status:** current directory guide · **Last verified against source:** 2026-08-08

This optional directory stores `.gguf` files used by llama.cpp-backed conscious
models and task-specific micro-models loaded through `core/gguf_manager.py`.
Large model files are ignored by Git.

Helix does not require fixed filenames here. The setup wizard scans for
`models/*.gguf`; select or configure the file appropriate to your model. The
GGUF manager also accepts an explicit filename when a subsystem loads a model
alias.

Current local vision does not use files in this directory. `VisionCortex` and
the local `SensoryCortex` path use `gemma3:4b` through Ollama:

```bash
ollama pull gemma3:4b
```

Native 1024D semantic retrieval likewise uses an Ollama-managed model rather
than a GGUF file here:

```bash
ollama pull qwen3-embedding:0.6b
```

Provider and retrieval boundaries are documented in
[`documents/architecture_current.md`](../documents/architecture_current.md).
