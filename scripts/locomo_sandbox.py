#!/usr/bin/env python3
"""
Helix — LoCoMo Conversational Memory Benchmark Sandbox

Evaluates Helix's dual-space memory architecture (384D Semantic Index and 8D Spatial Mind)
against the Snap Research LoCoMo dataset.

Evaluates:
  - Recall@1, Recall@3, Recall@5 (Evidence-based and Answer-based)
  - Token-level overlap F1 score of retrieved contexts
  - Average latency per query
"""

import os
import sys
import json
import argparse
import logging
import tempfile
import time
from pathlib import Path
from collections import Counter
import numpy as np

# Ensure Helix packages are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("locomo_sandbox")

# ── Metric Normalization & Scoring ────────────────────────────────────

def normalize_answer(s):
    """Normalize text for evaluation (lowercase, remove punctuation/articles)."""
    import re
    import string
    s = str(s).lower()
    # Remove punctuation
    exclude = set(string.punctuation)
    s = ''.join(ch for ch in s if ch not in exclude)
    # Remove articles
    s = re.sub(r'\b(a|an|the|and)\b', ' ', s)
    # White space fix
    s = ' '.join(s.split())
    return s

def compute_token_f1(prediction, ground_truth):
    """Calculate token-level F1 overlap."""
    pred_tokens = normalize_answer(prediction).split()
    gt_tokens = normalize_answer(ground_truth).split()
    
    if not pred_tokens or not gt_tokens:
        return 1.0 if pred_tokens == gt_tokens else 0.0
    
    # Try Porter Stemmer if available
    try:
        from nltk.stem import PorterStemmer
        ps = PorterStemmer()
        pred_tokens = [ps.stem(t) for t in pred_tokens]
        gt_tokens = [ps.stem(t) for t in gt_tokens]
    except ImportError:
        pass  # Fallback to unstemmed tokens
        
    common = Counter(pred_tokens) & Counter(gt_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    
    precision = 1.0 * num_same / len(pred_tokens)
    recall = 1.0 * num_same / len(gt_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return f1

def compute_multi_f1(prediction, ground_truth):
    """Calculate F1 for comma-separated or multi-answer targets."""
    predictions = [p.strip() for p in prediction.split(',')]
    ground_truths = [g.strip() for g in ground_truth.split(',')]
    return float(np.mean([max([compute_token_f1(p, gt) for p in predictions]) for gt in ground_truths]))

# ── Dialogue Ingestion ──────────────────────────────────────────────

def parse_dia_id(text_content):
    """Extract dia_id (e.g. D1:3) from the prefix if present."""
    if text_content.startswith("[") and "]" in text_content:
        idx = text_content.find("]")
        return text_content[1:idx]
    return None

# ── Main Evaluator ───────────────────────────────────────────────────

def run_evaluation(dataset_path, num_dialogues, dry_run=False, save_path=None):
    logger.info(f"Loading LoCoMo dataset from: {dataset_path}")
    if not os.path.exists(dataset_path):
        logger.error(f"Dataset not found at {dataset_path}")
        return False
        
    with open(dataset_path, "r") as f:
        data = json.load(f)
        
    total_dialogues = len(data)
    num_to_eval = min(num_dialogues, total_dialogues)
    logger.info(f"Dataset contains {total_dialogues} dialogues. Evaluating {num_to_eval}.")

    if dry_run:
        logger.info("=== DRY RUN MODE ===")
        # Just inspect and verify first dialogue
        sample = data[0]
        logger.info(f"Sample ID: {sample['sample_id']}")
        logger.info(f"Conversation sessions: {len(sample['conversation']) - 2} sessions") # excluding speaker_a/b keys
        logger.info(f"QA Pairs: {len(sample['qa'])}")
        logger.info("Dry run check passed successfully.")
        return True

    # Import Helix modules only when running to catch errors early
    from core.physics_engine import PhysicsEngine
    from memory.memory_manager import MemoryManager

    category_names = {
        1: "Multi-hop (Category 1)",
        2: "Temporal (Category 2)",
        3: "Open-domain (Category 3)",
        4: "Single-hop (Category 4)",
        5: "Adversarial (Category 5)"
    }

    # Global Stats
    global_results = {
        "semantic": {"recall@1": [], "recall@3": [], "recall@5": [], "f1": [], "latency": []},
        "gravity": {"recall@1": [], "recall@3": [], "recall@5": [], "f1": [], "latency": []}
    }
    
    # Per-category Stats
    cat_results = {}
    for cat in range(1, 6):
        cat_results[cat] = {
            "semantic": {"recall@1": [], "recall@3": [], "recall@5": [], "f1": []},
            "gravity": {"recall@1": [], "recall@3": [], "recall@5": [], "f1": []}
        }

    # Evaluate each selected dialogue
    for d_idx in range(num_to_eval):
        dialogue = data[d_idx]
        sample_id = dialogue["sample_id"]
        logger.info(f"[{d_idx + 1}/{num_to_eval}] Evaluating Dialogue: {sample_id}")

        # Setup temporary directories for Helix databases
        with tempfile.TemporaryDirectory() as tmp_dir:
            physics = PhysicsEngine(data_dir=tmp_dir)
            memory_manager = MemoryManager(data_dir=tmp_dir)
            memory_manager.set_physics(physics)

            # 1. Chronological Dialogue Injection
            conv = dialogue["conversation"]
            speaker_a = conv.get("speaker_a", "Speaker A")
            speaker_b = conv.get("speaker_b", "Speaker B")
            
            # Find and sort session keys
            session_nums = []
            for key in conv.keys():
                if key.startswith("session_") and not key.endswith("_date_time"):
                    session_nums.append(int(key.split("_")[1]))
            session_nums.sort()

            logger.info(f"Injecting {len(session_nums)} sessions...")
            turn_count = 0
            
            for s_num in session_nums:
                session_key = f"session_{s_num}"
                turns = conv[session_key]
                session_datetime = conv.get(f"{session_key}_date_time", "")

                for turn in turns:
                    speaker = turn["speaker"]
                    dia_id = turn["dia_id"]
                    text = turn["text"]
                    
                    # Construct memory payload containing dialogue ID
                    payload = f"[{dia_id}] {speaker}: {text}"
                    
                    # Store in MemoryManager journal and Register in Physics spaces
                    emb = physics.embed_text(payload)
                    physics.add_memory_point(
                        memory_id=f"mem_{dia_id}",
                        text=payload,
                        importance=0.5,
                        source=speaker,
                        dia_id=dia_id,
                        created_at=session_datetime,
                    )
                    
                    memory_manager.store(
                        content=payload,
                        memory_type="observation",
                        source=speaker,
                        tags=[dia_id],
                        embedding_384d=emb.tolist()
                    )
                    turn_count += 1

            logger.info(f"Seeded {turn_count} dialogue turns into Helix spaces.")

            # 2. Evaluation on Dialogue-Specific QA Pairs
            qas = dialogue["qa"]
            logger.info(f"Running evaluation on {len(qas)} QA pairs...")
            
            # Use tqdm if available
            try:
                from tqdm import tqdm
                qa_iterable = tqdm(qas, desc="QA Pairs")
            except ImportError:
                qa_iterable = qas

            for qa in qa_iterable:
                question = qa["question"]
                answer = qa["answer"]
                category = qa["category"]
                evidence = qa["evidence"] # list of dia_ids, e.g. ['D1:3']

                # Normalize category-specific answer targets (category 3 splits on semicolon in LoCoMo)
                if category == 3:
                    answer_target = answer.split(';')[0].strip()
                else:
                    answer_target = answer

                # --- Query 384D Semantic Index ---
                t0 = time.perf_counter()
                sem_res = memory_manager.search_semantic(question, limit=5)
                sem_latency = (time.perf_counter() - t0) * 1000.0
                
                # --- Query 8D Manifold ---
                t0 = time.perf_counter()
                grav_res = physics.query_neighborhood(question, k=5)
                grav_latency = (time.perf_counter() - t0) * 1000.0

                # Extract retrieved dialogue IDs
                sem_ids = []
                sem_texts = []
                for r in sem_res:
                    did = parse_dia_id(r["content"])
                    if did:
                        sem_ids.append(did)
                    sem_texts.append(r["content"])
                    
                grav_ids = []
                grav_texts = []
                for r in grav_res:
                    did = parse_dia_id(r["content"])
                    if did:
                        grav_ids.append(did)
                    grav_texts.append(r["content"])

                # --- Score Retrieval ---
                for mode, retrieved_ids, retrieved_texts, latency, target_dict in [
                    ("semantic", sem_ids, sem_texts, sem_latency, global_results["semantic"]),
                    ("gravity", grav_ids, grav_texts, grav_latency, global_results["gravity"])
                ]:
                    # Recall@K (evidence overlap check)
                    r1 = int(any(eid in retrieved_ids[:1] for eid in evidence)) if evidence else 1
                    r3 = int(any(eid in retrieved_ids[:3] for eid in evidence)) if evidence else 1
                    r5 = int(any(eid in retrieved_ids[:5] for eid in evidence)) if evidence else 1
                    
                    # Token F1 on concatenated top retrieval context
                    retrieved_context = " ".join(retrieved_texts[:3]) # Use top 3 context window
                    if category == 1:
                        f1_score = compute_multi_f1(retrieved_context, answer_target)
                    elif category == 5:
                        # Adversarial F1
                        pred_lower = retrieved_context.lower()
                        if 'no information available' in pred_lower or 'not mentioned' in pred_lower:
                            f1_score = 1.0 if 'not mentioned' in answer_target.lower() or 'no information' in answer_target.lower() else 0.0
                        else:
                            f1_score = 0.0
                    else:
                        f1_score = compute_token_f1(retrieved_context, answer_target)

                    # Append to Global
                    target_dict["recall@1"].append(r1)
                    target_dict["recall@3"].append(r3)
                    target_dict["recall@5"].append(r5)
                    target_dict["f1"].append(f1_score)
                    target_dict["latency"].append(latency)

                    # Append to Category
                    cat_dict = cat_results[category][mode]
                    cat_dict["recall@1"].append(r1)
                    cat_dict["recall@3"].append(r3)
                    cat_dict["recall@5"].append(r5)
                    cat_dict["f1"].append(f1_score)

    # ── Aggregate and Report ──────────────────────────────────────────

    report_lines = []
    report_lines.append("# Helix Memory Retrieval Benchmark Report (LoCoMo)")
    report_lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"**Dialogues Evaluated**: {num_to_eval}")
    report_lines.append("")

    report_lines.append("## Global Metrics Summary")
    report_lines.append("| Metric | Semantic Index (384D) | Spatial Mind (8D Manifold) |")
    report_lines.append("|---|---|---|")
    
    for metric in ["recall@1", "recall@3", "recall@5", "f1"]:
        sem_val = np.mean(global_results["semantic"][metric])
        grav_val = np.mean(global_results["gravity"][metric])
        report_lines.append(f"| Average {metric.title()} | {sem_val:.4f} | {grav_val:.4f} |")
        
    sem_lat = np.mean(global_results["semantic"]["latency"])
    grav_lat = np.mean(global_results["gravity"]["latency"])
    report_lines.append(f"| Avg Latency (ms) | {sem_lat:.2f} ms | {grav_lat:.2f} ms |")
    report_lines.append("")

    report_lines.append("## Category-Specific Breakdown")
    report_lines.append("### 384D Semantic Index")
    report_lines.append("| Category | Count | Recall@1 | Recall@3 | Recall@5 | Token F1 |")
    report_lines.append("|---|---|---|---|---|---|")
    for cat in range(1, 6):
        cat_dict = cat_results[cat]["semantic"]
        count = len(cat_dict["f1"])
        if count > 0:
            report_lines.append(
                f"| {category_names[cat]} | {count} | {np.mean(cat_dict['recall@1']):.4f} | "
                f"{np.mean(cat_dict['recall@3']):.4f} | {np.mean(cat_dict['recall@5']):.4f} | {np.mean(cat_dict['f1']):.4f} |"
            )
    report_lines.append("")

    report_lines.append("### 8D Spatial Mind (Manifold)")
    report_lines.append("| Category | Count | Recall@1 | Recall@3 | Recall@5 | Token F1 |")
    report_lines.append("|---|---|---|---|---|---|")
    for cat in range(1, 6):
        cat_dict = cat_results[cat]["gravity"]
        count = len(cat_dict["f1"])
        if count > 0:
            report_lines.append(
                f"| {category_names[cat]} | {count} | {np.mean(cat_dict['recall@1']):.4f} | "
                f"{np.mean(cat_dict['recall@3']):.4f} | {np.mean(cat_dict['recall@5']):.4f} | {np.mean(cat_dict['f1']):.4f} |"
            )
    report_lines.append("")

    report_output = "\n".join(report_lines)
    print(report_output)

    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(report_output)
        logger.info(f"Results saved to: {save_path}")

    return True

# ── Entry Point ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Helix LoCoMo Benchmark Sandbox")
    parser.add_argument(
        "--dataset",
        type=str,
        default="/home/nemo/locomo/data/locomo10.json",
        help="Path to locomo10.json dataset"
    )
    parser.add_argument(
        "--num-dialogues",
        type=int,
        default=1,
        help="Number of dialogue scenarios to evaluate (1-10)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and verify dataset structure without running the test"
    )
    parser.add_argument(
        "--save-results",
        type=str,
        default="/home/nemo/Helix_AGI (GitHub Repo) (Public)/documents/locomo_benchmark_report.md",
        help="Path to save the markdown benchmark report"
    )
    
    args = parser.parse_args()
    
    success = run_evaluation(
        dataset_path=args.dataset,
        num_dialogues=args.num_dialogues,
        dry_run=args.dry_run,
        save_path=args.save_results
    )
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
