# Helix Memory Retrieval Benchmark Report (STATE-Bench)
**Date**: 2026-06-09 12:32:38
**Tasks Evaluated per Domain**: 5 (Total: 15)

## Global Metrics Summary

| Metric | 384D Semantic Search | 8D Physics Manifold | Description |
| :--- | :---: | :---: | :--- |
| Task Recall@1 | 93.33% | 40.00% | Recall accuracy or trace token overlap F1. |
| Task Recall@3 | 100.00% | 53.33% | Recall accuracy or trace token overlap F1. |
| Task Recall@5 | 100.00% | 73.33% | Recall accuracy or trace token overlap F1. |
| Task-Type Recall@1 | 100.00% | 66.67% | Recall accuracy or trace token overlap F1. |
| Task-Type Recall@3 | 100.00% | 80.00% | Recall accuracy or trace token overlap F1. |
| Task-Type Recall@5 | 100.00% | 80.00% | Recall accuracy or trace token overlap F1. |
| Procedural Trace Token F1 | 48.71% | 3.12% | Recall accuracy or trace token overlap F1. |
| Avg Query Latency | 221.23 ms | 220.87 ms | Execution time in milliseconds. |

## Observations & Insights
- **Task-level Recall** measures whether the exact historical execution trajectory for the user's scenario is retrieved.
- **Task-Type Recall** measures whether a trajectory of the same functional category (e.g. cancellation, exchange) is retrieved, providing relevant procedural guidance even if the exact task was not previously run.
- The **8D Physics Manifold** combines semantic layout with topological recency/gravitational dynamics to refine context retrieval.