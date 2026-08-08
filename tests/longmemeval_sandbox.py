#!/usr/bin/env python3
"""Run a bounded, review-first LongMemEval-S development evaluation.

The runner creates a fresh temporary Helix memory system for every question,
indexes that question's historical sessions, and asks the answer through the
normal preconscious injection path.  Exam turns are retrieval-only and every
artifact needed for human review is retained.

This is intentionally a development harness, not an official LongMemEval
judge.  Its exact-match, token-F1, and evidence-retrieval numbers are
transparent diagnostics.  The generated hypotheses JSONL is compatible with
the upstream evaluator if an official judge is wanted later.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import html
import json
import logging
import math
import os
import random
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.providers.base import ProviderConfig
from tests.locomo_deep_memory_sandbox import configure_retrieval
from tests.locomo_sandbox import (
    ABSTENTION_MARKERS,
    build_runtime,
    compute_token_f1,
    normalize_answer,
    reset_question_state,
    run_agent_question,
)


logger = logging.getLogger("longmemeval_sandbox")

MAX_DEV_QUESTIONS = 100
DEFAULT_DATASET = Path("data/benchmarks/longmemeval_s_cleaned.json")
DEFAULT_OUTPUT_DIR = Path("benchmark_results/longmemeval_dev_100")
SESSION_RE = re.compile(r"\[SESSION:\s*([^\]]+)\]")

LONGMEMEVAL_QA_INSTRUCTION = """\
You are Helix answering a memory question about historical conversations.

Rules:
- Use only the historical context recalled through Helix memory.
- Use dates to resolve explicit temporal questions, updates, and relative
  time. The QUESTION DATE is a reference point, not a universal evidence
  cutoff: use all recalled history unless the question itself sets a cutoff.
- Some recalled memories may be distractors; do not treat relevance as truth.
- If the history does not supply the answer, answer "Not mentioned."
- Prefer the shortest direct answer that fully answers the question.
- Return exactly one JSON object: {"answer": "your short answer here"}
- Do not mention the benchmark, retrieval system, or injected context.
- Do not use markdown fences.
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_abstention_item(item: Dict[str, Any]) -> bool:
    """Identify upstream abstention items without looking at hidden turn flags."""
    return str(item.get("question_id", "")).endswith("_abs")


def validate_dataset(data: Any) -> List[str]:
    """Return schema errors for the cleaned LongMemEval-S JSON file."""
    if not isinstance(data, list) or not data:
        return ["dataset must be a non-empty JSON list"]

    errors: List[str] = []
    seen_ids = set()
    for index, item in enumerate(data):
        prefix = f"item[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        required = (
            "question_id", "question_type", "question", "answer",
            "question_date", "haystack_sessions", "haystack_session_ids",
            "haystack_dates", "answer_session_ids",
        )
        missing = [key for key in required if key not in item]
        if missing:
            errors.append(f"{prefix} lacks {', '.join(missing)}")
            continue
        qid = str(item["question_id"])
        if not qid or qid in seen_ids:
            errors.append(f"{prefix} has an empty or duplicate question_id={qid!r}")
        seen_ids.add(qid)

        sessions = item["haystack_sessions"]
        session_ids = item["haystack_session_ids"]
        dates = item["haystack_dates"]
        if not (isinstance(sessions, list) and isinstance(session_ids, list) and isinstance(dates, list)):
            errors.append(f"{prefix} haystack fields must be lists")
            continue
        if not sessions or len(sessions) != len(session_ids) or len(sessions) != len(dates):
            errors.append(f"{prefix} haystack sessions/ids/dates must be non-empty and aligned")
            continue
        # The official cleaned file contains a small number of repeated
        # session IDs (identical transcripts placed at two dates). Preserve
        # those rows exactly instead of silently deduplicating benchmark data.
        known_ids = set(map(str, session_ids))
        unknown_gold = set(map(str, item["answer_session_ids"])) - known_ids
        if unknown_gold:
            errors.append(f"{prefix} answer_session_ids are absent from the haystack: {sorted(unknown_gold)}")
        for session_index, turns in enumerate(sessions):
            if not isinstance(turns, list) or not turns:
                errors.append(f"{prefix}.haystack_sessions[{session_index}] must be non-empty")
                continue
            for turn_index, turn in enumerate(turns):
                if not isinstance(turn, dict) or not turn.get("role") or "content" not in turn:
                    errors.append(
                        f"{prefix}.haystack_sessions[{session_index}][{turn_index}] lacks role/content"
                    )
    return errors


def _stratum(item: Dict[str, Any]) -> Tuple[str, bool]:
    return str(item["question_type"]), is_abstention_item(item)


def stratified_selection(
    data: Sequence[Dict[str, Any]],
    limit: int = MAX_DEV_QUESTIONS,
    seed: int = 42,
) -> Tuple[List[int], Dict[str, int]]:
    """Select a deterministic proportional sample by type and abstention.

    Largest-remainder allocation makes the quotas sum to exactly ``limit``.
    The selected order is also shuffled deterministically so one category does
    not dominate the beginning of a resumable run.
    """
    if limit < 1 or limit > MAX_DEV_QUESTIONS:
        raise ValueError(f"num_questions must be between 1 and {MAX_DEV_QUESTIONS}")
    if limit > len(data):
        raise ValueError(f"requested {limit} questions from a {len(data)}-item dataset")

    groups: Dict[Tuple[str, bool], List[int]] = defaultdict(list)
    for index, item in enumerate(data):
        groups[_stratum(item)].append(index)

    exact = {
        key: limit * len(indices) / len(data)
        for key, indices in groups.items()
    }
    quotas = {key: int(math.floor(value)) for key, value in exact.items()}
    remaining = limit - sum(quotas.values())
    remainder_order = sorted(
        groups,
        key=lambda key: (-(exact[key] - quotas[key]), key[0], key[1]),
    )
    for key in remainder_order[:remaining]:
        quotas[key] += 1

    rng = random.Random(seed)
    selected: List[int] = []
    for key in sorted(groups):
        candidates = list(groups[key])
        rng.shuffle(candidates)
        selected.extend(candidates[:quotas[key]])
    rng.shuffle(selected)

    rendered_quotas = {
        f"{question_type}|{'abstention' if abstention else 'answerable'}": quotas[key]
        for key in sorted(quotas)
        for question_type, abstention in [key]
    }
    return selected, rendered_quotas


def format_session(session_id: str, date: str, turns: Sequence[Dict[str, Any]]) -> str:
    """Render one session while deliberately dropping scorer-only fields."""
    lines = [f"[SESSION: {session_id}]", f"[TIME: {date}]"]
    for turn in turns:
        role = str(turn.get("role", "speaker")).strip().lower()
        label = "User" if role == "user" else "Assistant" if role == "assistant" else role.title()
        lines.append(f"{label}: {turn.get('content', '')}")
    return "\n".join(lines).strip()


def render_sessions(item: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {
            "session_id": str(session_id),
            "date": str(date),
            "content": format_session(str(session_id), str(date), turns),
        }
        for session_id, date, turns in zip(
            item["haystack_session_ids"],
            item["haystack_dates"],
            item["haystack_sessions"],
        )
    ]


def _spatial_embeddings(physics: Any, texts: Sequence[str], batch_size: int = 16) -> np.ndarray:
    embedder = physics._get_embedder()
    if embedder is None:
        return np.zeros((len(texts), 384), dtype=np.float32)
    rows = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start:start + batch_size])
        try:
            vectors = np.asarray(embedder(batch), dtype=np.float32)
        except Exception as exc:
            logger.warning("Spatial embedding batch failed: %s", exc)
            vectors = np.zeros((len(batch), 384), dtype=np.float32)
        if vectors.shape != (len(batch), 384):
            logger.warning("Spatial embedding batch returned %s", vectors.shape)
            vectors = np.zeros((len(batch), 384), dtype=np.float32)
        rows.append(vectors)
    return np.vstack(rows) if rows else np.empty((0, 384), dtype=np.float32)


def index_history(runtime: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Batch-embed and store every historical session in an isolated Helix."""
    physics = runtime["physics"]
    memory = runtime["memory_manager"]
    sessions = render_sessions(item)
    texts = [record["content"] for record in sessions]
    started = time.perf_counter()

    spatial_vectors = _spatial_embeddings(physics, texts)
    semantic_vectors = physics.embed_semantic_batch(texts, is_query=False)
    if semantic_vectors.shape != (len(texts), physics.semantic_encoder.dim):
        raise RuntimeError(
            f"semantic encoder returned {semantic_vectors.shape}; expected "
            f"{(len(texts), physics.semantic_encoder.dim)}"
        )
    if texts and not np.any(np.linalg.norm(semantic_vectors, axis=1) > 1e-8):
        raise RuntimeError("semantic encoder returned only zero vectors")

    preconscious = runtime["preconscious"]
    associative = getattr(preconscious, "_associative", None)
    association_positions: List[Optional[List[float]]] = [None] * len(texts)
    if associative is not None:
        # Match the production resolver: volatile session/date/speaker
        # envelopes do not decide the learned cluster. Batch the stable
        # payloads so history indexing does not turn into one CPU model call
        # per session.
        association_payloads = [
            preconscious._association_payload(text)[:500] for text in texts
        ]
        association_vectors = _spatial_embeddings(physics, association_payloads)
        association_positions = [
            physics.spatial_mind.memory_space.projection.project(vector).tolist()
            for vector in association_vectors
        ]

    projection = physics.spatial_mind.memory_space.projection
    point_sessions: Dict[str, str] = {}
    for sequence, (record, spatial_vector, semantic_vector) in enumerate(
        zip(sessions, spatial_vectors, semantic_vectors), start=1,
    ):
        position = projection.project(spatial_vector).tolist()
        memory_id = memory.store(
            content=record["content"],
            memory_type="conversation_session",
            source="longmemeval_history",
            importance=0.75,
            tags=[
                "longmemeval",
                "timestamped",
                "granularity:session",
                f"session:{record['session_id']}",
            ],
            position_8d=position,
            embedding_384d=spatial_vector.tolist(),
            semantic_embedding_1024d=semantic_vector.tolist(),
            pulse_id=sequence,
        )
        point_id = physics.memory_point_id(memory_id)
        point_sessions[point_id] = record["session_id"]

        if associative is not None:
            cluster_id, prototype = preconscious._resolve_associative_cluster({
                "id": point_id,
                "content": "",
                "position_8d": association_positions[sequence - 1],
            })
            associative.observe(cluster_id, prototype)

        # Carry the historical trajectory through the non-semantic manifold.
        # The temporary run disables semantic-index persistence, so this does
        # not serialize the growing FAISS store every tenth historical pulse.
        physics.step_pulse(
            thought_text="",
            incoming_text=None,
            cluster_centroid=np.asarray(position, dtype=np.float32),
        )

    runtime["_longmemeval_point_sessions"] = point_sessions
    return {
        "sessions": len(sessions),
        "turns": sum(len(turns) for turns in item["haystack_sessions"]),
        "characters": sum(len(text) for text in texts),
        "seconds": round(time.perf_counter() - started, 3),
        "semantic_vectors": int(physics.semantic_index.count),
        "association_graph": (
            associative.get_stats() if associative is not None else {
                "edges": 0, "active_edges": 0, "clusters": 0,
                "previous_cluster": None,
            }
        ),
    }


def prepare_exam(runtime: Dict[str, Any], attention_mode: str) -> None:
    """Clear transient retrieval state, optionally retaining lived trajectory."""
    physics = runtime["physics"]
    if attention_mode == "warm":
        center = np.asarray(physics.attention_center, dtype=np.float32).copy()
        prev_center = getattr(physics.spatial_mind, "prev_center", None)
        prev_center = None if prev_center is None else np.asarray(prev_center, dtype=np.float32).copy()
        velocity = np.asarray(physics.spatial_mind._velocity, dtype=np.float32).copy()
        gamma = float(physics.spatial_mind._gamma)
    reset_question_state(runtime["preconscious"], physics)
    if attention_mode == "warm":
        physics.attention_center = center
        physics.spatial_mind.prev_center = prev_center
        physics.spatial_mind._velocity = velocity
        physics.spatial_mind._gamma = gamma


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def retrieval_record(runtime: Dict[str, Any], injected_context: str = "") -> Dict[str, Any]:
    preconscious = runtime["preconscious"]
    surfaced = set(getattr(preconscious, "_last_surfaced_memory_ids", []) or [])
    selected = getattr(preconscious, "_last_selected_beliefs", []) or []
    point_sessions = runtime.get("_longmemeval_point_sessions", {})
    memories = []
    for item in selected:
        point_id = str(item.get("id", ""))
        if not point_id.startswith("mem_") or point_id not in surfaced:
            continue
        session_id = point_sessions.get(point_id)
        if not session_id:
            match = SESSION_RE.search(str(item.get("content", "")))
            session_id = match.group(1).strip() if match else None
        memories.append({
            "point_id": point_id,
            "session_id": session_id,
            "lane": item.get("lane"),
            "tier": item.get("tier"),
            "rank": item.get("rank"),
            "semantic_score": item.get("semantic_score"),
            "gravity": item.get("gravity"),
            "association_linked": bool(item.get("association_linked")),
            "content": item.get("content", ""),
        })
    unified = getattr(preconscious, "_unified", None)
    selected_session_ids = list(dict.fromkeys(
        record["session_id"] for record in memories if record.get("session_id")
    ))
    context_session_ids = list(dict.fromkeys(
        match.strip() for match in SESSION_RE.findall(injected_context or "") if match.strip()
    ))
    return {
        "memories": _json_safe(memories),
        "selected_session_ids": selected_session_ids,
        # The full injection can also contain Helix's bounded recent-memory
        # continuity block. Evidence diagnostics must count what the model
        # actually saw, not just records attributed to the mRAG selection.
        "context_session_ids": context_session_ids,
        "session_ids": list(dict.fromkeys(selected_session_ids + context_session_ids)),
        "stats": _json_safe(dict(unified.last_stats) if unified is not None else {}),
    }


def answer_diagnostics(prediction: str, gold_answer: str, abstention: bool) -> Dict[str, Any]:
    normalized_prediction = normalize_answer(prediction)
    normalized_gold = normalize_answer(gold_answer)
    markers = tuple(
        normalize_answer(marker)
        for marker in ABSTENTION_MARKERS + ("I don't know", "I do not know")
    )
    predicted_abstention = any(marker and marker in normalized_prediction for marker in markers)
    contains = bool(
        normalized_prediction and normalized_gold and (
            normalized_gold in normalized_prediction or normalized_prediction in normalized_gold
        )
    )
    return {
        "normalized_exact_match": normalized_prediction == normalized_gold,
        "token_f1": round(compute_token_f1(prediction, gold_answer), 6),
        "normalized_contains": contains,
        "gold_is_abstention": abstention,
        "predicted_abstention": predicted_abstention,
        "abstention_match": predicted_abstention if abstention else None,
    }


def evidence_diagnostics(
    retrieved_session_ids: Sequence[str],
    gold_session_ids: Sequence[str],
    abstention: bool,
) -> Dict[str, Any]:
    retrieved = set(map(str, retrieved_session_ids))
    gold = set(map(str, gold_session_ids))
    overlap = retrieved & gold
    return {
        "gold_session_ids": sorted(gold),
        "retrieved_session_ids": list(dict.fromkeys(map(str, retrieved_session_ids))),
        "overlap_session_ids": sorted(overlap),
        "recall": None if abstention or not gold else round(len(overlap) / len(gold), 6),
        "precision": None if not retrieved else round(len(overlap) / len(retrieved), 6),
        "hit": None if abstention or not gold else bool(overlap),
    }


def gold_evidence(item: Dict[str, Any], rendered: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    wanted = set(map(str, item["answer_session_ids"]))
    return [record for record in rendered if record["session_id"] in wanted]


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_safe(payload), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def _markdown_cell(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _review_filename(sequence: int, question_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", question_id)
    return f"{sequence:03d}_{safe_id}.md"


def write_question_review(output_dir: Path, row: Dict[str, Any]) -> None:
    answer_metrics = row["answer_diagnostics"]
    evidence = row["evidence_diagnostics"]
    lines = [
        f"# {row['sequence']:03d} — {row['question_id']}",
        "",
        f"- Type: `{row['question_type']}`",
        f"- Question date: `{row['question_date']}`",
        f"- Abstention item: `{'yes' if row['is_abstention'] else 'no'}`",
        f"- Normalized exact match: `{answer_metrics['normalized_exact_match']}`",
        f"- Token F1 diagnostic: `{answer_metrics['token_f1']:.3f}`",
        f"- Gold-evidence session hit: `{evidence['hit']}`",
        "",
        "## Question",
        "",
        str(row["question"]),
        "",
        "## Gold answer",
        "",
        str(row["gold_answer"]),
        "",
        "## Helix answer",
        "",
        str(row["prediction"]),
        "",
        "## Retrieval attribution",
        "",
        "```json",
        json.dumps({
            "evidence_diagnostics": evidence,
            "selected_session_ids": row["retrieval"].get("selected_session_ids", []),
            "all_context_session_ids": row["retrieval"].get("context_session_ids", []),
            "retrieval_stats": row["retrieval"]["stats"],
            "selected_memories": [
                {key: memory.get(key) for key in (
                    "point_id", "session_id", "lane", "tier", "rank",
                    "semantic_score", "gravity", "association_linked",
                )}
                for memory in row["retrieval"]["memories"]
            ],
        }, indent=2),
        "```",
        "",
        "<details><summary>Gold evidence transcript(s)</summary>",
        "",
        f"<pre>{html.escape(chr(10).join(record['content'] for record in row['gold_evidence']))}</pre>",
        "",
        "</details>",
        "",
        "<details><summary>Context injected into Helix</summary>",
        "",
        f"<pre>{html.escape(row['injected_context'])}</pre>",
        "",
        "</details>",
        "",
        "<details><summary>Raw model response</summary>",
        "",
        f"<pre>{html.escape(row['raw_response'])}</pre>",
        "",
        "</details>",
        "",
        "The automated answer fields above are intentionally heuristic diagnostics, not a final grade.",
    ]
    path = output_dir / "review" / _review_filename(row["sequence"], row["question_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def rebuild_reports(output_dir: Path, manifest: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> None:
    ordered = sorted(rows, key=lambda row: row["sequence"])
    hypotheses_path = output_dir / "hypotheses.jsonl"
    with hypotheses_path.open("w", encoding="utf-8") as handle:
        for row in ordered:
            handle.write(json.dumps({
                "question_id": row["question_id"],
                "hypothesis": row["prediction"],
            }, ensure_ascii=False) + "\n")

    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        by_type[row["question_type"]].append(row)

    summary = {
        "status": "complete" if len(ordered) == manifest["num_questions"] else "incomplete",
        "completed_questions": len(ordered),
        "target_questions": manifest["num_questions"],
        "diagnostic_notice": "Heuristic diagnostics only; review the per-question artifacts.",
        "normalized_exact_match": round(_mean(
            float(row["answer_diagnostics"]["normalized_exact_match"]) for row in ordered
        ), 6),
        "mean_token_f1": round(_mean(
            float(row["answer_diagnostics"]["token_f1"]) for row in ordered
        ), 6),
        "evidence_hit_rate": round(_mean(
            float(row["evidence_diagnostics"]["hit"])
            for row in ordered if row["evidence_diagnostics"]["hit"] is not None
        ), 6),
        "abstention_accuracy": round(_mean(
            float(row["answer_diagnostics"]["abstention_match"])
            for row in ordered if row["answer_diagnostics"]["abstention_match"] is not None
        ), 6),
        "by_type": {
            question_type: {
                "questions": len(type_rows),
                "normalized_exact_match": round(_mean(
                    float(row["answer_diagnostics"]["normalized_exact_match"])
                    for row in type_rows
                ), 6),
                "mean_token_f1": round(_mean(
                    float(row["answer_diagnostics"]["token_f1"])
                    for row in type_rows
                ), 6),
                "evidence_hit_rate": round(_mean(
                    float(row["evidence_diagnostics"]["hit"])
                    for row in type_rows if row["evidence_diagnostics"]["hit"] is not None
                ), 6),
            }
            for question_type, type_rows in sorted(by_type.items())
        },
    }
    _atomic_json(output_dir / "summary.json", summary)

    report = [
        "# LongMemEval-S 100-question development review",
        "",
        f"Status: **{summary['status']}** ({len(ordered)}/{manifest['num_questions']} answered)",
        "",
        "Automated exact match, token F1, and evidence retrieval are transparent diagnostics only. "
        "They are not treated as the final grade; use the linked per-question pages for review.",
        "",
        "## Diagnostic summary",
        "",
        "| Type | Questions | Exact match | Mean token F1 | Evidence hit |",
        "|---|---:|---:|---:|---:|",
    ]
    for question_type, stats in summary["by_type"].items():
        report.append(
            f"| {question_type} | {stats['questions']} | {stats['normalized_exact_match']:.3f} | "
            f"{stats['mean_token_f1']:.3f} | {stats['evidence_hit_rate']:.3f} |"
        )
    report.extend([
        f"| **All** | **{len(ordered)}** | **{summary['normalized_exact_match']:.3f}** | "
        f"**{summary['mean_token_f1']:.3f}** | **{summary['evidence_hit_rate']:.3f}** |",
        "",
        "## Question index",
        "",
        "| # | ID | Type | Question | Gold | Helix | EM | F1 | Evidence |",
        "|---:|---|---|---|---|---|---:|---:|---|",
    ])
    for row in ordered:
        filename = _review_filename(row["sequence"], row["question_id"])
        report.append(
            f"| {row['sequence']} | [{row['question_id']}](review/{filename}) | "
            f"{row['question_type']} | {_markdown_cell(row['question'], 90)} | "
            f"{_markdown_cell(row['gold_answer'], 70)} | {_markdown_cell(row['prediction'], 100)} | "
            f"{int(row['answer_diagnostics']['normalized_exact_match'])} | "
            f"{row['answer_diagnostics']['token_f1']:.3f} | "
            f"{row['evidence_diagnostics']['hit']} |"
        )
    (output_dir / "manual_review.md").write_text("\n".join(report), encoding="utf-8")


def _manifest(
    *,
    dataset_path: Path,
    dataset_sha256: str,
    selected: Sequence[Dict[str, Any]],
    quotas: Dict[str, int],
    seed: int,
    backend: str,
    model: str,
    context_limit: int,
    attention_mode: str,
    association_memory: bool,
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": dataset_sha256,
        "dataset_variant": "longmemeval_s_cleaned",
        "selection_method": "fixed-seed proportional largest-remainder stratification",
        "stratification": "question_type x abstention",
        "selection_seed": seed,
        "stratum_quotas": quotas,
        "num_questions": len(selected),
        "hard_dev_limit": MAX_DEV_QUESTIONS,
        "selected_question_ids": [str(item["question_id"]) for item in selected],
        "provider": backend.replace("-", "_"),
        "model": model,
        "qa_instruction_sha256": hashlib.sha256(
            LONGMEMEVAL_QA_INSTRUCTION.encode("utf-8")
        ).hexdigest(),
        "retrieval_profile": "frontier",
        "context_limit": context_limit,
        "attention_mode": attention_mode,
        "association_memory": association_memory,
        "history_granularity": "session",
        "exam_learns": False,
        "scoring": "review-first; normalized EM/token-F1/evidence recall are diagnostics only",
    }


def _assert_resume_manifest(existing: Dict[str, Any], current: Dict[str, Any]) -> None:
    keys = (
        "dataset_sha256", "selection_seed", "num_questions",
        "selected_question_ids", "provider", "model", "context_limit",
        "qa_instruction_sha256", "attention_mode", "association_memory",
        "history_granularity",
    )
    mismatches = [key for key in keys if existing.get(key) != current.get(key)]
    if mismatches:
        raise ValueError(f"resume manifest differs in: {', '.join(mismatches)}")


def provider_for_backend(
    backend: str,
    model: str,
    context_limit: int,
) -> Tuple[ProviderConfig, str]:
    """Build an explicit benchmark reader without auto-detecting providers."""
    if backend == "ollama":
        reader_model = model or "granite4.1:8b"
        return ProviderConfig(
            provider_type="ollama",
            model=reader_model,
            context_window=context_limit,
            temperature=0.0,
            max_output_tokens=512,
            options={
                "num_ctx": context_limit,
                "num_predict": 512,
                "temperature": 0.0,
                "seed": 7,
            },
        ), reader_model
    if backend == "codex-subscription":
        reader_model = model or "account-default"
        return ProviderConfig(
            provider_type="codex_subscription",
            model=model,
            context_window=context_limit,
            temperature=0.2,
            max_output_tokens=512,
            options={"timeout": int(os.environ.get("HELIX_CODEX_TIMEOUT", "600"))},
        ), reader_model
    raise ValueError(f"unknown reader backend: {backend}")


def run_dev_evaluation(
    *,
    dataset_path: str,
    output_dir: str,
    num_questions: int = MAX_DEV_QUESTIONS,
    seed: int = 42,
    backend: str = "codex-subscription",
    model: str = "",
    context_limit: int = 128_000,
    attention_mode: str = "warm",
    association_memory: bool = True,
    max_retries: int = 3,
    resume: bool = False,
    dry_run: bool = False,
) -> bool:
    if num_questions < 1 or num_questions > MAX_DEV_QUESTIONS:
        raise ValueError(f"--num-questions must be 1..{MAX_DEV_QUESTIONS}")
    dataset_file = Path(dataset_path)
    if not dataset_file.exists():
        raise FileNotFoundError(f"LongMemEval dataset not found: {dataset_file}")

    dataset_hash = _sha256(dataset_file)
    data = json.loads(dataset_file.read_text(encoding="utf-8"))
    dataset_size = len(data) if isinstance(data, list) else 0
    errors = validate_dataset(data)
    if errors:
        preview = "\n".join(errors[:20])
        raise ValueError(f"LongMemEval dataset has {len(errors)} schema error(s):\n{preview}")
    selected_indices, quotas = stratified_selection(data, num_questions, seed)
    selected = [data[index] for index in selected_indices]
    del data
    gc.collect()

    if dry_run:
        counts = Counter(item["question_type"] for item in selected)
        abstentions = sum(is_abstention_item(item) for item in selected)
        print(
            f"LongMemEval dataset valid: {num_questions} selected from {dataset_size}; "
            f"types={dict(sorted(counts.items()))}; abstentions={abstentions}; seed={seed}."
        )
        return True

    configure_retrieval("frontier", association_memory, context_limit)
    os.environ["HELIX_MRAG_RENDER_MODE"] = "verbatim"
    provider, reader_model = provider_for_backend(backend, model, context_limit)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    current_manifest = _manifest(
        dataset_path=dataset_file,
        dataset_sha256=dataset_hash,
        selected=selected,
        quotas=quotas,
        seed=seed,
        backend=backend,
        model=reader_model,
        context_limit=context_limit,
        attention_mode=attention_mode,
        association_memory=association_memory,
    )
    manifest_path = output / "manifest.json"
    details_path = output / "details.jsonl"
    if manifest_path.exists():
        if not resume:
            raise FileExistsError(f"output already exists; use --resume: {output}")
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _assert_resume_manifest(existing_manifest, current_manifest)
        manifest = existing_manifest
    else:
        if details_path.exists():
            raise FileExistsError(f"details exist without a manifest: {details_path}")
        manifest = current_manifest
        _atomic_json(manifest_path, manifest)

    completed_rows = _read_jsonl(details_path)
    completed_ids = [str(row["question_id"]) for row in completed_rows]
    if len(completed_ids) != len(set(completed_ids)):
        raise ValueError("details.jsonl contains duplicate question IDs")
    expected_ids = manifest["selected_question_ids"]
    if any(question_id not in expected_ids for question_id in completed_ids):
        raise ValueError("details.jsonl contains a question outside the manifest")
    # Repair per-question pages if an earlier process stopped after the
    # crash-safe JSONL append but before writing its Markdown companion.
    for row in completed_rows:
        write_question_review(output, row)

    started = time.time()
    completed_set = set(completed_ids)
    for sequence, item in enumerate(selected, start=1):
        question_id = str(item["question_id"])
        if question_id in completed_set:
            continue
        logger.info(
            "[%d/%d] indexing %s (%s, %d sessions)",
            sequence, num_questions, question_id, item["question_type"],
            len(item["haystack_sessions"]),
        )
        with tempfile.TemporaryDirectory(prefix=f"helix_longmemeval_{sequence:03d}_") as tmp_dir:
            runtime = build_runtime(tmp_dir)
            # All benchmark state is ephemeral. Avoid serializing growing
            # semantic/spatial state every tenth historical pulse.
            runtime["physics"]._semantic_index_path = None
            runtime["physics"]._save_attention = lambda: None
            ingest_stats = index_history(runtime, item)
            rendered = render_sessions(item)
            dated_question = (
                f"[QUESTION DATE: {item['question_date']}]\n{item['question']}"
            )

            result = None
            error: Optional[Exception] = None
            for attempt in range(1, max(1, max_retries) + 1):
                prepare_exam(runtime, attention_mode)
                try:
                    result = run_agent_question(
                        runtime,
                        provider,
                        dated_question,
                        max_pulses=1,
                        system_instruction=LONGMEMEVAL_QA_INSTRUCTION,
                        learn=False,
                    )
                    if result["pulses"][-1]["raw_response"].lstrip().startswith(
                        "[internal error:"
                    ):
                        raise RuntimeError(result["pulses"][-1]["raw_response"])
                    error = None
                    break
                except Exception as exc:
                    error = exc
                    logger.warning(
                        "[%d/%d] answer attempt %d/%d failed: %s",
                        sequence, num_questions, attempt, max_retries, exc,
                    )
                    if attempt < max_retries:
                        time.sleep(min(30, 5 * attempt))
            if result is None:
                rebuild_reports(output, manifest, _read_jsonl(details_path))
                raise RuntimeError(
                    f"question {question_id} failed after {max_retries} attempts"
                ) from error

            final_pulse = result["pulses"][-1]
            retrieval = retrieval_record(
                runtime, final_pulse.get("context_string", ""),
            )
            abstention = is_abstention_item(item)
            evidence = evidence_diagnostics(
                retrieval["session_ids"], item["answer_session_ids"], abstention,
            )
            row = {
                "sequence": sequence,
                "question_id": question_id,
                "question_type": item["question_type"],
                "is_abstention": abstention,
                "question_date": item["question_date"],
                "question": item["question"],
                "gold_answer": item["answer"],
                "prediction": result["answer"],
                "raw_response": final_pulse["raw_response"],
                "answer_diagnostics": answer_diagnostics(
                    result["answer"], item["answer"], abstention,
                ),
                "evidence_diagnostics": evidence,
                "retrieval": retrieval,
                "gold_evidence": gold_evidence(item, rendered),
                "injected_context": final_pulse.get("context_string", ""),
                "ingest": ingest_stats,
                "qa_latency_ms": round(result["latency_ms"], 2),
            }
            _append_jsonl(details_path, row)
            write_question_review(output, row)
            completed_rows.append(row)
            completed_set.add(question_id)
            rebuild_reports(output, manifest, completed_rows)
            logger.info(
                "[%d/%d] answered %s: EM=%d F1=%.3f evidence=%s prediction=%r",
                sequence, num_questions, question_id,
                int(row["answer_diagnostics"]["normalized_exact_match"]),
                row["answer_diagnostics"]["token_f1"], evidence["hit"],
                row["prediction"][:160],
            )

    rebuild_reports(output, manifest, completed_rows)
    elapsed = time.time() - started
    logger.info(
        "Stopped at the manifest limit: %d/%d questions in %.1f seconds. Review %s",
        len(completed_rows), num_questions, elapsed, output / "manual_review.md",
    )
    return len(completed_rows) == num_questions


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Bounded, review-first LongMemEval-S sandbox for Helix",
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--num-questions", type=int, default=MAX_DEV_QUESTIONS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--backend", choices=("codex-subscription", "ollama"),
        default="codex-subscription",
    )
    parser.add_argument(
        "--model", default="",
        help="Empty uses the account default for Codex or granite4.1:8b for Ollama",
    )
    parser.add_argument("--context-limit", type=int, default=128_000)
    parser.add_argument("--attention-mode", choices=("warm", "cold"), default="warm")
    parser.add_argument("--association-memory", choices=("on", "off"), default="on")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        success = run_dev_evaluation(
            dataset_path=args.dataset,
            output_dir=args.output_dir,
            num_questions=args.num_questions,
            seed=args.seed,
            backend=args.backend,
            model=args.model,
            context_limit=max(1024, args.context_limit),
            attention_mode=args.attention_mode,
            association_memory=args.association_memory == "on",
            max_retries=max(1, args.max_retries),
            resume=args.resume,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        logger.error("LongMemEval run failed: %s", exc)
        success = False
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
