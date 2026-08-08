"""Learned situational attractors for routing task-focused cognition.

An orchestrator is not a persona or a hardcoded prompt.  It is a learned
centroid over prior task situations, plus outcome and capability-use telemetry.
The 1024D centroid answers "which working habit fits this situation?" while a
separate 8D transition overlay preserves habits that tend to follow one
another in lived sequence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

import numpy as np

from core.associative_transitions import AssociativeTransitionMemory
from core.task_cognition.models import TaskRecord, now_iso

logger = logging.getLogger("helix.core.task_cognition.orchestrators")
_TOKENS = re.compile(r"[a-z0-9]+", re.IGNORECASE)


@dataclass
class OrchestratorRecord:
    orchestrator_id: str = field(default_factory=lambda: f"orch_{uuid4().hex[:12]}")
    centroid_1024d: List[float] = field(default_factory=list)
    position_8d: List[float] = field(default_factory=list)
    observations: int = 0
    successes: int = 0
    failures: int = 0
    mean_focus_depth: float = 1.0
    task_type_counts: Dict[str, int] = field(default_factory=dict)
    capability_counts: Dict[str, int] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @classmethod
    def from_dict(cls, data: Dict) -> "OrchestratorRecord":
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in known})

    @property
    def reliability(self) -> float:
        # Bayesian smoothing prevents a single lucky first task dominating.
        return (self.successes + 1.0) / (self.successes + self.failures + 2.0)


class OrchestratorSpace:
    """Persistent reverse-vector index over learned working habits."""

    def __init__(
        self,
        data_dir: str | Path = "data/tasks",
        semantic_embedder: Optional[Callable[[str], Iterable[float]]] = None,
        spatial_projector: Optional[Callable[[str], Iterable[float]]] = None,
        semantic_dim: int = 1024,
        cluster_threshold: float = 0.72,
    ):
        self.data_dir = Path(data_dir)
        self.state_path = self.data_dir / "orchestrators.json"
        self.semantic_dim = int(semantic_dim)
        self.cluster_threshold = float(cluster_threshold)
        self._semantic_embedder = semantic_embedder
        self._spatial_projector = spatial_projector
        self._lock = threading.RLock()
        self._records: Dict[str, OrchestratorRecord] = {}
        self._transitions = AssociativeTransitionMemory(
            self.data_dir / "orchestrator_associations"
        )
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._records = {
                record.orchestrator_id: record
                for record in (
                    OrchestratorRecord.from_dict(item)
                    for item in payload.get("orchestrators", [])
                )
            }
        except Exception as exc:
            logger.warning("Orchestrator space could not be loaded: %s", exc)

    def _save_locked(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "semantic_dim": self.semantic_dim,
            "orchestrators": [asdict(record) for record in self._records.values()],
        }
        temp = self.state_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.state_path)

    def all(self) -> List[OrchestratorRecord]:
        with self._lock:
            return list(self._records.values())

    def get(self, orchestrator_id: str) -> Optional[OrchestratorRecord]:
        with self._lock:
            return self._records.get(orchestrator_id)

    def select(
        self,
        task: TaskRecord,
        *,
        limit: int = 3,
        observe_transition: bool = True,
    ) -> List[Tuple[OrchestratorRecord, float]]:
        """Reverse-search task space, with a small learned sequence nudge."""
        query = self._semantic_vector(self._task_text(task))
        query_pos = self._spatial_vector(self._task_text(task))
        with self._lock:
            if not self._records:
                created = self._create_locked(query, query_pos, task.objective)
                if observe_transition:
                    self._transitions.observe(created.orchestrator_id, created.position_8d)
                return [(created, 1.0)]

            semantic_scores = {}
            for record in self._records.values():
                centroid = self._coerce(record.centroid_1024d, self.semantic_dim)
                semantic_scores[record.orchestrator_id] = self._cosine(query, centroid)

            semantic_ranked = sorted(
                self._records.values(),
                key=lambda record: (
                    -semantic_scores[record.orchestrator_id],
                    -record.reliability,
                    record.orchestrator_id,
                ),
            )
            anchor = semantic_ranked[0]
            if semantic_scores[anchor.orchestrator_id] < self.cluster_threshold:
                created = self._create_locked(query, query_pos, task.objective)
                if observe_transition:
                    self._transitions.observe(created.orchestrator_id, created.position_8d)
                return [(created, 1.0)]
            habit_scores = {
                item["cluster_id"]: float(item.get("score", 0.0))
                for item in self._transitions.recall(anchor.orchestrator_id, limit=3)
            }
            combined = []
            for record in self._records.values():
                semantic = semantic_scores[record.orchestrator_id]
                habit = min(1.0, habit_scores.get(record.orchestrator_id, 0.0))
                score = (0.82 * semantic) + (0.10 * habit) + (0.08 * record.reliability)
                combined.append((record, score))
            combined.sort(key=lambda item: (-item[1], item[0].orchestrator_id))
            selected = combined[:max(1, int(limit))]
            if observe_transition and selected:
                chosen = selected[0][0]
                self._transitions.observe(chosen.orchestrator_id, chosen.position_8d)
            return selected

    def learn(
        self,
        task: TaskRecord,
        *,
        success: bool,
        capabilities: Iterable[str] = (),
        focus_depth: int = 1,
    ) -> OrchestratorRecord:
        """Move only the matching situational centroid after an outcome."""
        vector = self._semantic_vector(self._task_text(task))
        position = self._spatial_vector(self._task_text(task))
        with self._lock:
            chosen = None
            if task.orchestrator_ids:
                chosen = self._records.get(task.orchestrator_ids[0])
            if chosen is None and self._records:
                chosen = max(
                    self._records.values(),
                    key=lambda record: self._cosine(
                        vector, self._coerce(record.centroid_1024d, self.semantic_dim)
                    ),
                )
                if self._cosine(
                    vector, self._coerce(chosen.centroid_1024d, self.semantic_dim)
                ) < self.cluster_threshold:
                    chosen = None
            if chosen is None:
                chosen = self._create_locked(vector, position, task.objective)

            old_n = chosen.observations
            new_n = old_n + 1
            centroid = self._coerce(chosen.centroid_1024d, self.semantic_dim)
            centroid = self._normalize(((centroid * old_n) + vector) / new_n)
            chosen.centroid_1024d = centroid.tolist()
            if len(chosen.position_8d) != 8:
                chosen.position_8d = position.tolist()
            chosen.observations = new_n
            chosen.successes += int(bool(success))
            chosen.failures += int(not success)
            chosen.mean_focus_depth = (
                (chosen.mean_focus_depth * old_n) + max(1, int(focus_depth))
            ) / new_n
            chosen.task_type_counts[task.task_type] = (
                chosen.task_type_counts.get(task.task_type, 0) + 1
            )
            for capability in capabilities:
                chosen.capability_counts[capability] = (
                    chosen.capability_counts.get(capability, 0) + 1
                )
            chosen.examples = (chosen.examples + [task.objective[:240]])[-5:]
            chosen.updated_at = now_iso()
            self._save_locked()
            self._transitions.save()
            return chosen

    def _create_locked(
        self,
        vector: np.ndarray,
        position: np.ndarray,
        example: str,
    ) -> OrchestratorRecord:
        record = OrchestratorRecord(
            centroid_1024d=vector.tolist(),
            position_8d=position.tolist(),
            examples=[example[:240]],
        )
        self._records[record.orchestrator_id] = record
        self._save_locked()
        return record

    def _semantic_vector(self, text: str) -> np.ndarray:
        if self._semantic_embedder is not None:
            try:
                vector = self._coerce(self._semantic_embedder(text), self.semantic_dim)
                if float(np.linalg.norm(vector)) > 1e-8:
                    return self._normalize(vector)
            except Exception as exc:
                logger.debug("Semantic orchestrator embedding failed: %s", exc)
        return self._hashed_vector(text, self.semantic_dim)

    def _spatial_vector(self, text: str) -> np.ndarray:
        if self._spatial_projector is not None:
            try:
                vector = self._coerce(self._spatial_projector(text), 8)
                if np.all(np.isfinite(vector)):
                    return vector
            except Exception as exc:
                logger.debug("Spatial orchestrator projection failed: %s", exc)
        return self._hashed_vector(text, 8)

    @staticmethod
    def _task_text(task: TaskRecord) -> str:
        sections = [task.task_type, task.objective, task.details]
        sections.extend(task.goals)
        sections.extend(task.constraints)
        return " ".join(section for section in sections if section)

    @staticmethod
    def _coerce(value: Iterable[float], dimension: int) -> np.ndarray:
        vector = np.asarray(list(value), dtype=np.float32).reshape(-1)
        if vector.size != dimension or not np.all(np.isfinite(vector)):
            return np.zeros(dimension, dtype=np.float32)
        return vector

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 1e-8 else vector

    @classmethod
    def _hashed_vector(cls, text: str, dimension: int) -> np.ndarray:
        vector = np.zeros(dimension, dtype=np.float32)
        for token in _TOKENS.findall((text or "").lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        return cls._normalize(vector)

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        norm = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(np.dot(a, b) / norm) if norm > 1e-8 else 0.0
