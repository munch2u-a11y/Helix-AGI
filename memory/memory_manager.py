# Refactored MemoryManager – now uses the unified CognitiveJournal
"""
MemoryManager provides a simple API for storing and retrieving memories.
The legacy SQLite/ChromaDB implementation has been replaced with an
append‑only JSONL journal (`cognitive_journal.jsonl`). All historical data
is preserved via the migration script (to be added later).
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.cognitive_journal import CognitiveJournal

logger = logging.getLogger("helix.memory.manager")


def _now_iso() -> str:
    """Return the current UTC time as an ISO‑8601 string with seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryManager:
    """Simple memory manager backed by :class:`CognitiveJournal`.

    The public interface mirrors the original class so that higher‑level code
    (pre‑conscious, tools, etc.) can continue to call ``store`` and
    ``get_recent`` without modification.
    """

    def __init__(self, data_dir: str):
        """Initialize the manager.

        * ``data_dir`` – directory where the journal file will be stored.
        """
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        # Initialise the unified journal
        self.journal = CognitiveJournal(Path(data_dir))
        # In‑memory counter to emulate short‑term IDs for compatibility
        self._st_counter = 0
        # Physics engine reference (injected after construction)
        # Provides access to the 384D SemanticIndex for conscious recall
        self._physics = None
        logger.info(f"MemoryManager initialized with journal at {self.journal.path}")

    def set_physics(self, physics_engine):
        """Wire the physics engine for 384D semantic search.

        Called during setup_helix() after both MemoryManager and PhysicsEngine
        are constructed. Enables search_semantic() and recall_with_somatic_echo().
        """
        self._physics = physics_engine
        logger.info("MemoryManager: physics engine wired for 384D semantic search")

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
        embedding_384d: Optional[List[float]] = None,
    ) -> int:
        """Append a memory entry to the journal.

        Returns a generated short‑term ID (incrementing integer) for backward
        compatibility. No SQLite or ChromaDB writes are performed.

        If embedding_384d is provided, it is persisted in the journal for
        SemanticIndex rebuilds and also registered in the 384D index for
        immediate searchability.
        """
        tags = tags or []
        belief_ids = belief_ids or []
        lagrangian_snapshot = lagrangian_snapshot or {}
        now = _now_iso()
        self._st_counter += 1
        st_id = self._st_counter

        self.journal.append_memory(
            id=str(st_id),
            content=content,
            position_8d=position_8d or [],
            pulse_id=0,  # caller can later update if needed
            lagrangian=lagrangian_snapshot,
            metadata={
                "memory_type": memory_type,
                "source": source,
                "importance": importance,
                "tags": tags,
                "belief_ids": belief_ids,
                "created_at": now,
            },
            embedding_384d=embedding_384d,
        )

        # Register in the 384D SemanticIndex for conscious recall
        if self._physics and embedding_384d:
            import numpy as np
            self._physics.semantic_index.add(
                id=f"mem_{st_id}",
                embedding=np.array(embedding_384d, dtype=np.float32),
                metadata={
                    "content": content,
                    "memory_type": memory_type,
                    "importance": importance,
                    "created_at": now,
                    "source": source,
                    "encoding_omega": lagrangian_snapshot.get("omega", 0.5),
                },
            )

        logger.debug(
            f"Memory stored (st_id={st_id}, type={memory_type}, importance={importance:.2f}): {content[:80]}..."
        )
        return st_id

    # ── Retrieval ────────────────────────────────────────────────────
    def get_recent(self, limit: int = 20, minutes_back: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return the most recent memory entries from the journal.

        * ``limit`` – maximum number of entries to return.
        * ``minutes_back`` – if provided, filter out entries older than this
          many minutes.
        """
        entries = self.journal.load_all()
        mem_entries = [e for e in entries if e.get("type") == "memory"]
        if minutes_back is not None:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_back)
            cutoff_iso = cutoff_dt.isoformat(timespec="seconds")
            mem_entries = [e for e in mem_entries if e.get("timestamp") >= cutoff_iso]
        # newest first
        recent = mem_entries[-limit:][::-1] if limit else mem_entries[::-1]
        result = []
        for e in recent:
            meta = e.get("metadata", {})
            result.append(
                {
                    "id": e.get("id"),
                    "content": e.get("content"),
                    "memory_type": meta.get("memory_type"),
                    "source": meta.get("source"),
                    "importance": meta.get("importance"),
                    "tags": meta.get("tags"),
                    "created_at": e.get("timestamp"),
                    "lagrangian_snapshot": e.get("lagrangian", {}),
                }
            )
        return result

    def get_historical_sample(
        self,
        core_cap: int = 2000,
        timeline_pct: float = 0.10,
        timeline_min: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Return a representative sample of memories across the FULL timeline.

        Unlike get_recent (which returns only the newest), this method
        ensures historical memories are represented — people, events, and
        high-importance entries from months ago are included alongside
        recent ones.

        Sampling strategy:
            1. ALL entries with importance >= 0.7 ("core" memories),
               capped at ``core_cap`` (default 2000). These are the
               backbone of episodic recall.
            2. A percentage (``timeline_pct``, default 10%) of the
               remaining non-core entries, evenly spaced across the
               timeline, with a floor of ``timeline_min`` (default 1000).

        For a mature Helix mind (~20K memories), this produces:
            ~2000 core + ~1800 timeline = ~3800 memory points
        which combines with ~500 belief points for a total manifold
        of ~4-5K points.

        Args:
            core_cap: Maximum number of high-importance memories (>= 0.7).
            timeline_pct: Fraction (0.0-1.0) of remaining memories to sample.
            timeline_min: Minimum timeline samples regardless of percentage.
        """
        entries = self.journal.load_all()
        mem_entries = [e for e in entries if e.get("type") == "memory"]

        # Split into core (high importance) and timeline (everything else)
        core = []
        timeline = []
        for e in mem_entries:
            imp = e.get("metadata", {}).get("importance", 0.5)
            if imp >= 0.7 and len(core) < core_cap:
                core.append(e)
            else:
                timeline.append(e)

        # Sample timeline entries: percentage with a minimum floor
        timeline_slots = max(timeline_min, int(len(timeline) * timeline_pct))
        if len(timeline) <= timeline_slots:
            selected_timeline = timeline
        else:
            step = max(1, len(timeline) // timeline_slots)
            selected_timeline = [timeline[i] for i in range(0, len(timeline), step)]
            selected_timeline = selected_timeline[:timeline_slots]

        selected = core + selected_timeline

        # Build result dicts
        result = []
        for e in selected:
            meta = e.get("metadata", {})
            result.append({
                "id": e.get("id"),
                "content": e.get("content"),
                "memory_type": meta.get("memory_type"),
                "source": meta.get("source"),
                "importance": meta.get("importance", 0.5),
                "tags": meta.get("tags", []),
                "created_at": e.get("timestamp"),
                "lagrangian_snapshot": e.get("lagrangian", {}),
            })

        logger.info(
            f"Historical sample: {len(core)} core + {len(selected_timeline)} "
            f"timeline ({timeline_pct*100:.0f}% of {len(timeline)}) = {len(result)} total"
        )
        return result

    def search_semantic(
        self,
        query: str,
        limit: int = 10,
        filter_fn=None,
        return_embeddings: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search the 384D SemanticIndex for memories matching a query.

        Uses cosine similarity in native embedding space for precise
        semantic matching. Falls back gracefully if the physics engine
        is not wired or the index is empty.

        Args:
            query: Natural language search string
            limit: Maximum number of results
            filter_fn: Optional predicate (id, metadata) → bool. Only
                       vectors where filter_fn returns True are included.
            return_embeddings: If True, include the normalized 384D
                               embedding in each result dict.
        """
        if not self._physics:
            logger.debug("search_semantic called but physics engine not wired")
            return []

        try:
            results = self._physics.semantic_search(
                query, k=limit, filter_fn=filter_fn,
                return_embeddings=return_embeddings,
            )
            return [
                {
                    "id": r["id"],
                    "content": r["metadata"].get("content", ""),
                    "importance": r["metadata"].get("importance", 0.5),
                    "created_at": r["metadata"].get("created_at", ""),
                    "memory_type": r["metadata"].get("memory_type", ""),
                    "source": r["metadata"].get("source", ""),
                    "similarity": r.get("similarity", 0.0),
                    "encoding_omega": r["metadata"].get("encoding_omega", 0.5),
                    **({"embedding": r["embedding"]} if "embedding" in r else {}),
                }
                for r in results
            ]
        except Exception as e:
            logger.warning(f"search_semantic failed: {e}")
            return []

    def recall_with_somatic_echo(
        self,
        search: str,
        limit: int = 3,
        sentinel=None,
        filter_fn=None,
    ) -> List[Dict[str, Any]]:
        """Search 384D index + apply somatic echo from encoding state.

        Somatic echo: when a memory is recalled, the emotional state
        at encoding time gently nudges the current omega. Memories
        formed under stress pull Ω down; memories from flow states
        push Ω up. This is how the body "remembers" — recall isn't
        just informational, it's physiological.

        The nudge is gentle (10% weight) to avoid jarring state changes.

        Args:
            search: Natural language query string
            limit: Maximum number of results
            sentinel: StabilitySentinel instance (for omega nudging)
            filter_fn: Optional predicate (id, metadata) → bool
        """
        results = self.search_semantic(search, limit=limit, filter_fn=filter_fn)

        if sentinel and results:
            for r in results:
                encoding_omega = r.get("encoding_omega", 0.5)
                # Somatic echo: gently nudge ω toward the emotional
                # state at encoding.  Delta is the *difference* between
                # the memory's encoding omega and the current omega,
                # scaled by 0.1 so each recall is a gentle pull, not
                # a hard set.
                if hasattr(sentinel, 'nudge_omega'):
                    delta = (encoding_omega - sentinel.omega) * 0.1
                    sentinel.nudge_omega(delta, reason="memory_recall_somatic_echo")
                elif hasattr(sentinel, 'omega'):
                    # Fallback: manual blend if nudge_omega not available
                    current = sentinel.omega
                    sentinel.omega = current * 0.9 + encoding_omega * 0.1

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Return basic stats about the journal-backed memory store.

        Provides enough information for the StabilitySentinel health probe
        and the interactive CLI ``stats`` command.
        """
        try:
            entries = self.journal.load_all()
            mem_entries = [e for e in entries if e.get("type") == "memory"]
            return {
                "total_entries": len(entries),
                "total_memories": len(mem_entries),
                "journal_path": str(self.journal.path),
            }
        except Exception as e:
            logger.warning(f"get_stats failed: {e}")
            return {"total_entries": 0, "total_memories": 0, "error": str(e)}

    # re‑implemented as needed. They are omitted here to keep the class focused
    # on the new append‑only storage model.
