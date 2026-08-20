"""Native Helix mRAG runtime for the Over-Agent.

This module is the one memory boundary used by the conductor, researcher,
document ingester, and proactive vision path.  It does not maintain a second
JSON cache or a keyword-only fallback.  Reads go through Helix's unified mRAG
retrieval over the canonical belief store and cognitive journal; writes go
through :class:`memory.memory_manager.MemoryManager`.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


APP_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = APP_DIR.parent
LAYER2_BELIEF_CATEGORIES = ("people", "concepts", "skills", "desires")


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
        from core.unified_retrieval import UnifiedRetrieval
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

        self.retrieval = UnifiedRetrieval(
            belief_store=self.belief_store,
            memory_manager=self.memory_manager,
            physics_engine=self.physics_engine,
        )

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
            memory_id = self.memory_manager.store(
                content=content,
                memory_type=memory_type,
                source=source,
                importance=importance,
                tags=tags or [],
                record_metadata=record_metadata or {},
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
        return {
            "repo_root": str(self.config.repo_root),
            "data_dir": str(self.config.data_dir),
            "semantic_dimensions": int(self.physics_engine.semantic_encoder.dim),
            "semantic_index_count": int(self.physics_engine.semantic_index.count),
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
