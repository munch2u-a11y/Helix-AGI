"""Thread-safe outcome observations; activity alone never earns progress credit."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import threading
import time


_LESSON_CONTEXT = ContextVar("helix_lesson_context", default=("", frozenset()))


@contextmanager
def lesson_context(context_id, source_ids):
    """Bind exposure to this synchronous generation, never another focus thread."""
    token = _LESSON_CONTEXT.set((str(context_id), frozenset(str(sid) for sid in source_ids)))
    try:
        yield
    finally:
        _LESSON_CONTEXT.reset(token)


def current_lesson_context():
    return _LESSON_CONTEXT.get()


class ProgressFeedback:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.seen = OrderedDict()
        self.last_by_target = OrderedDict()
        self.counts = {"attempts": 0, "advanced": 0, "failures": 0}
        self.last_progress = None

    def record(self, event_id, *, advanced=False, failed=False, target=None, content=None):
        if not event_id:
            return
        with self.lock:
            if event_id in self.seen:
                return
            self.seen[event_id] = None
            # This bounds transient feedback bookkeeping, never goals/evidence.
            while len(self.seen) > 4096:
                self.seen.popitem(last=False)
            self.counts["attempts"] += 1
            if target is not None and advanced and not failed:
                advanced = advanced and self.last_by_target.get(target) != content
                self.last_by_target[target] = content
                self.last_by_target.move_to_end(target)
                while len(self.last_by_target) > 4096:
                    self.last_by_target.popitem(last=False)
            if advanced and not failed:
                self.counts["advanced"] += 1
                self.last_progress = self.clock()
            if failed:
                self.counts["failures"] += 1

    def observe_tool(self, receipt):
        from core.action_protocol import verify_receipts, EvidenceLevel
        evidence = verify_receipts([receipt])
        target = (receipt.tool, json.dumps(receipt.args, sort_keys=True, default=str))
        digest = hashlib.sha256(receipt.result.encode()).hexdigest()
        self.record(receipt.call_id, advanced=(evidence.verified and receipt.evidence in {
            EvidenceLevel.OBSERVED, EvidenceLevel.CONFIRMED}), failed=not receipt.ok,
                    target=target, content=digest)

    def snapshot(self):
        with self.lock:
            result = {**self.counts, "last_progress_age_seconds": (
                None if self.last_progress is None else max(0.0, self.clock() - self.last_progress))}
            self.counts = {"attempts": 0, "advanced": 0, "failures": 0}
            return result
