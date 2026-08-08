# Helix Unified Retrieval Benchmark (LoCoMo)

> [!NOTE]
> **Historical benchmark record.** Dimensions, retrieval labels, and metrics describe the build evaluated on 2026-08-07; they are not current runtime documentation. The report is preserved as the baseline that preceded the native 1024D semantic split. See the [current architecture](architecture_current.md).

**Date**: 2026-08-07 17:59:44
**Dialogues Evaluated**: 3

## Global Metrics Summary
| Metric | Semantic Index (384D) | Spatial Mind (8D Manifold) | Preconscious (Combined) | Unified (cosine + spatial) |
|---|---|---|---|---|
| Average Recall@1 | 0.2093 | 0.0241 | 0.0744 | 0.1469 |
| Average Recall@3 | 0.2918 | 0.0463 | 0.1066 | 0.3421 |
| Average Recall@5 | 0.3783 | 0.0624 | 0.1308 | 0.4869 |
| Average Recall@10 | 0.4507 | 0.0825 | 0.1771 | 0.6258 |
| Average Recall@20 | 0.5634 | 0.1489 | 0.2696 | 0.6962 |
| Average F1 | 0.0243 | 0.0084 | 0.0123 | 0.0274 |
| Avg Items Injected | 20.0 | 20.0 | 20.0 | 17.1 |
| Avg Latency | 480.30 ms | 279.47 ms | 758.66 ms | 1753.17 ms |

Recall@5 is the baseline-comparable column. Recall@10/@20 report the pipeline's actual operating point, since the injection is bounded by a token budget rather than a fixed item count.

## Unified Lane Attribution
Per-question averages over the 5 injected slots. The spatial lane earns its place only if `spatial only` is non-zero AND unified recall beats the 384D lane alone.

| Signal | Avg per question |
|---|---|
| Injected — semantic lane only | 11.75 |
| Injected — spatial lane only (the complement) | 2.63 |
| Injected — found by both lanes | 2.18 |
| Dropped — provenance suppression | 0.00 |
| Dropped — near-duplicate purge | 0.31 |

## Category-Specific Breakdown
### Semantic Index (384D)
| Category | Count | R@1 | R@3 | R@5 | R@10 | R@20 | Token F1 |
|---|---|---|---|---|---|---|---|
| Multi-hop (Category 1) | 74 | 0.1892 | 0.2973 | 0.3784 | 0.4730 | 0.5811 | 0.0570 |
| Temporal (Category 2) | 90 | 0.2444 | 0.3778 | 0.4444 | 0.5000 | 0.6333 | 0.0045 |
| Open-domain (Category 3) | 21 | 0.1905 | 0.2381 | 0.3333 | 0.3810 | 0.4762 | 0.0078 |
| Single-hop (Category 4) | 200 | 0.2500 | 0.3100 | 0.4100 | 0.4800 | 0.6050 | 0.0364 |
| Adversarial (Category 5) | 112 | 0.1250 | 0.1964 | 0.2768 | 0.3571 | 0.4375 | 0.0000 |

### Spatial Mind (8D Manifold)
| Category | Count | R@1 | R@3 | R@5 | R@10 | R@20 | Token F1 |
|---|---|---|---|---|---|---|---|
| Multi-hop (Category 1) | 74 | 0.0270 | 0.0405 | 0.0541 | 0.1081 | 0.1486 | 0.0129 |
| Temporal (Category 2) | 90 | 0.0111 | 0.0556 | 0.1000 | 0.1111 | 0.2111 | 0.0011 |
| Open-domain (Category 3) | 21 | 0.0952 | 0.1905 | 0.1905 | 0.1905 | 0.2857 | 0.0064 |
| Single-hop (Category 4) | 200 | 0.0300 | 0.0450 | 0.0550 | 0.0800 | 0.1400 | 0.0149 |
| Adversarial (Category 5) | 112 | 0.0089 | 0.0179 | 0.0268 | 0.0268 | 0.0893 | 0.0000 |

### Preconscious (Combined)
| Category | Count | R@1 | R@3 | R@5 | R@10 | R@20 | Token F1 |
|---|---|---|---|---|---|---|---|
| Multi-hop (Category 1) | 74 | 0.0541 | 0.0946 | 0.1351 | 0.2297 | 0.3108 | 0.0177 |
| Temporal (Category 2) | 90 | 0.0889 | 0.1556 | 0.1778 | 0.2222 | 0.3444 | 0.0022 |
| Open-domain (Category 3) | 21 | 0.1429 | 0.1905 | 0.1905 | 0.1905 | 0.2857 | 0.0059 |
| Single-hop (Category 4) | 200 | 0.0950 | 0.1150 | 0.1350 | 0.1900 | 0.2800 | 0.0225 |
| Adversarial (Category 5) | 112 | 0.0268 | 0.0446 | 0.0714 | 0.0804 | 0.1607 | 0.0000 |

### Unified (cosine + spatial)
| Category | Count | R@1 | R@3 | R@5 | R@10 | R@20 | Token F1 |
|---|---|---|---|---|---|---|---|
| Multi-hop (Category 1) | 74 | 0.0811 | 0.2838 | 0.4595 | 0.5946 | 0.7027 | 0.0557 |
| Temporal (Category 2) | 90 | 0.1667 | 0.4889 | 0.7111 | 0.8222 | 0.8333 | 0.0065 |
| Open-domain (Category 3) | 21 | 0.1429 | 0.2381 | 0.2857 | 0.4762 | 0.5238 | 0.0068 |
| Single-hop (Category 4) | 200 | 0.1900 | 0.3450 | 0.4500 | 0.6200 | 0.6850 | 0.0439 |
| Adversarial (Category 5) | 112 | 0.0982 | 0.2768 | 0.4286 | 0.5268 | 0.6339 | 0.0000 |
