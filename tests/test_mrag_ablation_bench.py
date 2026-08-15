#!/usr/bin/env python3
"""A/B Benchmark Suite for mRAG + Spatial Gravity Integration.

Evaluates 4 configurations on a 100-question retrieval dataset:
  1. Baseline mRAG (semantic foreground only)
  2. mRAG + 1 Spatial Complement
  3. mRAG + 2 Spatial Complements
  4. mRAG + Gravity-Guided Second-Hop Query (multi-hop 8D basin recall)

Calculates Recall@5, Recall@10, Full-Evidence Recall, and Multi-Hop Recall.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Ensure repo root is on python path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from memory.belief_store import BeliefStore
from core.unified_retrieval import UnifiedRetrieval
from core.spatial_mind import SpatialMind

logger = logging.getLogger("mrag_ablation_bench")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def generate_synthetic_benchmark_dataset(num_questions: int = 100) -> List[Dict[str, Any]]:
    """Generate 100 benchmark questions with ground truth evidence items for testing."""
    dataset = []
    
    for i in range(1, num_questions + 1):
        is_multihop = (i % 2 == 0)
        category = "multi_hop" if is_multihop else "single_hop"
        
        if is_multihop:
            q = f"Question {i}: What was the consequence of the hospital visit for the veteran's military resilience?"
            evidence = [f"mem_hospital_visit_{i}", f"mem_veteran_resilience_{i}"]
        else:
            q = f"Question {i}: Where did the user attend college in 2018?"
            evidence = [f"mem_college_location_{i}"]
            
        dataset.append({
            "id": f"q_{i:03d}",
            "question": q,
            "category": category,
            "ground_truth_evidence": evidence,
        })
    return dataset


def evaluate_configuration(
    retriever: UnifiedRetrieval,
    dataset: List[Dict[str, Any]],
    config_name: str,
    complement_quota: int = 0,
    use_multihop: bool = False,
    mock_spatial_candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Evaluate a single retrieval configuration over the dataset."""
    total_q = len(dataset)
    r5_sum = 0.0
    r10_sum = 0.0
    full_evidence_hits = 0
    multihop_hits = 0
    multihop_total = 0

    for item in dataset:
        q_text = item["question"]
        gt = set(item["ground_truth_evidence"])
        is_mh = item.get("category") == "multi_hop"

        if is_mh:
            multihop_total += 1

        if use_multihop:
            retrieved = retriever.retrieve_multihop(
                trigger_text=q_text,
                spatial_candidates=mock_spatial_candidates,
                complement_quota=complement_quota,
                max_items=15,
            )
        else:
            retrieved = retriever.retrieve(
                trigger_text=q_text,
                spatial_candidates=mock_spatial_candidates,
                complement_quota=complement_quota,
                max_items=15,
            )

        retrieved_ids = [r.get("id") for r in retrieved if r.get("id")]
        
        # Calculate Recall@5 and Recall@10
        top5 = set(retrieved_ids[:5])
        top10 = set(retrieved_ids[:10])

        r5 = len(gt & top5) / max(1, len(gt))
        r10 = len(gt & top10) / max(1, len(gt))

        r5_sum += r5
        r10_sum += r10

        if gt.issubset(set(retrieved_ids)):
            full_evidence_hits += 1
            if is_mh:
                multihop_hits += 1

    return {
        "configuration": config_name,
        "complement_quota": complement_quota,
        "use_multihop": use_multihop,
        "total_questions": total_q,
        "Recall@5": round(r5_sum / max(1, total_q), 4),
        "Recall@10": round(r10_sum / max(1, total_q), 4),
        "Full_Evidence_Recall": round(full_evidence_hits / max(1, total_q), 4),
        "MultiHop_Recall": round(multihop_hits / max(1, multihop_total), 4) if multihop_total > 0 else 0.0,
    }


def populate_benchmark_corpus(retriever: UnifiedRetrieval, dataset: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Populate retriever belief store, corpus and spatial mind with dataset evidence memories."""
    spatial_mind = retriever._get_spatial_mind()
    spatial_candidates = []
    for item in dataset:
        for ev_id in item["ground_truth_evidence"]:
            content = f"Record {ev_id}: details regarding {item['question']}"
            retriever.belief_store.add_belief(
                category="propositions",
                belief_id=ev_id,
                content=content,
                confidence=0.85,
                stability_index=0.85,
                mass=1.5,
            )
            spatial_candidates.append({
                "id": ev_id,
                "gravity": 1.5,
                "stability_index": 0.85,
                "affective_salience": 0.75,
            })
            if spatial_mind:
                emb = spatial_mind.embed_text(content) if hasattr(spatial_mind, "embed_text") else None
                if emb is not None:
                    spatial_mind.add_memory(ev_id, emb, content=content, importance=0.75, stability_index=0.85)

    retriever.lane_a.sync()
    return spatial_candidates


def run_ablation_experiment(data_path: Optional[str] = None):
    """Run full A/B evaluation suite across the 4 configurations."""
    logger.info("Initializing BeliefStore, PhysicsEngine, and UnifiedRetrieval for ablation experiment...")
    import tempfile
    from core.physics_engine import PhysicsEngine
    tmp_dir = tempfile.mkdtemp()
    beliefs_dir = os.path.join(tmp_dir, "beliefs")
    belief_store = BeliefStore(beliefs_dir)
    physics_engine = PhysicsEngine(data_dir=tmp_dir)
    retriever = UnifiedRetrieval(belief_store=belief_store, physics_engine=physics_engine)

    if data_path and Path(data_path).exists():
        logger.info("Loading dataset from %s", data_path)
        with open(data_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    else:
        logger.info("Generating synthetic 100-question retrieval benchmark set...")
        dataset = generate_synthetic_benchmark_dataset(num_questions=100)

    spatial_candidates = populate_benchmark_corpus(retriever, dataset)

    # 4 Experimental Configurations
    configs = [
        {"name": "Baseline mRAG", "quota": 0, "multihop": False},
        {"name": "mRAG + 1 Spatial Complement", "quota": 1, "multihop": False},
        {"name": "mRAG + 2 Spatial Complements", "quota": 2, "multihop": False},
        {"name": "mRAG + Gravity-Guided Second-Hop Query", "quota": 2, "multihop": True},
    ]

    results = []
    print("\n" + "=" * 70)
    print("  mRAG 8D SPATIAL GRAVITY A/B BENCHMARK EVALUATION (100 QUESTIONS)")
    print("=" * 70)

    for cfg in configs:
        res = evaluate_configuration(
            retriever=retriever,
            dataset=dataset,
            config_name=cfg["name"],
            complement_quota=cfg["quota"],
            use_multihop=cfg["multihop"],
            mock_spatial_candidates=spatial_candidates if cfg["quota"] > 0 else None,
        )
        results.append(res)
        print(f"\nConfiguration: {res['configuration']}")
        print(f"  Recall@5:             {res['Recall@5']:.4f}")
        print(f"  Recall@10:            {res['Recall@10']:.4f}")
        print(f"  Full-Evidence Recall: {res['Full_Evidence_Recall']:.4f}")
        print(f"  Multi-Hop Recall:     {res['MultiHop_Recall']:.4f}")

    print("\n" + "=" * 70)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="mRAG Spatial Gravity A/B Benchmark")
    parser.add_argument("--dataset", type=str, default=None, help="Path to 100-question retrieval JSON dataset")
    args = parser.parse_args()
    
    run_ablation_experiment(data_path=args.dataset)
