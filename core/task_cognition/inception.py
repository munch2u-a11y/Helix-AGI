"""Detect committed tasks in natural internal monologue.

This is intentionally not a command syntax.  It observes ordinary first-person
intention language and distinguishes commitment from speculation so that Helix
can remain in a fluid planning mode.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


_INTENTION_RE = re.compile(
    r"\b(?P<marker>"
    r"I\s+(?:will|need\s+to|have\s+to|should|intend\s+to|want\s+to|"
    r"am\s+going\s+to|can\s+now)|I'll|Let\s+me"
    r")\s+(?P<objective>.+)",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)
_EXPLICIT_REQUEST = re.compile(
    r"\b(?:please|can\s+you|could\s+you|would\s+you|I\s+need\s+you\s+to|"
    r"go\s+ahead\s+and|create|write|update|edit|run|search|find|send|post)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskCandidate:
    objective: str
    task_type: str
    commitment: float
    authorization_scope: str
    signature: str
    evidence: str


class IntentionDetector:
    """Conservative deterministic detector for naturally voiced intentions."""

    DEFAULT_THRESHOLD = 0.68
    _COMMITMENT = {
        "i will": 0.96,
        "i'll": 0.96,
        "let me": 0.90,
        "i need to": 0.88,
        "i have to": 0.88,
        "i am going to": 0.86,
        "i intend to": 0.84,
        "i should": 0.72,
        "i can now": 0.70,
        "i want to": 0.60,
    }
    _HYPOTHETICAL = re.compile(
        r"\b(?:maybe|perhaps|possibly|might|could|if\s+I|I\s+wonder|hypothetically)\b",
        re.IGNORECASE,
    )
    _NEGATED = re.compile(
        r"\b(?:will\s+not|won't|should\s+not|shouldn't|do\s+not\s+need|don't\s+need)\b",
        re.IGNORECASE,
    )

    def __init__(self, threshold: float = DEFAULT_THRESHOLD, max_tasks: int = 3):
        self.threshold = float(threshold)
        self.max_tasks = max(1, int(max_tasks))

    def detect(
        self,
        thought: str,
        events: Optional[Iterable[str]] = None,
    ) -> List[TaskCandidate]:
        thought = " ".join(str(thought or "").split())
        if not thought or thought.startswith("[internal error:"):
            return []

        event_list = list(events or [])
        candidates: List[TaskCandidate] = []
        seen = set()
        for sentence in _SENTENCE_RE.split(thought):
            for match in _INTENTION_RE.finditer(sentence):
                marker = " ".join(match.group("marker").lower().split())
                evidence = match.group(0).strip()
                objective = self._clean_objective(match.group("objective"))
                if not objective or self._NEGATED.search(evidence):
                    continue

                commitment = self._COMMITMENT.get(marker, 0.65)
                if self._HYPOTHETICAL.search(sentence):
                    commitment -= 0.30
                if sentence.rstrip().endswith("?"):
                    commitment -= 0.18
                commitment = max(0.0, min(1.0, commitment))
                if commitment < self.threshold:
                    continue

                task_type = self._classify(objective)
                scope = self._authorization_scope(task_type, event_list)
                signature = self.signature(task_type, objective)
                if signature in seen:
                    continue
                seen.add(signature)
                candidates.append(TaskCandidate(
                    objective=objective,
                    task_type=task_type,
                    commitment=commitment,
                    authorization_scope=scope,
                    signature=signature,
                    evidence=evidence,
                ))
                if len(candidates) >= self.max_tasks:
                    return candidates
        return candidates

    @staticmethod
    def _clean_objective(text: str) -> str:
        objective = text.strip(" \t\n.,;:!?")
        # Do not let a second reflective clause silently expand authority.
        objective = re.split(
            r"\s+(?:but|although|though|unless)\s+",
            objective,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        return objective[:1000].strip()

    @staticmethod
    def _classify(objective: str) -> str:
        words = set(_WORD_RE.findall(objective.lower()))
        if words & {"reply", "respond", "answer", "tell", "message", "say"}:
            return "respond"
        if words & {"remember", "recall", "revisit"} or "look up in memory" in objective.lower():
            return "remember"
        if words & {"think", "consider", "understand", "reflect", "explore"}:
            return "deliberate"
        if words & {"plan", "organize", "decide", "outline"}:
            return "plan"
        return "action"

    @staticmethod
    def _authorization_scope(task_type: str, events: List[str]) -> str:
        if task_type in {"remember", "deliberate", "plan"}:
            return "internal"
        if task_type == "respond" and any("is talking to me via" in event for event in events):
            return "direct_response"
        if any(
            "is talking to me via" in event and _EXPLICIT_REQUEST.search(event)
            for event in events
        ):
            return "explicit"
        return "unverified"

    @staticmethod
    def signature(task_type: str, objective: str) -> str:
        normalized = " ".join(_WORD_RE.findall(objective.lower()))
        return hashlib.sha256(f"{task_type}:{normalized}".encode("utf-8")).hexdigest()[:20]
