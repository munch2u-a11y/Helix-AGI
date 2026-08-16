"""Shared schemas for the derived catalog and unified retrieval lanes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FocusState(str, Enum):
    DEEP = "deep"
    WORKING = "working"
    OPEN = "open"

    @property
    def token_budget(self) -> int:
        return {
            FocusState.DEEP: 300,
            FocusState.WORKING: 500,
            FocusState.OPEN: 700,
        }[self]


@dataclass
class RetrievalCandidate:
    """One canonical candidate shared by every retrieval lane."""

    canonical_id: str
    kind: str
    content: str
    provenance: Dict[str, Any]
    semantic_rank: Optional[int] = None
    lane: str = "semantic"
    topic_matches: List[str] = field(default_factory=list)
    entity_matches: List[str] = field(default_factory=list)
    position_8d: List[float] = field(default_factory=list)
    stability: Optional[float] = None
    affect: Dict[str, Any] = field(default_factory=dict)
    suppression_reason: Optional[str] = None
    semantic_score: float = 0.0
    token_count: int = 0
    retrieval_status: str = "hot"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    candidates: List[RetrievalCandidate]
    stats: Dict[str, Any]

    @property
    def injected_tokens(self) -> int:
        return sum(candidate.token_count for candidate in self.candidates)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "stats": dict(self.stats),
        }


def estimate_tokens(text: str) -> int:
    """Deterministic approximation used for hard evidence budgets."""
    words = len((text or "").split())
    return max(1, int(round(words * 1.33))) if text else 0
