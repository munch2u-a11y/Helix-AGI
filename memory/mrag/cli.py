"""Operator CLI for audit, shadow migration, benchmark, promotion, and rollback."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.physics_engine import PhysicsEngine
from memory.mrag.benchmark import BenchmarkRunner, generate_candidate_manifest
from memory.mrag.catalog import (
    SnapshotStore,
    audit_store,
    canonical_json,
    content_fingerprint,
    normalized_text,
    read_jsonl,
    sha256_file,
    write_json_atomic,
)
from memory.mrag.maintenance import NightlyMaintenance, PromotionManager, ReviewApplier
from memory.mrag.models import FocusState, estimate_tokens
from memory.mrag.retrieval import HelixMRAGAdapter, STOPWORDS, _tokens


def state_dir_for(root: Path) -> Path:
    return root / "data" / "memory_reorganization"


class SourceResolver:
    def __init__(self, run_dir: Path):
        self.entries = list(read_jsonl(Path(run_dir) / "catalog.jsonl"))
        self.by_id = {entry["canonical_id"]: entry for entry in self.entries}
        self.beliefs = defaultdict(list)
        self.memories = defaultdict(list)
        for entry in self.entries:
            target = self.beliefs if entry["kind"] == "belief" else self.memories
            target[str(entry.get("original_id", ""))].append(entry)

    def resolve(self, source_id: str, metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if str(metadata.get("type", "")) == "belief" or source_id in self.beliefs:
            records = [
                entry for entry in self.beliefs.get(source_id, [])
                if entry.get("record_role") == "belief_projection"
            ]
            if records:
                return sorted(records, key=lambda item: item["canonical_id"])[0]
        raw_id = str(metadata.get("journal_id") or source_id)
        if raw_id.startswith("mem_"):
            raw_id = raw_id[4:]
        records = self.memories.get(raw_id, [])
        content = str(metadata.get("content", ""))
        if len(records) > 1 and content:
            fingerprint = content_fingerprint(content)
            records = [entry for entry in records if entry["content_fingerprint"] == fingerprint]
            if not records:
                candidates = self.memories.get(raw_id, [])
                source_text = normalized_text(content)
                records = [
                    entry for entry in candidates
                    if normalized_text(entry.get("content", "")).startswith(source_text)
                    or source_text.startswith(normalized_text(entry.get("content", "")))
                ]
            if len(records) > 1 and metadata.get("pulse_id") is not None:
                pulse_matches = [
                    entry for entry in records
                    if entry.get("pulse_id") == metadata.get("pulse_id")
                ]
                if pulse_matches:
                    records = pulse_matches
        return records[0] if len(records) == 1 else None

    @staticmethod
    def candidate(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "canonical_id": entry["canonical_id"],
            "content": entry.get("content", ""),
            "provenance": entry.get("provenance", {}),
        }


class CurrentSemanticRetriever:
    def __init__(self, physics: PhysicsEngine, resolver: SourceResolver, k: int = 10):
        self.physics = physics
        self.resolver = resolver
        self.k = k

    def __call__(self, query: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        embedding = self.physics.embed_text(query["question"])
        raw = self.physics.semantic_index.search(embedding, k=max(100, self.k))
        candidates = []
        seen = set()
        tokens = 0
        for result in raw:
            entry = self.resolver.resolve(result["id"], result.get("metadata", {}))
            if not entry or entry["canonical_id"] in seen:
                continue
            cost = estimate_tokens(entry.get("content", ""))
            if tokens + cost > 500:
                continue
            candidates.append(self.resolver.candidate(entry))
            seen.add(entry["canonical_id"])
            tokens += cost
            if len(candidates) >= self.k:
                break
        return {
            "candidates": candidates,
            "injected_tokens": tokens,
            "latency_ms": (time.perf_counter() - started) * 1000.0,
        }


class CurrentSpatialRetriever:
    def __init__(self, root: Path, physics: PhysicsEngine, resolver: SourceResolver):
        self.physics = physics
        self.resolver = resolver
        self.points = []
        for filename in ("belief_space_state.json", "memory_space_state.json"):
            path = root / "data" / "spatial" / filename
            data = json.loads(path.read_text(encoding="utf-8"))
            for source_id, point in data.items():
                if source_id != "__meta__" and len(point.get("position", [])) == 8:
                    self.points.append((source_id, point))

    def __call__(self, query: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        position = np.asarray(self.physics.embed_and_project(query["question"]), dtype=np.float32)
        ranked = []
        for source_id, point in self.points:
            distance_sq = float(
                np.sum((np.asarray(point["position"], dtype=np.float32) - position) ** 2)
            ) + 1e-4
            gravity = float(point.get("importance", 1.0)) / distance_sq
            ranked.append((gravity, source_id, point))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        candidates = []
        tokens = 0
        seen = set()
        for _gravity, source_id, point in ranked:
            entry = self.resolver.resolve(source_id, point)
            if not entry or entry["canonical_id"] in seen:
                continue
            cost = estimate_tokens(entry.get("content", ""))
            if tokens + cost > 500:
                continue
            candidates.append(self.resolver.candidate(entry))
            seen.add(entry["canonical_id"])
            tokens += cost
            if len(candidates) >= 10:
                break
        return {
            "candidates": candidates,
            "injected_tokens": tokens,
            "latency_ms": (time.perf_counter() - started) * 1000.0,
        }


class UnreorganizedMRAGRetriever:
    """Multi-head diagnostic over all valid legacy records, before tiering."""

    def __init__(self, semantic: CurrentSemanticRetriever, resolver: SourceResolver):
        self.semantic = semantic
        self.resolver = resolver
        self.entries = [
            entry for entry in resolver.entries if entry["retrieval_status"] != "quarantined"
        ]
        self.token_sets = {
            entry["canonical_id"]: set(_tokens(entry.get("content", "")))
            for entry in self.entries
        }

    def __call__(self, query: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        semantic = self.semantic(query)
        scores = defaultdict(float)
        by_id = {entry["canonical_id"]: entry for entry in self.entries}
        for rank, candidate in enumerate(semantic["candidates"], 1):
            scores[candidate["canonical_id"]] += 1.0 / (60 + rank)
        significant = set(_tokens(query["question"])) - STOPWORDS
        lexical = []
        for entry in self.entries:
            overlap = len(significant & self.token_sets[entry["canonical_id"]])
            if overlap:
                lexical.append((overlap, entry["canonical_id"]))
        lexical.sort(key=lambda item: (-item[0], item[1]))
        for rank, (_overlap, canonical_id) in enumerate(lexical[:100], 1):
            scores[canonical_id] += 0.85 / (60 + rank)
        ranked = sorted(scores, key=lambda canonical_id: (-scores[canonical_id], canonical_id))
        candidates = []
        seen_content = set()
        tokens = 0
        for canonical_id in ranked:
            entry = by_id.get(canonical_id)
            if not entry or entry["content_fingerprint"] in seen_content:
                continue
            cost = estimate_tokens(entry.get("content", ""))
            if tokens + cost > 500:
                continue
            candidates.append(self.resolver.candidate(entry))
            seen_content.add(entry["content_fingerprint"])
            tokens += cost
            if len(candidates) >= 10:
                break
        return {
            "candidates": candidates,
            "injected_tokens": tokens,
            "latency_ms": (time.perf_counter() - started) * 1000.0,
        }


def command_audit(args: argparse.Namespace) -> Dict[str, Any]:
    report = audit_store(args.root)
    if args.output:
        write_json_atomic(args.output, report, readonly=True)
    return report


def command_snapshot(args: argparse.Namespace) -> Dict[str, Any]:
    return SnapshotStore(args.root, state_dir_for(args.root)).create(args.benchmark_id)


def command_migrate(args: argparse.Namespace) -> Dict[str, Any]:
    return NightlyMaintenance(
        args.root, state_dir_for(args.root), benchmark_id=args.benchmark_id
    ).run()


def command_init_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    run_dir = state_dir_for(args.root) / "runs" / args.run_id
    return generate_candidate_manifest(run_dir, args.output)


def command_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    run_dir = state_dir_for(args.root) / "runs" / args.run_id
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    run_manifest_path = run_dir / "run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("benchmark_id") != run_manifest.get("benchmark_id"):
        raise ValueError("benchmark identity does not match the shadow run")
    if Path(manifest.get("source_run", "")).resolve() != run_dir.resolve():
        raise ValueError("benchmark worksheet was generated from a different shadow run")
    if args.output.exists():
        raise FileExistsError(f"benchmark report already exists and is immutable: {args.output}")
    runner = BenchmarkRunner(manifest)
    physics = PhysicsEngine(str(args.root / "data" / "spatial"))
    probe = physics.embed_text("Helix benchmark embedding probe")
    if float(np.linalg.norm(probe)) <= 1e-8:
        raise RuntimeError("the configured local 384D embedder is unavailable")
    resolver = SourceResolver(run_dir)
    current_semantic = CurrentSemanticRetriever(physics, resolver)
    current_spatial = CurrentSpatialRetriever(args.root, physics, resolver)
    unreorganized = UnreorganizedMRAGRetriever(current_semantic, resolver)
    adapter = HelixMRAGAdapter(run_dir, embed_query=physics.embed_text)
    index_manifest = json.loads((run_dir / "index_manifest.json").read_text(encoding="utf-8"))
    current_vectors = physics.semantic_index.count
    run_disk = sum(path.stat().st_size for path in run_dir.rglob("*") if path.is_file())
    source_disk = sum(
        path.stat().st_size
        for path in (args.root / "data" / "spatial" / "semantic_index").rglob("*")
        if path.is_file()
    )
    systems = {
        "current_preconscious": runner.evaluate(
            "current_preconscious", current_spatial,
            hot_vector_count=current_vectors, disk_size_bytes=source_disk,
        ),
        "current_384d": runner.evaluate(
            "current_384d", current_semantic,
            hot_vector_count=current_vectors, disk_size_bytes=source_disk,
        ),
        "mrag_unreorganized": runner.evaluate(
            "mrag_unreorganized", unreorganized,
            hot_vector_count=current_vectors, disk_size_bytes=source_disk,
        ),
        "reorganized_mrag": runner.evaluate(
            "reorganized_mrag",
            lambda query: adapter.retrieve(
                query["question"], focus_state=FocusState.WORKING,
                query_position_8d=None, spatial_limit=0,
            ),
            hot_vector_count=index_manifest["hot_vectors"], disk_size_bytes=run_disk,
        ),
        "reorganized_mrag_plus_8d": runner.evaluate(
            "reorganized_mrag_plus_8d",
            lambda query: adapter.retrieve(
                query["question"], focus_state=FocusState.WORKING,
                query_position_8d=physics.embed_and_project(query["question"]), spatial_limit=2,
            ),
            hot_vector_count=index_manifest["hot_vectors"], disk_size_bytes=run_disk,
        ),
    }
    report = runner.compare(systems)
    report["run_id"] = args.run_id
    report["manifest_path"] = str(args.manifest.resolve())
    report["manifest_sha256"] = sha256_file(args.manifest)
    report["run_manifest_sha256"] = sha256_file(run_manifest_path)
    report["snapshot_identity_sha256"] = run_manifest["snapshot"]["identity_sha256"]
    write_json_atomic(args.output, report, readonly=True)
    return report


def command_apply_reviews(args: argparse.Namespace) -> Dict[str, Any]:
    return ReviewApplier(args.root, state_dir_for(args.root)).apply(
        args.run_id, args.decisions
    )


def command_promote(args: argparse.Namespace) -> Dict[str, Any]:
    run_dir = state_dir_for(args.root) / "runs" / args.run_id
    return PromotionManager(state_dir_for(args.root)).promote(run_dir, args.report)


def command_rollback(args: argparse.Namespace) -> Dict[str, Any]:
    target = state_dir_for(args.root) / "runs" / args.to_run if args.to_run else None
    return PromotionManager(state_dir_for(args.root)).rollback(target)


def command_restore_snapshot(args: argparse.Namespace) -> Dict[str, Any]:
    return SnapshotStore(args.root, state_dir_for(args.root)).restore(
        args.snapshot_id, confirmed=args.yes
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Helix memory reorganization operator CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="read-only corpus and index audit")
    audit.add_argument("--output", type=Path)
    audit.set_defaults(handler=command_audit)

    snapshot = subparsers.add_parser("snapshot", help="create checksum-addressed snapshot")
    snapshot.add_argument("--benchmark-id", default="real-memory-120-v1")
    snapshot.set_defaults(handler=command_snapshot)

    migrate = subparsers.add_parser("shadow-migrate", help="build a complete immutable shadow run")
    migrate.add_argument("--benchmark-id", default="real-memory-120-v1")
    migrate.set_defaults(handler=command_migrate)

    nightly = subparsers.add_parser("nightly", help="run safe nightly shadow maintenance")
    nightly.add_argument("--benchmark-id", default="real-memory-120-v1")
    nightly.set_defaults(handler=command_migrate)

    init_benchmark = subparsers.add_parser("init-benchmark", help="create a 120-query review worksheet")
    init_benchmark.add_argument("--run-id", required=True)
    init_benchmark.add_argument("--output", type=Path, required=True)
    init_benchmark.set_defaults(handler=command_init_benchmark)

    benchmark = subparsers.add_parser("benchmark", help="run the reviewed retrieval-only exam")
    benchmark.add_argument("--run-id", required=True)
    benchmark.add_argument("--manifest", type=Path, required=True)
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.set_defaults(handler=command_benchmark)

    reviews = subparsers.add_parser("apply-reviews", help="apply an explicit reviewer decision file")
    reviews.add_argument("--run-id", required=True)
    reviews.add_argument("--decisions", type=Path, required=True)
    reviews.set_defaults(handler=command_apply_reviews)

    promote = subparsers.add_parser("promote", help="activate a run only if all gates pass")
    promote.add_argument("--run-id", required=True)
    promote.add_argument("--report", type=Path, required=True)
    promote.set_defaults(handler=command_promote)

    rollback = subparsers.add_parser("rollback", help="atomically restore a prior active run")
    rollback.add_argument("--to-run")
    rollback.set_defaults(handler=command_rollback)

    restore = subparsers.add_parser("restore-snapshot", help="restore snapshotted source files")
    restore.add_argument("--snapshot-id", required=True)
    restore.add_argument("--yes", action="store_true", help="confirm source-file overwrite")
    restore.set_defaults(handler=command_restore_snapshot)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    try:
        result = args.handler(args)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
