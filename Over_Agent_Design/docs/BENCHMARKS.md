# 🧪 Empirical Benchmark Suite & Evaluation Methodology

> **Real-Agent Evaluation Specifications for LoCoMo, LongMemEval, and MemoryArena Benchmarks.**

---

## 1. Overview & Verification Protocol

To ensure empirical validity, all benchmark evaluations are conducted against a **live, running instance of the Subconscious Over-Agent** (`SubconsciousConductor` connected to local Ollama `granite4.1:8b`).

### Strict Verification Rules:
1. **Zero Mock Data**: Benchmark turns execute actual conversational turns against the Conductor engine.
2. **Raw Transcript Logging**: Every input prompt, intermediate subconscious monologue, subagent dispatch, and exact LLM output string is saved to `eval_results/raw_transcript.jsonl`.
3. **Multi-Constraint Criteria**: Verification logic checks exact string matches, temporal chain links, and false-memory rejection without relying on flawed LLM graders.

---

## 2. Benchmark Suite Breakdown

### 2.1 LoCoMo Benchmark (Long Context Multi-Turn Temporal Memory)
* **Objective**: Evaluate an agent's ability to maintain a coherent temporal sequence of project timeline events across 5+ sequential conversational turns and answer complex multi-turn dependency questions.
* **Test Sequence**:
  - `Turn 1`: Monday — Deployed local Ollama backend with `granite4.1:8b`.
  - `Turn 2`: Tuesday — Updated composite memory database with 50 belief nodes.
  - `Turn 3`: Wednesday — Encountered 120s timeout on Ollama due to parallel thread collision.
  - `Turn 4`: Thursday — Fixed it by adding a thread safety lock (`self.lock`) in `subconscious_conductor.py`.
  - `Turn 5 (Exam Question)`: *"What specific fix was applied on Thursday, and what problem on Wednesday did it solve?"*
* **Pass Condition**: Output must explicitly cite both Thursday's fix (`self.lock` / thread lock) AND Wednesday's problem (timeout / thread collision).
* **Live Agent Result**: **PASS ✓**

---

### 2.2 LongMemEval Benchmark (Long-Term Retrieval, Fact Update & Rejection)
* **Objective**: Evaluate long-term memory retrieval across three distinct cognitive dimensions:
  1. **Canonical Memory Recall**: Retrieves configuration specs (`granite4.1:8b` on port `11434`).
  2. **Dynamic Fact Overwriting**: Ingests an updated preference replacing `memorybench` with `state_bench v2`, verifying that the agent updates its internal belief model on subsequent turns.
  3. **False Memory Rejection**: Tests false-premise questions (*"Did Nemo start a snowmobile company in Alaska?"*), verifying that the agent rejects un-discussed facts.
* **Live Agent Result**: **PASS ✓ (3/3 Subtests Passed)**

---

### 2.3 MemoryArena Benchmark (High-Density Context Noise & Needle Extraction)
* **Objective**: Evaluate needle-in-a-haystack memory extraction when two target needles are embedded inside a high-density stream of 6 distractor server specs.
* **Distractors Ingested**: Specs for PostgreSQL, Redis, Nginx, MongoDB servers.
* **Target Needles**:
  - `Needle Alpha`: Emergency recovery key = `APOLLO-99-ALPHA`
  - `Needle Beta`: Backup storage bucket region = `eu-central-1-private`
* **Exam Question**: *"From the specs logged above, what is the emergency recovery pass key and what is the backup storage bucket region?"*
* **Pass Condition**: Output must extract both `APOLLO-99-ALPHA` and `eu-central-1-private` verbatim.
* **Live Agent Result**: **PASS ✓ (100% Precision Needle Retrieval)**

---

## 3. Latest Benchmark Results (`eval_results/real_agent_benchmark_report.json`)

```json
{
  "timestamp": 1771572025.0,
  "model": "granite4.1:8b",
  "results": {
    "locomo": {
      "benchmark": "LoCoMo",
      "total_turns": 5,
      "status": "PASS"
    },
    "longmemeval": {
      "benchmark": "LongMemEval",
      "subtests": [
        {"id": "recall", "pass": true},
        {"id": "update", "pass": true},
        {"id": "rejection", "pass": true}
      ],
      "status": "PASS"
    },
    "memory_arena": {
      "benchmark": "MemoryArena",
      "criteria": {
        "needle_1_apollo": true,
        "needle_2_eucentral": true
      },
      "status": "PASS"
    }
  }
}
```

---

## 4. How to Re-Run Benchmarks

To execute the live real-agent benchmark suite and generate updated report logs:

```bash
python3 run_real_agent_memory_benchmarks.py
```
