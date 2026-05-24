"""
Helix — Three-Tier Memory Manager (Journal Backend)

Manages the unified memory pipeline using the append-only CognitiveJournal.
Replaces the legacy SQLite/ChromaDB architecture.

1. SHORT-TERM (ephemeral): Most recent journal entries.
2. LONG-TERM (deep archive): The full append-only journal file.
   Powers the conscious 'remember' tool and the spatial representation.
3. CORE (functional long-term): High importance memories in the journal.

Pre-conscious ONLY queries: short-term + core.
Long-term is ONLY used by: conscious remember tool + spatial engine.
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
        self._spatial_mind = None  # Injected later for KD-Tree search
        
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
        """Inject spatial_mind so search_semantic can query the in-memory KD-Tree."""
        self._spatial_mind = spatial_mind
        logger.info("MemoryManager: spatial_mind injected for KD-Tree search")

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
        position_8d: Optional[List[float]] = None,
    ) -> str:
        """Store a memory to the unified journal.

        Returns the string memory ID.

        EVERY memory gets a mandatory ISO 8601 timestamp with timezone.
        Memories are stored with their 8D spatial position and the
        Lagrangian state at time of encoding (somatic snapshot).
        """
        if self._frozen:
            logger.debug(f"Memory frozen — write suppressed: {content[:60]}...")
            return "-1"

        tags = tags or []
        belief_ids = belief_ids or []
        lagrangian_snapshot = lagrangian_snapshot or {}
        now = _now_iso()

        entry = {
            "content": content,
            "type": memory_type,
            "source": source,
            "importance": importance,
            "tags": tags,
            "timestamp": now,
            "encoding_lagrangian": lagrangian_snapshot,
            "belief_ids": belief_ids,
            "position_8d": position_8d,
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
        
        # If spatial_mind is loaded, directly inject this new point so it's instantly searchable!
        if self._spatial_mind and position_8d and len(position_8d) == 8:
            # Reformat for the memory space
            point = {
                "id": entry_id,
                "content": content,
                "type": "memory",
                "importance": importance,
                "mass": importance,
                "timestamp": now,
                "position_8d": position_8d
            }
            try:
                self._spatial_mind.memory_space.add_point(point)
            except Exception as e:
                logger.error(f"Failed to inject new memory into KD-Tree: {e}")

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
        """Semantic search via the in-memory KD-Tree.
        
        Queries self._spatial_mind.memory_space instead of ChromaDB.
        """
        if not self._spatial_mind:
            logger.warning("search_semantic called but _spatial_mind is not injected.")
            return []

        try:
            # The spatial_mind needs an embedding for the query.
            # We use the belief_space or memory_space embedder.
            # It's more robust to let the space handle the text embedding and search.
            results = self._spatial_mind.memory_space.search(query, k=limit)
            
            memories = []
            for res in results:
                point = res["point"]
                # Convert KD-Tree distance back to a 0-1 relevance score
                distance = res.get("distance", 1.0)
                relevance = round(max(0.0, 1.0 - (distance / 2.0)), 3)
                
                # Exclude completely irrelevant results
                if relevance > 0.3:
                    memories.append({
                        "id": point.get("id", ""),
                        "content": point.get("content", ""),
                        "memory_type": point.get("type", "unknown"),
                        "importance": point.get("importance", 0.5),
                        "created_at": point.get("timestamp", ""),
                        "relevance": relevance,
                    })
            
            # Sort by relevance
            memories.sort(key=lambda x: x["relevance"], reverse=True)
            return memories

        except Exception as e:
            logger.error(f"KD-Tree search failed: {e}")
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
