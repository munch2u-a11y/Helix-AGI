"""Helix memory runtime for the Over-Agent subproject.

This module is the one memory boundary used by the conductor, researcher,
document ingester, and proactive vision path.  It does not maintain a second
JSON cache.  On Helix revisions that provide ``core.unified_retrieval`` reads
use that native mRAG pipeline.  The original ``main`` branch predates that
module, so a small in-folder bridge uses its canonical 384D semantic index and
exact Layer-2 anchors instead.  Writes always go through
:class:`memory.memory_manager.MemoryManager`.
"""

from __future__ import annotations

import os
import inspect
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


APP_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = APP_DIR.parent
LAYER2_BELIEF_CATEGORIES = ("people", "concepts", "skills", "desires")
_WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(frozen=True)
class MRAGConfig:
    """Filesystem and retrieval settings for the embedded Helix runtime."""

    repo_root: Path = field(default_factory=lambda: DEFAULT_REPO_ROOT)
    data_dir: Optional[Path] = None
    bootstrap: bool = True
    complement_quota: int = 2
    max_items: int = 12
    token_budget: Optional[int] = None

    def __post_init__(self) -> None:
        root = Path(self.repo_root).expanduser().resolve()
        data = Path(self.data_dir).expanduser().resolve() if self.data_dir else root / "data"
        object.__setattr__(self, "repo_root", root)
        object.__setattr__(self, "data_dir", data)


class _MainRetrievalBridge:
    """Read adapter for Helix ``main`` without copying feature-branch code.

    The bridge keeps semantic retrieval as the foreground lane.  Explicit
    Layer-2 terms and aliases are prepended when the query names them exactly;
    this bounded lexicon pass does not replace semantic evidence.
    """

    def __init__(self, belief_store, memory_manager, physics_engine):
        self.belief_store = belief_store
        self.memory_manager = memory_manager
        self.physics_engine = physics_engine

    @staticmethod
    def _words(text: str) -> List[str]:
        return [word.casefold() for word in _WORD_RE.findall(text or "")]

    @classmethod
    def _contains_phrase(cls, query: str, phrase: str) -> bool:
        query_words = cls._words(query)
        phrase_words = cls._words(phrase)
        if not phrase_words or len(phrase_words) > len(query_words):
            return False
        width = len(phrase_words)
        return any(
            query_words[index:index + width] == phrase_words
            for index in range(len(query_words) - width + 1)
        )

    def _layer2_matches(self, query: str) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for category in LAYER2_BELIEF_CATEGORIES:
            for belief in self.belief_store.get_category(category, limit=500):
                names = [belief.get("term", ""), belief.get("name", "")]
                names.extend(belief.get("aliases", []) or [])
                matched = [
                    str(name) for name in names
                    if name and self._contains_phrase(query, str(name))
                ]
                if not matched:
                    continue
                item = dict(belief)
                item.update({
                    "id": str(belief.get("id", "")),
                    "content": str(belief.get("content", "")),
                    "tier": 2,
                    "lane": "layer2_exact",
                    "_category": category,
                    "category": category,
                    "score": 2.0 + max(len(self._words(name)) for name in matched),
                })
                matches.append(item)
        matches.sort(
            key=lambda item: (item.get("score", 0.0), item.get("mass", 0.0)),
            reverse=True,
        )
        return matches

    def _semantic_matches(self, query: str, limit: int) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        try:
            memories = self.memory_manager.search_semantic(query, limit=limit)
        except Exception:
            memories = []
        for memory in memories:
            item = dict(memory)
            item.update({
                "id": str(memory.get("id", "")),
                "content": str(memory.get("content", "")),
                "tier": 0,
                "lane": "semantic_384d",
                "category": memory.get("memory_type") or "memory",
                "score": float(memory.get("similarity", 0.0)),
            })
            matches.append(item)

        try:
            beliefs = self.physics_engine.semantic_search(
                query,
                k=limit,
                filter_fn=lambda _record_id, metadata: metadata.get("type") == "belief",
            )
        except Exception:
            beliefs = []
        for belief in beliefs:
            metadata = dict(belief.get("metadata", {}))
            category = str(metadata.get("category", "belief"))
            item = {
                "id": str(belief.get("id", "")),
                "content": str(metadata.get("content", "")),
                "tier": 2 if category in LAYER2_BELIEF_CATEGORIES else 1,
                "lane": "semantic_384d",
                "_category": category,
                "category": category,
                "score": float(belief.get("similarity", 0.0)),
            }
            matches.append(item)
        matches.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return matches

    def retrieve(
        self,
        trigger_text: str,
        complement_quota: int = 2,
        max_items: int = 12,
        token_budget: Optional[int] = None,
        **_unused: Any,
    ) -> List[Dict[str, Any]]:
        del complement_quota  # Main's 384D bridge has no separate complement lane.
        query = (trigger_text or "").strip()
        if not query:
            return []

        limit = max(1, int(max_items))
        ordered = self._layer2_matches(query)
        ordered.extend(self._semantic_matches(query, limit=max(limit * 2, 8)))

        selected: List[Dict[str, Any]] = []
        seen = set()
        used_tokens = 0
        for item in ordered:
            record_id = str(item.get("id", ""))
            if not record_id or record_id in seen:
                continue
            item_tokens = len(str(item.get("content", "")).split())
            if token_budget is not None and used_tokens + item_tokens > token_budget:
                continue
            selected.append(item)
            seen.add(record_id)
            used_tokens += item_tokens
            if len(selected) >= limit:
                break
        return selected


class HelixMRAGRuntime:
    """Own Helix memory storage, indexing, retrieval, and persistence."""

    def __init__(self, config: Optional[MRAGConfig] = None):
        self.config = config or MRAGConfig()
        self._lock = threading.RLock()
        self.last_retrieval: List[Dict[str, Any]] = []

        root_text = str(self.config.repo_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)

        from core.physics_engine import PhysicsEngine
        from memory.belief_store import BeliefStore
        from memory.memory_manager import MemoryManager

        data_dir = Path(self.config.data_dir)
        self.memory_manager = MemoryManager(str(data_dir / "memory"))
        self.belief_store = BeliefStore(str(data_dir / "beliefs"))
        self.physics_engine = PhysicsEngine(data_dir=str(data_dir / "spatial"))
        self.memory_manager.set_physics(self.physics_engine)
        self.belief_store.set_runtime(
            physics_engine=self.physics_engine,
            memory_manager=self.memory_manager,
        )
        if self.config.bootstrap:
            self.physics_engine.bootstrap_from_stores(
                self.belief_store,
                self.memory_manager,
            )

        try:
            from core.unified_retrieval import UnifiedRetrieval
        except ModuleNotFoundError as exc:
            if exc.name != "core.unified_retrieval":
                raise
            self.retrieval = _MainRetrievalBridge(
                belief_store=self.belief_store,
                memory_manager=self.memory_manager,
                physics_engine=self.physics_engine,
            )
            self.retrieval_mode = "main_semantic_384d_bridge"
        else:
            self.retrieval = UnifiedRetrieval(
                belief_store=self.belief_store,
                memory_manager=self.memory_manager,
                physics_engine=self.physics_engine,
            )
            self.retrieval_mode = "unified_mrag"

    def recall(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return bounded, provenance-bearing unified mRAG results."""

        query = (query or "").strip()
        if not query:
            self.last_retrieval = []
            return []

        limit = max(1, min(int(top_k), self.config.max_items))
        with self._lock:
            selected = self.retrieval.retrieve(
                trigger_text=query,
                complement_quota=self.config.complement_quota,
                max_items=limit,
                token_budget=self.config.token_budget,
            )
            self.last_retrieval = [dict(item) for item in selected]
            return [dict(item) for item in self.last_retrieval]

    def recall_context(self, query: str, top_k: int = 5) -> str:
        """Render retrieved records as compact grounding for an LLM call."""

        items = self.recall(query, top_k=top_k)
        if not items:
            return ""

        layer2 = [item for item in items if item.get("tier") == 2]
        foreground = [item for item in items if item.get("tier") != 2]
        lines = ["--- HELIX mRAG RECALLED CONTEXT ---"]
        if layer2:
            lines.append("LAYER 2 BELIEF ANCHORS")
            lines.extend(self._render_item(item) for item in layer2)
        if foreground:
            lines.append("SEMANTIC MEMORY EVIDENCE")
            lines.extend(self._render_item(item) for item in foreground)
        lines.append("-------------------------------------")
        return "\n".join(lines)

    @staticmethod
    def _render_item(item: Dict[str, Any]) -> str:
        category = item.get("_category") or item.get("category") or "memory"
        metadata = (
            f"id={item.get('id', '')} tier={item.get('tier', '')} "
            f"category={category} lane={item.get('lane', 'semantic')}"
        )
        return f"- [{metadata}] {str(item.get('content', '')).strip()}"

    def remember(
        self,
        content: str,
        *,
        memory_type: str = "observation",
        source: str = "over_agent",
        importance: float = 0.6,
        tags: Optional[List[str]] = None,
        record_metadata: Optional[Dict[str, Any]] = None,
        persist_index: bool = False,
    ) -> Optional[str]:
        """Append one canonical memory and index it in both Helix lanes."""

        content = (content or "").strip()
        if not content:
            return None
        with self._lock:
            store_kwargs: Dict[str, Any] = {
                "content": content,
                "memory_type": memory_type,
                "source": source,
                "importance": importance,
                "tags": list(tags or []),
            }
            store_parameters = inspect.signature(self.memory_manager.store).parameters
            if "record_metadata" in store_parameters:
                store_kwargs["record_metadata"] = record_metadata or {}
            else:
                # Original main has no structured record-envelope argument.
                # Preserve the boundary metadata as inspectable canonical tags.
                for key, value in sorted((record_metadata or {}).items()):
                    values = value if isinstance(value, (list, tuple, set)) else [value]
                    store_kwargs["tags"].extend(
                        f"record:{key}:{entry}" for entry in values
                        if entry is not None and str(entry).strip()
                    )
                store_kwargs["tags"] = list(dict.fromkeys(store_kwargs["tags"]))

            memory_id = self.memory_manager.store(
                **store_kwargs,
            )
            if persist_index:
                self.physics_engine.save_all()
            return str(memory_id)

    def ingest_document_chunks(
        self,
        filename: str,
        chunks: Iterable[Dict[str, Any]],
    ) -> List[str]:
        """Persist document chunks through the same canonical write path."""

        safe_name = os.path.basename(filename or "document")
        ids: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text") or chunk.get("content") or "").strip()
            if not text:
                continue
            chunk_index = int(chunk.get("chunk_index") or len(ids) + 1)
            memory_id = self.remember(
                text,
                memory_type="document_chunk",
                source=f"document:{safe_name}",
                importance=0.65,
                tags=[f"document:{safe_name}", f"chunk:{chunk_index}"],
                record_metadata={
                    "record_kind": "document_chunk",
                    "direction": "internal",
                    "epistemic_role": "source_evidence",
                    "evidence_scopes": ["document"],
                },
            )
            if memory_id is not None:
                ids.append(memory_id)
        if ids:
            self.physics_engine.save_all()
        return ids

    def get_status(self) -> Dict[str, Any]:
        stats = self.belief_store.get_stats()
        semantic_encoder = getattr(self.physics_engine, "semantic_encoder", None)
        semantic_index = getattr(self.physics_engine, "semantic_index", None)
        semantic_dimensions = int(
            getattr(semantic_encoder, "dim", 0)
            or getattr(semantic_index, "dim", 0)
            or 0
        )
        return {
            "repo_root": str(self.config.repo_root),
            "data_dir": str(self.config.data_dir),
            "retrieval_mode": self.retrieval_mode,
            "semantic_dimensions": semantic_dimensions,
            "semantic_index_count": int(getattr(semantic_index, "count", 0)),
            "memory_count": int(self.memory_manager.get_stats().get("total_memories", 0)),
            "layer2_categories": {
                category: int(stats.get(category, 0))
                for category in LAYER2_BELIEF_CATEGORIES
            },
            "last_retrieval_count": len(self.last_retrieval),
        }

    def close(self) -> None:
        with self._lock:
            self.physics_engine.save_all()


__all__ = [
    "HelixMRAGRuntime",
    "LAYER2_BELIEF_CATEGORIES",
    "MRAGConfig",
]
