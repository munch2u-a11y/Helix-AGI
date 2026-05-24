"""
Helix — Three-Tier Memory Manager (Journal Backend)

Manages the unified memory pipeline using the append-only CognitiveJournal.
Replaces the legacy SQLite/ChromaDB architecture.

1. SHORT-TERM (ephemeral): Most recent journal entries.
2. LONG-TERM (deep archive): The full append-only journal file.
   Powers the conscious 'remember' tool and the spatial representation.
3. CORE (functional long-term): High importance memories in the journal.

Pre-conscious ONLY queries: short-term + core.
Long-term is ONLY used by: conscious memory_recall tool.
Beliefs are spatially indexed in the manifold; memories are NOT.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from .cognitive_journal import CognitiveJournal

logger = logging.getLogger("helix.memory.manager")


def _now_iso() -> str:
    """Returns current local time as ISO 8601 with timezone offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class MemoryManager:
    """Unified memory system for Helix, backed by an append-only JSONL journal."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        
        journal_path = os.path.join(data_dir, "cognitive_journal.jsonl")
        self.journal = CognitiveJournal(journal_path)
        
        self._frozen = False  # When True, store() calls are suppressed
        self._embedder = None  # Lazy-loaded for on-demand search
        
        logger.info(f"MemoryManager initialized with journal at {journal_path}")

    def freeze(self):
        """Prevent new writes during unconscious processing."""
        self._frozen = True
        logger.info("Memory FROZEN — writes suppressed")

    def unfreeze(self):
        """Resume normal write operations."""
        self._frozen = False
        logger.info("Memory UNFROZEN — writes resumed")

    def set_spatial_mind(self, spatial_mind):
        """Legacy compatibility — spatial mind no longer needed for memory search."""
        logger.info("MemoryManager: set_spatial_mind called (no-op in 384D mode)")

    def compact_journal(self) -> int:
        """Triggers compaction on the underlying journal."""
        return self.journal.compact()

    # ── Primary Write ────────────────────────────────────────────────

    def store(
        self,
        content: str,
        memory_type: str = "observation",
        source: str = "system",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        lagrangian_snapshot: Optional[Dict[str, Any]] = None,
        belief_ids: Optional[List[str]] = None,
        embedding: Optional[List[float]] = None,
        position_8d: Optional[List[float]] = None,  # backward compat alias
    ) -> str:
        """Store a memory to the unified journal.

        Returns the string memory ID.

        EVERY memory gets a mandatory ISO 8601 timestamp with timezone.
        Memories are stored with their 384D embedding and the
        Lagrangian state at time of encoding (somatic snapshot).
        """
        if self._frozen:
            logger.debug(f"Memory frozen — write suppressed: {content[:60]}...")
            return "-1"

        tags = tags or []
        belief_ids = belief_ids or []
        lagrangian_snapshot = lagrangian_snapshot or {}
        now = _now_iso()
        
        # Accept either 'embedding' or legacy 'position_8d'
        emb = embedding or position_8d

        entry = {
            "content": content,
            "type": memory_type,
            "source": source,
            "importance": importance,
            "tags": tags,
            "timestamp": now,
            "encoding_lagrangian": lagrangian_snapshot,
            "belief_ids": belief_ids,
            "embedding": emb,
            "access_count": 0,
        }

        entry_id = self.journal.append(entry)
        
        severity_tag = ""
        if lagrangian_snapshot:
            severity_tag = f", encoded_at={lagrangian_snapshot.get('severity', '?')}"

        logger.debug(
            f"Memory stored (id={entry_id}, type={memory_type}, "
            f"importance={importance:.2f}{severity_tag}): {content[:80]}..."
        )

        return entry_id

    # ── Retrieval ────────────────────────────────────────────────────

    def get_recent(self, limit: int = 20, minutes_back: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get most recent memories from the journal.
        
        Used by the pre-conscious for temporal context.
        """
        entries = self.journal.load_all()
        
        if minutes_back is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes_back)
            cutoff_iso = cutoff.isoformat()
            recent = [e for e in entries if e.get("timestamp", "") >= cutoff_iso]
        else:
            recent = entries
            
        recent.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return recent[:limit]

    def get_core_memories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all core memories.
        
        In the journal paradigm, core memories are simply those with high access count
        or high importance.
        """
        entries = self.journal.load_all()
        # Filter for "core-like" memories
        core = [
            e for e in entries 
            if e.get("access_count", 0) >= 2 or e.get("importance", 0.0) >= 0.7
        ]
        core.sort(key=lambda x: x.get("access_count", 0), reverse=True)
        return core[:limit]

    def search_semantic(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """On-demand semantic search over journal memories.
        
        Embeds the query and computes L2 distances against stored
        memory embeddings. No per-pulse indexing cost — this is
        only called by the conscious memory_recall tool.
        """
        try:
            import numpy as np
            
            # Lazy-load embedder
            if self._embedder is None:
                try:
                    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
                    self._embedder = DefaultEmbeddingFunction()
                except Exception as e:
                    logger.warning(f"Embedder init failed: {e}")
                    return []
            
            # Embed query
            query_emb = np.array(self._embedder([query])[0], dtype=np.float32)
            
            # Load all entries and filter those with embeddings
            entries = self.journal.load_all()
            candidates = []
            for e in entries:
                emb = e.get("embedding") or e.get("position_8d")
                if emb and len(emb) == len(query_emb):
                    candidates.append(e)
            
            if not candidates:
                return []
            
            # Compute distances
            emb_matrix = np.array(
                [c.get("embedding") or c.get("position_8d") for c in candidates],
                dtype=np.float32
            )
            dists = np.sqrt(np.sum((emb_matrix - query_emb) ** 2, axis=1))
            
            # Sort by distance, take top K
            top_idxs = np.argsort(dists)[:limit]
            
            memories = []
            for idx in top_idxs:
                c = candidates[int(idx)]
                dist = float(dists[idx])
                relevance = round(max(0.0, 1.0 - (dist / 2.0)), 3)
                if relevance > 0.3:
                    memories.append({
                        "id": c.get("id", ""),
                        "content": c.get("content", ""),
                        "memory_type": c.get("type", "unknown"),
                        "importance": c.get("importance", 0.5),
                        "created_at": c.get("timestamp", ""),
                        "relevance": relevance,
                        "encoding_lagrangian": c.get("encoding_lagrangian", {}),
                    })
            
            return memories

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    def touch_memory(self, memory_id: str, table: str = "short_term"):
        """Increment access_count for a memory in the journal.
        
        Finds the latest entry for memory_id, increments its count,
        and appends it back to the journal as the new authoritative version.
        """
        if self._frozen:
            return
            
        entries = self.journal.load_all()
        # entries is a list of the latest versions
        target = next((e for e in entries if e.get("id") == memory_id), None)
        
        if target:
            target["access_count"] = target.get("access_count", 0) + 1
            target["last_accessed"] = _now_iso()
            # Append the updated entry
            self.journal.append(target)

    def get_stats(self) -> Dict[str, Any]:
        """Stats from the journal."""
        return self.journal.get_stats()
