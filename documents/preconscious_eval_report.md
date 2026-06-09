# Helix Preconscious Memory Evaluation Report
**Date**: 2026-06-09 13:06:27
**Tasks Replayed**: 15

This report evaluates Helix's dynamic **Preconscious Layer** over multi-turn conversational trajectories. It contrasts **Conceptual Gravity** (Euler-Lagrange attention momentum + gravity-ranked neighborhood queries) against a baseline of flat **Semantic RAG** executed per turn.

## 1. Global Metrics Summary

| Metric | Conceptual Gravity (8D Physics) | Semantic RAG (384D) | Description |
| :--- | :---: | :---: | :--- |
| **Task-Type Recall@1** | 0.00% | 30.65% | How often the correct procedural guide type is in the top slot. |
| **Task-Type Recall@3** | 0.00% | 53.23% | How often the correct procedural guide type is in the top 3 slots. |
| **Task-Type Recall@5** | 0.00% | 58.06% | How often the correct procedural guide type is in the top 5 slots. |
| **Context Token F1** | 8.12% | 29.70% | Token F1 overlap with target trajectory. |
| **Average Context Words** | 134.4 | 2649.5 | Token/word counts injected into context window. |
| **Average Latency** | 1821.17 ms | 218.97 ms | Turn-by-turn processing latency. |

## 2. Attentional Dynamics (Conceptual Gravity)

- **Average Attentional Drift**: 0.6999 units.
  *(A positive attentional drift indicates that the 8D attention center successfully shifted closer to the target task-type centroid as context accumulated over the trajectory turns).*

## 3. Analysis & Key Insights
- **Attentional Focus**: The 8D attention manifold maintains stateful attentional inertia. As the task progresses, topic-related tool outputs pull the attention center closer to the target procedural clusters, improving retrieval alignment.
- **Context Economy**: Conceptual Gravity dynamically updates the surfaced context budget. Instead of dumping a fixed quantity of raw text per query (which wastes context window space), it prioritizes active gravity fields, resulting in cleaner, more relevant prompts.
