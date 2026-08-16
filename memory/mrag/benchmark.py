"""Reviewed real-memory retrieval benchmark manifest and metrics."""

from __future__ import annotations

import json
import math
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from memory.mrag.catalog import read_jsonl, utc_now, write_json_atomic
from memory.mrag.models import RetrievalResult, estimate_tokens

BENCHMARK_SCHEMA_VERSION = "helix-real-memory-benchmark-v1"
EXPECTED_COUNTS = {"direct": 80, "multi_hop": 30, "false_premise": 10}


def generate_candidate_manifest(run_dir: Path, output: Path) -> Dict[str, Any]:
    """Create a 120-query review worksheet from real catalog records.

    The worksheet is intentionally marked pending.  Code can propose queries
    and evidence IDs, but cannot impersonate the human approval required by the
    promotion gate.
    """
    entries = [
        entry for entry in read_jsonl(Path(run_dir) / "catalog.jsonl")
        if entry["retrieval_status"] == "hot" and entry["kind"] == "belief"
    ]
    entries.sort(
        key=lambda entry: (
            entry.get("metadata", {}).get("category", ""),
            entry["canonical_id"],
        )
    )
    document_frequency = Counter()
    token_lists = {}
    label_stop = {
        "about", "after", "again", "because", "being", "belief", "could",
        "does", "from", "have", "helix", "into", "recorded", "should",
        "their", "there", "these", "this", "through", "under", "what",
        "when", "where", "which", "with", "would", "people", "concepts",
        "preferences", "premises", "propositions", "skills",
    }
    for entry in entries:
        words = [
            word.casefold()
            for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", entry.get("content", ""))
            if len(word) >= 5 and word.casefold() not in label_stop
        ]
        token_lists[entry["canonical_id"]] = words
        document_frequency.update(set(words))

    def key_phrase(entry: Dict[str, Any], excluded: str = "") -> str:
        words = token_lists[entry["canonical_id"]]
        excluded_words = set(excluded.casefold().split())
        ranked = sorted(
            set(words) - excluded_words,
            key=lambda word: (document_frequency[word], words.index(word), word),
        )[:3]
        return " ".join(ranked)

    def question_label(entry: Dict[str, Any]) -> str:
        label = _entry_label(entry)
        phrase = key_phrase(entry, label)
        if label and phrase:
            return f"{label} concerning {phrase}"
        return label or phrase

    queries = []
    category_buckets = defaultdict(list)
    for entry in entries:
        category_buckets[entry.get("metadata", {}).get("category", "propositions")].append(entry)

    target_mix = {
        "people": 15,
        "preferences": 12,
        "skills": 10,
        "propositions": 20,
        "premises": 10,
        "concepts": 13,
    }
    used_direct = set()
    for category, target in target_mix.items():
        for entry in category_buckets.get(category, []):
            label = question_label(entry)
            if not label:
                continue
            queries.append(
                _query(
                    len(queries) + 1,
                    "direct",
                    f"What is recorded about {label}?",
                    [[entry["canonical_id"]]],
                    entry,
                    notes=f"machine candidate from {category}; verify wording and evidence",
                )
            )
            used_direct.add(entry["canonical_id"])
            if sum(q["category"] == "direct" for q in queries) >= sum(
                target_mix[key] for key in list(target_mix)[: list(target_mix).index(category) + 1]
            ):
                break

    # Deterministic fallback when a category lacks enough named entries.
    for entry in entries:
        if sum(query["category"] == "direct" for query in queries) >= 80:
            break
        if entry["canonical_id"] in used_direct:
            continue
        label = question_label(entry)
        if not label:
            words = entry.get("content", "").split()[:6]
            label = "the belief beginning " + " ".join(words)
        queries.append(
            _query(
                len(queries) + 1,
                "direct",
                f"What durable fact is recorded for {label}?",
                [[entry["canonical_id"]]],
                entry,
                notes="machine fallback candidate; rewrite before approval",
            )
        )
        used_direct.add(entry["canonical_id"])

    groups = defaultdict(list)
    for entry in entries:
        for label in entry.get("entities", []) or entry.get("topics", []):
            groups[label].append(entry)
    used_pairs = set()
    for label, grouped in sorted(groups.items()):
        distinct = []
        for entry in grouped:
            if entry["canonical_id"] not in {item["canonical_id"] for item in distinct}:
                distinct.append(entry)
        for index in range(0, len(distinct) - 1, 2):
            if sum(query["category"] == "multi_hop" for query in queries) >= 30:
                break
            left, right = distinct[index], distinct[index + 1]
            pair = tuple(sorted((left["canonical_id"], right["canonical_id"])))
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            left_phrase = key_phrase(left, label)
            right_phrase = key_phrase(right, label)
            queries.append(
                {
                    "id": f"q{len(queries) + 1:03d}",
                    "category": "multi_hop",
                    "question": (
                        f"How do the records about {label} connect "
                        f"{left_phrase} with {right_phrase}?"
                    ),
                    "gold_evidence_sets": [[left["canonical_id"], right["canonical_id"]]],
                    "acceptable_compound_ids": [],
                    "prohibited_distractors": [],
                    "requires_raw_episode": False,
                    "review_status": "pending",
                    "notes": "verify that the two facts are distinct and the question requires both",
                }
            )
        if sum(query["category"] == "multi_hop" for query in queries) >= 30:
            break

    # Fallback multi-hop pairs remain review-only and never enter a runnable exam.
    if sum(query["category"] == "multi_hop" for query in queries) < 30:
        pair_source = [entry for entry in entries if entry["canonical_id"] in used_direct]
        for index in range(0, len(pair_source) - 1, 2):
            if sum(query["category"] == "multi_hop" for query in queries) >= 30:
                break
            left, right = pair_source[index], pair_source[index + 1]
            queries.append(
                {
                    "id": f"q{len(queries) + 1:03d}",
                    "category": "multi_hop",
                    "question": "REVIEW REQUIRED: write a question requiring both cited facts.",
                    "gold_evidence_sets": [[left["canonical_id"], right["canonical_id"]]],
                    "acceptable_compound_ids": [],
                    "prohibited_distractors": [],
                    "requires_raw_episode": False,
                    "review_status": "pending",
                    "notes": "placeholder evidence pair; do not approve without corpus review",
                }
            )

    labels = [(entry, question_label(entry)) for entry in entries]
    labels = [(entry, label) for entry, label in labels if label]
    for index in range(10):
        left, left_label = labels[index % len(labels)]
        right, right_label = labels[(index + max(11, len(labels) // 3)) % len(labels)]
        queries.append(
            {
                "id": f"q{len(queries) + 1:03d}",
                "category": "false_premise",
                "question": f"Does the record identify {left_label} as {right_label}?",
                "gold_evidence_sets": [[left["canonical_id"], right["canonical_id"]]],
                "acceptable_compound_ids": [],
                "prohibited_distractors": [],
                "requires_raw_episode": False,
                "review_status": "pending",
                "expected_answerability": "false_premise",
                "notes": "verify that the identities are actually distinct before approval",
            }
        )

    counts = Counter(query["category"] for query in queries)
    if dict(counts) != EXPECTED_COUNTS:
        raise ValueError(f"could not generate requested 120-query mix: {dict(counts)}")
    manifest = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_id": "real-memory-120-v1",
        "created_at": utc_now(),
        "source_run": str(Path(run_dir).resolve()),
        "review_status": "pending",
        "counts": EXPECTED_COUNTS,
        "queries": queries,
    }
    write_json_atomic(Path(output), manifest)
    return manifest


def _entry_label(entry: Dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    explicit = str(metadata.get("term") or "").strip()
    if explicit:
        return explicit
    category = str(metadata.get("category") or "").casefold()
    entities = [value for value in entry.get("entities", []) if value != category]
    if entities:
        return entities[0]
    stop = {
        "about", "after", "again", "because", "being", "belief", "could",
        "does", "from", "have", "into", "recorded", "should", "their",
        "there", "these", "this", "through", "under", "what", "when",
        "where", "which", "with", "would",
    }
    words = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", entry.get("content", "")):
        lowered = word.casefold()
        if len(lowered) >= 5 and lowered not in stop and lowered not in words:
            words.append(lowered)
        if len(words) == 3:
            break
    return " ".join(words)


def _query(
    ordinal: int,
    category: str,
    question: str,
    evidence: List[List[str]],
    entry: Dict[str, Any],
    notes: str,
) -> Dict[str, Any]:
    return {
        "id": f"q{ordinal:03d}",
        "category": category,
        "question": question,
        "gold_evidence_sets": evidence,
        "acceptable_compound_ids": (
            [entry["canonical_id"]]
            if entry.get("compound_type") == "lossless_compound"
            else []
        ),
        "prohibited_distractors": [],
        "requires_raw_episode": entry.get("kind") == "memory",
        "review_status": "pending",
        "notes": notes,
    }


def validate_manifest(manifest: Dict[str, Any], *, require_reviewed: bool = True) -> None:
    if manifest.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        raise ValueError("unsupported benchmark manifest schema")
    queries = manifest.get("queries", [])
    counts = Counter(query.get("category") for query in queries)
    if dict(counts) != EXPECTED_COUNTS:
        raise ValueError(f"benchmark category counts must be {EXPECTED_COUNTS}, got {dict(counts)}")
    ids = [query.get("id") for query in queries]
    if len(ids) != len(set(ids)) or None in ids:
        raise ValueError("benchmark query IDs must be present and unique")
    for query in queries:
        if not str(query.get("question", "")).strip():
            raise ValueError(f"blank question: {query.get('id')}")
        if not query.get("gold_evidence_sets"):
            raise ValueError(f"missing evidence set: {query.get('id')}")
        if require_reviewed and query.get("review_status") != "approved":
            raise ValueError(f"query is not approved: {query.get('id')}")


class BenchmarkRunner:
    """Compute retrieval-only metrics; readers are deliberately out of scope."""

    def __init__(self, manifest: Dict[str, Any]):
        validate_manifest(manifest, require_reviewed=True)
        self.manifest = manifest

    def evaluate(
        self,
        name: str,
        retriever: Callable[[Dict[str, Any]], Any],
        *,
        hot_vector_count: int,
        disk_size_bytes: int = 0,
    ) -> Dict[str, Any]:
        rows = []
        for query in self.manifest["queries"]:
            started = time.perf_counter()
            result = retriever(query)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            ids, candidates, tokens, reported_latency = _unpack_result(result)
            latency = reported_latency if reported_latency is not None else elapsed_ms
            rows.append(_score_query(query, ids, candidates, tokens, latency))
        return _aggregate(name, rows, hot_vector_count, disk_size_bytes)

    @staticmethod
    def compare(systems: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        baseline = systems.get("current_384d", {})
        baseline_rows = {row["query_id"]: row for row in baseline.get("rows", [])}
        for system_name, system in systems.items():
            if system_name == "current_384d":
                system["baseline_sufficient_regressions"] = []
                continue
            regressions = []
            for row in system.get("rows", []):
                baseline_row = baseline_rows.get(row["query_id"])
                if (
                    row.get("category") == "direct"
                    and baseline_row
                    and baseline_row.get("sufficient")
                    and not row.get("sufficient")
                ):
                    regressions.append(row["query_id"])
            system["baseline_sufficient_regressions"] = regressions
        return {
            "schema_version": "helix-retrieval-benchmark-report-v1",
            "benchmark_id": "real-memory-120-v1",
            "created_at": utc_now(),
            "reader_tested": False,
            "unreviewed_queries": 0,
            "systems": systems,
        }


def _unpack_result(result: Any) -> Tuple[List[str], List[Dict[str, Any]], int, Optional[float]]:
    if isinstance(result, RetrievalResult):
        candidates = [candidate.to_dict() for candidate in result.candidates]
        ids = [candidate["canonical_id"] for candidate in candidates]
        return ids, candidates, result.injected_tokens, result.stats.get("latency_ms")
    if isinstance(result, dict):
        candidates = result.get("candidates", [])
        ids = result.get("ids") or [
            candidate.get("canonical_id", candidate.get("id")) for candidate in candidates
        ]
        tokens = result.get("injected_tokens")
        if tokens is None:
            tokens = sum(estimate_tokens(candidate.get("content", "")) for candidate in candidates)
        return list(ids), list(candidates), int(tokens), result.get("latency_ms")
    candidates = list(result or [])
    ids = [candidate.get("canonical_id", candidate.get("id")) for candidate in candidates]
    return ids, candidates, sum(estimate_tokens(candidate.get("content", "")) for candidate in candidates), None


def _score_query(
    query: Dict[str, Any],
    ids: List[str],
    candidates: List[Dict[str, Any]],
    tokens: int,
    latency_ms: float,
) -> Dict[str, Any]:
    evidence_sets = [set(values) for values in query["gold_evidence_sets"]]
    acceptable = set(query.get("acceptable_compound_ids", []))
    prohibited = set(query.get("prohibited_distractors", []))
    truncated = {
        candidate.get("canonical_id", candidate.get("id"))
        for candidate in candidates
        if candidate.get("metadata", {}).get("truncated_for_budget")
    }
    effective_ids = [value for value in ids if value not in truncated]
    retrieved = set(effective_ids)
    sufficient = any(values.issubset(retrieved) for values in evidence_sets) or bool(
        acceptable & retrieved
    )
    best_set = max(evidence_sets, key=lambda values: len(values & retrieved) / max(1, len(values)))
    recall5 = len(best_set & set(effective_ids[:5])) / max(1, len(best_set))
    recall10 = len(best_set & set(effective_ids[:10])) / max(1, len(best_set))
    relevant = set().union(*evidence_sets) | acceptable
    first_rank = next((index + 1 for index, value in enumerate(effective_ids) if value in relevant), None)
    gains = [1.0 if value in relevant else 0.0 for value in effective_ids[:10]]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(relevant), 10)))
    provenance_complete = all(
        bool(candidate.get("provenance"))
        for candidate in candidates
        if candidate.get("canonical_id", candidate.get("id")) in relevant
    )
    return {
        "query_id": query["id"],
        "category": query["category"],
        "sufficient": sufficient,
        "recall_at_5": recall5,
        "recall_at_10": recall10,
        "full_evidence": any(values.issubset(retrieved) for values in evidence_sets),
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        "ndcg_at_10": dcg / ideal if ideal else 0.0,
        "topical_contamination": len(prohibited & set(effective_ids[:10])) / max(1, min(10, len(effective_ids))),
        "false_premise_error": query["category"] == "false_premise" and not sufficient,
        "provenance_complete": provenance_complete,
        "injected_tokens": tokens,
        "latency_ms": latency_ms,
        "retrieved_ids": ids[:10],
    }


def _aggregate(
    name: str,
    rows: Sequence[Dict[str, Any]],
    hot_vector_count: int,
    disk_size_bytes: int,
) -> Dict[str, Any]:
    def mean(field: str, subset: Sequence[Dict[str, Any]]) -> float:
        return statistics.mean(float(row[field]) for row in subset) if subset else 0.0

    def section(category: str) -> Dict[str, Any]:
        subset = [row for row in rows if row["category"] == category]
        return {
            "count": len(subset),
            "sufficient_context_rate": mean("sufficient", subset),
            "recall_at_5": mean("recall_at_5", subset),
            "recall_at_10": mean("recall_at_10", subset),
            "full_evidence_recall": mean("full_evidence", subset),
        }

    latencies = sorted(float(row["latency_ms"]) for row in rows)
    tokens = sorted(int(row["injected_tokens"]) for row in rows)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1) if latencies else 0
    return {
        "name": name,
        "direct": section("direct"),
        "multi_hop": section("multi_hop"),
        "false_premise": section("false_premise"),
        "mrr": mean("reciprocal_rank", rows),
        "ndcg_at_10": mean("ndcg_at_10", rows),
        "topical_contamination": mean("topical_contamination", rows),
        "false_premise_error_rate": mean(
            "false_premise_error", [row for row in rows if row["category"] == "false_premise"]
        ),
        "provenance_completeness": mean("provenance_complete", rows),
        "median_injected_tokens": statistics.median(tokens) if tokens else 0,
        "p95_injected_tokens": tokens[p95_index] if tokens else 0,
        "median_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": latencies[p95_index] if latencies else 0.0,
        "hot_vector_count": int(hot_vector_count),
        "disk_size_bytes": int(disk_size_bytes),
        "rows": list(rows),
    }
