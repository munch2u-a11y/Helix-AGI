# Validation Status

The previous files described as LoCoMo, LongMemEval, MemoryArena, and
head-to-head benchmarks were removed on 2026-08-20. They used small custom
prompts rather than the named datasets and protocols, and one head-to-head
harness instantiated prompt wrappers defined inside the benchmark instead of
the Helix Over-Agent. Their scores are not valid evidence about this system.

## What is currently verified

The deterministic test suite checks implementation boundaries, not model
quality claims:

- Helix `main` 384D semantic retrieval compatibility, including exact Layer-2 term anchors;
- canonical inbound and outbound turn persistence;
- document ingestion through the same memory write boundary;
- desktop widget drag, resize, and local WebGL asset wiring;
- MCP/CLI adapter initialization and bounded component behavior.

Run it from the repository root with the project environment:

```bash
venv/bin/python -m pip install -r Over_Agent_Design/requirements-dev.txt
venv/bin/python -m pytest -q Over_Agent_Design/tests
```

## Requirements for a future benchmark

A publishable run must record the exact Helix commit, dataset identity and
hash, case IDs, model name and Ollama model digest, generation parameters,
retrieval configuration, raw per-case inputs/outputs, scoring code, seeds,
and failures. The harness must instantiate `SubconsciousConductor` (or a
documented lower-level retrieval boundary) from this repository. Silent model
fallbacks are forbidden during measured runs. `LLMBackend.last_model_used`
must agree with the declared model; leave `HELIX_LLM_FALLBACK_MODEL` unset.

Report these claim boundaries separately:

1. controller routing;
2. retrieval-only Recall@K / exact evidence recall;
3. end-to-end answer quality;
4. action execution with authoritative receipts;
5. latency and token use.

No benchmark score is currently claimed for the Over-Agent branch.
