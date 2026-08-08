"""Contextual procedural memory for tool-backed task habits."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict, Iterable, List

from core.task_cognition.models import TaskRecord, now_iso


class ProceduralMemory:
    """Small learned store kept separate from identity and factual beliefs."""

    def __init__(self, data_dir: str | Path = "data/tasks"):
        self.path = Path(data_dir) / "procedural_skills.json"
        self._lock = threading.RLock()
        self._records: List[Dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = payload.get("procedures", [])
        except Exception:
            self._records = []

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps({"version": 1, "procedures": self._records}, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, self.path)

    def observe(
        self,
        task: TaskRecord,
        tool_sequence: Iterable[str],
        *,
        success: bool,
    ) -> None:
        sequence = [name for name in tool_sequence if name]
        if not sequence:
            return
        key = f"{task.task_type}|{'->'.join(sequence)}"
        with self._lock:
            record = next((item for item in self._records if item.get("key") == key), None)
            if record is None:
                record = {
                    "key": key,
                    "task_type": task.task_type,
                    "tool_sequence": sequence,
                    "successes": 0,
                    "failures": 0,
                    "examples": [],
                    "updated_at": now_iso(),
                }
                self._records.append(record)
            record["successes"] += int(bool(success))
            record["failures"] += int(not success)
            record["examples"] = (record.get("examples", []) + [task.objective[:180]])[-5:]
            record["updated_at"] = now_iso()
            self._records = sorted(
                self._records,
                key=lambda item: (
                    -(item.get("successes", 0) - item.get("failures", 0)),
                    item.get("key", ""),
                ),
            )[:500]
            self._save_locked()

    def relevant(self, task: TaskRecord, limit: int = 3) -> List[Dict]:
        words = set(task.objective.lower().split())
        scored = []
        with self._lock:
            for record in self._records:
                if record.get("task_type") != task.task_type:
                    continue
                examples = " ".join(record.get("examples", [])).lower().split()
                overlap = len(words & set(examples))
                reliability = (
                    (record.get("successes", 0) + 1)
                    / (record.get("successes", 0) + record.get("failures", 0) + 2)
                )
                scored.append((overlap + reliability, record))
        scored.sort(key=lambda item: (-item[0], item[1].get("key", "")))
        return [dict(record) for _score, record in scored[:max(0, int(limit))]]
