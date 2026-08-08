#!/usr/bin/env python3
"""
Helix — mRAG Port Parity Check

Answers one question: does the semantic lane, after being re-pointed at
Helix's stores, still retrieve what Micro-RAG retrieves?

Everything about the port that could silently degrade retrieval lives in the
swap of storage underneath it — Helix's SemanticIndex instead of a Chroma
collection, Helix's belief/journal schema instead of mRAG's, an inverted token
index instead of a per-query regex scan. A recall number on its own can't tell
you whether that swap cost anything, because there's nothing to compare it
against. This runs BOTH implementations over the same LoCoMo dialogue, with
the same embedding model, and reports:

  - evidence Recall@K for each, side by side
  - Jaccard overlap of the retrieved sets, per question

Overlap well below 1.0 with equal recall means the two find different valid
evidence. Overlap near 1.0 means the port is faithful item-for-item. Recall
notably below mRAG's is the failure this exists to catch.

Requires the Micro-RAG source tree (--mrag-path, default /home/nemo/Local-mRag).

Usage:
    python scripts/mrag_port_parity.py --dataset /path/to/locomo10.json -d 0 -q 60
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Set

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mrag_port_parity")

from tests.locomo_sandbox import parse_dia_id  # noqa: E402

RECALL_CUTOFFS = (1, 3, 5, 10, 20)
RETRIEVAL_WINDOW = 20


def mean(values):
    return sum(values) / len(values) if values else 0.0


def load_turns(dialogue) -> List[Dict]:
    conv = dialogue["conversation"]
    session_nums = sorted(
        int(k.split("_")[1]) for k in conv
        if k.startswith("session_") and not k.endswith("_date_time")
    )
    turns = []
    for s_num in session_nums:
        date = conv.get(f"session_{s_num}_date_time", "")
        for turn in conv[f"session_{s_num}"]:
            turns.append({
                "dia_id": turn["dia_id"],
                "speaker": turn["speaker"],
                "text": turn["text"],
                "date": date,
                "session": s_num,
            })
    return turns


def recall_at_k(retrieved_ids: List[str], evidence: List[str]) -> Dict[str, int]:
    return {
        f"recall@{k}": (
            int(any(e in retrieved_ids[:k] for e in evidence)) if evidence else 1
        )
        for k in RECALL_CUTOFFS
    }


# ── Helix port ───────────────────────────────────────────────────────

def build_helix(turns, tmp_dir):
    from core.physics_engine import PhysicsEngine
    from core.unified_retrieval import UnifiedRetrieval
    from memory.belief_store import BeliefStore
    from memory.memory_manager import MemoryManager

    physics = PhysicsEngine(data_dir=tmp_dir)
    memory_manager = MemoryManager(data_dir=tmp_dir)
    memory_manager.set_physics(physics)
    belief_store = BeliefStore(os.path.join(tmp_dir, "beliefs"))

    for idx, turn in enumerate(turns):
        payload = f"[{turn['dia_id']}] {turn['speaker']}: {turn['text']}"
        emb = physics.embed_text(payload)
        memory_manager.store(
            content=payload, memory_type="observation", source=turn["speaker"],
            tags=[turn["dia_id"]], embedding_384d=emb.tolist(), pulse_id=idx,
        )

    unified = UnifiedRetrieval(belief_store=belief_store,
                              memory_manager=memory_manager,
                              physics_engine=physics)
    unified.corpus.all_items()
    return unified


def query_helix(unified, question) -> List[str]:
    items = unified.lane_a.retrieve(question, limit=RETRIEVAL_WINDOW)
    return [d for d in (parse_dia_id(i.get("content", "")) for i in items) if d]


# ── Original mRAG ────────────────────────────────────────────────────

def build_mrag(turns, tmp_dir, mrag_path):
    if mrag_path not in sys.path:
        sys.path.insert(0, mrag_path)

    from mrag.core.pre_generative_injection import PreGenerativeInjector
    from mrag.core.vector_store import ChromaVectorStore
    from mrag.memory.belief_store import BeliefStore as MragBeliefStore

    store = MragBeliefStore(os.path.join(tmp_dir, "mrag_beliefs"))
    # Chroma's DefaultEmbeddingFunction is all-MiniLM-L6-v2 — the same model
    # PhysicsEngine.embed_text uses, so neither side gets an embedding
    # advantage and the comparison isolates the retrieval logic.
    vector_store = ChromaVectorStore(persist_dir=None, collection_name="parity")

    store.load_into_cache()
    for idx, turn in enumerate(turns):
        payload = f"[{turn['dia_id']}] {turn['speaker']}: {turn['text']}"
        store.add_belief(
            category="memory", belief_id=f"mem_{turn['dia_id']}", content=payload,
            confidence=1.0, source="user_input",
            session_id=turn["session"], turn_id=idx, chunk_index=0,
        )

    # mRAG's _pull_relevant_beliefs applies its token budget before returning,
    # so its default (~15x average item length) would cut the list short of
    # RETRIEVAL_WINDOW and understate Recall@10/@20 for reasons that have
    # nothing to do with ranking quality. Raising the ceiling lets rank order,
    # not budget size, decide what the comparison sees — which is the thing
    # being compared, since the Helix lane returns an unbudgeted ranking.
    injector = PreGenerativeInjector(
        store, vector_store,
        top_k_candidates=RETRIEVAL_WINDOW,
        max_injected_tokens=8000,
    )
    injector.sync_index()
    return injector


def query_mrag(injector, question) -> List[str]:
    items = injector._pull_relevant_beliefs(question, limit=RETRIEVAL_WINDOW)
    return [d for d in (parse_dia_id(i.get("content", "")) for i in items) if d]


# ── Comparison ───────────────────────────────────────────────────────

def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def run(dataset_path, dialogue_index, max_questions, mrag_path, save_path):
    with open(dataset_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    dialogue = data[dialogue_index]
    turns = load_turns(dialogue)
    qas = dialogue["qa"][:max_questions] if max_questions else dialogue["qa"]

    print(f"Dialogue {dialogue['sample_id']}: {len(turns)} turns, {len(qas)} questions")

    results = {
        "helix": {f"recall@{k}": [] for k in RECALL_CUTOFFS},
        "mrag": {f"recall@{k}": [] for k in RECALL_CUTOFFS},
    }
    results["helix"]["latency"] = []
    results["mrag"]["latency"] = []
    overlaps = []
    per_question = []

    with tempfile.TemporaryDirectory(prefix="parity_helix_") as helix_dir, \
            tempfile.TemporaryDirectory(prefix="parity_mrag_") as mrag_dir:

        print("Seeding Helix port...")
        unified = build_helix(turns, helix_dir)

        print("Seeding original mRAG...")
        try:
            injector = build_mrag(turns, mrag_dir, mrag_path)
        except Exception as exc:
            print(f"\nCould not build the original mRAG side: {exc}")
            print(f"Checked --mrag-path={mrag_path}. Skipping parity comparison.")
            return False

        print("Querying both...\n")
        for qa in qas:
            question = qa["question"]
            evidence = qa.get("evidence", [])

            t0 = time.perf_counter()
            helix_ids = query_helix(unified, question)
            helix_latency = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            mrag_ids = query_mrag(injector, question)
            mrag_latency = (time.perf_counter() - t0) * 1000.0

            for key, value in recall_at_k(helix_ids, evidence).items():
                results["helix"][key].append(value)
            for key, value in recall_at_k(mrag_ids, evidence).items():
                results["mrag"][key].append(value)
            results["helix"]["latency"].append(helix_latency)
            results["mrag"]["latency"].append(mrag_latency)

            overlap = jaccard(set(helix_ids[:10]), set(mrag_ids[:10]))
            overlaps.append(overlap)
            per_question.append({
                "question": question,
                "evidence": evidence,
                "helix_top10": helix_ids[:10],
                "mrag_top10": mrag_ids[:10],
                "jaccard_top10": round(overlap, 4),
            })

    lines = []
    lines.append("# mRAG Port Parity (LoCoMo)")
    lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Dialogue**: {dialogue['sample_id']} "
                 f"({len(turns)} turns, {len(qas)} questions)")
    lines.append("")
    lines.append("Both sides use all-MiniLM-L6-v2, so this isolates retrieval logic.")
    lines.append("")
    lines.append("| Metric | Helix port (Lane A) | Original mRAG | Delta |")
    lines.append("|---|---|---|---|")
    for k in RECALL_CUTOFFS:
        key = f"recall@{k}"
        h, m = mean(results["helix"][key]), mean(results["mrag"][key])
        lines.append(f"| Recall@{k} | {h:.4f} | {m:.4f} | {h - m:+.4f} |")
    h_lat, m_lat = mean(results["helix"]["latency"]), mean(results["mrag"]["latency"])
    lines.append(f"| Avg latency | {h_lat:.1f} ms | {m_lat:.1f} ms | {h_lat - m_lat:+.1f} ms |")
    lines.append("")
    lines.append(f"**Mean top-10 Jaccard overlap**: {mean(overlaps):.4f}")
    lines.append("")
    lines.append(
        "Overlap near 1.0 means the port is faithful item-for-item. Lower "
        "overlap with equal recall means both find valid evidence by "
        "different routes. Recall materially below mRAG's is a port defect."
    )
    lines.append("")

    report = "\n".join(lines)
    print(report)

    if save_path:
        out = Path(save_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        detail = out.with_suffix(".details.json")
        detail.write_text(json.dumps(per_question, indent=2), encoding="utf-8")
        print(f"Saved: {out} and {detail}")

    return True


def main():
    parser = argparse.ArgumentParser(description="mRAG port parity check")
    parser.add_argument("--dataset", default="locomo10.json")
    parser.add_argument("-d", "--dialogue-index", type=int, default=0)
    parser.add_argument("-q", "--max-questions", type=int, default=60)
    parser.add_argument("--mrag-path", default="/home/nemo/Local-mRag")
    parser.add_argument("--save", default="documents/mrag_port_parity.md")
    args = parser.parse_args()

    ok = run(args.dataset, args.dialogue_index, args.max_questions,
             args.mrag_path, args.save)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
