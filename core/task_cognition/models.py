"""Durable data models for Helix's event-driven task layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TaskStatus(str, Enum):
    CREATED = "created"
    FOCUSING = "focusing"
    READY = "ready"
    EXECUTING = "executing"
    REFLECTING = "reflecting"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    TaskStatus.COMPLETE,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED,
    TaskStatus.CANCELLED,
}


VALID_TRANSITIONS = {
    TaskStatus.CREATED: {
        TaskStatus.FOCUSING, TaskStatus.CANCELLED, TaskStatus.BLOCKED,
    },
    TaskStatus.FOCUSING: {
        TaskStatus.READY, TaskStatus.EXECUTING, TaskStatus.FAILED,
        TaskStatus.BLOCKED, TaskStatus.CANCELLED,
    },
    TaskStatus.READY: {
        TaskStatus.EXECUTING, TaskStatus.FOCUSING, TaskStatus.BLOCKED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.EXECUTING: {
        TaskStatus.REFLECTING, TaskStatus.COMPLETE, TaskStatus.FAILED,
        TaskStatus.BLOCKED,
    },
    TaskStatus.REFLECTING: {
        TaskStatus.COMPLETE, TaskStatus.FAILED, TaskStatus.FOCUSING,
        TaskStatus.BLOCKED,
    },
    TaskStatus.BLOCKED: {TaskStatus.FOCUSING, TaskStatus.CANCELLED},
    TaskStatus.FAILED: {TaskStatus.FOCUSING, TaskStatus.CANCELLED},
    TaskStatus.COMPLETE: set(),
    TaskStatus.CANCELLED: set(),
}


@dataclass
class TaskRecord:
    """One intention carried across conscious pulses and focus threads."""

    objective: str
    task_type: str = "action"
    details: str = ""
    task_id: str = field(default_factory=lambda: f"task_{uuid4().hex[:16]}")
    signature: str = ""
    source_thought_id: Optional[int] = None
    source_pulse: int = 0
    source_events: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    success_conditions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    parent_task_id: Optional[str] = None
    status: TaskStatus = TaskStatus.CREATED
    commitment: float = 0.0
    authorization_scope: str = "unverified"
    capability_names: List[str] = field(default_factory=list)
    orchestrator_ids: List[str] = field(default_factory=list)
    focus_depth: int = 1
    attempts: int = 0
    result: str = ""
    error: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRecord":
        values = dict(data)
        try:
            values["status"] = TaskStatus(values.get("status", TaskStatus.CREATED))
        except ValueError:
            values["status"] = TaskStatus.CREATED
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES
