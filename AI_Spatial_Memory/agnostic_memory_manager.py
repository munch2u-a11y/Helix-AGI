"""
Helix — Memory Manager (LLM-Agnostic)

Coordinates interactions between the short-term (working) memory
(ChromaDB vector store) and long-term (episodic) memory (SQLite).

This module is responsible for:
  1. Adding new memories (thoughts, events, tool outputs) to short-term.
  2. Retrieving memories from short-term based on semantic similarity.
  3. Promoting short-term memories to long-term storage based on importance.
  4. Loading long-term memories back into short-term if frequently accessed.
  5. Managing memory decay and pruning.

This version is LLM-agnostic, replacing direct embedding function imports
with a generic embedding provider interface.
"""

import json
import os
import logging
import uuid
import time
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import sqlite3

# Placeholder for a generic embedding function. This should be provided
# by the calling environment.
_GLOBAL_EMBEDDING_FUNCTION = None

logger = logging.getLogger("helix.memory.memory_manager")

# ── Configuration ────────────────────────────────────────────────────

CHROMA_PATH = "data/chroma_db"
SQLITE_PATH = "data/helix_memory.db"

# Memory promotion thresholds
IMPORTANCE_THRESHOLD = 0.7  # Memories with importance >= this are promoted
ACCESS_COUNT_THRESHOLD = 2  # Memories accessed this many times are promoted

# Memory decay rates (for short-term, in pulses)
HIGHEST_IMPORTANCE_HALFLIFE = 1000  # Max pulses a critical memory stays fresh
LOW_IMPORTANCE_HALFLIFE = 100       # Min pulses a trivial memory stays fresh

# ── SQLite Schema ────────────────────────────────────────────────────

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    importance REAL NOT NULL,
    created_at TEXT NOT NULL,
    last_accessed TEXT NOT NULL,
    access_count INTEGER NOT NULL,
    source TEXT,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_created_at ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_last_accessed ON memories(last_accessed);
CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance);
"""


def set_global_embedding_function(embed_function: Any):
    """Sets the global embedding function for the MemoryManager.

    This allows the MemoryManager to be LLM-agnostic, receiving its
    embedding capability from an external source.
    """
    global _GLOBAL_EMBEDDING_FUNCTION
    _GLOBAL_EMBEDDING_FUNCTION = embed_function


class MemoryManager:
    """Manages short-term (ChromaDB) and long-term (SQLite) memory.

    The MemoryManager is responsible for adding, retrieving, promoting,
    and managing the lifecycle of memories within Helix's cognitive system.
    It uses a ChromaDB instance for fast semantic search of recent memories
    and an SQLite database for persistent long-term storage.
    """

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client. It will create the directory if it doesn't exist.
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path=str(self.data_dir / CHROMA_PATH))
            self.collection = self.client.get_or_create_collection(name="helix_memories")
            logger.info("ChromaDB initialized at %s", self.data_dir / CHROMA_PATH)
        except ImportError:
            logger.error("ChromaDB not installed. MemoryManager will not function correctly.")
            self.client = None
            self.collection = None
        except Exception as e:
            logger.error("Failed to initialize ChromaDB: %s", e)
            self.client = None
            self.collection = None

        # Initialize SQLite database
        self.db_path = self.data_dir / SQLITE_PATH
        self._init_sqlite()
        logger.info("SQLite memory database initialized at %s", self.db_path)

        # Cache for recently accessed long-term memories to reduce DB hits
        self._lru_cache: Dict[str, Dict[str, Any]] = {}
        self._lru_capacity = 100 # Max items in cache

        # Embedding function. Will be set externally via set_global_embedding_function
        if _GLOBAL_EMBEDDING_FUNCTION is None:
            logger.warning("No global embedding function set. Embeddings will not be generated.")


    def _init_sqlite(self):
        """Initialize the SQLite database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executescript(SQLITE_SCHEMA)
            conn.commit()

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Generates an embedding for the given text using the global embedding function.
        Returns None if no embedding function is set or on failure.
        """
        if _GLOBAL_EMBEDDING_FUNCTION is None:
            logger.warning("Attempted to get embedding without a global embedding function set.")
            return None
        try:
            # The global embedding function is expected to return a list of floats
            return _GLOBAL_EMBEDDING_FUNCTION([text])[0]
        except Exception as e:
            logger.error("Error generating embedding: %s", e)
            return None

    def add_memory(
        self,
        content: str,
        importance: float = 0.5,
        source: str = "internal_thought",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Adds a new memory to the short-term memory (ChromaDB).

        Args:
            content: The text content of the memory.
            importance: A float from 0.0 to 1.0 indicating memory importance.
            source: Where the memory came from (e.g., "user_message", "tool_output").
            metadata: Optional dictionary for additional memory metadata.

        Returns:
            The ID of the new memory, or None if addition failed.
        """
        if self.collection is None or _GLOBAL_EMBEDDING_FUNCTION is None:
            logger.warning("ChromaDB collection or embedding function not initialized. Cannot add memory.")
            return None

        embedding = self._get_embedding(content)
        if embedding is None:
            return None

        mem_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        meta = metadata or {}
        meta.update({
            "importance": importance,
            "created_at": now,
            "last_accessed": now,
            "access_count": 0,
            "source": source,
        })

        try:
            self.collection.add(
                embeddings=[embedding],
                documents=[content],
                metadatas=[meta],
                ids=[mem_id],
            )
            logger.debug("Added memory '%s' (importance=%.2f)", mem_id, importance)
            return mem_id
        except Exception as e:
            logger.error("Failed to add memory to ChromaDB: %s", e)
            return None

    def retrieve_memories(
        self,
        query_text: str,
        n_results: int = 5,
        min_importance: float = 0.0,
        max_age_days: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves semantically similar memories from short-term memory.

        Args:
            query_text: The text to query against memories.
            n_results: The maximum number of similar memories to return.
            min_importance: Filter memories by minimum importance score.
            max_age_days: Filter memories by maximum age in days.

        Returns:
            A list of dictionaries, each representing a retrieved memory.
        """
        if self.collection is None or _GLOBAL_EMBEDDING_FUNCTION is None:
            logger.warning("ChromaDB collection or embedding function not initialized. Cannot retrieve memories.")
            return []

        query_embedding = self._get_embedding(query_text)
        if query_embedding is None:
            return []

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=['documents', 'metadatas', 'distances']
            )

            retrieved_memories = []
            now = datetime.now()

            if results and results['ids']:
                for i in range(len(results['ids'][0])):
                    mem_id = results['ids'][0][i]
                    content = results['documents'][0][i]
                    metadata = results['metadatas'][0][i]
                    distance = results['distances'][0][i]

                    importance = metadata.get("importance", 0.0)
                    created_at_str = metadata.get("created_at")

                    if importance < min_importance:
                        continue

                    if max_age_days and created_at_str:
                        try:
                            created_at = datetime.fromisoformat(created_at_str)
                            age_days = (now - created_at).days
                            if age_days > max_age_days:
                                continue
                        except ValueError:
                            logger.warning("Invalid created_at format for memory %s", mem_id)
                            continue

                    # Update access count and last_accessed for short-term memory
                    metadata["access_count"] = metadata.get("access_count", 0) + 1
                    metadata["last_accessed"] = now.isoformat()
                    # In ChromaDB, metadata is immutable, so we re-add/update the document
                    # This is a simplification; for true updates, you'd need to delete and re-add
                    # or use a separate metadata store.
                    # For now, we'll just return the updated metadata in the result.

                    retrieved_memories.append({
                        "id": mem_id,
                        "content": content,
                        "importance": importance,
                        "created_at": created_at_str,
                        "last_accessed": now.isoformat(),
                        "access_count": metadata["access_count"],
                        "source": metadata.get("source"),
                        "distance": distance,
                        "metadata": metadata # Include all metadata
                    })
            logger.debug("Retrieved %d memories for query '%s'", len(retrieved_memories), query_text)
            return retrieved_memories
        except Exception as e:
            logger.error("Failed to retrieve memories from ChromaDB: %s", e)
            return []

    def _add_to_long_term_memory(self, memory: Dict[str, Any]) -> None:
        """Adds a memory to the SQLite long-term store."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory["id"],
                    memory["content"],
                    json.dumps(memory["embedding"]) if "embedding" in memory else "[]",
                    memory["importance"],
                    memory["created_at"],
                    memory["last_accessed"],
                    memory["access_count"],
                    memory.get("source"),
                    json.dumps(memory.get("metadata", {}))
                )
            )
            conn.commit()
            logger.debug("Promoted memory '%s' to long-term storage.", memory["id"])
        except Exception as e:
            logger.error("Failed to add memory '%s' to SQLite: %s", memory["id"], e)
        finally:
            conn.close()

    def _get_from_long_term_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a memory by ID from the SQLite long-term store."""
        if memory_id in self._lru_cache:
            # Move to front/update access for LRU behavior
            memory = self._lru_cache.pop(memory_id)
            self._lru_cache[memory_id] = memory
            return memory

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
            row = cursor.fetchone()
            if row:
                memory = {
                    "id": row[0],
                    "content": row[1],
                    "embedding": json.loads(row[2]),
                    "importance": row[3],
                    "created_at": row[4],
                    "last_accessed": row[5],
                    "access_count": row[6],
                    "source": row[7],
                    "metadata": json.loads(row[8]),
                }
                # Update access in DB
                memory["access_count"] += 1
                memory["last_accessed"] = datetime.now().isoformat()
                cursor.execute(
                    "UPDATE memories SET access_count = ?, last_accessed = ? WHERE id = ?",
                    (memory["access_count"], memory["last_accessed"], memory_id)
                )
                conn.commit()

                # Add to LRU cache
                if len(self._lru_cache) >= self._lru_capacity:
                    # Remove oldest item (first in dict for Python 3.7+)
                    self._lru_cache.pop(next(iter(self._lru_cache)))
                self._lru_cache[memory_id] = memory

                return memory
        except Exception as e:
            logger.error("Failed to retrieve memory '%s' from SQLite: %s", memory_id, e)
        finally:
            conn.close()
        return None

    def promote_memory(self, memory_id: str, embedding: List[float], content: str, metadata: Dict[str, Any]) -> None:
        """Promotes a memory from short-term to long-term storage.

        This involves adding it to SQLite if it meets promotion criteria.
        The embedding is passed explicitly as ChromaDB doesn't expose it directly
        in query results without an extra fetch.
        """
        # Check if already in long-term (via cache or direct DB query)
        if self._get_from_long_term_memory(memory_id):
            logger.debug("Memory '%s' already in long-term store.", memory_id)
            return

        # Check promotion criteria
        importance = metadata.get("importance", 0.0)
        access_count = metadata.get("access_count", 0)

        if importance >= IMPORTANCE_THRESHOLD or access_count >= ACCESS_COUNT_THRESHOLD:
            memory_to_promote = {
                "id": memory_id,
                "content": content,
                "embedding": embedding,
                "importance": importance,
                "created_at": metadata.get("created_at", datetime.now().isoformat()),
                "last_accessed": metadata.get("last_accessed", datetime.now().isoformat()),
                "access_count": access_count,
                "source": metadata.get("source"),
                "metadata": metadata # Store all metadata
            }
            self._add_to_long_term_memory(memory_to_promote)

    def get_recent_memories(self, n: int = 3) -> List[Dict[str, Any]]:
        """Retrieves the N most recently accessed memories from long-term store.

        Useful for providing short-term context continuity.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT id, content, importance, created_at, last_accessed, access_count, source, metadata_json "
                "FROM memories ORDER BY last_accessed DESC LIMIT ?",
                (n,)
            )
            rows = cursor.fetchall()
            recent_memories = []
            for row in rows:
                recent_memories.append({
                    "id": row[0],
                    "content": row[1],
                    "importance": row[2],
                    "created_at": row[3],
                    "last_accessed": row[4],
                    "access_count": row[5],
                    "source": row[6],
                    "metadata": json.loads(row[7]),
                })
            return recent_memories
        except Exception as e:
            logger.error("Failed to get recent memories from SQLite: %s", e)
            return []
        finally:
            conn.close()

    def consolidate_memories(self) -> None:
        """Consolidates short-term memories into long-term based on criteria.

        This method is intended to be called periodically (e.g., nightly) to
        transfer important short-term memories to the persistent long-term store
        and prune old/unimportant short-term memories.
        """
        if self.collection is None:
            logger.warning("ChromaDB collection not initialized. Cannot consolidate memories.")
            return

        logger.info("Starting memory consolidation pass.")

        # Retrieve all short-term memories. This can be memory-intensive for large collections.
        try:
            all_chroma_memories = self.collection.get(
                ids=self.collection.get(include=[])['ids'],
                include=['embeddings', 'documents', 'metadatas']
            )
        except Exception as e:
            logger.error("Failed to retrieve all ChromaDB memories for consolidation: %s", e)
            return

        memories_to_delete_from_chroma = []

        if all_chroma_memories and all_chroma_memories['ids']:
            now_ts = time.time()
            for i in range(len(all_chroma_memories['ids'])):
                mem_id = all_chroma_memories['ids'][i]
                content = all_chroma_memories['documents'][i]
                embedding = all_chroma_memories['embeddings'][i]
                metadata = all_chroma_memories['metadatas'][i]

                created_at_str = metadata.get("created_at", datetime.now().isoformat())
                importance = metadata.get("importance", 0.0)

                # Calculate decay factor based on importance
                if importance >= IMPORTANCE_THRESHOLD:
                    halflife = HIGHEST_IMPORTANCE_HALFLIFE
                else:
                    halflife = LOW_IMPORTANCE_HALFLIFE

                # Simple exponential decay for pruning short-term memory
                try:
                    created_at_dt = datetime.fromisoformat(created_at_str)
                    age_pulses = (now_ts - created_at_dt.timestamp()) # Assuming 1 pulse/sec for halflife calc
                    decay_factor = 0.5 ** (age_pulses / halflife)
                except ValueError:
                    logger.warning("Invalid created_at format for memory %s during decay: %s", mem_id, created_at_str)
                    decay_factor = 0.0 # Assume max decay if date is bad

                # Promote to long-term if criteria met
                self.promote_memory(mem_id, embedding, content, metadata)

                # Decide if memory should be pruned from short-term ChromaDB
                # Prune if low importance AND has decayed significantly
                # Or if it's been promoted and is old enough in Chroma
                if (importance < IMPORTANCE_THRESHOLD and decay_factor < 0.1) or \
                   (self._get_from_long_term_memory(mem_id) and age_pulses > 100): # Already in long-term and old in short-term
                    memories_to_delete_from_chroma.append(mem_id)

        if memories_to_delete_from_chroma:
            try:
                self.collection.delete(ids=memories_to_delete_from_chroma)
                logger.info("Pruned %d memories from short-term ChromaDB.", len(memories_to_delete_from_chroma))
            except Exception as e:
                logger.error("Failed to prune memories from ChromaDB: %s", e)

        logger.info("Memory consolidation pass complete.")

    def retrieve_long_term_memories(
        self,
        query_text: str,
        n_results: int = 5,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Retrieves semantically similar memories from long-term memory (SQLite).

        Since SQLite does not support vector search directly, this function
        fetches all long-term memories, computes their similarity to the query
        embedding, and returns the top N. This can be inefficient for very large
        long-term stores and would typically be optimized with a vector index
        on the SQLite side or by using a hybrid approach.
        """
        if _GLOBAL_EMBEDDING_FUNCTION is None:
            logger.warning("No global embedding function set. Cannot retrieve long-term memories.")
            return []

        query_embedding = self._get_embedding(query_text)
        if query_embedding is None:
            return []
        query_embedding_np = np.array(query_embedding)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        all_long_term_memories = []
        try:
            cursor.execute("SELECT id, content, embedding_json, importance, created_at, last_accessed, access_count, source, metadata_json FROM memories")
            rows = cursor.fetchall()

            for row in rows:
                mem_id = row[0]
                content = row[1]
                embedding = json.loads(row[2])
                importance = row[3]
                created_at = row[4]
                last_accessed = row[5]
                access_count = row[6]
                source = row[7]
                metadata = json.loads(row[8])

                if importance < min_importance:
                    continue

                # Calculate cosine similarity
                mem_embedding_np = np.array(embedding)
                # Handle cases where embeddings might be zero vectors
                if np.linalg.norm(query_embedding_np) == 0 or np.linalg.norm(mem_embedding_np) == 0:
                    similarity = 0.0
                else:
                    similarity = np.dot(query_embedding_np, mem_embedding_np) / \
                                 (np.linalg.norm(query_embedding_np) * np.linalg.norm(mem_embedding_np))

                all_long_term_memories.append({
                    "id": mem_id,
                    "content": content,
                    "embedding": embedding,
                    "importance": importance,
                    "created_at": created_at,
                    "last_accessed": last_accessed,
                    "access_count": access_count,
                    "source": source,
                    "metadata": metadata,
                    "similarity": similarity
                })
        except Exception as e:
            logger.error("Failed to retrieve all long-term memories from SQLite: %s", e)
            return []
        finally:
            conn.close()

        # Sort by similarity and return top N
        all_long_term_memories.sort(key=lambda x: x["similarity"], reverse=True)
        return all_long_term_memories[:n_results]
