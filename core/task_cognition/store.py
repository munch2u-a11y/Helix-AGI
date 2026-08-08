"""Thread-safe task persistence with a compact state file and audit journal."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.task_cognition.models import (
    TERMINAL_STATUSES,
    VALID_TRANSITIONS,
    TaskRecord,
    TaskStatus,
    now_iso,
)

logger = logging.getLogger("helix.core.task_cognition.store")


class TaskStore:
    """Durable source of truth for tasks created from Helix's intentions."""

    def __init__(self, data_dir: str | Path = "data/tasks"):
        self.data_dir = Path(data_dir)
        self.state_path = self.data_dir / "tasks.json"
        self.events_path = self.data_dir / "task_events.jsonl"
        self._lock = threading.RLock()
        self._tasks: Dict[str, TaskRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            records = payload.get("tasks", []) if isinstance(payload, dict) else payload
            self._tasks = {
                record.task_id: record
                for record in (TaskRecord.from_dict(item) for item in records)
            }
        except Exception as exc:
            logger.warning("Task state could not be loaded: %s", exc)
            self._tasks = {}

    def _save_locked(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "tasks": [task.to_dict() for task in self._tasks.values()],
        }
        temp_path = self.state_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, self.state_path)

    def _event_locked(self, task: TaskRecord, event: str, **details: Any) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": now_iso(),
            "task_id": task.task_id,
            "event": event,
            "status": task.status.value,
            **details,
        }
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def create(self, task: TaskRecord) -> TaskRecord:
        """Persist a new task, coalescing duplicate open intentions."""
        with self._lock:
            duplicate = self.find_open_by_signature(task.signature)
            if duplicate is not None:
                self._event_locked(
                    duplicate,
                    "duplicate_observed",
                    source_pulse=task.source_pulse,
                )
                return duplicate
            self._tasks[task.task_id] = task
            self._save_locked()
            self._event_locked(task, "created", objective=task.objective)
            return task

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)

    def all(self) -> List[TaskRecord]:
        with self._lock:
            return list(self._tasks.values())

    def open_tasks(self) -> List[TaskRecord]:
        with self._lock:
            return [task for task in self._tasks.values() if task.status not in TERMINAL_STATUSES]

    def find_open_by_signature(self, signature: str) -> Optional[TaskRecord]:
        if not signature:
            return None
        with self._lock:
            for task in self._tasks.values():
                if task.signature == signature and task.status not in TERMINAL_STATUSES:
                    return task
        return None

    def transition(
        self,
        task_id: str,
        status: TaskStatus | str,
        *,
        force: bool = False,
        **updates: Any,
    ) -> TaskRecord:
        """Apply a validated state transition and persist it atomically."""
        status = TaskStatus(status)
        with self._lock:
            task = self._tasks[task_id]
            if not force and status not in VALID_TRANSITIONS.get(task.status, set()):
                raise ValueError(f"Invalid task transition: {task.status.value} -> {status.value}")
            previous = task.status
            task.status = status
            for key, value in updates.items():
                if key in task.__dataclass_fields__ and key not in {"task_id", "status"}:
                    setattr(task, key, value)
            task.updated_at = now_iso()
            self._save_locked()
            self._event_locked(task, "transition", previous=previous.value)
            return task

    def update(self, task_id: str, **updates: Any) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            for key, value in updates.items():
                if key in task.__dataclass_fields__ and key not in {"task_id", "status"}:
                    setattr(task, key, value)
            task.updated_at = now_iso()
            self._save_locked()
            self._event_locked(task, "updated", fields=sorted(updates))
            return task
