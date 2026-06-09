# Helix Memory Retrieval Benchmark Report (STATE-Bench)

**Status**: Sandbox Ready & Verified (Dry-run Passed)
**STATE-Bench Path**: `/home/nemo/state_bench`
**Date**: 2026-06-09

This report template is prepared for Helix's memory retrieval evaluation on Microsoft's **STATE-Bench** dataset. The sandbox harness has been successfully configured and verified.

## Verified Dataset Structure

A dry-run parsing check was executed across all three enterprise domains:
- **Customer Support**: Verified (Sample task `100-challenge_warranty_maxed_return_option` parsed successfully, trace length: 3,601 characters).
- **Shopping Assistant**: Verified (Sample task `1-recommend_college_laptop` parsed successfully, trace length: 4,510 characters).
- **Travel**: Verified (Sample task `10-book_with_points_full` parsed successfully, trace length: 3,587 characters).

## Evaluation Metrics Configuration

Once executed, the benchmark will track:
- **Task Recall@K (K=1, 3, 5)**: The percentage of queries that retrieve the exact historical execution trajectory for the user's scenario.
- **Task-Type Recall@K (K=1, 3, 5)**: The percentage of queries that retrieve a trajectory belonging to the same functional category, indicating whether Helix can find relevant procedural patterns for unseen tasks.
- **Procedural Trace Token F1**: A token-level overlap F1 score (with Porter Stemming) measuring the semantic similarity between the retrieved historical context and the target trajectory.
- **Avg Query Latency**: Time in milliseconds for semantic search and physics manifold query lookups.

---

### Executing the Benchmark

To start the actual evaluation run, execute:
```bash
/home/nemo/Helix/.venv/bin/python3 scripts/statebench_sandbox.py --num-tasks 5
```
*(The `--num-tasks` argument configures the number of tasks per domain to ingest and evaluate).*
