# Helix Memory Retrieval Benchmark Report (LoCoMo)
**Date**: 2026-07-06 08:44:37
**Dialogues Evaluated**: 3

## Global Metrics Summary
| Metric | Semantic Index (384D) | Spatial Mind (8D Manifold) | Preconscious (Combined) |
|---|---|---|---|
| Average Recall@1 | 0.2093 | 0.0282 | 0.0785 |
| Average Recall@3 | 0.2918 | 0.0543 | 0.1167 |
| Average Recall@5 | 0.3783 | 0.0624 | 0.1449 |
| Average F1 | 0.0243 | 0.0083 | 0.0134 |
| Avg Latency (ms) | 241.85 ms | 138.37 ms | 377.27 ms |

## Category-Specific Breakdown
### 384D Semantic Index
| Category | Count | Recall@1 | Recall@3 | Recall@5 | Token F1 |
|---|---|---|---|---|---|
| Multi-hop (Category 1) | 74 | 0.1892 | 0.2973 | 0.3784 | 0.0570 |
| Temporal (Category 2) | 90 | 0.2444 | 0.3778 | 0.4444 | 0.0045 |
| Open-domain (Category 3) | 21 | 0.1905 | 0.2381 | 0.3333 | 0.0078 |
| Single-hop (Category 4) | 200 | 0.2500 | 0.3100 | 0.4100 | 0.0364 |
| Adversarial (Category 5) | 112 | 0.1250 | 0.1964 | 0.2768 | 0.0000 |

### 8D Spatial Mind (Manifold)
| Category | Count | Recall@1 | Recall@3 | Recall@5 | Token F1 |
|---|---|---|---|---|---|
| Multi-hop (Category 1) | 74 | 0.0270 | 0.0541 | 0.0541 | 0.0122 |
| Temporal (Category 2) | 90 | 0.0222 | 0.0889 | 0.1000 | 0.0011 |
| Open-domain (Category 3) | 21 | 0.1429 | 0.1905 | 0.1905 | 0.0062 |
| Single-hop (Category 4) | 200 | 0.0300 | 0.0450 | 0.0550 | 0.0151 |
| Adversarial (Category 5) | 112 | 0.0089 | 0.0179 | 0.0268 | 0.0000 |

### Preconscious (Combined)
| Category | Count | Recall@1 | Recall@3 | Recall@5 | Token F1 |
|---|---|---|---|---|---|
| Multi-hop (Category 1) | 74 | 0.0405 | 0.1216 | 0.1622 | 0.0226 |
| Temporal (Category 2) | 90 | 0.0889 | 0.1333 | 0.1667 | 0.0019 |
| Open-domain (Category 3) | 21 | 0.1905 | 0.1905 | 0.1905 | 0.0069 |
| Single-hop (Category 4) | 200 | 0.1050 | 0.1400 | 0.1600 | 0.0234 |
| Adversarial (Category 5) | 112 | 0.0268 | 0.0446 | 0.0804 | 0.0000 |
