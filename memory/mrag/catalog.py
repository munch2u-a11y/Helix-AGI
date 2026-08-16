"""Immutable snapshots, canonical catalog construction, and shadow indexes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import statistics
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from memory.cognitive_journal import _checksum as journal_checksum

SCHEMA_VERSION = "helix-derived-catalog-v1"
INDEX_SCHEMA_VERSION = "helix-shadow-index-v1"
APPROVED_REVIEW_STATES = {"approved", "approved_legacy", "legacy_approved"}
VALID_RETRIEVAL_STATES = {"hot", "cold", "quarantined", "superseded"}
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_'-]*")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_fingerprint(text: str) -> str:
    normalized = normalized_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalized_text(text: str) -> str:
    return " ".join(WORD_RE.findall((text or "").casefold()))


def normalize_label(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = " ".join(WORD_RE.findall(value.casefold())).strip()
    return value or None


def normalized_labels(values: Iterable[Any]) -> List[str]:
    result = {label for label in (normalize_label(value) for value in values) if label}
    return sorted(result)


def inferred_entities(text: str) -> List[str]:
    """Conservative proper-name extraction for legacy records without tags."""
    candidates = []
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text or ""):
        word = match.group(0)
        if word.casefold() in {
            "the", "this", "that", "these", "those", "when", "what", "there",
            "helix",  # Helix is useful only when explicitly tagged as a subject.
        }:
            continue
        if match.start() == 0 and not re.search(
            r"\b" + re.escape(word) + r"\b", (text or "")[match.end():]
        ):
            continue
        candidates.append(word)
    return normalized_labels(candidates[:8])


def write_json_atomic(path: Path, value: Any, *, readonly: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(canonical_json(value) + b"\n")
    tmp.replace(path)
    if readonly:
        path.chmod(0o444)


def write_jsonl_atomic(
    path: Path, records: Iterable[Dict[str, Any]], *, readonly: bool = False
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as handle:
        for record in records:
            handle.write(canonical_json(record) + b"\n")
    tmp.replace(path)
    if readonly:
        path.chmod(0o444)


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if raw:
                yield json.loads(raw)


def locate_journal(root: Path) -> Path:
    candidates = [
        root / "data" / "memory" / "cognitive_journal.jsonl",
        root / "data" / "cognitive_journal.jsonl",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size:
            return candidate
    return candidates[0]


class SnapshotStore:
    """Checksum-addressed, deduplicated read-only snapshots."""

    def __init__(self, root: Path, state_dir: Optional[Path] = None):
        self.root = Path(root).resolve()
        self.state_dir = Path(state_dir or self.root / "data" / "memory_reorganization")
        self.snapshots_dir = self.state_dir / "snapshots"
        self.blobs_dir = self.snapshots_dir / "blobs"
        self.manifests_dir = self.snapshots_dir / "manifests"

    def source_paths(self) -> List[Path]:
        paths = [locate_journal(self.root)]
        paths.extend(sorted((self.root / "data" / "beliefs").glob("*.json")))
        optional = [
            self.root / "data" / "spatial" / "belief_space_state.json",
            self.root / "data" / "spatial" / "memory_space_state.json",
            self.root / "data" / "spatial" / "semantic_index" / "embeddings.npy",
            self.root / "data" / "spatial" / "semantic_index" / "ids.json",
            self.root / "data" / "spatial" / "semantic_index" / "metadata.json",
            self.root / "data" / "co_occurrence_state.json",
            self.root / "data" / "affect_field.json",
            self.root / "data" / "pending_beliefs.json",
            self.state_dir / "review_overrides.json",
            self.state_dir / "reviews" / "decisions.jsonl",
        ]
        paths.extend(path for path in optional if path.exists())
        return sorted({path.resolve() for path in paths if path.exists()})

    def create(self, benchmark_id: str = "unassigned") -> Dict[str, Any]:
        files = []
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        for path in self.source_paths():
            digest = sha256_file(path)
            blob = self.blobs_dir / digest
            if not blob.exists():
                tmp = blob.with_suffix(".tmp")
                shutil.copyfile(path, tmp)
                tmp.replace(blob)
                blob.chmod(0o444)
            files.append(
                {
                    "path": str(path.relative_to(self.root)),
                    "sha256": digest,
                    "size": path.stat().st_size,
                    "blob": str(blob.relative_to(self.state_dir)),
                }
            )

        identity = hashlib.sha256(canonical_json(files)).hexdigest()
        snapshot_id = identity[:20]
        manifest = {
            "schema_version": "helix-snapshot-v1",
            "snapshot_id": snapshot_id,
            "identity_sha256": identity,
            "created_at": utc_now(),
            "benchmark_id": benchmark_id,
            "root": str(self.root),
            "files": files,
        }
        path = self.manifests_dir / f"{snapshot_id}.json"
        if not path.exists():
            write_json_atomic(path, manifest, readonly=True)
        else:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        return manifest

    def load(self, snapshot_id: str) -> Dict[str, Any]:
        path = self.manifests_dir / f"{snapshot_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def restore(self, snapshot_id: str, *, confirmed: bool = False) -> Dict[str, Any]:
        """Restore snapshotted source files after explicit confirmation."""
        if not confirmed:
            raise PermissionError("snapshot restore requires confirmed=True")
        manifest = self.load(snapshot_id)
        restored = []
        for record in manifest["files"]:
            target = (self.root / record["path"]).resolve()
            if self.root not in target.parents:
                raise ValueError(f"snapshot target escapes root: {target}")
            blob = self.state_dir / record["blob"]
            if sha256_file(blob) != record["sha256"]:
                raise ValueError(f"snapshot blob checksum mismatch: {blob}")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".restore.tmp")
            shutil.copyfile(blob, tmp)
            tmp.replace(target)
            restored.append(record["path"])
        return {"snapshot_id": snapshot_id, "restored": restored}


@dataclass
class CatalogBuildResult:
    run_dir: Path
    manifest: Dict[str, Any]
    review_queue: List[Dict[str, Any]]


class CatalogBuilder:
    """Canonicalize the existing stores into a disposable retrieval view."""

    def __init__(self, root: Path, run_dir: Path, snapshot: Dict[str, Any]):
        self.root = Path(root).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.snapshot = snapshot
        self.entries: List[Dict[str, Any]] = []
        self.review_queue: List[Dict[str, Any]] = []
        self.quarantine: List[Dict[str, Any]] = []
        self._memory_by_original: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._belief_by_original: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    def build(self) -> CatalogBuildResult:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        journal_counts = self._read_journal()
        belief_counts = self._read_beliefs()
        self._resolve_belief_versions()
        self._mark_exact_duplicates()
        pungency = self._apply_pungency()
        coverage = self._apply_coverage()
        self._build_adjacency()
        transitions = self._build_transitions()

        self.entries.sort(key=lambda entry: entry["canonical_id"])
        write_jsonl_atomic(self.run_dir / "catalog.jsonl", self.entries)
        write_jsonl_atomic(self.run_dir / "quarantine.jsonl", self.quarantine)
        write_jsonl_atomic(self.run_dir / "review_queue.jsonl", self.review_queue)
        write_json_atomic(self.run_dir / "transition_graph.json", transitions)

        counts = Counter(entry["retrieval_status"] for entry in self.entries)
        kinds = Counter(entry["kind"] for entry in self.entries)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": self.snapshot["snapshot_id"],
            "snapshot_identity_sha256": self.snapshot["identity_sha256"],
            "created_at": utc_now(),
            "embedding_model": "all-MiniLM-L6-v2",
            "embedding_dimensions": 384,
            "canonical_store_mutated": False,
            "journal": journal_counts,
            "beliefs": belief_counts,
            "catalog_counts": dict(sorted(counts.items())),
            "kind_counts": dict(sorted(kinds.items())),
            "pungency": pungency,
            "coverage": coverage,
            "review_queue_count": len(self.review_queue),
            "quarantine_count": len(self.quarantine),
        }
        write_json_atomic(self.run_dir / "catalog_manifest.json", manifest)
        return CatalogBuildResult(self.run_dir, manifest, self.review_queue)

    def _read_journal(self) -> Dict[str, Any]:
        path = locate_journal(self.root)
        counts = Counter()
        seen_canonical = Counter()
        previous_id = None
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, 1):
                counts["lines"] += 1
                try:
                    source = json.loads(raw)
                except json.JSONDecodeError as exc:
                    counts["malformed"] += 1
                    self.quarantine.append(
                        {
                            "canonical_id": f"quarantine:journal-line:{line_number}",
                            "source": str(path.relative_to(self.root)),
                            "line": line_number,
                            "reason": "malformed_json",
                            "detail": str(exc),
                        }
                    )
                    continue

                stored_checksum = source.get("checksum")
                payload = dict(source)
                payload.pop("checksum", None)
                computed = journal_checksum(payload)
                if stored_checksum != computed:
                    counts["checksum_failures"] += 1
                    self.quarantine.append(
                        {
                            "canonical_id": f"quarantine:journal-line:{line_number}",
                            "source": str(path.relative_to(self.root)),
                            "line": line_number,
                            "reason": "checksum_mismatch",
                            "stored_checksum": stored_checksum,
                            "computed_checksum": computed,
                        }
                    )
                    continue

                raw_id = str(source.get("id", ""))
                raw_type = str(source.get("type", "memory") or "memory")
                kind = "belief" if raw_type == "belief" else "memory"
                typed_id = self._journal_canonical_id(
                    kind, raw_id, str(source.get("timestamp", "")), raw_type, computed
                )
                seen_canonical[typed_id] += 1
                if seen_canonical[typed_id] > 1:
                    typed_id = f"{typed_id}:copy:{seen_canonical[typed_id]}"

                metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
                lagrangian = source.get("lagrangian") if isinstance(source.get("lagrangian"), dict) else {}
                tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
                topics = normalized_labels(tags)
                entities = normalized_labels(metadata.get("entities", []))
                content = str(source.get("content", ""))
                durable_fact_ids = metadata.get("durable_fact_ids")
                if not isinstance(durable_fact_ids, list) or not durable_fact_ids:
                    durable_fact_ids = [f"fact:{content_fingerprint(content)[:24]}"]

                position = source.get("position_8d")
                if not isinstance(position, list) or len(position) != 8:
                    position = []
                retrieval_status = "superseded" if kind == "belief" else "hot"
                entry = {
                    "schema_version": SCHEMA_VERSION,
                    "canonical_id": typed_id,
                    "kind": kind,
                    "record_role": "belief_history" if kind == "belief" else "canonical_event",
                    "content": content,
                    "content_fingerprint": content_fingerprint(content),
                    "original_id": raw_id,
                    "raw_type": raw_type,
                    "timestamp": source.get("timestamp"),
                    "pulse_id": source.get("pulse_id"),
                    "retrieval_status": retrieval_status,
                    "review_status": "historical" if kind == "belief" else "not_applicable",
                    "contradiction_state": "none",
                    "coverage_status": "none",
                    "compound_type": "atomic",
                    "fact_refs": [],
                    "durable_fact_ids": sorted(str(value) for value in durable_fact_ids),
                    "source_links": [],
                    "relations": [],
                    "adjacent_ids": [],
                    "topics": topics,
                    "entities": entities,
                    "aliases": [],
                    "position_8d": [float(value) for value in position],
                    "stability_index": self._float_or_none(
                        metadata.get("stability_index", lagrangian.get("omega"))
                    ),
                    "affect": {
                        "omega": self._float_or_none(lagrangian.get("omega")),
                        "s_total": self._float_or_none(lagrangian.get("s_total")),
                        "H": self._float_or_none(lagrangian.get("H")),
                        "D_KL": self._float_or_none(lagrangian.get("D_KL")),
                        "delta_omega": self._float_or_none(lagrangian.get("delta_omega")),
                        "severity": lagrangian.get("severity"),
                    },
                    "importance": self._float(metadata.get("importance"), 0.5),
                    "metadata": {
                        "memory_type": metadata.get("memory_type"),
                        "source": metadata.get("source"),
                        "tags": tags,
                        "belief_ids": metadata.get("belief_ids", []),
                        "created_at": metadata.get("created_at"),
                        "severity_before": metadata.get("severity_before"),
                        "severity_after": metadata.get("severity_after"),
                        "delta_omega": metadata.get("delta_omega"),
                        "novelty": metadata.get("novelty"),
                    },
                    "provenance": {
                        "store": "cognitive_journal",
                        "path": str(path.relative_to(self.root)),
                        "line": line_number,
                        "checksum": computed,
                        "original_id": raw_id,
                    },
                    "suppression_reason": "belief_file_projection_preferred" if kind == "belief" else None,
                    "pungency": {},
                    "previous_journal_id": previous_id,
                }
                self.entries.append(entry)
                if kind == "memory":
                    self._memory_by_original[raw_id].append(entry)
                    counts["canonical_events"] += 1
                else:
                    counts["belief_history"] += 1
                previous_id = typed_id
        counts["reused_original_ids"] = sum(
            1 for records in self._memory_by_original.values() if len(records) > 1
        )
        counts["valid_lines"] = counts["canonical_events"] + counts["belief_history"]
        return dict(counts)

    @staticmethod
    def _journal_canonical_id(
        kind: str, raw_id: str, timestamp: str, raw_type: str, checksum: str
    ) -> str:
        if UUID_RE.match(raw_id):
            return f"{kind}:{raw_id.lower()}"
        material = "\x00".join((raw_id, timestamp, raw_type, checksum)).encode("utf-8")
        digest = hashlib.sha256(material).hexdigest()[:24]
        return f"{kind}:legacy-{digest}"

    def _read_beliefs(self) -> Dict[str, Any]:
        counts = Counter()
        beliefs_dir = self.root / "data" / "beliefs"
        for path in sorted(beliefs_dir.glob("*.json")):
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                counts["malformed_files"] += 1
                self.quarantine.append(
                    {
                        "canonical_id": f"quarantine:belief-file:{path.name}",
                        "source": str(path.relative_to(self.root)),
                        "reason": "malformed_belief_file",
                        "detail": str(exc),
                    }
                )
                continue
            if not isinstance(records, list):
                counts["malformed_files"] += 1
                continue
            category = path.stem
            for ordinal, belief in enumerate(records):
                if not isinstance(belief, dict) or not belief.get("id") or not belief.get("content"):
                    counts["malformed_entries"] += 1
                    self.quarantine.append(
                        {
                            "canonical_id": f"quarantine:{path.name}:{ordinal}",
                            "source": str(path.relative_to(self.root)),
                            "reason": "malformed_belief_entry",
                        }
                    )
                    continue
                original_id = str(belief["id"])
                content = str(belief["content"])
                position = belief.get("position_8d")
                if not isinstance(position, list) or len(position) != 8:
                    position = []
                review_status = str(belief.get("review_status") or "legacy_approved")
                coverage_status = str(belief.get("coverage_status") or "none")
                compound_type = str(belief.get("compound_type") or "atomic")
                contradiction = str(belief.get("contradiction_state") or "none")
                aliases = normalized_labels(belief.get("aliases", []))
                entities = normalized_labels(
                    list(belief.get("entities", []) or [])
                    + ([belief.get("term")] if belief.get("term") else [])
                    + aliases
                    + inferred_entities(content)
                )
                topics = normalized_labels(
                    list(belief.get("topics", []) or [])
                    + list(belief.get("tags", []) or [])
                    + [category]
                )
                memory_links, unresolved = self._resolve_memory_refs(
                    belief.get("memory_refs", []), belief.get("created_at")
                )
                fact_refs = self._normalize_fact_refs(belief.get("fact_refs", []))
                relations = [
                    value if str(value).startswith("belief:") else f"belief:{value}"
                    for value in belief.get("relations", []) or []
                    if value not in (None, "", -1, "-1")
                ]
                entry = {
                    "schema_version": SCHEMA_VERSION,
                    "canonical_id": f"belief:{original_id}",
                    "kind": "belief",
                    "record_role": "belief_projection",
                    "content": content,
                    "content_fingerprint": content_fingerprint(content),
                    "original_id": original_id,
                    "raw_type": "belief",
                    "timestamp": belief.get("created_at"),
                    "pulse_id": belief.get("creation_pulse"),
                    "retrieval_status": "hot" if review_status in APPROVED_REVIEW_STATES else "quarantined",
                    "review_status": review_status,
                    "contradiction_state": contradiction,
                    "coverage_status": coverage_status,
                    "compound_type": compound_type,
                    "fact_refs": fact_refs,
                    "durable_fact_ids": [],
                    "source_links": sorted(set(memory_links)),
                    "unresolved_source_refs": unresolved,
                    "relations": sorted(set(relations)),
                    "adjacent_ids": [],
                    "topics": topics,
                    "entities": entities,
                    "aliases": aliases,
                    "position_8d": [float(value) for value in position],
                    "stability_index": self._float_or_none(belief.get("stability_index")),
                    "affect": dict(belief.get("encoding_lagrangian") or {}),
                    "importance": self._float(belief.get("mass"), 1.0),
                    "confidence": self._float(belief.get("confidence"), 0.5),
                    "supersedes": [
                        value if str(value).startswith("belief:") else f"belief:{value}"
                        for value in belief.get("supersedes", []) or []
                    ],
                    "component_ids": [
                        value if str(value).startswith(("belief:", "memory:")) else f"belief:{value}"
                        for value in belief.get("component_ids", []) or []
                    ],
                    "metadata": {
                        "category": category,
                        "source": belief.get("source"),
                        "term": belief.get("term"),
                        "verifications": belief.get("verifications"),
                        "memory_refs": belief.get("memory_refs", []),
                    },
                    "provenance": {
                        "store": "belief_files",
                        "path": str(path.relative_to(self.root)),
                        "ordinal": ordinal,
                        "checksum": hashlib.sha256(canonical_json(belief)).hexdigest(),
                        "original_id": original_id,
                    },
                    "suppression_reason": None,
                    "pungency": {},
                }
                if contradiction == "unresolved":
                    entry["retrieval_status"] = "quarantined"
                    self.review_queue.append(
                        self._review_item("contradiction", entry, "unresolved contradiction")
                    )
                if unresolved:
                    self.review_queue.append(
                        self._review_item(
                            "provenance", entry, "ambiguous or missing legacy memory refs"
                        )
                    )
                self.entries.append(entry)
                self._belief_by_original[original_id].append(entry)
                counts["canonical_entries"] += 1
        counts["reused_ids"] = sum(
            1 for records in self._belief_by_original.values() if len(records) > 1
        )
        return dict(counts)

    def _resolve_memory_refs(
        self, refs: Sequence[Any], belief_time: Optional[str]
    ) -> Tuple[List[str], List[Any]]:
        resolved: List[str] = []
        unresolved: List[Any] = []
        for ref in refs or []:
            if ref in (None, "", -1, "-1", True, False):
                continue
            text = str(ref)
            if text.startswith("memory:"):
                resolved.append(text)
                continue
            if text.startswith("mem_"):
                text = text[4:]
            records = self._memory_by_original.get(text, [])
            if len(records) == 1:
                resolved.append(records[0]["canonical_id"])
                continue
            if len(records) > 1 and belief_time:
                eligible = [
                    record for record in records
                    if str(record.get("timestamp") or "") <= str(belief_time)
                ]
                eligible.sort(key=lambda record: str(record.get("timestamp") or ""))
                if eligible:
                    # Temporal resolution is useful for provenance display but
                    # remains too weak to authorize coverage suppression.
                    resolved.append(eligible[-1]["canonical_id"])
                    unresolved.append({"ref": ref, "reason": "legacy_reuse_temporal_guess"})
                    continue
            unresolved.append({"ref": ref, "reason": "unresolved"})
        return resolved, unresolved

    @staticmethod
    def _normalize_fact_refs(values: Sequence[Any]) -> List[Dict[str, Any]]:
        normalized = []
        for value in values or []:
            if not isinstance(value, dict) or not value.get("claim"):
                continue
            sources = value.get("source_ids", value.get("sources", []))
            if not isinstance(sources, list):
                sources = [sources]
            source_ids = []
            for source in sources:
                text = str(source)
                if text.startswith("memory:"):
                    source_ids.append(text)
            normalized.append(
                {
                    "claim": str(value["claim"]).strip(),
                    "source_ids": sorted(set(source_ids)),
                    "source_fact_ids": sorted(
                        str(item) for item in value.get("source_fact_ids", []) or []
                    ),
                    "covers_all_source_facts": bool(value.get("covers_all_source_facts", False)),
                }
            )
        return normalized

    def _resolve_belief_versions(self) -> None:
        for original_id, records in self._belief_by_original.items():
            if len(records) < 2:
                continue
            ranked = sorted(
                records,
                key=lambda record: (
                    record.get("review_status") in APPROVED_REVIEW_STATES,
                    record.get("confidence", 0.0),
                    record.get("timestamp") or "",
                    record["provenance"]["path"],
                ),
                reverse=True,
            )
            winner = ranked[0]
            distinct = {record["content_fingerprint"] for record in ranked}
            for ordinal, record in enumerate(ranked[1:], 1):
                digest = record["provenance"]["checksum"][:12]
                record["canonical_id"] = f"belief:{original_id}:version:{digest}"
                record["retrieval_status"] = "superseded"
                record["suppression_reason"] = f"version_of:{winner['canonical_id']}"
            if len(distinct) > 1:
                winner["retrieval_status"] = "quarantined"
                winner["suppression_reason"] = "conflicting_reused_belief_id"
                self.review_queue.append(
                    self._review_item(
                        "belief_version_conflict",
                        winner,
                        f"{len(records)} records reuse belief ID {original_id}",
                    )
                )

    def _mark_exact_duplicates(self) -> None:
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for entry in self.entries:
            if entry["retrieval_status"] not in {"quarantined", "superseded"}:
                groups[(entry["kind"], entry["content_fingerprint"])].append(entry)
        for records in groups.values():
            if len(records) < 2:
                continue
            records.sort(
                key=lambda entry: (
                    entry["kind"] == "belief",
                    entry.get("review_status") in APPROVED_REVIEW_STATES,
                    entry.get("importance", 0.0),
                    entry.get("timestamp") or "",
                    entry["canonical_id"],
                ),
                reverse=True,
            )
            winner = records[0]
            for duplicate in records[1:]:
                duplicate["retrieval_status"] = "superseded"
                duplicate["suppression_reason"] = f"exact_duplicate_of:{winner['canonical_id']}"
        overrides = self._semantic_duplicate_overrides()
        for loser_id, decision in overrides.items():
            loser = next(
                (entry for entry in self.entries if entry["canonical_id"] == loser_id), None
            )
            winner_id = str(decision.get("winner_id", ""))
            if loser and any(entry["canonical_id"] == winner_id for entry in self.entries):
                loser["retrieval_status"] = "superseded"
                loser["suppression_reason"] = f"reviewed_semantic_duplicate_of:{winner_id}"

    def _semantic_duplicate_overrides(self) -> Dict[str, Any]:
        path = self.run_dir.parent.parent / "review_overrides.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return dict(data.get("semantic_duplicate_losers", {}))
        except Exception:
            return {}

    def _affect_anchor_strengths(self) -> Dict[str, float]:
        path = self.root / "data" / "affect_field.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        strengths: Dict[str, float] = defaultdict(float)
        for packet in data.get("packets", []):
            amplitude = self._float(packet.get("amplitude", packet.get("initial_amplitude")), 0.0)
            for anchor in packet.get("anchor_memories", []) or []:
                strengths[str(anchor)] = max(strengths[str(anchor)], amplitude)
        return dict(strengths)

    def _apply_pungency(self) -> Dict[str, Any]:
        anchor_strength = self._affect_anchor_strengths()
        memories = [entry for entry in self.entries if entry["kind"] == "memory"]
        scores = []
        for entry in memories:
            metadata = entry.get("metadata", {})
            affect = entry.get("affect", {})
            lag = affect if isinstance(affect, dict) else {}
            raw_id = entry.get("original_id", "")
            severity_before = metadata.get("severity_before")
            severity_after = metadata.get("severity_after")
            explicit_transition = (
                severity_before is not None
                and severity_after is not None
                and str(severity_before) != str(severity_after)
            )
            delta = metadata.get("delta_omega", lag.get("delta_omega"))
            stability_delta = abs(self._float(delta, 0.0))
            omega = self._float(lag.get("omega"), 0.5)
            s_total = self._float(lag.get("s_total"), 0.15)
            d_kl = self._float(lag.get("D_KL"), 0.0)
            extremity = min(1.0, abs(omega - 0.5) * 2.0 + s_total * 0.5 + d_kl * 0.1)
            affect_strength = max(
                anchor_strength.get(raw_id, 0.0),
                anchor_strength.get(f"mem_{raw_id}", 0.0),
            )
            importance = max(0.0, min(1.0, self._float(entry.get("importance"), 0.5)))
            novelty = self._float(metadata.get("novelty"), 1.0)
            relational = min(
                1.0,
                0.2 * len(metadata.get("belief_ids", []) or [])
                + 0.1 * len(entry.get("entities", [])),
            )
            score = (
                (3.0 if explicit_transition else 0.0)
                + 2.0 * min(1.0, stability_delta)
                + 1.5 * min(1.0, affect_strength)
                + extremity
                + importance
                + 0.5 * min(1.0, novelty)
                + 0.5 * relational
            )
            entry["pungency"] = {
                "score": round(score, 6),
                "explicit_severity_transition": explicit_transition,
                "absolute_stability_change": round(stability_delta, 6),
                "affect_anchor_amplitude": round(affect_strength, 6),
                "encoding_extremity": round(extremity, 6),
                "importance": round(importance, 6),
                "novelty": round(min(1.0, novelty), 6),
                "relational_significance": round(relational, 6),
                "confidence": "high" if explicit_transition or stability_delta else "low",
            }
            scores.append(score)

        median = statistics.median(scores) if scores else 0.0
        deviations = [abs(score - median) for score in scores]
        mad = statistics.median(deviations) if deviations else 0.0
        robust_mad = mad if mad > 1e-9 else 0.1
        robust_boundary = median + 2.0 * robust_mad
        # Discrete legacy metadata can put the theoretical MAD boundary above
        # the corpus maximum.  Retain the strongest one percent rather than
        # declaring that a lifetime contains no pungent episodes at all.
        percentile_boundary = float(np.quantile(np.asarray(scores), 0.99)) if scores else 0.0
        threshold = min(robust_boundary, percentile_boundary)
        borderline_floor = threshold - 0.5 * robust_mad
        pungent_count = borderline_count = 0
        for entry in memories:
            pungency = entry["pungency"]
            score = pungency["score"]
            override = self._pungency_override(entry["canonical_id"])
            pungent = pungency["explicit_severity_transition"] or score >= threshold
            if override is not None:
                pungent = bool(override.get("retain_hot", True))
            borderline = not pungent and borderline_floor <= score <= threshold
            if override is not None:
                borderline = False
            pungency["is_pungent"] = pungent
            pungency["borderline"] = borderline
            pungency["threshold"] = round(threshold, 6)
            if pungent:
                pungent_count += 1
            if borderline and entry["retrieval_status"] == "hot":
                borderline_count += 1
                self.review_queue.append(
                    self._review_item(
                        "pungency", entry, "score lies on the robust outlier boundary"
                    )
                )
        return {
            "median": round(median, 6),
            "mad": round(mad, 6),
            "threshold": round(threshold, 6),
            "pungent": pungent_count,
            "borderline": borderline_count,
            "legacy_low_confidence": sum(
                entry["pungency"].get("confidence") == "low" for entry in memories
            ),
        }

    def _pungency_override(self, canonical_id: str) -> Optional[Dict[str, Any]]:
        if not hasattr(self, "_pungency_overrides"):
            path = self.run_dir.parent.parent / "review_overrides.json"
            try:
                self._pungency_overrides = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._pungency_overrides = {}
        return self._pungency_overrides.get(canonical_id)

    def _apply_coverage(self) -> Dict[str, Any]:
        memories = {
            entry["canonical_id"]: entry
            for entry in self.entries
            if entry["kind"] == "memory"
        }
        covered_facts: Dict[str, set] = defaultdict(set)
        full_sources = set()
        eligible_beliefs = 0
        for belief in self.entries:
            if belief["kind"] != "belief":
                continue
            if belief.get("review_status") not in APPROVED_REVIEW_STATES:
                continue
            if belief.get("contradiction_state") != "none":
                continue
            if belief.get("coverage_status") not in {"verified", "full"}:
                continue
            if belief.get("compound_type") == "interpretive":
                continue
            eligible_beliefs += 1
            for fact in belief.get("fact_refs", []):
                for source_id in fact.get("source_ids", []):
                    if source_id not in memories:
                        continue
                    if fact.get("covers_all_source_facts"):
                        full_sources.add(source_id)
                    covered_facts[source_id].update(fact.get("source_fact_ids", []))

        cold = retained_pungent = 0
        for canonical_id, memory in memories.items():
            if memory["retrieval_status"] != "hot":
                continue
            facts = set(memory.get("durable_fact_ids", []))
            fully_covered = canonical_id in full_sources or (
                bool(facts) and facts.issubset(covered_facts.get(canonical_id, set()))
            )
            if not fully_covered:
                continue
            if memory.get("pungency", {}).get("is_pungent") or memory.get("pungency", {}).get("borderline"):
                retained_pungent += 1
                continue
            memory["retrieval_status"] = "cold"
            memory["coverage_status"] = "covered_by_approved_belief"
            memory["suppression_reason"] = "fully_covered_non_pungent_episode"
            cold += 1
        return {
            "eligible_approved_beliefs": eligible_beliefs,
            "cold_memories": cold,
            "covered_but_pungent_retained": retained_pungent,
        }

    def _build_adjacency(self) -> None:
        journal = sorted(
            (
                entry for entry in self.entries
                if entry.get("provenance", {}).get("store") == "cognitive_journal"
            ),
            key=lambda entry: entry["provenance"].get("line", 0),
        )
        for index, entry in enumerate(journal):
            adjacent = []
            for other_index in (index - 1, index + 1):
                if not 0 <= other_index < len(journal):
                    continue
                other = journal[other_index]
                pulse = entry.get("pulse_id")
                other_pulse = other.get("pulse_id")
                if pulse is None or other_pulse is None or abs(int(pulse) - int(other_pulse)) <= 1:
                    adjacent.append(other["canonical_id"])
            entry["adjacent_ids"] = adjacent

    def _build_transitions(self) -> Dict[str, Any]:
        graph: Dict[str, Dict[str, float]] = defaultdict(dict)
        previous = None
        journal = sorted(
            (entry for entry in self.entries if entry["kind"] == "memory"),
            key=lambda entry: entry.get("provenance", {}).get("line", 0),
        )
        for entry in journal:
            clusters = entry.get("entities") or entry.get("topics")
            current = clusters[0] if clusters else None
            if previous and current and previous != current:
                graph[previous][current] = graph[previous].get(current, 0.0) * 0.995 + 1.0
                if len(graph[previous]) > 12:
                    graph[previous] = dict(
                        sorted(graph[previous].items(), key=lambda item: (-item[1], item[0]))[:12]
                    )
            if current:
                previous = current
        return {
            "schema_version": "directed-cluster-transitions-v1",
            "max_outgoing": 12,
            "transitions": {
                source: dict(sorted(outgoing.items(), key=lambda item: (-item[1], item[0])))
                for source, outgoing in sorted(graph.items())
            },
        }

    def _review_item(self, decision_type: str, entry: Dict[str, Any], reason: str) -> Dict[str, Any]:
        material = f"{decision_type}\x00{entry['canonical_id']}\x00{reason}"
        return {
            "review_id": "review:" + hashlib.sha256(material.encode()).hexdigest()[:24],
            "decision_type": decision_type,
            "canonical_id": entry["canonical_id"],
            "reason": reason,
            "status": "pending",
            "source_provenance": entry.get("provenance", {}),
        }

    @staticmethod
    def _float(value: Any, default: float) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else default
        except (TypeError, ValueError):
            return default

    @classmethod
    def _float_or_none(cls, value: Any) -> Optional[float]:
        if value is None:
            return None
        return cls._float(value, 0.0)


class ShadowIndexBuilder:
    """Rebuild hot/cold semantic and 8D views from validated canonical records."""

    def __init__(self, root: Path, run_dir: Path):
        self.root = Path(root).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.entries = list(read_jsonl(self.run_dir / "catalog.jsonl"))
        self.by_id = {entry["canonical_id"]: entry for entry in self.entries}
        self.beliefs = defaultdict(list)
        self.memories = defaultdict(list)
        for entry in self.entries:
            target = self.beliefs if entry["kind"] == "belief" else self.memories
            target[str(entry.get("original_id", ""))].append(entry)

    def build(self) -> Dict[str, Any]:
        source = self.root / "data" / "spatial" / "semantic_index"
        ids = json.loads((source / "ids.json").read_text(encoding="utf-8"))
        metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
        embeddings = np.load(source / "embeddings.npy", mmap_mode="r")
        if len(ids) != embeddings.shape[0]:
            raise ValueError("semantic source index has mismatched IDs and embeddings")

        lanes: Dict[str, List[Tuple[str, int, Dict[str, Any]]]] = {"hot": [], "cold": []}
        stale = []
        seen = set()
        for row, source_id in enumerate(ids):
            entry, reason = self._resolve_vector(str(source_id), metadata.get(source_id, {}))
            if entry is None:
                stale.append({"source_id": source_id, "reason": reason})
                continue
            canonical_id = entry["canonical_id"]
            if canonical_id in seen:
                stale.append({"source_id": source_id, "reason": "duplicate_canonical_vector"})
                continue
            seen.add(canonical_id)
            status = entry["retrieval_status"]
            if status not in lanes:
                continue
            lanes[status].append((canonical_id, row, metadata.get(source_id, {})))

        vector_counts = {}
        for lane, records in lanes.items():
            target = self.run_dir / "indexes" / lane
            target.mkdir(parents=True, exist_ok=True)
            rows = [row for _canonical_id, row, _metadata in records]
            matrix = np.asarray(embeddings[rows], dtype=np.float32) if rows else np.empty((0, 384), dtype=np.float32)
            np.save(target / "embeddings.npy", matrix)
            write_json_atomic(target / "ids.json", [record[0] for record in records])
            write_json_atomic(
                target / "metadata.json",
                {
                    canonical_id: {
                        "content": self.by_id[canonical_id]["content"],
                        "kind": self.by_id[canonical_id]["kind"],
                        "source_index_metadata": source_meta,
                    }
                    for canonical_id, _row, source_meta in records
                },
            )
            write_jsonl_atomic(
                self.run_dir / "indexes" / f"{lane}_8d.jsonl",
                (
                    {
                        "canonical_id": entry["canonical_id"],
                        "position_8d": entry.get("position_8d", []),
                        "stability_index": entry.get("stability_index"),
                        "affect": entry.get("affect", {}),
                    }
                    for entry in self.entries
                    if entry["retrieval_status"] == lane and len(entry.get("position_8d", [])) == 8
                ),
            )
            vector_counts[lane] = len(records)
        write_jsonl_atomic(self.run_dir / "indexes" / "stale_vectors.jsonl", stale)
        near_duplicates = self._near_duplicate_pairs(lanes["hot"], embeddings)
        write_jsonl_atomic(
            self.run_dir / "indexes" / "semantic_duplicate_candidates.jsonl",
            near_duplicates,
        )
        manifest = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "embedding_model": "all-MiniLM-L6-v2",
            "dimensions": int(embeddings.shape[1]),
            "source_vectors": len(ids),
            "hot_vectors": vector_counts["hot"],
            "cold_vectors": vector_counts["cold"],
            "stale_vectors": len(stale),
            "semantic_duplicate_candidates": len(near_duplicates),
            "catalog_sha256": sha256_file(self.run_dir / "catalog.jsonl"),
        }
        write_json_atomic(self.run_dir / "index_manifest.json", manifest)
        return manifest

    def _near_duplicate_pairs(
        self,
        records: Sequence[Tuple[str, int, Dict[str, Any]]],
        source_embeddings: np.ndarray,
        threshold: float = 0.985,
    ) -> List[Dict[str, Any]]:
        """Detect, but never auto-merge, high-cosine semantic duplicates."""
        if len(records) < 2:
            return []
        rows = [row for _canonical_id, row, _metadata in records]
        matrix = np.asarray(source_embeddings[rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.maximum(norms, 1e-8)
        pairs = {}
        block_size = 256
        for start in range(0, len(records), block_size):
            stop = min(len(records), start + block_size)
            scores = matrix[start:stop] @ matrix.T
            for local_index, values in enumerate(scores):
                left_index = start + local_index
                values[left_index] = -1.0
                top_count = min(4, len(values))
                candidate_indices = np.argpartition(-values, top_count - 1)[:top_count]
                for right_index in candidate_indices:
                    similarity = float(values[int(right_index)])
                    if similarity < threshold or left_index >= int(right_index):
                        continue
                    left_id = records[left_index][0]
                    right_id = records[int(right_index)][0]
                    left = self.by_id[left_id]
                    right = self.by_id[right_id]
                    if left["kind"] != right["kind"]:
                        continue
                    if left["content_fingerprint"] == right["content_fingerprint"]:
                        continue
                    key = (left_id, right_id)
                    pairs[key] = {
                        "left_id": left_id,
                        "right_id": right_id,
                        "similarity": round(similarity, 6),
                        "status": "pending_review",
                        "left_provenance": left.get("provenance", {}),
                        "right_provenance": right.get("provenance", {}),
                    }
        return [pairs[key] for key in sorted(pairs)][:2000]

    def _resolve_vector(
        self, source_id: str, metadata: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        kind = str(metadata.get("type", ""))
        if kind == "belief" or source_id in self.beliefs:
            records = [
                entry for entry in self.beliefs.get(source_id, [])
                if entry["retrieval_status"] not in {"superseded", "quarantined"}
            ]
            return (records[0], "") if len(records) == 1 else (None, "ambiguous_belief_vector")

        raw_id = str(metadata.get("journal_id") or source_id)
        if raw_id.startswith("mem_"):
            raw_id = raw_id[4:]
        records = self.memories.get(raw_id, [])
        content = str(metadata.get("content", ""))
        if len(records) > 1 and content:
            fingerprint = content_fingerprint(content)
            records = [record for record in records if record["content_fingerprint"] == fingerprint]
            if not records:
                candidates = self.memories.get(raw_id, [])
                source_text = normalized_text(content)
                records = [
                    record for record in candidates
                    if normalized_text(record.get("content", "")).startswith(source_text)
                    or source_text.startswith(normalized_text(record.get("content", "")))
                ]
            if len(records) > 1 and metadata.get("pulse_id") is not None:
                pulse_matches = [
                    record for record in records
                    if record.get("pulse_id") == metadata.get("pulse_id")
                ]
                if pulse_matches:
                    records = pulse_matches
        active = [record for record in records if record["retrieval_status"] in {"hot", "cold"}]
        if len(active) == 1:
            return active[0], ""
        return None, "missing_memory_vector" if not active else "ambiguous_memory_vector"


def audit_store(root: Path) -> Dict[str, Any]:
    """Cheap read-only inventory used before a full snapshot/migration."""
    root = Path(root).resolve()
    journal = locate_journal(root)
    lines = valid = malformed = checksum_failures = 0
    original_ids = Counter()
    types = Counter()
    with journal.open("r", encoding="utf-8") as handle:
        for raw in handle:
            lines += 1
            try:
                source = json.loads(raw)
            except json.JSONDecodeError:
                malformed += 1
                continue
            payload = dict(source)
            checksum = payload.pop("checksum", None)
            if checksum != journal_checksum(payload):
                checksum_failures += 1
                continue
            valid += 1
            original_ids[str(source.get("id"))] += 1
            types[str(source.get("type"))] += 1

    belief_count = 0
    belief_ids = Counter()
    malformed_belief_files = []
    for path in sorted((root / "data" / "beliefs").glob("*.json")):
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError("top level is not a list")
            belief_count += len(records)
            belief_ids.update(str(record.get("id")) for record in records if isinstance(record, dict))
        except Exception as exc:
            malformed_belief_files.append({"path": str(path), "error": str(exc)})

    def json_count(path: Path) -> int:
        if not path.exists():
            return 0
        value = json.loads(path.read_text(encoding="utf-8"))
        return max(0, len(value) - (1 if isinstance(value, dict) and "__meta__" in value else 0))

    semantic_ids_path = root / "data" / "spatial" / "semantic_index" / "ids.json"
    semantic_count = len(json.loads(semantic_ids_path.read_text())) if semantic_ids_path.exists() else 0
    return {
        "schema_version": "helix-memory-audit-v1",
        "root": str(root),
        "journal": {
            "path": str(journal.relative_to(root)),
            "sha256": sha256_file(journal),
            "lines": lines,
            "valid": valid,
            "malformed": malformed,
            "checksum_failures": checksum_failures,
            "reused_original_ids": sum(count > 1 for count in original_ids.values()),
            "max_id_reuse": max(original_ids.values()) if original_ids else 0,
            "types": dict(sorted(types.items())),
        },
        "belief_files": {
            "entries": belief_count,
            "reused_ids": sum(count > 1 for count in belief_ids.values()),
            "malformed_files": malformed_belief_files,
        },
        "spatial": {
            "belief_points": json_count(root / "data" / "spatial" / "belief_space_state.json"),
            "memory_points": json_count(root / "data" / "spatial" / "memory_space_state.json"),
            "semantic_vectors": semantic_count,
        },
    }
