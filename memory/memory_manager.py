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
import threading
from functools import wraps
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.cognitive_journal import CognitiveJournal

logger = logging.getLogger("helix.memory.manager")


def _serialized_store(method):
    """Serialize memory ingest across conscious and task-focus threads."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._store_lock:
            return method(self, *args, **kwargs)
    return wrapped


def _now_iso() -> str:
    """Return the local wall-clock timestamp with seconds precision."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class MemoryManager:
    """Simple memory manager backed by :class:`CognitiveJournal`.

    The public interface mirrors the original class so that higher‑level code
    (pre‑conscious, tools, etc.) can continue to call ``store`` and
    ``get_recent`` without modification.
    """

    REINFORCEMENT_MEMORY_TYPES = {
        "event",
        "incoming_message",
        "tool_intake",
        "tool_failure",
        "reminder",
    }
    REINFORCEMENT_SIMILARITY = 0.94
    POSITION_ECHO_BLEND = 0.70

    def __init__(self, data_dir: str):
        """Initialize the manager.

        * ``data_dir`` – directory where the journal file will be stored.
        """
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        # Initialise the unified journal
        self.journal = CognitiveJournal(Path(data_dir))
        # In‑memory counter to emulate short‑term IDs for compatibility
        self._st_counter = self._initialize_counter()
        # Physics engine reference (injected after construction)
        # Provides access to the 1024D SemanticIndex for conscious recall
        self._physics = None
        self._store_lock = threading.RLock()
        logger.info(f"MemoryManager initialized with journal at {self.journal.path}")

    def _initialize_counter(self) -> int:
        """Resume the legacy integer memory counter from journal contents."""
        highest = 0
        try:
            for entry in self.journal.load_all():
                if entry.get("type") != "memory":
                    continue
                raw_id = str(entry.get("id", ""))
                if raw_id.isdigit():
                    highest = max(highest, int(raw_id))
        except Exception as e:
            logger.debug("Failed to restore memory counter: %s", e)
        return highest

    @staticmethod
    def point_id(memory_id: Any) -> str:
        """Canonical runtime point ID for a journal memory entry."""
        return f"mem_{memory_id}"

    @staticmethod
    def journal_id(point_id: Any) -> str:
        """Recover the journal ID from a runtime point ID."""
        point_id = str(point_id)
        if point_id.startswith("mem_"):
            return point_id[4:]
        return point_id

    def set_physics(self, physics_engine):
        """Wire the physics engine for native 1024D semantic search.

        Called during setup_helix() after both MemoryManager and PhysicsEngine
        are constructed. Enables semantic anchoring, contextual recall,
        and somatic-echo retrieval.
        """
        self._physics = physics_engine
        logger.info("MemoryManager: physics engine wired for 1024D semantic search")

    def _find_reinforcement_target(
        self,
        content: str,
        memory_type: str,
        source: str,
    ) -> Optional[Dict[str, Any]]:
        """Find a prior intake memory to reinforce before storing a new episode."""
        if (
            self._physics is None
            or source != "pulse_input"
            or memory_type not in self.REINFORCEMENT_MEMORY_TYPES
            or not content.strip()
        ):
            return None

        def _filter(_vid: str, meta: Dict[str, Any]) -> bool:
            return (
                meta.get("type") == "memory"
                and meta.get("source") == source
                and meta.get("memory_type") in self.REINFORCEMENT_MEMORY_TYPES
            )

        try:
            candidates = self._physics.semantic_search(
                content,
                k=3,
                filter_fn=_filter,
            )
            memory_space = getattr(
                getattr(self._physics, "spatial_mind", None),
                "memory_space",
                None,
            )
            if memory_space is None:
                return None

            for candidate in candidates:
                similarity = float(candidate.get("similarity", 0.0))
                if similarity < self.REINFORCEMENT_SIMILARITY:
                    continue
                point_id = candidate.get("id", "")
                point = memory_space.get_point(point_id) if point_id else None
                if not point:
                    continue
                return {
                    "point_id": point_id,
                    "journal_id": str(candidate.get("metadata", {}).get("journal_id") or self.journal_id(point_id)),
                    "position": point.get("position"),
                    "similarity": similarity,
                }
        except Exception as e:
            logger.debug("Reinforcement lookup failed: %s", e)
        return None

    def _blend_echo_position(
        self,
        current_position: Optional[List[float]],
        prior_position: Any,
    ) -> List[float]:
        """Blend a repeated intake episode toward the prior attractor."""
        if prior_position is None:
            return list(current_position or [])

        prior = [float(x) for x in prior_position]
        current = list(current_position or [])
        if not current:
            return prior
        if len(current) != len(prior):
            return current

        prior_weight = self.POSITION_ECHO_BLEND
        current_weight = 1.0 - prior_weight
        return [
            (prior_weight * float(old)) + (current_weight * float(new))
            for old, new in zip(prior, current)
        ]

    def _format_memory_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a journal memory entry for callers."""
        meta = entry.get("metadata", {})
        memory_id = str(entry.get("id", ""))
        created_at = meta.get("created_at") or entry.get("timestamp")
        return {
            "id": memory_id,
            "point_id": meta.get("point_id", self.point_id(memory_id)),
            "content": entry.get("content", ""),
            "memory_type": meta.get("memory_type"),
            "source": meta.get("source"),
            "importance": meta.get("importance", 0.5),
            "tags": meta.get("tags", []),
            "belief_ids": meta.get("belief_ids", []),
            "echo_of": meta.get("echo_of"),
            "created_at": created_at,
            "timestamp": entry.get("timestamp"),
            "pulse_id": entry.get("pulse_id", 0),
            "position_8d": entry.get("position_8d", []),
            "attention_position_8d": meta.get("attention_position_8d", []),
            "embedding_384d": entry.get("embedding_384d"),
            "lagrangian_snapshot": entry.get("lagrangian", {}),
        }

    # ── Primary Write ────────────────────────────────────────────────
    @_serialized_store
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
        pulse_id: Optional[int] = None,
    ) -> int:
        """Append a memory entry to the journal.

        Returns a generated short‑term ID (incrementing integer) for backward
        compatibility. No SQLite or ChromaDB writes are performed.

        If embedding_384d is provided, it is persisted in the journal for
        SemanticIndex rebuilds and also registered in the 384D index for
        immediate searchability.
        """
        tags = list(dict.fromkeys(tags or []))
        belief_ids = belief_ids or []
        lagrangian_snapshot = lagrangian_snapshot or {}
        now = _now_iso()
        self._st_counter += 1
        st_id = self._st_counter
        actual_pulse_id = pulse_id
        if actual_pulse_id is None and self._physics is not None:
            actual_pulse_id = getattr(self._physics, "_pulse_count", 0)
        if actual_pulse_id is None:
            actual_pulse_id = 0

        reinforcement_target = self._find_reinforcement_target(
            content=content,
            memory_type=memory_type,
            source=source,
        )
        if reinforcement_target and self._physics is not None:
            memory_space = getattr(
                getattr(self._physics, "spatial_mind", None),
                "memory_space",
                None,
            )
            if memory_space is not None:
                memory_space.update_access(reinforcement_target["point_id"])
            tags = list(dict.fromkeys(tags + ["repeat_echo"]))

        canonical_position = self._blend_echo_position(
            position_8d,
            reinforcement_target.get("position") if reinforcement_target else None,
        )
        canonical_embedding = list(embedding_384d) if embedding_384d is not None else None

        if self._physics is not None:
            _, canonical_position, canonical_embedding = self._physics.register_memory_entry(
                memory_id=st_id,
                content=content,
                importance=importance,
                memory_type=memory_type,
                source=source,
                created_at=now,
                lagrangian_snapshot=lagrangian_snapshot,
                pulse_id=actual_pulse_id,
                embedding_384d=embedding_384d,
                position_8d=canonical_position,
                tags=tags,
                belief_ids=belief_ids,
            )

        self.journal.append_memory(
            id=str(st_id),
            content=content,
            position_8d=canonical_position,
            pulse_id=actual_pulse_id,
            lagrangian=lagrangian_snapshot,
            metadata={
                "memory_type": memory_type,
                "source": source,
                "importance": importance,
                "tags": tags,
                "belief_ids": belief_ids,
                "echo_of": reinforcement_target.get("journal_id") if reinforcement_target else None,
                "created_at": now,
                "attention_position_8d": position_8d or [],
                "point_id": self.point_id(st_id),
            },
            embedding_384d=canonical_embedding,
        )

        logger.debug(
            f"Memory stored (st_id={st_id}, type={memory_type}, importance={importance:.2f}): {content[:80]}..."
        )
        return st_id

    # ── Retrieval ────────────────────────────────────────────────────
    def get_recent(self, limit: int = 20, pulses_back: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return the most recent memory entries from the journal.

        * ``limit`` – maximum number of entries to return.
        * ``pulses_back`` – if provided, filter out entries older than this
          many pulses. This keeps internal recency tied to Helix's own
          cognitive time rather than wall-clock minutes.
        """
        entries = self.journal.load_all()
        mem_entries = [e for e in entries if e.get("type") == "memory"]
        if pulses_back is not None:
            reference_pulse = 0
            if self._physics is not None:
                reference_pulse = int(getattr(self._physics, "_pulse_count", 0) or 0)
            if reference_pulse <= 0:
                reference_pulse = max(
                    (int(entry.get("pulse_id", 0) or 0) for entry in mem_entries),
                    default=0,
                )
            if reference_pulse > 0:
                cutoff_pulse = max(0, reference_pulse - int(pulses_back))
                mem_entries = [
                    entry
                    for entry in mem_entries
                    if int(entry.get("pulse_id", 0) or 0) >= cutoff_pulse
                ]
        # newest first
        recent = mem_entries[-limit:][::-1] if limit else mem_entries[::-1]
        result = []
        for e in recent:
            result.append(self._format_memory_entry(e))
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
            result.append(self._format_memory_entry(e))

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
        """Search the 1024D SemanticIndex for memories matching a query.

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
            latest_journal = self.journal.latest_by_id()

            def wrapped_filter(vid, meta):
                if meta.get("type") != "memory":
                    return False
                if filter_fn is None:
                    return True
                journal_id = meta.get("journal_id") or self.journal_id(vid)
                return bool(filter_fn(journal_id, meta))

            results = self._physics.semantic_search(
                query,
                k=limit,
                filter_fn=wrapped_filter,
                return_embeddings=return_embeddings,
            )
            normalized = []
            for r in results:
                meta = r.get("metadata", {})
                if meta.get("type") != "memory":
                    continue
                point_id = r.get("id", "")
                journal_id = str(meta.get("journal_id") or self.journal_id(point_id))
                entry = latest_journal.get(journal_id, {})
                formatted = self._format_memory_entry(entry) if entry else {
                    "id": journal_id,
                    "point_id": point_id,
                    "content": meta.get("content", ""),
                    "memory_type": meta.get("memory_type", ""),
                    "source": meta.get("source", ""),
                    "importance": meta.get("importance", 0.5),
                    "tags": meta.get("tags", []),
                    "belief_ids": meta.get("belief_ids", []),
                    "echo_of": meta.get("echo_of"),
                    "created_at": meta.get("created_at", ""),
                    "timestamp": meta.get("created_at", ""),
                    "pulse_id": meta.get("pulse_id", 0),
                    "position_8d": meta.get("position_8d", []),
                    "attention_position_8d": [],
                    "embedding_384d": None,
                    "lagrangian_snapshot": {},
                }
                formatted.update({
                    "similarity": r.get("similarity", 0.0),
                    "encoding_omega": meta.get("encoding_omega", 0.5),
                })
                if "embedding" in r:
                    formatted["embedding"] = r["embedding"]
                normalized.append(formatted)
            return normalized
        except Exception as e:
            logger.warning(f"search_semantic failed: {e}")
            return []

    def search_contextual(
        self,
        query: str,
        limit: int = 10,
        filter_fn=None,
        return_embeddings: bool = False,
        refresh_access: bool = True,
    ) -> List[Dict[str, Any]]:
        """Search memories via semantic anchors, then rerank by manifold gravity.

        This keeps conscious recall precise while letting the current
        attention trajectory shape which matching memories feel most alive.
        """
        semantic_limit = max(limit * 4, 20)
        candidates = self.search_semantic(
            query,
            limit=semantic_limit,
            filter_fn=filter_fn,
            return_embeddings=return_embeddings,
        )
        if not candidates or not self._physics:
            return candidates[:limit]

        try:
            center = self._physics.derive_query_center(
                focus_text=query,
                attention_relative=True,
            )
            memory_space = getattr(
                getattr(self._physics, "spatial_mind", None),
                "memory_space",
                None,
            )
            if memory_space is None:
                return candidates[:limit]

            rescored = []
            for candidate in candidates:
                point_id = candidate.get("point_id", "")
                point = memory_space.get_point(point_id) if point_id else None
                gravity = 0.0
                if point:
                    position = point.get("position")
                    if position is not None:
                        dist_sq = sum(
                            (float(a) - float(b)) ** 2
                            for a, b in zip(position, center)
                        )
                        gravity = (
                            memory_space._compute_temperature(point)
                            * memory_space._compute_structural_mass(point)
                        ) / (dist_sq + 1e-4)

                scored = dict(candidate)
                similarity = float(candidate.get("similarity", 0.0))
                scored["gravity"] = round(float(gravity), 4)
                scored["contextual_score"] = round(similarity * (1.0 + float(gravity)), 4)
                rescored.append(scored)

            rescored.sort(
                key=lambda item: (
                    item.get("contextual_score", 0.0),
                    item.get("similarity", 0.0),
                ),
                reverse=True,
            )

            if refresh_access:
                for item in rescored[:limit]:
                    point_id = item.get("point_id", "")
                    if point_id:
                        memory_space.update_access(point_id)

            return rescored[:limit]
        except Exception as e:
            logger.warning(f"search_contextual failed: {e}")
            return candidates[:limit]

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
        results = self.search_contextual(search, limit=limit, filter_fn=filter_fn)

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
