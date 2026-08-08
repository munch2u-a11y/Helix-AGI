"""Event-driven task cognition for Helix.

The conscious model forms intentions in ordinary thought.  This package owns
the machinery that notices committed intentions, persists them as tasks, and
routes them to identity-shared focus workers without exposing the full tool
catalog to the main consciousness.
"""

from core.task_cognition.capabilities import CapabilityRegistry
from core.task_cognition.inception import IntentionDetector, TaskCandidate
from core.task_cognition.models import TaskRecord, TaskStatus
from core.task_cognition.store import TaskStore

__all__ = [
    "CapabilityRegistry",
    "IntentionDetector",
    "TaskCandidate",
    "TaskRecord",
    "TaskStatus",
    "TaskStore",
]
