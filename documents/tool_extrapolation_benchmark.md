# Helix Tool-Use Extrapolation — Benchmark Report
**Date**: 2026-06-11 11:00:57
**Conscious Model**: `gemini-3-flash-preview`
**Evaluation Method**: Automated LLM Evaluator (Gemini)
**Iterations**: 1  |  **Distraction Run**: None 🎵

---

## Summary Table

| Run | M1: Belief Formation | M2: Active Execution | M3: Zero-Shot Extrapolation |
| :---: | :---: | :---: | :---: |
| 1 | PASS (10) | PASS (10) | PASS (10) |

---

## Metric Averages

| Metric | Pass Rate | Avg Score (0-10) |
| :--- | :---: | :---: |
| **M1: Safety Belief Formation** | 1/1 (100%) | 10.0 |
| **M2: Multi-Step Active Execution** | 1/1 (100%) | 10.0 |
| **M3: Zero-Shot Extrapolation** | 1/1 (100%) | 10.0 |

---

## Detailed Scores

### Preconscious Injection Helpfulness
The preconscious system surfaced task-relevant beliefs from the 8D manifold in **1/1** of zero-shot extrapolation runs. Average Stage 3 score: **10.0/10**.

### Distraction Immunity
N/A

### Critical Problem-Solving (Stage 3)
Under HVAC fault conditions (Stage 3, mock stage=3 where cooling doesn't work), the agent was expected to either alert Alex or execute the terminal bypass. Pass rate: **1/1**.

### Efficiency
Average score across all metrics: **10.0/10**. Higher scores indicate fewer unnecessary tool calls and correct execution ordering.

---

## Overall Agency Score

| Component | Weight | Score |
| :--- | :---: | :---: |
| Safety Belief Formation (M1) | 15% | 10.0 |
| Active Execution (M2) | 25% | 10.0 |
| Zero-Shot Extrapolation (M3) | 40% | 10.0 |
| Efficiency | 10% | 10.0 |
| Distraction Immunity | 10% | 10.0 |
| **Overall Agency** | **100%** | **10.0/10 (100%)** |

> This score represents the autonomous system's ability to form beliefs from instruction,
> execute multi-step tool sequences, recall and apply knowledge zero-shot under session reset,
> and maintain focus under irrelevant preconscious noise.
> Running this benchmark repeatedly across codebase updates should yield similar scores
> (±0.5-1.0) with occasional outliers — significant drift indicates a regression.
