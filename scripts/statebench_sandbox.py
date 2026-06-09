#!/usr/bin/env python3
"""
Helix — Microsoft STATE-Bench Memory Retrieval Sandbox

Evaluates Helix's dual-space memory architecture (384D Semantic Index and 8D Spatial Mind)
against Microsoft's STATE-Bench dataset.

Evaluates:
  - Recall@1, Recall@3, Recall@5 (Task-based Match)
  - Recall@1, Recall@3, Recall@5 (Task-Type-based Match)
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
logger = logging.getLogger("statebench_sandbox")

# ── Metric Normalization & Scoring ────────────────────────────────────

def normalize_answer(s):
    """Normalize text for evaluation (lowercase, remove punctuation/articles)."""
    import re
    import string
    s = str(s).lower()
    exclude = set(string.punctuation)
    s = ''.join(ch for ch in s if ch not in exclude)
    s = re.sub(r'\b(a|an|the|and)\b', ' ', s)
    s = ' '.join(s.split())
    return s

def compute_token_f1(prediction, ground_truth):
    """Calculate token-level F1 overlap."""
    pred_tokens = normalize_answer(prediction).split()
    gt_tokens = normalize_answer(ground_truth).split()
    
    if not pred_tokens or not gt_tokens:
        return 1.0 if pred_tokens == gt_tokens else 0.0
    
    try:
        from nltk.stem import PorterStemmer
        ps = PorterStemmer()
        pred_tokens = [ps.stem(t) for t in pred_tokens]
        gt_tokens = [ps.stem(t) for t in gt_tokens]
    except ImportError:
        pass
        
    common = Counter(pred_tokens) & Counter(gt_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    
    precision = 1.0 * num_same / len(pred_tokens)
    recall = 1.0 * num_same / len(gt_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return f1

# ── Trace Extractor ───────────────────────────────────────────────────

def format_trajectory_trace(trajectory_data):
    """Converts conversation turns and tool calls into a concise procedural string."""
    trace_parts = []
    convo = trajectory_data.get("conversation", [])
    
    for turn in convo:
        role = turn.get("role")
        content = turn.get("content", "")
        if content:
            content = content.strip()
        
        if role == "system":
            # System prompt is usually instructions/policies, capture concisely
            if content:
                # Truncate system prompt to prevent context blowup
                sys_summary = content if len(content) < 150 else content[:150] + "..."
                trace_parts.append(f"System: {sys_summary}")
        elif role == "user":
            if content:
                trace_parts.append(f"User: {content}")
        elif role == "assistant":
            if content:
                trace_parts.append(f"Assistant: {content}")
            
            tool_calls = turn.get("tool_calls") or []
            for tc in tool_calls:
                name = tc.get("name")
                args = tc.get("arguments", {})
                result = tc.get("result", {})
                
                args_str = json.dumps(args, ensure_ascii=False)
                result_str = json.dumps(result, ensure_ascii=False)
                if len(result_str) > 150:
                    result_str = result_str[:150] + "... [truncated]"
                
                trace_parts.append(f"Tool Call: {name}({args_str}) -> {result_str}")
                
    return "\n".join(trace_parts)

def parse_task_id(text_content):
    """Extract task_id (e.g. 13-cancel_partial) from the prefix if present."""
    if text_content.startswith("[TASK:") and "]" in text_content:
        idx = text_content.find("]")
        return text_content[6:idx]
    return None

# ── Main Evaluator ───────────────────────────────────────────────────

def run_evaluation(state_bench_path, num_tasks_per_domain, dry_run=False, save_path=None):
    logger.info(f"Using STATE-Bench path: {state_bench_path}")
    if not os.path.exists(state_bench_path):
        logger.error(f"STATE-Bench repository not found at {state_bench_path}")
        return False

    domains = ["customer_support", "shopping_assistant", "travel"]
    trajectories_dir = os.path.join(state_bench_path, "datasets", "train_task_trajectories")
    
    # Locate all available files
    domain_files = {}
    for d in domains:
        d_dir = os.path.join(trajectories_dir, d)
        if os.path.exists(d_dir):
            files = sorted([f for f in os.listdir(d_dir) if f.endswith(".json")])
            domain_files[d] = files
            logger.info(f"Domain '{d}': Found {len(files)} trajectory files.")
        else:
            logger.warning(f"Domain directory '{d_dir}' not found.")
            domain_files[d] = []

    if dry_run:
        logger.info("=== DRY RUN MODE ===")
        # Verify parser logic on first file of each domain
        for d in domains:
            files = domain_files.get(d, [])
            if not files:
                logger.warning(f"No files available for dry-run in domain {d}.")
                continue
            
            sample_file = files[0]
            task_id = sample_file.replace(".json", "")
            traj_path = os.path.join(trajectories_dir, d, sample_file)
            task_def_path = os.path.join(state_bench_path, "state_bench", "domains", d, "tasks", sample_file)
            
            if not os.path.exists(task_def_path):
                logger.warning(f"Task definition not found at {task_def_path}")
                continue
                
            # Test loading
            with open(traj_path, "r") as f:
                traj_data = json.load(f)
            with open(task_def_path, "r") as f:
                task_data = json.load(f)
                
            trace = format_trajectory_trace(traj_data)
            logger.info(f"[{d}] Dry run parse success for task ID: {task_id}")
            logger.info(f" - Opening Message: {task_data.get('opening_message')}")
            logger.info(f" - Trace length: {len(trace)} characters")
        logger.info("Dry run check passed successfully.")
        return True

    # Import Helix modules only when running
    from core.physics_engine import PhysicsEngine
    from memory.memory_manager import MemoryManager

    # Prepare datasets
    all_eval_tasks = []
    
    for d in domains:
        files = domain_files.get(d, [])
        num_to_take = min(num_tasks_per_domain, len(files))
        logger.info(f"Selecting {num_to_take} tasks from domain '{d}'...")
        
        for i in range(num_to_take):
            filename = files[i]
            task_id = filename.replace(".json", "")
            traj_path = os.path.join(trajectories_dir, d, filename)
            task_def_path = os.path.join(state_bench_path, "state_bench", "domains", d, "tasks", filename)
            
            if not os.path.exists(task_def_path):
                logger.warning(f"Skipping task '{task_id}', definition file not found at: {task_def_path}")
                continue
                
            with open(traj_path, "r") as f:
                traj_data = json.load(f)
            with open(task_def_path, "r") as f:
                task_data = json.load(f)
                
            trace_content = format_trajectory_trace(traj_data)
            
            all_eval_tasks.append({
                "task_id": task_id,
                "domain": d,
                "task_type": task_data.get("task_type", "unknown"),
                "task_summary": task_data.get("task_summary", ""),
                "opening_message": task_data.get("opening_message", ""),
                "trace": trace_content
            })

    if not all_eval_tasks:
        logger.error("No valid evaluation tasks found. Exiting.")
        return False

    # Stats Tracker
    global_results = {
        "semantic": {"recall@1": [], "recall@3": [], "recall@5": [], "type_recall@1": [], "type_recall@3": [], "type_recall@5": [], "f1": [], "latency": []},
        "gravity": {"recall@1": [], "recall@3": [], "recall@5": [], "type_recall@1": [], "type_recall@3": [], "type_recall@5": [], "f1": [], "latency": []}
    }

    # Setup temporary directory for Helix DBs
    with tempfile.TemporaryDirectory() as tmp_dir:
        physics = PhysicsEngine(data_dir=tmp_dir)
        memory_manager = MemoryManager(data_dir=tmp_dir)
        memory_manager.set_physics(physics)

        # 1. Inject procedural learnings into Helix
        logger.info("Injecting STATE-Bench task trajectories into Helix memory...")
        for t_idx, task in enumerate(all_eval_tasks):
            # Construct a clear procedural learning memory block
            payload = f"[TASK:{task['task_id']}] Domain: {task['domain']} | Type: {task['task_type']}\n"
            payload += f"Summary: {task['task_summary']}\n"
            payload += f"Opening Message: {task['opening_message']}\n"
            payload += f"Trace:\n{task['trace']}"

            # Store in MemoryManager and register in Physics
            emb = physics.embed_text(payload)
            physics.add_memory_point(
                memory_id=f"mem_{task['task_id']}",
                text=payload,
                importance=0.8,
                content=payload,
            )
            memory_manager.store(
                content=payload,
                memory_type="observation",
                source="procedural_learning",
                tags=[task['task_id'], task['task_type']],
                embedding_384d=emb.tolist()
            )

        logger.info(f"Successfully seeded {len(all_eval_tasks)} task traces into Helix.")

        # 2. Run Retrieval Evaluation
        logger.info("Running retrieval evaluation...")
        for t_idx, task in enumerate(all_eval_tasks):
            query = task["opening_message"]
            
            # --- Query 384D Semantic Index ---
            t0 = time.perf_counter()
            sem_res = memory_manager.search_semantic(query, limit=5)
            sem_latency = (time.perf_counter() - t0) * 1000.0
            
            # --- Query 8D Manifold ---
            t0 = time.perf_counter()
            grav_res = physics.query_neighborhood(query, k=5)
            grav_latency = (time.perf_counter() - t0) * 1000.0

            # Parse search results
            sem_task_ids = []
            sem_task_types = []
            sem_texts = []
            for r in sem_res:
                tid = parse_task_id(r["content"])
                if tid:
                    sem_task_ids.append(tid)
                    # Find task_type
                    matching_task = next((t for t in all_eval_tasks if t["task_id"] == tid), None)
                    if matching_task:
                        sem_task_types.append(matching_task["task_type"])
                sem_texts.append(r["content"])
                
            grav_task_ids = []
            grav_task_types = []
            grav_texts = []
            for r in grav_res:
                tid = parse_task_id(r["content"])
                if tid:
                    grav_task_ids.append(tid)
                    matching_task = next((t for t in all_eval_tasks if t["task_id"] == tid), None)
                    if matching_task:
                        grav_task_types.append(matching_task["task_type"])
                grav_texts.append(r["content"])

            # --- Score Retrieval ---
            for mode, retrieved_ids, retrieved_types, retrieved_texts, latency, target_dict in [
                ("semantic", sem_task_ids, sem_task_types, sem_texts, sem_latency, global_results["semantic"]),
                ("gravity", grav_task_ids, grav_task_types, grav_texts, grav_latency, global_results["gravity"])
            ]:
                # Task-level Recall (exact match)
                r1 = int(task["task_id"] in retrieved_ids[:1])
                r3 = int(task["task_id"] in retrieved_ids[:3])
                r5 = int(task["task_id"] in retrieved_ids[:5])
                
                # Task-Type Recall (domain procedural similarity match)
                tr1 = int(task["task_type"] in retrieved_types[:1])
                tr3 = int(task["task_type"] in retrieved_types[:3])
                tr5 = int(task["task_type"] in retrieved_types[:5])
                
                # Token F1 of the retrieved procedural trace
                retrieved_context = retrieved_texts[0] if retrieved_texts else ""
                f1_score = compute_token_f1(retrieved_context, task["trace"])

                # Log to stats
                target_dict["recall@1"].append(r1)
                target_dict["recall@3"].append(r3)
                target_dict["recall@5"].append(r5)
                target_dict["type_recall@1"].append(tr1)
                target_dict["type_recall@3"].append(tr3)
                target_dict["type_recall@5"].append(tr5)
                target_dict["f1"].append(f1_score)
                target_dict["latency"].append(latency)

    # ── Aggregate and Report ──────────────────────────────────────────

    report_lines = []
    report_lines.append("# Helix Memory Retrieval Benchmark Report (STATE-Bench)")
    report_lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"**Tasks Evaluated per Domain**: {num_tasks_per_domain} (Total: {len(all_eval_tasks)})")
    report_lines.append("")

    report_lines.append("## Global Metrics Summary")
    report_lines.append("")
    report_lines.append("| Metric | 384D Semantic Search | 8D Physics Manifold | Description |")
    report_lines.append("| :--- | :---: | :---: | :--- |")
    
    for metric_name, key in [
        ("Task Recall@1", "recall@1"),
        ("Task Recall@3", "recall@3"),
        ("Task Recall@5", "recall@5"),
        ("Task-Type Recall@1", "type_recall@1"),
        ("Task-Type Recall@3", "type_recall@3"),
        ("Task-Type Recall@5", "type_recall@5"),
        ("Procedural Trace Token F1", "f1"),
    ]:
        sem_mean = np.mean(global_results["semantic"][key]) * 100.0
        grav_mean = np.mean(global_results["gravity"][key]) * 100.0
        report_lines.append(f"| {metric_name} | {sem_mean:.2f}% | {grav_mean:.2f}% | Recall accuracy or trace token overlap F1. |")

    sem_lat = np.mean(global_results["semantic"]["latency"])
    grav_lat = np.mean(global_results["gravity"]["latency"])
    report_lines.append(f"| Avg Query Latency | {sem_lat:.2f} ms | {grav_lat:.2f} ms | Execution time in milliseconds. |")
    report_lines.append("")

    report_lines.append("## Observations & Insights")
    report_lines.append("- **Task-level Recall** measures whether the exact historical execution trajectory for the user's scenario is retrieved.")
    report_lines.append("- **Task-Type Recall** measures whether a trajectory of the same functional category (e.g. cancellation, exchange) is retrieved, providing relevant procedural guidance even if the exact task was not previously run.")
    report_lines.append("- The **8D Physics Manifold** combines semantic layout with topological recency/gravitational dynamics to refine context retrieval.")
    
    report_content = "\n".join(report_lines)
    print("\n" + report_content + "\n")

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w") as f:
            f.write(report_content)
        logger.info(f"Saved benchmark report to: {save_path}")

    return True

def main():
    parser = argparse.ArgumentParser(description="Helix STATE-Bench Memory Retrieval Sandbox")
    parser.add_argument(
        "--state-bench",
        type=str,
        default="/home/nemo/state_bench",
        help="Path to STATE-Bench repository"
    )
    parser.add_argument(
        "--num-tasks",
        type=int,
        default=5,
        help="Number of tasks per domain to evaluate (1-100)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run parser verification"
    )
    parser.add_argument(
        "--save-results",
        type=str,
        default="/home/nemo/Helix_AGI (GitHub Repo) (Public)/documents/statebench_benchmark_report.md",
        help="Path to save report"
    )

    args = parser.parse_args()
    success = run_evaluation(
        state_bench_path=args.state_bench,
        num_tasks_per_domain=args.num_tasks,
        dry_run=args.dry_run,
        save_path=args.save_results
    )
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
