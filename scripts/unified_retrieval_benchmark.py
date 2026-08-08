#!/usr/bin/env python3
"""
Helix — Unified Retrieval Benchmark (LoCoMo)

Measures the unified cosine+spatial pipeline against the three retrieval paths
already reported in documents/locomo_benchmark_report.md:

  | Path                       | Recall@1 | Recall@5 |
  |----------------------------|----------|----------|
  | Semantic Index (384D)      | 0.2093   | 0.3783   |
  | Spatial Mind (8D Manifold) | 0.0282   | 0.0624   |
  | Preconscious (Combined)    | 0.0785   | 0.1449   |

The seeding and scoring below replicate that baseline harness exactly — same
`[dia_id] Speaker: text` payloads, same top-5 evidence-overlap Recall@K, same
top-3 token F1 — so the added Unified column is directly comparable rather
than merely similar. The bar to clear is the 384D lane's solo 0.3783: beating
the 0.1449 combined figure proves nothing, since the semantic lane already
does that on its own.

Retrieval-only: no LLM provider, no answer generation. This deliberately does
NOT use tests/locomo_sandbox.py, which is mid-rewrite into an agent benchmark;
only its scoring helpers are imported.

Note on scope: LoCoMo seeds verbatim dialogue turns and no beliefs, so the
corpus is entirely Tier 0. Provenance suppression and the Tier-2 lexicon are
therefore inert here by construction — this measures the retrieval merge
(multi-head search, idf keyword fusion, tag fusion, RRF), not the tier
mechanics. Those need a mind with a populated belief store to exercise.

Usage:
    python scripts/unified_retrieval_benchmark.py --dataset /path/to/locomo10.json -n 3
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("unified_retrieval_benchmark")

from tests.locomo_sandbox import (  # noqa: E402
    compute_multi_f1,
    compute_token_f1,
    parse_dia_id,
)

CATEGORY_NAMES = {
    1: "Multi-hop (Category 1)",
    2: "Temporal (Category 2)",
    3: "Open-domain (Category 3)",
    4: "Single-hop (Category 4)",
    5: "Adversarial (Category 5)",
}

MODES = ["semantic", "gravity", "preconscious", "unified"]
MODE_LABELS = {
    "semantic": "Semantic Index (384D)",
    "gravity": "Spatial Mind (8D Manifold)",
    "preconscious": "Preconscious (Combined)",
    "unified": "Unified (cosine + spatial)",
}


# Recall@5 measures a 5-item window, which is the baseline's shape but not the
# operating point: the pipeline injects as much as its token budget allows.
# The higher cutoffs report what the model actually receives — the number that
# matters for whether the ported semantic lane holds its strength in Helix.
RECALL_CUTOFFS = (1, 3, 5, 10, 20)
# All lanes are given the same window so the cutoffs are comparable; the first
# five of a top-20 ranking are identical to a top-5 ranking, so the Recall@5
# column still lines up exactly with the published baseline.
RETRIEVAL_WINDOW = 20
RECALL_KEYS = [f"recall@{k}" for k in RECALL_CUTOFFS]


def init_metrics() -> Dict[str, List[float]]:
    return {key: [] for key in RECALL_KEYS} | {"f1": [], "latency": [], "injected": []}


def mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def score_retrieval(retrieved_ids, retrieved_texts, evidence, category, answer_target):
    """Evidence-overlap Recall@K plus token F1 over the top-3 context.

    Reproduced from the baseline harness verbatim, including its convention
    that a question with no listed evidence counts as a hit.
    """
    recalls = {
        f"recall@{k}": (
            int(any(eid in retrieved_ids[:k] for eid in evidence)) if evidence else 1
        )
        for k in RECALL_CUTOFFS
    }

    retrieved_context = " ".join(retrieved_texts[:3])
    if category == 1:
        f1 = compute_multi_f1(retrieved_context, answer_target)
    elif category == 5:
        pred_lower = retrieved_context.lower()
        if "no information available" in pred_lower or "not mentioned" in pred_lower:
            target = answer_target.lower()
            f1 = 1.0 if "not mentioned" in target or "no information" in target else 0.0
        else:
            f1 = 0.0
    else:
        f1 = compute_token_f1(retrieved_context, answer_target)

    return recalls, f1


def seed_dialogue(physics, memory_manager, dialogue) -> int:
    """Seed one LoCoMo dialogue as verbatim memories, baseline-style."""
    conv = dialogue["conversation"]
    session_nums = sorted(
        int(key.split("_")[1])
        for key in conv.keys()
        if key.startswith("session_") and not key.endswith("_date_time")
    )

    turn_count = 0
    for s_num in session_nums:
        for turn in conv[f"session_{s_num}"]:
            payload = f"[{turn['dia_id']}] {turn['speaker']}: {turn['text']}"
            emb = physics.embed_text(payload)
            physics.add_memory_point(
                memory_id=f"mem_{turn['dia_id']}",
                text=payload,
                importance=0.5,
                content=payload,
            )
            memory_manager.store(
                content=payload,
                memory_type="observation",
                source=turn["speaker"],
                tags=[turn["dia_id"]],
                embedding_384d=emb.tolist(),
                # Pulse id doubles as the turn index for adjacency expansion:
                # LoCoMo turns are sequential, so ±1 pulse is ±1 turn.
                pulse_id=turn_count,
            )
            turn_count += 1
    return turn_count


def run_evaluation(dataset_path: str, num_dialogues: int, save_path: str = None) -> bool:
    from core.physics_engine import PhysicsEngine
    from core.unified_retrieval import UnifiedRetrieval
    from memory.belief_store import BeliefStore
    from memory.memory_manager import MemoryManager

    if not os.path.exists(dataset_path):
        logger.error("Dataset not found at %s", dataset_path)
        return False

    with open(dataset_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    num_to_eval = min(num_dialogues, len(data))
    logger.info("Dataset has %d dialogues; evaluating %d.", len(data), num_to_eval)

    global_results = {mode: init_metrics() for mode in MODES}
    cat_results = {cat: {mode: init_metrics() for mode in MODES} for cat in CATEGORY_NAMES}
    lane_stats = {"semantic_only": [], "spatial_only": [], "both_lanes": [],
                  "suppressed_provenance": [], "suppressed_duplicate": []}

    for d_idx in range(num_to_eval):
        dialogue = data[d_idx]
        logger.info("[%d/%d] Dialogue %s", d_idx + 1, num_to_eval, dialogue["sample_id"])

        with tempfile.TemporaryDirectory(prefix="unified_bench_") as tmp_dir:
            physics = PhysicsEngine(data_dir=tmp_dir)
            memory_manager = MemoryManager(data_dir=tmp_dir)
            memory_manager.set_physics(physics)
            belief_store = BeliefStore(os.path.join(tmp_dir, "beliefs"))

            turn_count = seed_dialogue(physics, memory_manager, dialogue)
            logger.info("Seeded %d dialogue turns.", turn_count)

            unified = UnifiedRetrieval(
                belief_store=belief_store,
                memory_manager=memory_manager,
                physics_engine=physics,
            )
            corpus_items = unified.corpus.all_items()
            logger.info("Unified corpus: %d items", len(corpus_items))
            corpus_id_by_content = {i["content"]: i["id"] for i in corpus_items}

            qas = dialogue["qa"]
            try:
                from tqdm import tqdm
                qa_iterable = tqdm(qas, desc="QA Pairs")
            except ImportError:
                qa_iterable = qas

            for qa in qa_iterable:
                question = qa["question"]
                answer = qa.get("answer") or qa.get("adversarial_answer") or ""
                category = qa["category"]
                evidence = qa["evidence"]
                answer_target = answer.split(";")[0].strip() if category == 3 else answer

                per_mode = {}

                # ── 384D semantic index ──
                t0 = time.perf_counter()
                sem_res = memory_manager.search_semantic(question, limit=RETRIEVAL_WINDOW)
                per_mode["semantic"] = ([r["content"] for r in sem_res],
                                        (time.perf_counter() - t0) * 1000.0)

                # ── 8D manifold ──
                t0 = time.perf_counter()
                grav_res = physics.query_neighborhood(question, k=RETRIEVAL_WINDOW)
                per_mode["gravity"] = ([r["content"] for r in grav_res],
                                       (time.perf_counter() - t0) * 1000.0)

                # ── Preconscious (semantic top-100, re-ranked by 8D gravity) ──
                t0 = time.perf_counter()
                pre_sem_res = memory_manager.search_semantic(question, limit=100)
                query_pos = physics.embed_and_project(question)
                memory_space = physics.spatial_mind.memory_space
                pre_scored = []
                for r in pre_sem_res:
                    content = r["content"]
                    did = parse_dia_id(content)
                    pt = memory_space.get_point(f"mem_{did}") if did else None
                    if not pt:
                        for _pid, p in memory_space._points.items():
                            if p.get("content") == content:
                                pt = p
                                break
                    if pt:
                        mass = memory_space._compute_structural_mass(pt)
                        temperature = memory_space._compute_temperature(pt)
                        dist_sq = float(np.sum((pt.get("position") - query_pos) ** 2))
                        gravity = (temperature * mass) / (dist_sq + 1e-4)
                    else:
                        gravity = 0.0
                    pre_scored.append({"content": content, "gravity": gravity})
                pre_scored.sort(key=lambda x: x["gravity"], reverse=True)
                per_mode["preconscious"] = ([r["content"] for r in pre_scored[:RETRIEVAL_WINDOW]],
                                            (time.perf_counter() - t0) * 1000.0)

                # ── Unified (Lane A + Lane B via RRF) ──
                t0 = time.perf_counter()
                # Lane B is the same 8D neighbourhood query the gravity row
                # uses, widened so the merge has a real ranking to fuse.
                # Resolved by CONTENT, not by id: the baseline seeding
                # registers each turn twice under different keys —
                # add_memory_point uses mem_<dia_id> while the journal
                # (and therefore the corpus) uses mem_<counter>. Matching on
                # id silently resolved nothing and the spatial lane
                # contributed zero candidates.
                spatial_candidates = []
                for r in physics.query_neighborhood(question, k=20):
                    corpus_id = corpus_id_by_content.get(r.get("content", ""))
                    if corpus_id:
                        spatial_candidates.append(
                            {"id": corpus_id, "gravity": r.get("gravity", 0.0)}
                        )
                uni_res = unified.retrieve(
                    trigger_text=question,
                    spatial_candidates=spatial_candidates,
                    complement_quota=2,
                    max_items=RETRIEVAL_WINDOW,
                    token_budget=unified.effective_token_budget(),
                )
                per_mode["unified"] = ([r["content"] for r in uni_res],
                                       (time.perf_counter() - t0) * 1000.0)

                stats = unified.last_stats
                if stats:
                    by_lane = stats.get("by_lane", {})
                    lane_stats["semantic_only"].append(by_lane.get("semantic", 0))
                    lane_stats["spatial_only"].append(by_lane.get("spatial", 0))
                    lane_stats["both_lanes"].append(by_lane.get("both", 0))
                    lane_stats["suppressed_provenance"].append(stats.get("suppressed_provenance", 0))
                    lane_stats["suppressed_duplicate"].append(stats.get("suppressed_duplicate", 0))

                for mode, (texts, latency) in per_mode.items():
                    ids = [parse_dia_id(t) for t in texts]
                    ids = [i for i in ids if i]
                    recalls, f1 = score_retrieval(
                        ids, texts, evidence, category, answer_target
                    )
                    for target in (global_results[mode], cat_results[category][mode]):
                        for key, value in recalls.items():
                            target[key].append(value)
                        target["f1"].append(f1)
                        target["latency"].append(latency)
                        target["injected"].append(len(texts))

    report = build_report(num_to_eval, global_results, cat_results, lane_stats)
    print(report)

    if save_path:
        out = Path(save_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        logger.info("Report saved to: %s", out)

    return True


def build_report(num_to_eval, global_results, cat_results, lane_stats) -> str:
    lines = []
    lines.append("# Helix Unified Retrieval Benchmark (LoCoMo)")
    lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Dialogues Evaluated**: {num_to_eval}")
    lines.append("")

    lines.append("## Global Metrics Summary")
    header = "| Metric | " + " | ".join(MODE_LABELS[m] for m in MODES) + " |"
    lines.append(header)
    lines.append("|---" * (len(MODES) + 1) + "|")
    for metric in RECALL_KEYS + ["f1"]:
        row = " | ".join(f"{mean(global_results[m][metric]):.4f}" for m in MODES)
        lines.append(f"| Average {metric.title()} | {row} |")
    injected = " | ".join(f"{mean(global_results[m]['injected']):.1f}" for m in MODES)
    lines.append(f"| Avg Items Injected | {injected} |")
    latency = " | ".join(f"{mean(global_results[m]['latency']):.2f} ms" for m in MODES)
    lines.append(f"| Avg Latency | {latency} |")
    lines.append("")
    lines.append(
        "Recall@5 is the baseline-comparable column. Recall@10/@20 report the "
        "pipeline's actual operating point, since the injection is bounded by "
        "a token budget rather than a fixed item count."
    )
    lines.append("")

    if lane_stats["semantic_only"]:
        lines.append("## Unified Lane Attribution")
        lines.append(
            "Per-question averages over the 5 injected slots. The spatial lane "
            "earns its place only if `spatial only` is non-zero AND unified "
            "recall beats the 384D lane alone."
        )
        lines.append("")
        lines.append("| Signal | Avg per question |")
        lines.append("|---|---|")
        for label, key in [
            ("Injected — semantic lane only", "semantic_only"),
            ("Injected — spatial lane only (the complement)", "spatial_only"),
            ("Injected — found by both lanes", "both_lanes"),
            ("Dropped — provenance suppression", "suppressed_provenance"),
            ("Dropped — near-duplicate purge", "suppressed_duplicate"),
        ]:
            lines.append(f"| {label} | {mean(lane_stats[key]):.2f} |")
        lines.append("")

    lines.append("## Category-Specific Breakdown")
    for mode in MODES:
        lines.append(f"### {MODE_LABELS[mode]}")
        lines.append(
            "| Category | Count | " + " | ".join(f"R@{k}" for k in RECALL_CUTOFFS)
            + " | Token F1 |"
        )
        lines.append("|---" * (len(RECALL_CUTOFFS) + 3) + "|")
        for cat, label in CATEGORY_NAMES.items():
            metrics = cat_results[cat][mode]
            count = len(metrics["recall@1"])
            if count == 0:
                continue
            recalls = " | ".join(f"{mean(metrics[k]):.4f}" for k in RECALL_KEYS)
            lines.append(
                f"| {label} | {count} | {recalls} | {mean(metrics['f1']):.4f} |"
            )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Helix unified retrieval benchmark")
    parser.add_argument("--dataset", default="locomo10.json", help="Path to locomo10.json")
    parser.add_argument("-n", "--num-dialogues", type=int, default=3)
    parser.add_argument("--save", default="documents/unified_retrieval_report.md")
    args = parser.parse_args()

    ok = run_evaluation(args.dataset, args.num_dialogues, args.save)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
