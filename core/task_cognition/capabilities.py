"""Hidden capability catalog and broad conscious ability awareness."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

import numpy as np


_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "use", "via", "with", "you", "your",
}


@dataclass(frozen=True)
class Capability:
    name: str
    toolset: str
    description: str
    schema: Dict[str, Any]
    risk: str


class CapabilityRegistry:
    """Reverse-searchable view of tools that keeps schemas out of main thought."""

    _READ_PREFIXES = (
        "read", "search", "list", "get", "look", "listen", "memory_recall",
        "browse", "drive_read", "email_read", "calendar_list", "tasks_list",
    )
    _INTERNAL_NAMES = {
        "memory_recall", "note_write", "note_append", "note_clear", "journal", "nap",
    }
    _COMMUNICATION_NAMES = {"reply", "send_message", "verbalize"}

    def __init__(
        self,
        tool_registry=None,
        *,
        query_embedder=None,
        document_batch_embedder=None,
    ):
        if tool_registry is None:
            from tools.tool_registry import registry as tool_registry
        self._registry = tool_registry
        self._query_embedder = query_embedder
        self._document_batch_embedder = document_batch_embedder
        self._embedding_generation = -1
        self._embeddings: Dict[str, np.ndarray] = {}

    def available(
        self,
        active_toolsets: Optional[Set[str]] = None,
        *,
        include_dormant: bool = False,
    ) -> List[Capability]:
        if include_dormant:
            active_toolsets = set(self._registry.get_toolset_names())
        allowed = {
            declaration.get("name")
            for declaration in self._registry.get_declarations(active_toolsets)
        }
        capabilities = []
        for name in sorted(item for item in allowed if item):
            entry = self._registry.get_entry(name)
            if entry is None:
                continue
            capabilities.append(Capability(
                name=name,
                toolset=entry.toolset,
                description=entry.schema.get("description", "") or entry.description,
                schema=copy.deepcopy(entry.schema),
                risk=self._risk(name, entry.schema.get("description", "")),
            ))
        return capabilities

    def select(
        self,
        objective: str,
        *,
        task_type: str = "action",
        authorization_scope: str = "unverified",
        active_toolsets: Optional[Set[str]] = None,
        preferred_names: Optional[Iterable[str]] = None,
        limit: int = 8,
    ) -> List[Capability]:
        """Select a small task-specific schema set by reverse lexical search."""
        query = self._tokens(objective)
        preferred = set(preferred_names or [])
        active = set(active_toolsets or {"core"})
        available = self.available(active_toolsets, include_dormant=True)
        semantic_scores = self._semantic_scores(objective, available)
        scored = []
        for capability in available:
            if not self._authorized(capability, task_type, authorization_scope):
                continue
            haystack = self._tokens(
                capability.name.replace("_", " ") + " " + capability.description
            )
            overlap = len(query & haystack)
            score = overlap / max(1.0, len(query) ** 0.5)
            score += 0.85 * max(0.0, semantic_scores.get(capability.name, 0.0))
            score += self._type_bonus(task_type, capability.name)
            if capability.name in preferred:
                score += 1.5
            if capability.toolset in active:
                score += 0.03
            if score > 0:
                scored.append((score, capability.name, capability))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[:max(1, int(limit))]]

    def declarations_for(self, capabilities: Iterable[Capability]) -> List[Dict[str, Any]]:
        return [copy.deepcopy(capability.schema) for capability in capabilities]

    def broad_awareness(self, active_toolsets: Optional[Set[str]] = None) -> str:
        """Describe ability families without revealing callable names or schemas."""
        capabilities = self.available(active_toolsets, include_dormant=True)
        if not capabilities:
            return ""
        families = []
        toolsets = {capability.toolset for capability in capabilities}
        family_map = {
            "core": "communicate, remember, keep notes, and reflect",
            "operational": "communicate, remember, keep notes, and reflect",
            "perception": "look and listen through local senses",
            "web": "research public information on the web",
            "files": "read and work with local files",
            "browser": "interact with browser-based interfaces",
            "git": "work with source-control history and changes",
            "github": "work with hosted repositories and collaboration",
            "email": "read and manage email",
            "calendar": "inspect and manage calendar commitments",
            "drive": "read and manage cloud documents",
            "tasks": "inspect and manage task lists",
            "desktop": "interact with the local desktop",
            "moltbook": "participate in the configured social space",
            "social": "participate in the configured social space",
        }
        for toolset in sorted(toolsets):
            description = family_map.get(toolset)
            if not description:
                info = next(
                    (item for item in self._registry.get_toolset_info(active_toolsets)
                     if item.get("name") == toolset),
                    None,
                )
                description = (info or {}).get("description", "").strip().rstrip(".")
            if description and description not in families:
                families.append(description)
        if not families:
            return "I can act through task-specific abilities when an intention requires it."
        return (
            "I can form intentions and carry them out through task-specific abilities. "
            "Depending on the situation, I can " + "; ".join(families) + "."
        )

    @classmethod
    def _risk(cls, name: str, description: str) -> str:
        lower = name.lower()
        if lower in cls._INTERNAL_NAMES:
            return "internal"
        if lower in cls._COMMUNICATION_NAMES:
            return "communication"
        if lower.startswith(cls._READ_PREFIXES):
            return "read"
        mutating = {
            "write", "send", "reply", "create", "delete", "remove", "post",
            "commit", "push", "execute", "terminal", "amend", "move", "update",
        }
        if set(lower.split("_")) & mutating or any(word in description.lower() for word in mutating):
            return "write"
        return "unknown"

    @classmethod
    def _authorized(cls, capability: Capability, task_type: str, scope: str) -> bool:
        if capability.risk in {"read", "internal"}:
            return True
        if capability.name == "reply" and task_type == "respond" and scope == "direct_response":
            return True
        # External mutation is withheld until an explicit authorization layer
        # attaches a stronger scope to the TaskRecord.
        return scope in {"explicit", "trusted_workflow"}

    @staticmethod
    def _type_bonus(task_type: str, name: str) -> float:
        if task_type == "respond" and name == "reply":
            return 3.0
        if task_type == "remember" and name == "memory_recall":
            return 3.0
        if task_type in {"plan", "deliberate"} and name in {"memory_recall", "note_append"}:
            return 1.0
        return 0.0

    @staticmethod
    def _tokens(text: str) -> Set[str]:
        return {
            token for token in _WORD_RE.findall((text or "").lower())
            if token not in _STOP and len(token) > 1
        }

    def _semantic_scores(
        self,
        objective: str,
        capabilities: List[Capability],
    ) -> Dict[str, float]:
        if self._query_embedder is None or self._document_batch_embedder is None:
            return {}
        try:
            generation = int(getattr(self._registry, "generation", 0))
            capability_names = {capability.name for capability in capabilities}
            if (
                generation != self._embedding_generation
                or capability_names != set(self._embeddings)
            ):
                documents = [
                    capability.name.replace("_", " ") + ". " + capability.description
                    for capability in capabilities
                ]
                vectors = np.asarray(
                    self._document_batch_embedder(documents), dtype=np.float32
                )
                if vectors.ndim != 2 or vectors.shape[0] != len(capabilities):
                    return {}
                self._embeddings = {
                    capability.name: self._normalize(vector)
                    for capability, vector in zip(capabilities, vectors)
                }
                self._embedding_generation = generation
            query = self._normalize(
                np.asarray(self._query_embedder(objective), dtype=np.float32).reshape(-1)
            )
            if float(np.linalg.norm(query)) < 1e-8:
                return {}
            return {
                name: float(np.dot(query, vector))
                for name, vector in self._embeddings.items()
                if vector.shape == query.shape
            }
        except Exception:
            return {}

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 1e-8 else vector
