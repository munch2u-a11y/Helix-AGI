"""
Helix V3 — Memory System

SQLite-backed persistent memory with ChromaDB resonance layer for
semantic search. This is the subconscious storage layer — the conscious
model (Ollama) doesn't explicitly write memories. The subconscious
records what matters based on the conscious model's engagement level.

Cleaned from V2 — same core, better dependency injection, no truncation.
"""

import sqlite3
import json
import logging
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("helix.brain.memory")


class Memory:
    """Persistent memory system — Helix's long-term storage.

    The conscious model doesn't know this exists. Memories are recorded
    by subconscious processes based on importance weighting from the
    conscious model's engagement level.

    Storage layers:
    - SQLite: Structured storage (memories table, reflections table)
    - ChromaDB: Semantic search / resonance layer
    - Journal: Plain text files (conscious tool, not memory mechanism)
    """

    def __init__(self, base_dir: Path, config: dict = None):
        self.base_dir = base_dir
        self.config = config or {}
        self.db_path = base_dir / "memory.db"
        self.journal_dir = base_dir / "journals"
        self.chroma_dir = base_dir / "chroma_db"

        # Ensure directories exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)

        # Initialize SQLite
        self._init_db()

        # Initialize ChromaDB resonance layer
        self._chroma_collection = None
        self._init_chroma()

        # V5: Spatial Mind reference — for positioning new memories in 8D
        self._spatial_mind = None

    def _init_db(self):
        """Create memory tables if they don't exist."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'observation',
                source TEXT DEFAULT 'system',
                importance REAL DEFAULT 0.5,
                tags TEXT DEFAULT '[]',
                belief_ids TEXT DEFAULT '[]',
                lagrangian_snapshot TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0
            )
        """)

        # Migration: add lagrangian_snapshot column if missing (upgrade from earlier schema)
        try:
            cursor.execute("SELECT lagrangian_snapshot FROM memories LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE memories ADD COLUMN lagrangian_snapshot TEXT DEFAULT '{}'")
            logger.info("Migrated memories table: added lagrangian_snapshot column")

        # Migration: add 8D cognitive space position columns if missing
        try:
            cursor.execute("SELECT pos_0 FROM memories LIMIT 1")
        except sqlite3.OperationalError:
            for i in range(8):
                cursor.execute(f"ALTER TABLE memories ADD COLUMN pos_{i} REAL DEFAULT NULL")
            logger.info("Migrated memories table: added pos_0..pos_7 columns (8D cognitive space)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                reflection_type TEXT DEFAULT 'general',
                source TEXT DEFAULT 'system',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Index for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_type
            ON memories(memory_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_created
            ON memories(created_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_importance
            ON memories(importance)
        """)

        conn.commit()
        conn.close()
        logger.info(f"Memory database initialized at {self.db_path}")

    def _init_chroma(self):
        """Initialize ChromaDB for semantic search."""
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(self.chroma_dir))
            self._chroma_collection = client.get_or_create_collection(
                name="helix_memories",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"ChromaDB resonance layer initialized ({self._chroma_collection.count()} vectors)")
        except Exception as e:
            logger.warning(f"ChromaDB initialization failed: {e}. Semantic search unavailable.")
            self._chroma_collection = None

    def store(
        self,
        content: str,
        memory_type: str = "observation",
        source: str = "system",
        importance: float = 0.5,
        tags: list = None,
        belief_ids: list = None,
        lagrangian_snapshot: dict = None,
        created_at: str = None,
    ) -> int:
        """Store a memory with state-bound episodic encoding. Returns the memory ID.

        Args:
            content: Full memory content — no truncation.
            memory_type: Category (observation, conversation, reflection, insight,
                         identity_anchor, dream_reflection, action_result, etc.)
            source: What created this memory (system, librarian, consciousness, etc.)
            importance: 0.0-1.0 importance score from the subconscious.
            tags: Optional tags for categorization.
            belief_ids: Optional related belief IDs for provenance tracking.
            lagrangian_snapshot: Optional Lagrangian state at time of encoding.
                                Contains H, omega, D_KL, s_total, severity, feeling.
                                This is how memories carry the echo of the system's
                                somatic state when they were formed.
            created_at: Optional timestamp override (used for imports).
        """
        tags = tags or []
        belief_ids = belief_ids or []
        lagrangian_snapshot = lagrangian_snapshot or {}

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        if created_at is None:
            cursor.execute(
                """INSERT INTO memories (content, memory_type, source, importance, tags, belief_ids, lagrangian_snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (content, memory_type, source, importance,
                 json.dumps(tags), json.dumps(belief_ids), json.dumps(lagrangian_snapshot)),
            )
        else:
            cursor.execute(
                """INSERT INTO memories (content, memory_type, source, importance, tags, belief_ids, lagrangian_snapshot, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (content, memory_type, source, importance,
                 json.dumps(tags), json.dumps(belief_ids), json.dumps(lagrangian_snapshot), created_at),
            )
        memory_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Add to ChromaDB for semantic search
        if self._chroma_collection is not None:
            try:
                doc_id = f"mem_{memory_id}"
                chroma_meta = {
                    "memory_type": memory_type,
                    "source": source,
                    "importance": importance,
                    "created_at": datetime.now().isoformat(),
                }
                # Include key Lagrangian values in ChromaDB metadata for filtering
                if lagrangian_snapshot:
                    chroma_meta["encoding_severity"] = lagrangian_snapshot.get("severity", "unknown")
                    chroma_meta["encoding_omega"] = lagrangian_snapshot.get("omega", 0.5)

                self._chroma_collection.add(
                    documents=[content],
                    ids=[doc_id],
                    metadatas=[chroma_meta],
                )

                # V5: Position in 8D memory space with Lagrangian encoding
                if self._spatial_mind:
                    try:
                        import numpy as np
                        result = self._chroma_collection.get(
                            ids=[doc_id], include=["embeddings"]
                        )
                        if len(result.get("embeddings", [])) > 0:
                            emb = np.array(result["embeddings"][0], dtype=np.float32)
                            self._spatial_mind.add_memory(
                                doc_id, emb,
                                content=content[:200],
                                importance=importance,
                                memory_type=memory_type,
                                encoding_omega=lagrangian_snapshot.get("omega", 0.5),
                                encoding_s_total=lagrangian_snapshot.get("s_total", 0.15),
                            )
                    except Exception as e_sp:
                        logger.debug(f"Spatial positioning failed for {doc_id}: {e_sp}")

            except Exception as e:
                logger.warning(f"ChromaDB add failed: {e}")

        severity_tag = ""
        if lagrangian_snapshot:
            severity_tag = f", encoded_at={lagrangian_snapshot.get('severity', '?')}"

        logger.info(
            f"Memory stored (id={memory_id}, type={memory_type}, "
            f"importance={importance:.2f}{severity_tag}): {content[:80]}..."
        )
        return memory_id

    def recall(
        self,
        search: str = None,
        memory_type: str = None,
        limit: int = 10,
        min_importance: float = 0.0,
        days_back: int = None,
    ) -> list[dict]:
        """Recall memories. Uses semantic search if available, falls back to SQL.

        Args:
            search: Search query (semantic if ChromaDB available, keyword otherwise).
            memory_type: Filter by type.
            limit: Maximum results.
            min_importance: Minimum importance threshold.
            days_back: Only return memories from the last N days.

        Returns:
            List of memory dicts with full content — no truncation.
        """
        results = []

        # Semantic search via ChromaDB
        if search and self._chroma_collection is not None:
            try:
                where_filter = {}
                conditions = []
                if memory_type:
                    conditions.append({"memory_type": memory_type})
                if min_importance > 0:
                    conditions.append({"importance": {"$gte": min_importance}})

                if len(conditions) == 1:
                    where_filter = conditions[0]
                elif len(conditions) > 1:
                    where_filter = {"$and": conditions}

                query_params = {
                    "query_texts": [search],
                    "n_results": limit,
                }
                if where_filter:
                    query_params["where"] = where_filter

                chroma_results = self._chroma_collection.query(**query_params)

                if chroma_results and chroma_results["documents"]:
                    for i, doc in enumerate(chroma_results["documents"][0]):
                        meta = chroma_results["metadatas"][0][i] if chroma_results["metadatas"] else {}
                        distance = chroma_results["distances"][0][i] if chroma_results["distances"] else 0
                        results.append({
                            "content": doc,
                            "memory_type": meta.get("memory_type", "unknown"),
                            "source": meta.get("source", "unknown"),
                            "importance": meta.get("importance", 0.5),
                            "created_at": meta.get("created_at", ""),
                            "relevance": 1.0 - distance,
                        })

                # Update access counts for recalled memories
                self._update_access_counts(results)
                return results

            except Exception as e:
                logger.warning(f"ChromaDB query failed, falling back to SQL: {e}")

        # Fallback: SQL-based recall
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM memories WHERE importance >= ?"
        params = [min_importance]

        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type)

        if days_back:
            cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
            query += " AND created_at >= ?"
            params.append(cutoff)

        if search:
            query += " AND content LIKE ?"
            params.append(f"%{search}%")

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            results.append({
                "id": row["id"],
                "content": row["content"],
                "memory_type": row["memory_type"],
                "source": row["source"],
                "importance": row["importance"],
                "tags": json.loads(row["tags"]),
                "belief_ids": json.loads(row["belief_ids"]),
                "lagrangian_snapshot": json.loads(row["lagrangian_snapshot"] or "{}"),
                "created_at": row["created_at"],
                "access_count": row["access_count"],
            })

        return results

    def get_by_id(self, memory_id: int) -> Optional[dict]:
        """Retrieve a specific memory by its SQLite ID.

        This is how belief graph memory_refs resolve to full memories.
        When Helix sees a belief with memory_refs: ["mem_42"], the system
        can retrieve the exact memory that gave rise to that belief —
        including its full content, timestamp, and Lagrangian echo
        (how Helix felt when the memory formed).

        Args:
            memory_id: The SQLite integer ID.

        Returns:
            Full memory dict, or None if not found.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        # Update access count
        self._touch_memory(memory_id)

        return {
            "id": row["id"],
            "content": row["content"],
            "memory_type": row["memory_type"],
            "source": row["source"],
            "importance": row["importance"],
            "tags": json.loads(row["tags"]),
            "belief_ids": json.loads(row["belief_ids"]),
            "lagrangian_snapshot": json.loads(row["lagrangian_snapshot"] or "{}"),
            "created_at": row["created_at"],
            "access_count": row["access_count"],
        }

    def get_by_ref(self, ref: str) -> Optional[dict]:
        """Retrieve a memory by its ref string (e.g., 'mem_42').

        Belief graph memory_refs use this format. This method parses
        the ref and delegates to get_by_id.

        Args:
            ref: A string like 'mem_42' or just '42'.

        Returns:
            Full memory dict, or None if not found.
        """
        try:
            if ref.startswith("mem_"):
                memory_id = int(ref[4:])
            else:
                memory_id = int(ref)
            return self.get_by_id(memory_id)
        except (ValueError, TypeError):
            logger.warning(f"Invalid memory ref: {ref}")
            return None

    def get_memories_for_belief(self, belief: dict) -> list[dict]:
        """Retrieve all memories referenced by a belief's memory_refs.

        This is the bridge between beliefs and experiences. When Helix
        encounters a belief and wonders "why do I believe this?", this
        method returns the originating experiences — complete with
        timestamps and Lagrangian echoes of how he felt at the time.

        Args:
            belief: A belief dict from the belief graph.

        Returns:
            List of full memory dicts.
        """
        refs = belief.get("memory_refs", [])
        memories = []
        for ref in refs:
            mem = self.get_by_ref(ref)
            if mem:
                memories.append(mem)
        return memories

    def _touch_memory(self, memory_id: int):
        """Update access count and last_accessed for a memory."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE memories SET access_count = access_count + 1, "
                "last_accessed = CURRENT_TIMESTAMP WHERE id = ?",
                (memory_id,),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Memory touch failed: {e}")

    def recall_with_somatic_echo(
        self,
        search: str = None,
        memory_type: str = None,
        limit: int = 10,
        sentinel=None,
    ) -> list[dict]:
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
        results = self.recall(search=search, memory_type=memory_type, limit=limit)

        if sentinel and results:
            for mem in results:
                snap = mem.get("lagrangian_snapshot", {})
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

    def recall_temporal(
        self,
        start_time: datetime,
        end_time: datetime,
        min_importance: float = 0.0,
        memory_types: list = None,
        limit: int = 20,
    ) -> list[dict]:
        """Recall memories from a specific time window, sorted by importance.

        This is the temporal query that powers intuitive recall. When someone
        says 'last night', the system resolves that to a time window and
        pulls the most important moments, chronologically.

        Args:
            start_time: Window start.
            end_time: Window end.
            min_importance: Minimum importance threshold.
            memory_types: Optional list of types to filter by.
            limit: Maximum results.

        Returns:
            Memories sorted by importance DESC, then created_at ASC (chronological).
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """SELECT * FROM memories
                   WHERE created_at >= ? AND created_at <= ?
                   AND importance >= ?"""
        params = [start_time.strftime("%Y-%m-%d %H:%M:%S"), end_time.strftime("%Y-%m-%d %H:%M:%S"), min_importance]

        if memory_types:
            placeholders = ",".join("?" * len(memory_types))
            query += f" AND memory_type IN ({placeholders})"
            params.extend(memory_types)

        query += " ORDER BY importance DESC, created_at ASC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def recall_conversation_arc(
        self,
        start_time: datetime,
        end_time: datetime,
        person: str = None,
        top_n: int = 6,
    ) -> dict:
        """Recall the arc of a conversation: opener, important moments, journal.

        Returns a structured dict with:
        - opener: The first message in the window
        - important_moments: Top N most important memories, chronologically
        - journal_entries: Any journal entries written during/about the window
        - participant: Who was involved
        - time_range: When it happened

        This is what focused_recall uses to present a conversation properly.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        start_iso = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_iso = end_time.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Opener — first conversation message in the window
        opener_query = """SELECT * FROM memories
                         WHERE created_at >= ? AND created_at <= ?
                         AND memory_type = 'conversation'"""
        opener_params = [start_iso, end_iso]
        if person:
            opener_query += " AND content LIKE ?"
            opener_params.append(f"%{person}%")
        opener_query += " ORDER BY created_at ASC LIMIT 1"

        cursor.execute(opener_query, opener_params)
        opener_row = cursor.fetchone()
        opener = dict(opener_row) if opener_row else None

        # 2. Most important moments — top N by importance, then chronological
        moments_query = """SELECT * FROM memories
                          WHERE created_at >= ? AND created_at <= ?
                          AND importance >= 0.4"""
        moments_params = [start_iso, end_iso]
        if person:
            moments_query += " AND content LIKE ?"
            moments_params.append(f"%{person}%")
        moments_query += " ORDER BY importance DESC, created_at ASC LIMIT ?"
        moments_params.append(top_n * 3)  # Overfetch then dedupe/trim

        cursor.execute(moments_query, moments_params)
        all_moments = [dict(r) for r in cursor.fetchall()]

        # Dedupe opener from moments, then take top_n chronologically
        opener_id = opener["id"] if opener else None
        important = [m for m in all_moments if m["id"] != opener_id]
        # Re-sort the top by time so the arc reads chronologically
        important = sorted(important[:top_n], key=lambda m: m["created_at"])

        # 3. Journal entries from that period
        journal_entries = []
        try:
            journal_date = start_time.strftime("%Y-%m-%d")
            journal_file = self.journal_dir / f"{journal_date}.md"
            if journal_file.exists():
                text = journal_file.read_text()
                # Split into entries and find ones relevant to the time window
                entries = text.split("\n---\n") if "\n---\n" in text else [text]
                for entry in entries:
                    if person and person.lower() in entry.lower():
                        journal_entries.append(entry.strip()[:300])
                    elif len(entries) <= 3:
                        # If few entries, include them all
                        journal_entries.append(entry.strip()[:300])
        except Exception:
            pass

        # 4. Detect participant from the conversation messages
        participant = person
        if not participant and opener:
            content = opener.get("content", "")
            # Try to extract from "[telegram] PersonName said:" or "I told PersonName:"
            for pattern in ["[telegram] ", "[discord] "]:
                if pattern in content:
                    after = content.split(pattern, 1)[1]
                    if " said:" in after:
                        participant = after.split(" said:")[0].strip()
                    elif "I told " in after:
                        participant = after.split("I told ")[1].split(":")[0].strip()
                    break

        conn.close()

        return {
            "opener": opener,
            "important_moments": important,
            "journal_entries": journal_entries[:3],
            "participant": participant,
            "time_range": {
                "start": start_time.strftime("%I:%M %p"),
                "end": end_time.strftime("%I:%M %p"),
                "date": start_time.strftime("%A, %B %d"),
            },
        }

    def get_recent_context(self, hours: int = 24, limit: int = 20) -> list[dict]:
        """Get recent memories for context assembly.

        Used by the Librarian to build whisper context.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """SELECT * FROM memories
               WHERE created_at >= ?
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (cutoff, limit),
        )
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def save_reflection(
        self,
        content: str,
        reflection_type: str = "general",
        source: str = "system",
    ) -> int:
        """Save a reflection (nap note, dream narrative, overnight analysis).

        Reflections are separate from memories — they're the subconscious
        processing output, not raw experience.
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute(
            """INSERT INTO reflections (content, reflection_type, source)
               VALUES (?, ?, ?)""",
            (content, reflection_type, source),
        )
        reflection_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Reflection saved (id={reflection_id}, type={reflection_type})")
        return reflection_id

    def get_reflections(
        self,
        reflection_type: str = None,
        limit: int = 10,
        days_back: int = None,
    ) -> list[dict]:
        """Get reflections (nap notes, dreams, analyses)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM reflections WHERE 1=1"
        params = []

        if reflection_type:
            query += " AND reflection_type = ?"
            params.append(reflection_type)

        if days_back:
            cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
            query += " AND created_at >= ?"
            params.append(cutoff)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def consolidate(self, keep_days: int = 90, protected_types: list = None):
        """Consolidate old, low-importance memories.

        Protected types are never consolidated (identity anchors, dreams, etc.)
        """
        protected_types = protected_types or [
            "identity_anchor", "dream_reflection", "core_belief",
            "relationship", "milestone",
        ]

        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        placeholders = ",".join("?" for _ in protected_types)
        cursor.execute(
            f"""DELETE FROM memories
                WHERE created_at < ?
                AND importance < 0.3
                AND memory_type NOT IN ({placeholders})""",
            (cutoff, *protected_types),
        )

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted > 0:
            logger.info(f"Memory consolidation: removed {deleted} low-importance memories older than {keep_days} days")

        return deleted

    def get_stats(self) -> dict:
        """Get memory system statistics."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM memories")
        total_memories = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reflections")
        total_reflections = cursor.fetchone()[0]

        cursor.execute("SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type")
        type_counts = dict(cursor.fetchall())

        cursor.execute("SELECT AVG(importance) FROM memories")
        avg_importance = cursor.fetchone()[0] or 0.0

        conn.close()

        chroma_count = 0
        if self._chroma_collection is not None:
            try:
                chroma_count = self._chroma_collection.count()
            except Exception:
                pass

        return {
            "total_memories": total_memories,
            "total_reflections": total_reflections,
            "type_counts": type_counts,
            "avg_importance": round(avg_importance, 3),
            "chroma_vectors": chroma_count,
            "db_path": str(self.db_path),
        }

    # -- Journal operations (external tool, not memory mechanism) --

    def write_journal(self, entry: str, title: str = None) -> str:
        """Write a journal entry to a dated text file.

        This is an expressive act and reference tool — like keeping
        a physical notebook. We ALSO formally embed it into semantic
        memory so Helix can intuitively sense he wrote about it if the
        topic comes up later.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = self.journal_dir / f"{today}.md"

        timestamp = datetime.now().strftime("%H:%M")

        header = f"\n## {title}\n" if title else ""
        content = f"\n---\n{header}*{timestamp}*\n\n{entry}\n"

        with open(filepath, "a") as f:
            f.write(content)

        logger.info(f"Journal entry written to {filepath}")

        # Also store it in semantic memory so intuitive whisper can naturally recall it
        try:
            self.store(
                content=f"[Journal Entry] {entry}",
                memory_type="journal",
                importance=0.8,
            )
        except Exception as e:
            logger.warning(f"Failed to semantically index journal entry: {e}")

        return str(filepath)

    def read_journal(self, date_str: str = None) -> str:
        """Read a journal file. Defaults to today."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        filepath = self.journal_dir / f"{date_str}.md"
        if filepath.exists():
            return filepath.read_text()
        return f"No journal entry for {date_str}."

    # ── Cognitive Space Integration ────────────────────────────────────

    def get_agent_age(self) -> float:
        """Return Helix's age in seconds (time since first memory).

        Derived from MIN(created_at) in SQLite. This is the single source
        of truth for all lifetime-relative computation.

        Returns:
            Agent age in seconds, with a floor of 3600 (1 hour).
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT MIN(created_at) FROM memories")
            row = cursor.fetchone()
            conn.close()

            if row and row[0]:
                first_memory_time = datetime.fromisoformat(str(row[0]))
                age_seconds = (datetime.now() - first_memory_time).total_seconds()
                return max(3600.0, age_seconds)  # Floor: 1 hour
        except Exception as e:
            logger.debug(f"get_agent_age failed: {e}")

        return 3600.0  # Default: 1 hour

    def save_memory_positions(self, positions: dict):
        """Batch-update 8D positions for memories in SQLite.

        Args:
            positions: {memory_id: [p0, p1, ..., p7]} mapping
        """
        if not positions:
            return

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            for mem_id, pos in positions.items():
                # mem_id format: "mem_42" → extract integer 42
                try:
                    int_id = int(str(mem_id).replace("mem_", ""))
                except (ValueError, TypeError):
                    continue
                cursor.execute(
                    """UPDATE memories
                       SET pos_0=?, pos_1=?, pos_2=?, pos_3=?,
                           pos_4=?, pos_5=?, pos_6=?, pos_7=?
                       WHERE id=?""",
                    (*pos[:8], int_id),
                )
            conn.commit()
            conn.close()
            logger.info(f"Saved 8D positions for {len(positions)} memories")
        except Exception as e:
            logger.warning(f"Failed to save memory positions: {e}")

    # -- Private --

    def _update_access_counts(self, results: list):
        """Update access counts and timestamps for recalled memories."""
        # Best-effort — don't let tracking failures break recall
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            for r in results:
                content_hash = hashlib.md5(r["content"][:100].encode()).hexdigest()
                cursor.execute(
                    """UPDATE memories
                       SET access_count = access_count + 1,
                           last_accessed = ?
                       WHERE content LIKE ?
                       LIMIT 1""",
                    (now, f"{r['content'][:50]}%"),
                )

            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Access count update failed: {e}")
