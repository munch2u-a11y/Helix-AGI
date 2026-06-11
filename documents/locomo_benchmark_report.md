# Helix Memory Retrieval Benchmark Report (LoCoMo)
**Date**: 2026-06-11 16:59:27
**Dialogues Evaluated**: 1

## Global Metrics Summary
| Metric | Semantic Index (384D) | Spatial Mind (8D Manifold) |
|---|---|---|
| Average Recall@1 | 0.1960 | 0.0151 |
| Average Recall@3 | 0.2714 | 0.0503 |
| Average Recall@5 | 0.3719 | 0.0905 |
| Average F1 | 0.0187 | 0.0132 |
| Avg Latency (ms) | 139.21 ms | 135.46 ms |

## Category-Specific Breakdown
### 384D Semantic Index
| Category | Count | Recall@1 | Recall@3 | Recall@5 | Token F1 |
|---|---|---|---|---|---|
| Multi-hop (Category 1) | 32 | 0.1562 | 0.2500 | 0.2812 | 0.0237 |
| Temporal (Category 2) | 37 | 0.1892 | 0.3243 | 0.4054 | 0.0034 |
| Open-domain (Category 3) | 13 | 0.3077 | 0.3846 | 0.5385 | 0.0059 |
| Single-hop (Category 4) | 70 | 0.2571 | 0.2857 | 0.4286 | 0.0395 |
| Adversarial (Category 5) | 47 | 0.1064 | 0.1915 | 0.2766 | 0.0000 |

### 8D Spatial Mind (Manifold)
| Category | Count | Recall@1 | Recall@3 | Recall@5 | Token F1 |
|---|---|---|---|---|---|
| Multi-hop (Category 1) | 32 | 0.0000 | 0.0625 | 0.1562 | 0.0182 |
| Temporal (Category 2) | 37 | 0.0000 | 0.0541 | 0.1081 | 0.0015 |
| Open-domain (Category 3) | 13 | 0.1538 | 0.2308 | 0.2308 | 0.0077 |
| Single-hop (Category 4) | 70 | 0.0143 | 0.0429 | 0.0714 | 0.0269 |
| Adversarial (Category 5) | 47 | 0.0000 | 0.0000 | 0.0213 | 0.0000 |
