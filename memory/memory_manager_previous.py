"""
Helix — Three-Tier Memory Manager

Manages the unified memory pipeline:
  1. SHORT-TERM (ephemeral): Rolling SQLite table (most recent 10,000 logs).
     Combined with CORE for pre-conscious context. Pruned on overflow.
  2. LONG-TERM (deep archive): ChromaDB collection (infinite) + SQLite.
     Permanent store. Powers the conscious 'remember' tool and the
     spatial/gravitational representation. Never pruned.
  3. CORE (functional long-term): SQLite table for promoted memories.
     Memories promoted from short-term when accessed 2+ times or
     importance >= 0.7. Never pruned. Always available to pre-conscious.

Pre-conscious ONLY queries: short-term + core.
Long-term is ONLY used by: conscious remember tool + spatial engine.

Every memory is dual-written to short-term AND long-term simultaneously.
Timestamps are mandatory ISO 8601 with timezone offset.
"""

import sqlite3
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger("helix.memory.manager")


def _now_iso() -> str:
    """Returns current local time as ISO 8601 with timezone offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class MemoryManager:
    """Unified three-tier memory system for Helix.

    All writes go to both short-term and long-term simultaneously.
    Core memories are promoted from short-term based on access frequency.
    """

    SHORT_TERM_CAPACITY = 10_000
    CORE_PROMOTION_THRESHOLD = 2    # access_count needed for promotion (low bar)
    CORE_IMPORTANCE_THRESHOLD = 0.7  # importance score that auto-promotes

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self.db_path = os.path.join(data_dir, "helix_memory.db")
        self._frozen = False  # When True, store() calls are suppressed
        self._init_db()

        # ChromaDB for long-term semantic search
        self._chroma_collection = None
        self._init_chroma()

        logger.info(
            f"MemoryManager initialized at {self.db_path} "
            f"(chroma={'OK' if self._chroma_collection else 'UNAVAILABLE'})"
        )

    def freeze(self):
        """Prevent new writes during unconscious processing.

        All store() calls will be silently suppressed and return -1.
        Read operations (get_recent, get_core, search_semantic) still work.
        """
        self._frozen = True
        logger.info("Memory FROZEN — writes suppressed")

    def unfreeze(self):
        """Resume normal write operations."""
        self._frozen = False
        logger.info("Memory UNFROZEN — writes resumed")

    # ── Database Initialization ──────────────────────────────────────

    def _init_db(self):
        """Create the three-tier tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # SHORT-TERM: Rolling buffer of recent memories
        c.execute("""
            CREATE TABLE IF NOT EXISTS short_term (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'observation',
                source TEXT DEFAULT 'system',
                importance REAL DEFAULT 0.5,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                last_accessed TEXT
            )
        """)

        # LONG-TERM: Permanent archive (mirrors short-term writes)
        c.execute("""
            CREATE TABLE IF NOT EXISTS long_term (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'observation',
                source TEXT DEFAULT 'system',
                importance REAL DEFAULT 0.5,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                last_accessed TEXT
            )
        """)

        # CORE: Promoted memories that are never pruned
        c.execute("""
            CREATE TABLE IF NOT EXISTS core_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_short_term_id INTEGER,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'observation',
                source TEXT DEFAULT 'system',
                importance REAL DEFAULT 0.5,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                promoted_at TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                last_accessed TEXT
            )
        """)

        # ── Migration: add 8D cognitive space position columns ────────
        try:
            c.execute("SELECT pos_0 FROM long_term LIMIT 1")
        except sqlite3.OperationalError:
            for i in range(8):
                c.execute(f"ALTER TABLE long_term ADD COLUMN pos_{i} REAL DEFAULT NULL")
            logger.info("Migrated long_term: added pos_0..pos_7 columns (8D cognitive space)")

        # ── Migration: add lagrangian_snapshot column ──────────────────
        try:
            c.execute("SELECT lagrangian_snapshot FROM long_term LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE long_term ADD COLUMN lagrangian_snapshot TEXT DEFAULT '{}'")
            logger.info("Migrated long_term: added lagrangian_snapshot column")

        # ── Migration: add belief_ids column ──────────────────────────
        try:
            c.execute("SELECT belief_ids FROM long_term LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE long_term ADD COLUMN belief_ids TEXT DEFAULT '[]'")
            logger.info("Migrated long_term: added belief_ids column")

        # Indexes for fast temporal and importance queries
        c.execute("CREATE INDEX IF NOT EXISTS idx_st_created ON short_term(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_st_importance ON short_term(importance)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_st_access ON short_term(access_count)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_lt_created ON long_term(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_core_created ON core_memories(created_at)")

        conn.commit()
        conn.close()

    def _init_chroma(self):
        """Initialize ChromaDB for long-term semantic search."""
        try:
            import chromadb
            chroma_dir = os.path.join(self.data_dir, "chroma_db")
            os.makedirs(chroma_dir, exist_ok=True)
            client = chromadb.PersistentClient(path=chroma_dir)
            self._chroma_collection = client.get_or_create_collection(
                name="helix_long_term",
                metadata={"hnsw:space": "cosine"},
            )
            count = self._chroma_collection.count()
            logger.info(f"ChromaDB initialized ({count} vectors)")
        except ImportError:
            logger.warning("ChromaDB not installed — semantic search unavailable")
        except Exception as e:
            logger.warning(f"ChromaDB init failed: {e}")

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
    ) -> int:
        """Store a memory to ALL tiers simultaneously.

        Returns the short-term memory ID.

        EVERY memory gets a mandatory ISO 8601 timestamp with timezone.
        Memories are stored with their 8D spatial position and the
        Lagrangian state at time of encoding (somatic snapshot).

        Args:
            content: Full memory content.
            memory_type: Category (observation, conversation, thought, etc.)
            source: What created this memory.
            importance: 0.0-1.0 importance score.
            tags: Optional tags.
            lagrangian_snapshot: Somatic state at encoding {omega, s_total, H, D_KL, severity}.
            belief_ids: Related belief IDs for provenance tracking.
            position_8d: Pre-computed 8D coordinates (if None, computed from embedding).
        """
        tags = tags or []
        belief_ids = belief_ids or []
        lagrangian_snapshot = lagrangian_snapshot or {}
        now = _now_iso()
        tags_json = json.dumps(tags)
        lagrangian_json = json.dumps(lagrangian_snapshot)
        belief_ids_json = json.dumps(belief_ids)

        # Freeze guard — unconscious cycle suppresses writes
        if self._frozen:
            logger.debug(f"Memory frozen — write suppressed: {content[:60]}...")
            return -1

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # 1. Write to SHORT-TERM
        c.execute(
            """INSERT INTO short_term
               (content, memory_type, source, importance, tags, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (content, memory_type, source, importance, tags_json, now),
        )
        st_id = c.lastrowid

        # 2. Write to LONG-TERM with spatial + somatic data
        if position_8d and len(position_8d) == 8:
            c.execute(
                """INSERT INTO long_term
                   (content, memory_type, source, importance, tags, created_at,
                    lagrangian_snapshot, belief_ids,
                    pos_0, pos_1, pos_2, pos_3, pos_4, pos_5, pos_6, pos_7)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (content, memory_type, source, importance, tags_json, now,
                 lagrangian_json, belief_ids_json,
                 *position_8d),
            )
        else:
            c.execute(
                """INSERT INTO long_term
                   (content, memory_type, source, importance, tags, created_at,
                    lagrangian_snapshot, belief_ids)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (content, memory_type, source, importance, tags_json, now,
                 lagrangian_json, belief_ids_json),
            )
        lt_id = c.lastrowid

        conn.commit()
        conn.close()

        # 3. Write to ChromaDB for semantic search
        if self._chroma_collection is not None:
            try:
                chroma_meta = {
                    "memory_type": memory_type,
                    "source": source,
                    "importance": importance,
                    "created_at": now,
                }
                # Include Lagrangian encoding data in ChromaDB metadata
                if lagrangian_snapshot:
                    chroma_meta["encoding_severity"] = lagrangian_snapshot.get("severity", "unknown")
                    chroma_meta["encoding_omega"] = lagrangian_snapshot.get("omega", 0.5)

                self._chroma_collection.add(
                    documents=[content],
                    ids=[f"mem_{lt_id}"],
                    metadatas=[chroma_meta],
                )
            except Exception as e:
                logger.warning(f"ChromaDB add failed: {e}")

        # 4. Prune short-term if over capacity
        self._prune_short_term()

        severity_tag = ""
        if lagrangian_snapshot:
            severity_tag = f", encoded_at={lagrangian_snapshot.get('severity', '?')}"

        logger.debug(
            f"Memory stored (st_id={st_id}, type={memory_type}, "
            f"importance={importance:.2f}{severity_tag}): {content[:80]}..."
        )
        return st_id

    # ── Retrieval ────────────────────────────────────────────────────

    def get_recent(self, limit: int = 20, minutes_back: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get most recent memories from short-term.

        Used by the pre-conscious for temporal context.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if minutes_back is not None:
            cutoff = (datetime.now().astimezone() - timedelta(minutes=minutes_back)).isoformat(timespec="seconds")
            c.execute(
                """SELECT * FROM short_term
                   WHERE created_at >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (cutoff, limit),
            )
        else:
            c.execute(
                "SELECT * FROM short_term ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_core_memories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all core (promoted) memories, ordered by access count."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM core_memories ORDER BY access_count DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def search_semantic(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Semantic search via ChromaDB against long-term memory."""
        if self._chroma_collection is None:
            return []

        try:
            results = self._chroma_collection.query(
                query_texts=[query],
                n_results=limit,
            )
            if not results or not results["documents"]:
                return []

            memories = []
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 1.0

                # Only keep reasonably relevant results
                if distance < 0.70:
                    memories.append({
                        "content": doc,
                        "memory_type": meta.get("memory_type", "unknown"),
                        "source": meta.get("source", "unknown"),
                        "importance": meta.get("importance", 0.5),
                        "created_at": meta.get("created_at", ""),
                        "relevance": round(1.0 - distance, 3),
                    })
            return memories

        except Exception as e:
            logger.warning(f"ChromaDB search failed: {e}")
            return []

    def touch_memory(self, memory_id: int, table: str = "short_term"):
        """Increment access_count and update last_accessed for a memory.

        If this pushes a short-term memory past the promotion threshold,
        promote it to core.
        """
        now = _now_iso()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute(
            f"""UPDATE {table} SET access_count = access_count + 1,
                last_accessed = ? WHERE id = ?""",
            (now, memory_id),
        )

        # Check for core promotion (only from short_term)
        if table == "short_term":
            c.execute(
                "SELECT access_count, importance FROM short_term WHERE id = ?",
                (memory_id,),
            )
            row = c.fetchone()
            if row:
                access_count, importance = row[0], row[1]
                # Promote if accessed enough OR if importance is high enough
                if (access_count >= self.CORE_PROMOTION_THRESHOLD or
                        importance >= self.CORE_IMPORTANCE_THRESHOLD):
                    self._promote_to_core(memory_id, conn)

        conn.commit()
        conn.close()

    # ── Pruning & Promotion ──────────────────────────────────────────

    def _prune_short_term(self):
        """Prune short-term table to stay within capacity.

        Strategy: Remove oldest memories with the lowest access_count first.
        Before pruning, promote any high-access memories to core.
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM short_term")
        count = c.fetchone()[0]

        if count <= self.SHORT_TERM_CAPACITY:
            conn.close()
            return

        overflow = count - self.SHORT_TERM_CAPACITY

        # First: promote any memories that qualify before they get pruned
        # Promote by access_count OR by importance ("heavy" memories)
        c.execute(
            """SELECT id FROM short_term
               WHERE access_count >= ? OR importance >= ?
               ORDER BY created_at ASC LIMIT ?""",
            (self.CORE_PROMOTION_THRESHOLD, self.CORE_IMPORTANCE_THRESHOLD, overflow * 2),
        )
        for row in c.fetchall():
            self._promote_to_core(row[0], conn)

        # Now prune: oldest with lowest access_count
        c.execute(
            """DELETE FROM short_term WHERE id IN (
                   SELECT id FROM short_term
                   ORDER BY access_count ASC, created_at ASC
                   LIMIT ?
               )""",
            (overflow,),
        )

        pruned = c.rowcount
        conn.commit()
        conn.close()

        if pruned > 0:
            logger.info(f"Pruned {pruned} memories from short-term (capacity: {self.SHORT_TERM_CAPACITY})")

    def _promote_to_core(self, short_term_id: int, conn: sqlite3.Connection):
        """Promote a short-term memory to the core_memories table."""
        c = conn.cursor()

        # Check if already promoted
        c.execute(
            "SELECT id FROM core_memories WHERE original_short_term_id = ?",
            (short_term_id,),
        )
        if c.fetchone():
            return  # Already promoted

        c.execute("SELECT * FROM short_term WHERE id = ?", (short_term_id,))
        row = c.fetchone()
        if not row:
            return

        now = _now_iso()
        # row indices: 0=id, 1=content, 2=memory_type, 3=source,
        #              4=importance, 5=tags, 6=created_at, 7=access_count, 8=last_accessed
        c.execute(
            """INSERT INTO core_memories
               (original_short_term_id, content, memory_type, source,
                importance, tags, created_at, promoted_at, access_count, last_accessed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (short_term_id, row[1], row[2], row[3],
             row[4], row[5], row[6], now, row[7], row[8]),
        )
        logger.info(f"Promoted memory {short_term_id} to core (access_count={row[7]})")

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return counts for each tier."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        stats = {}
        for table in ("short_term", "long_term", "core_memories"):
            c.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = c.fetchone()[0]
        conn.close()

        if self._chroma_collection:
            stats["chroma_vectors"] = self._chroma_collection.count()

        return stats

    # ── 8D Spatial Data ──────────────────────────────────────────────

    def get_all_with_positions(self) -> List[Dict[str, Any]]:
        """Fetch all memories with their 8D spatial coordinates.

        Used by the cognitive manifold to bootstrap/rebuild the spatial
        index from persisted positions.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT id, content, memory_type, importance, created_at,
                       pos_0, pos_1, pos_2, pos_3, pos_4, pos_5, pos_6, pos_7,
                       lagrangian_snapshot
                FROM long_term
            ''')
            rows = cur.fetchall()

            results = []
            for row in rows:
                data = dict(row)
                pos = [data.pop(f"pos_{i}", None) for i in range(8)]
                if all(p is not None for p in pos):
                    data["position_8d"] = pos
                # Parse lagrangian_snapshot from JSON string
                snap = data.get("lagrangian_snapshot", "{}")
                try:
                    data["lagrangian_snapshot"] = json.loads(snap) if snap else {}
                except (json.JSONDecodeError, TypeError):
                    data["lagrangian_snapshot"] = {}
                results.append(data)
            return results
        except Exception as e:
            logger.error(f"Failed to fetch memories with positions: {e}")
            return []
        finally:
            conn.close()

    def recall_with_somatic_echo(
        self,
        search: str = None,
        memory_type: str = None,
        limit: int = 10,
        sentinel=None,
    ) -> List[Dict[str, Any]]:
        """Recall memories and reproduce somatic echoes from encoding.

        State-bound episodic recall: when a memory formed under stress is
        retrieved, the system mildly re-experiences that stress. This is
        how experiential learning works — the Lagrangian snapshot stored
        with the memory creates a visceral echo in the present.

        Args:
            search: Semantic search query.
            memory_type: Filter by type.
            limit: Max results.
            sentinel: StabilitySentinel reference for somatic echo injection.

        Returns:
            List of memory dicts, with somatic processing applied.
        """
        results = self.search_semantic(query=search, limit=limit) if search else []

        if sentinel and results:
            for mem in results:
                snap = mem.get("lagrangian_snapshot", {})
                if isinstance(snap, str):
                    try:
                        snap = json.loads(snap)
                    except (json.JSONDecodeError, TypeError):
                        snap = {}
                if not snap:
                    continue

                historical_omega = snap.get("omega", 0.5)
                historical_severity = snap.get("severity", "all_clear")

                # If this memory was formed under significant stress,
                # mildly reproduce that stress in the present
                if historical_severity in ("warning", "critical"):
                    echo_magnitude = 0.02 if historical_severity == "warning" else 0.05
                    sentinel.nudge_omega(
                        -echo_magnitude,
                        f"somatic echo from memory (encoded at {historical_severity})"
                    )
                    logger.debug(
                        f"Somatic echo: memory encoded at "
                        f"Ω={historical_omega:.3f}/{historical_severity}, "
                        f"nudged current Ω by {-echo_magnitude:+.3f}"
                    )

                # If this memory was formed during a flow state,
                # mildly boost current omega
                elif historical_severity == "all_clear" and historical_omega > 0.7:
                    sentinel.nudge_omega(
                        +0.01,
                        f"positive somatic echo from memory (encoded at Ω={historical_omega:.2f})"
                    )

        return results
