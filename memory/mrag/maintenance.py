"""Nightly shadow maintenance, review application, promotion, and rollback."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from memory.belief_store import BeliefStore
from memory.mrag.catalog import (
    CatalogBuilder,
    ShadowIndexBuilder,
    SnapshotStore,
    canonical_json,
    content_fingerprint,
    read_jsonl,
    sha256_file,
    utc_now,
    write_json_atomic,
    write_jsonl_atomic,
)

MAINTENANCE_SCHEMA_VERSION = "helix-nightly-maintenance-v4"

IMPLEMENTATION_PATHS = (
    "memory/mrag/models.py",
    "memory/mrag/catalog.py",
    "memory/mrag/retrieval.py",
    "memory/mrag/maintenance.py",
    "memory/mrag/benchmark.py",
    "memory/mrag/cli.py",
    "memory/cognitive_journal.py",
    "memory/memory_manager.py",
    "memory/belief_store.py",
    "core/preconscious.py",
    "core/co_occurrence_hook.py",
    "core/affect_field.py",
    "core/cognitive_space.py",
    "core/physics_engine.py",
    "llm/background_daemon.py",
)


def parse_grounded_belief_lines(lines: Iterable[str]) -> List[Dict[str, Any]]:
    """Parse slim source-grounded lines; IDs and metadata stay system-owned.

    Accepted format::

        memory:<canonical-id>[,memory:<canonical-id>]\tPlain durable claim

    Model-produced JSON, IDs, categories, and review flags are deliberately not
    accepted.  Malformed lines are ignored and can never reach active recall.
    """
    candidates = []
    for line in lines:
        line = str(line).strip()
        if not line or "\t" not in line:
            continue
        source_text, claim = line.split("\t", 1)
        claim = " ".join(claim.split()).strip()
        sources = sorted(
            {
                source.strip()
                for source in source_text.split(",")
                if source.strip().startswith("memory:")
            }
        )
        if not sources or not (15 <= len(claim) <= 250):
            continue
        digest = hashlib.sha256(
            canonical_json({"claim": claim, "source_ids": sources})
        ).hexdigest()[:24]
        candidates.append(
            {
                "candidate_id": f"belief-candidate:{digest}",
                "claim": claim,
                "source_ids": sources,
                "status": "pending_review",
            }
        )
    return candidates


class NightlyMaintenance:
    """Build a safe shadow run; never auto-apply semantic decisions."""

    def __init__(
        self,
        root: Path,
        state_dir: Optional[Path] = None,
        benchmark_id: str = "real-memory-120-v1",
    ):
        self.root = Path(root).resolve()
        self.state_dir = Path(state_dir or self.root / "data" / "memory_reorganization")
        self.benchmark_id = benchmark_id
        self.snapshot_store = SnapshotStore(self.root, self.state_dir)

    def run(self, grounded_lines: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        snapshot = self.snapshot_store.create(benchmark_id=self.benchmark_id)
        implementation = self._implementation_manifest()
        config = {
            "schema": MAINTENANCE_SCHEMA_VERSION,
            "snapshot": snapshot["identity_sha256"],
            "implementation": implementation["identity_sha256"],
            "embedding_dimensions": 384,
            "spatial_cap": 2,
            "focus_budgets": {"deep": 300, "working": 500, "open": 700},
        }
        run_id = hashlib.sha256(canonical_json(config)).hexdigest()[:20]
        run_dir = self.state_dir / "runs" / run_id
        final_manifest = run_dir / "run_manifest.json"
        if final_manifest.exists():
            return json.loads(final_manifest.read_text(encoding="utf-8"))

        run_dir.mkdir(parents=True, exist_ok=False)
        build = CatalogBuilder(self.root, run_dir, snapshot).build()
        index_manifest = ShadowIndexBuilder(self.root, run_dir).build()
        catalog = list(read_jsonl(run_dir / "catalog.jsonl"))
        review_queue = list(build.review_queue)
        review_queue.extend(self._semantic_duplicate_reviews(run_dir))

        if grounded_lines is not None:
            review_queue.extend(self._queue_grounded_lines(catalog, grounded_lines))
        review_queue.extend(self._compound_candidates(catalog))
        review_queue = self._deduplicate_reviews(review_queue)
        write_jsonl_atomic(run_dir / "review_queue.jsonl", review_queue)
        catalog_manifest_path = run_dir / "catalog_manifest.json"
        catalog_manifest = json.loads(catalog_manifest_path.read_text(encoding="utf-8"))
        catalog_manifest["review_queue_count"] = len(review_queue)
        write_json_atomic(catalog_manifest_path, catalog_manifest)

        report = {
            "run_id": run_id,
            "snapshot_id": snapshot["snapshot_id"],
            "canonical_entries": len(catalog),
            "review_required": len(review_queue),
            "hot_vectors": index_manifest["hot_vectors"],
            "cold_vectors": index_manifest["cold_vectors"],
            "stale_vectors": index_manifest["stale_vectors"],
            "catalog_counts": build.manifest["catalog_counts"],
            "pungency": build.manifest["pungency"],
            "coverage": build.manifest["coverage"],
            "automatic_changes": [
                "canonical typed-ID catalog",
                "validated retrieval tiers",
                "hot/cold semantic indexes",
                "hot/cold 8D views",
                "bounded directed transition graph",
            ],
            "semantic_changes_applied": 0,
        }
        write_json_atomic(run_dir / "maintenance_report.json", report, readonly=True)

        outputs = []
        for path in sorted(run_dir.rglob("*")):
            if path.is_file() and path.name != "run_manifest.json":
                outputs.append(
                    {
                        "path": str(path.relative_to(run_dir)),
                        "sha256": sha256_file(path),
                        "size": path.stat().st_size,
                    }
                )
        manifest = {
            "schema_version": MAINTENANCE_SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": utc_now(),
            "root": str(self.root),
            "run_dir": str(run_dir),
            "benchmark_id": self.benchmark_id,
            "snapshot": snapshot,
            "implementation": implementation,
            "configuration": config,
            "outputs": outputs,
            "review_queue_count": len(review_queue),
            "promotion_status": "shadow_only",
        }
        write_json_atomic(final_manifest, manifest, readonly=True)
        for path in run_dir.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        return manifest

    def _implementation_manifest(self) -> Dict[str, Any]:
        files = []
        for relative in IMPLEMENTATION_PATHS:
            path = self.root / relative
            if not path.is_file():
                raise FileNotFoundError(
                    f"required maintenance implementation is missing: {path}"
                )
            files.append(
                {
                    "path": relative,
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
        return {
            "identity_sha256": hashlib.sha256(canonical_json(files)).hexdigest(),
            "files": files,
        }

    @staticmethod
    def _semantic_duplicate_reviews(run_dir: Path) -> List[Dict[str, Any]]:
        path = run_dir / "indexes" / "semantic_duplicate_candidates.jsonl"
        reviews = []
        for pair in read_jsonl(path):
            material = canonical_json(
                {"left": pair["left_id"], "right": pair["right_id"]}
            )
            digest = hashlib.sha256(material).hexdigest()[:24]
            reviews.append(
                {
                    "review_id": f"review:{digest}",
                    "decision_type": "semantic_duplicate",
                    "canonical_id": pair["left_id"],
                    "reason": f"cosine similarity {pair['similarity']:.6f}; merge requires review",
                    "status": "pending",
                    "pair": pair,
                }
            )
        return reviews

    def _queue_grounded_lines(
        self, catalog: Sequence[Dict[str, Any]], lines: Iterable[str]
    ) -> List[Dict[str, Any]]:
        by_id = {entry["canonical_id"]: entry for entry in catalog}
        reviews = []
        for candidate in parse_grounded_belief_lines(lines):
            valid, reasons = validate_atomic_fact(
                candidate["claim"], candidate["source_ids"], by_id
            )
            review_id = "review:" + candidate["candidate_id"].split(":")[-1]
            reviews.append(
                {
                    "review_id": review_id,
                    "decision_type": "belief_candidate",
                    "canonical_id": candidate["candidate_id"],
                    "reason": "source-grounded candidate" if valid else "; ".join(reasons),
                    "status": "pending" if valid else "rejected_unsupported",
                    "proposal": {
                        "category": "propositions",
                        "content": candidate["claim"],
                        "fact_refs": [
                            {
                                "claim": candidate["claim"],
                                "source_ids": candidate["source_ids"],
                                "covers_all_source_facts": False,
                                "source_fact_ids": [],
                            }
                        ],
                        "review_status": "pending",
                        "coverage_status": "partial",
                        "compound_type": "atomic",
                    },
                }
            )
        return reviews

    def _compound_candidates(self, catalog: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for belief in catalog:
            if belief["kind"] != "belief" or belief["retrieval_status"] != "hot":
                continue
            if not belief.get("fact_refs"):
                continue
            for label in belief.get("entities", []) or belief.get("topics", []):
                groups[label].append(belief)

        reviews = []
        for label, beliefs in sorted(groups.items()):
            distinct = []
            seen = set()
            for belief in sorted(beliefs, key=lambda item: item["canonical_id"]):
                if belief["content_fingerprint"] not in seen:
                    distinct.append(belief)
                    seen.add(belief["content_fingerprint"])
            if len(distinct) < 2:
                continue
            chosen = distinct[:3]
            facts = [fact for belief in chosen for fact in belief.get("fact_refs", [])]
            content = " ".join(fact["claim"].rstrip(". ") + "." for fact in facts)
            if len(content) > 500:
                continue
            material = canonical_json(
                {"label": label, "beliefs": [belief["canonical_id"] for belief in chosen]}
            )
            digest = hashlib.sha256(material).hexdigest()[:24]
            reviews.append(
                {
                    "review_id": f"review:{digest}",
                    "decision_type": "compound_belief",
                    "canonical_id": f"belief-candidate:{digest}",
                    "reason": f"lossless multi-fact consolidation for shared cluster {label}",
                    "status": "pending",
                    "proposal": {
                        "category": "propositions",
                        "content": content,
                        "fact_refs": facts,
                        "component_ids": [belief["canonical_id"] for belief in chosen],
                        "topics": [label],
                        "entities": [label] if label in chosen[0].get("entities", []) else [],
                        "review_status": "pending",
                        "coverage_status": "verified",
                        "compound_type": "lossless_compound",
                    },
                }
            )
        return reviews[:500]

    @staticmethod
    def _deduplicate_reviews(reviews: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_id = {}
        for review in reviews:
            by_id.setdefault(review["review_id"], review)
        return [by_id[key] for key in sorted(by_id)]


def validate_atomic_fact(
    claim: str,
    source_ids: Sequence[str],
    catalog_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[bool, List[str]]:
    """Strict source validation: claims must be directly present in a source."""
    normalized_claim = " ".join(claim.casefold().split()).strip(" .")
    reasons = []
    supported = False
    for source_id in source_ids:
        source = catalog_by_id.get(source_id)
        if not source or source.get("kind") != "memory":
            reasons.append(f"missing canonical memory source {source_id}")
            continue
        normalized_source = " ".join(source.get("content", "").casefold().split())
        if normalized_claim in normalized_source:
            supported = True
    if not supported and not reasons:
        reasons.append("claim is not a direct source substring")
    return supported, reasons


class ReviewApplier:
    """Apply explicit human decisions; never called by nightly maintenance."""

    def __init__(self, root: Path, state_dir: Optional[Path] = None):
        self.root = Path(root).resolve()
        self.state_dir = Path(state_dir or self.root / "data" / "memory_reorganization")
        self.beliefs = BeliefStore(str(self.root / "data" / "beliefs"))

    def apply(self, run_id: str, decisions_path: Path) -> Dict[str, Any]:
        run_dir = self.state_dir / "runs" / run_id
        queue = {review["review_id"]: review for review in read_jsonl(run_dir / "review_queue.jsonl")}
        decisions = json.loads(Path(decisions_path).read_text(encoding="utf-8"))
        if not isinstance(decisions, list):
            raise ValueError("review decision file must contain a JSON list")
        catalog = {entry["canonical_id"]: entry for entry in read_jsonl(run_dir / "catalog.jsonl")}
        applied = rejected = ignored = 0
        log_records = []
        pungency_overrides = self._load_overrides()

        for decision in decisions:
            review_id = str(decision.get("review_id", ""))
            review = queue.get(review_id)
            outcome = str(decision.get("decision", "")).casefold()
            reviewer = str(decision.get("reviewer", "")).strip()
            if not review or outcome not in {"approve", "reject"} or not reviewer:
                ignored += 1
                continue
            log = {
                "review_id": review_id,
                "decision": outcome,
                "reviewer": reviewer,
                "decided_at": utc_now(),
                "run_id": run_id,
                "reason": decision.get("reason", ""),
            }
            if outcome == "reject":
                rejected += 1
                log_records.append(log)
                continue

            kind = review.get("decision_type")
            if kind in {"belief_candidate", "compound_belief"}:
                self._apply_belief(review["proposal"], catalog)
            elif kind == "pungency":
                retain = bool(decision.get("retain_hot", True))
                pungency_overrides[review["canonical_id"]] = {
                    "retain_hot": retain,
                    "review_id": review_id,
                    "reviewer": reviewer,
                }
            elif kind in {"belief_version_conflict", "contradiction"}:
                winner = str(decision.get("winner_id", ""))
                supersedes = list(decision.get("supersedes", []))
                original = winner.removeprefix("belief:")
                if not original or not self.beliefs.get_belief(original):
                    raise ValueError(f"review winner does not exist: {winner}")
                self.beliefs.update_belief(
                    original,
                    review_status="approved",
                    contradiction_state="resolved",
                    supersedes=[value.removeprefix("belief:") for value in supersedes],
                )
            elif kind == "provenance":
                original = review["canonical_id"].removeprefix("belief:").split(":version:", 1)[0]
                belief = self.beliefs.get_belief(original)
                resolved = [str(value) for value in decision.get("resolved_source_ids", [])]
                if not belief or not resolved:
                    raise ValueError(
                        "provenance approval requires an existing belief and resolved_source_ids"
                    )
                if any(
                    source not in catalog or catalog[source].get("kind") != "memory"
                    for source in resolved
                ):
                    raise ValueError("provenance approval cites a non-canonical memory")
                fact_refs = decision.get("fact_refs", [])
                for fact in fact_refs:
                    valid, reasons = validate_atomic_fact(
                        fact.get("claim", ""), fact.get("source_ids", []), catalog
                    )
                    if not valid:
                        raise ValueError(
                            "unsupported reviewed fact: " + "; ".join(reasons)
                        )
                self.beliefs.update_belief(
                    original,
                    memory_refs=resolved,
                    fact_refs=fact_refs,
                    coverage_status=("verified" if fact_refs else "none"),
                    review_status="approved",
                )
            elif kind == "semantic_duplicate":
                pair = review.get("pair", {})
                winner = str(decision.get("winner_id", ""))
                loser = str(decision.get("loser_id", ""))
                if {winner, loser} != {pair.get("left_id"), pair.get("right_id")}:
                    raise ValueError("semantic duplicate decision must name the queued pair")
                semantic = pungency_overrides.setdefault("semantic_duplicate_losers", {})
                semantic[loser] = {
                    "winner_id": winner,
                    "review_id": review_id,
                    "reviewer": reviewer,
                }
            else:
                ignored += 1
                continue
            applied += 1
            log_records.append(log)

        write_json_atomic(self.state_dir / "review_overrides.json", pungency_overrides)
        self._append_decision_log(log_records)
        return {"applied": applied, "rejected": rejected, "ignored": ignored}

    def _apply_belief(
        self, proposal: Dict[str, Any], catalog: Dict[str, Dict[str, Any]]
    ) -> None:
        for fact in proposal.get("fact_refs", []):
            valid, reasons = validate_atomic_fact(
                fact.get("claim", ""), fact.get("source_ids", []), catalog
            )
            if not valid:
                raise ValueError("unsupported fact in approved proposal: " + "; ".join(reasons))
        category = proposal.get("category", "propositions")
        belief_id = "cmp_" + uuid.uuid4().hex
        stored = self.beliefs.add_belief(
            category=category,
            belief_id=belief_id,
            content=proposal["content"],
            source="reviewed_memory_maintenance",
            fact_refs=proposal.get("fact_refs", []),
            memory_refs=sorted(
                {
                    source
                    for fact in proposal.get("fact_refs", [])
                    for source in fact.get("source_ids", [])
                }
            ),
            component_ids=proposal.get("component_ids", []),
            topics=proposal.get("topics", []),
            entities=proposal.get("entities", []),
            review_status="approved",
            coverage_status=proposal.get("coverage_status", "partial"),
            compound_type=proposal.get("compound_type", "atomic"),
            contradiction_state="none",
        )
        if not stored:
            raise RuntimeError(f"failed to store approved belief {belief_id}")

    def _load_overrides(self) -> Dict[str, Any]:
        path = self.state_dir / "review_overrides.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _append_decision_log(self, records: Sequence[Dict[str, Any]]) -> None:
        if not records:
            return
        path = self.state_dir / "reviews" / "decisions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(canonical_json(record).decode("utf-8") + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class PromotionManager:
    """Atomic active-run pointer with a strict retrieval-only gate."""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir).resolve()
        self.active_path = self.state_dir / "ACTIVE.json"
        self.history_path = self.state_dir / "promotion_history.jsonl"

    def evaluate_gate(self, report: Dict[str, Any]) -> Tuple[bool, List[str]]:
        systems = report.get("systems", {})
        baseline = systems.get("current_384d")
        candidate = systems.get("reorganized_mrag_plus_8d")
        if not baseline or not candidate:
            return False, ["report must include current_384d and reorganized_mrag_plus_8d"]
        failures = []
        direct = candidate.get("direct", {})
        if float(direct.get("sufficient_context_rate", 0.0)) < 0.95:
            failures.append("direct sufficient-context rate is below 95%")
        regressions = candidate.get("baseline_sufficient_regressions", [])
        if regressions:
            failures.append(f"{len(regressions)} baseline-sufficient direct queries regressed")
        for metric in ("sufficient_context_rate", "full_evidence_recall"):
            if float(candidate.get("multi_hop", {}).get(metric, 0.0)) <= float(
                baseline.get("multi_hop", {}).get(metric, 0.0)
            ):
                failures.append(f"multi-hop {metric} did not improve")
        if int(candidate.get("hot_vector_count", 10**18)) >= int(
            baseline.get("hot_vector_count", 0)
        ):
            failures.append("hot vector count did not decrease")
        if float(candidate.get("median_injected_tokens", 10**18)) >= float(
            baseline.get("median_injected_tokens", 0)
        ):
            failures.append("median injected tokens did not decrease")
        if float(candidate.get("topical_contamination", 1.0)) > float(
            baseline.get("topical_contamination", 0.0)
        ):
            failures.append("topical contamination increased")
        baseline_p95 = float(baseline.get("p95_latency_ms", 0.0))
        candidate_p95 = float(candidate.get("p95_latency_ms", 10**18))
        if baseline_p95 <= 0 or candidate_p95 > baseline_p95 * 1.25:
            failures.append("p95 latency exceeds the 25% allowance")
        if int(report.get("unreviewed_queries", 1)) != 0:
            failures.append("benchmark contains unreviewed queries")
        return not failures, failures

    def promote(self, run_dir: Path, benchmark_report: Path) -> Dict[str, Any]:
        run_dir = Path(run_dir).resolve()
        report = json.loads(Path(benchmark_report).read_text(encoding="utf-8"))
        passed, failures = self.evaluate_gate(report)
        if not passed:
            raise ValueError("promotion gate failed: " + "; ".join(failures))
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        if report.get("run_id") and report.get("run_id") != manifest["run_id"]:
            raise ValueError("benchmark report was produced for a different shadow run")
        if report.get("benchmark_id") != manifest.get("benchmark_id"):
            raise ValueError("benchmark identity does not match the shadow run")
        if report.get("run_manifest_sha256") != sha256_file(run_dir / "run_manifest.json"):
            raise ValueError("benchmark report is not bound to this immutable run manifest")
        benchmark_manifest = Path(str(report.get("manifest_path", ""))).resolve()
        if (
            not benchmark_manifest.is_file()
            or report.get("manifest_sha256") != sha256_file(benchmark_manifest)
        ):
            raise ValueError("reviewed benchmark manifest failed checksum validation")
        root = Path(manifest["root"])
        for source in manifest.get("implementation", {}).get("files", []):
            path = root / source["path"]
            if not path.is_file() or sha256_file(path) != source["sha256"]:
                raise ValueError(
                    f"active implementation differs from the shadow run: {path}"
                )
        for output in manifest.get("outputs", []):
            path = run_dir / output["path"]
            if not path.exists() or sha256_file(path) != output["sha256"]:
                raise ValueError(f"immutable run output failed checksum validation: {path}")
        # Pending candidates, quarantined conflicts, and borderline episodes do
        # not influence this run's active indexes.  They may remain in the
        # review queue; the safety invariant is that only already-approved
        # records reached the hot index, which the run manifest/index builder
        # guarantees.
        previous = None
        if self.active_path.exists():
            previous = json.loads(self.active_path.read_text(encoding="utf-8"))
        active = {
            "schema_version": "helix-active-memory-run-v1",
            "run_id": manifest["run_id"],
            "run_dir": str(run_dir),
            "promoted_at": utc_now(),
            "benchmark_report": str(Path(benchmark_report).resolve()),
            "benchmark_report_sha256": sha256_file(Path(benchmark_report)),
            "previous_run_id": previous.get("run_id") if previous else None,
            "previous_run_dir": previous.get("run_dir") if previous else None,
        }
        self._append_history({"action": "promote", **active})
        write_json_atomic(self.active_path, active)
        return active

    def rollback(self, to_run_dir: Optional[Path] = None) -> Dict[str, Any]:
        if not self.active_path.exists():
            raise FileNotFoundError("no active run to roll back")
        current = json.loads(self.active_path.read_text(encoding="utf-8"))
        target = Path(to_run_dir).resolve() if to_run_dir else None
        if target is None and current.get("previous_run_dir"):
            target = Path(current["previous_run_dir"]).resolve()
        if target is None:
            disabled = self.active_path.with_name("ACTIVE.disabled.json")
            self.active_path.replace(disabled)
            record = {
                "action": "rollback_disable",
                "rolled_back_at": utc_now(),
                "from_run_id": current.get("run_id"),
            }
            self._append_history(record)
            return record
        manifest = json.loads((target / "run_manifest.json").read_text(encoding="utf-8"))
        for output in manifest.get("outputs", []):
            path = target / output["path"]
            if not path.exists() or sha256_file(path) != output["sha256"]:
                raise ValueError(f"rollback target failed checksum validation: {path}")
        active = {
            "schema_version": "helix-active-memory-run-v1",
            "run_id": manifest["run_id"],
            "run_dir": str(target),
            "promoted_at": utc_now(),
            "rollback_from": current.get("run_id"),
        }
        self._append_history({"action": "rollback", **active})
        write_json_atomic(self.active_path, active)
        return active

    def _append_history(self, record: Dict[str, Any]) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(record).decode("utf-8") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
