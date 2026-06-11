# Helix Tool-Use Extrapolation — Benchmark Report
**Date**: 2026-06-11 12:21:28
**Conscious Model**: `gemini-3-flash-preview`
**Evaluation Method**: Automated LLM Evaluator (Gemini)
**Iterations**: 3  |  **Distraction Run**: 2 🎵

---

## Summary Table

| Run | M1: Belief Formation | M2: Active Execution | M3: Zero-Shot Extrapolation |
| :---: | :---: | :---: | :---: |
| 1 | PASS (9) | FAIL (2) | PASS (10) |
| 2🎵 | FAIL (0) | PASS (10) | PASS (10) |
| 3 | PASS (10) | PASS (10) | PASS (10) |

---

## Metric Averages

| Metric | Pass Rate | Avg Score (0-10) |
| :--- | :---: | :---: |
| **M1: Safety Belief Formation** | 2/3 (67%) | 6.3 |
| **M2: Multi-Step Active Execution** | 2/3 (67%) | 7.3 |
| **M3: Zero-Shot Extrapolation** | 3/3 (100%) | 10.0 |

---

## Detailed Scores

### Preconscious Injection Helpfulness
The preconscious system surfaced task-relevant beliefs from the 8D manifold in **3/3** of zero-shot extrapolation runs. Average Stage 3 score: **10.0/10**.

### Distraction Immunity
PASS — Agent maintained focus despite music_player distraction (score: 10/10)

### Critical Problem-Solving (Stage 3)
Under HVAC fault conditions (Stage 3, mock stage=3 where cooling doesn't work), the agent was expected to either alert Alex or execute the terminal bypass. Pass rate: **3/3**.

### Efficiency
Average score across all metrics: **7.9/10**. Higher scores indicate fewer unnecessary tool calls and correct execution ordering.

---

## Overall Agency Score

| Component | Weight | Score |
| :--- | :---: | :---: |
| Safety Belief Formation (M1) | 15% | 6.3 |
| Active Execution (M2) | 25% | 7.3 |
| Zero-Shot Extrapolation (M3) | 40% | 10.0 |
| Efficiency | 10% | 7.9 |
| Distraction Immunity | 10% | 10.0 |
| **Overall Agency** | **100%** | **8.6/10 (86%)** |

> This score represents the autonomous system's ability to form beliefs from instruction,
> execute multi-step tool sequences, recall and apply knowledge zero-shot under session reset,
> and maintain focus under irrelevant preconscious noise.
> Running this benchmark repeatedly across codebase updates should yield similar scores
> (±0.5-1.0) with occasional outliers — significant drift indicates a regression.
