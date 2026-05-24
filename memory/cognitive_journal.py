"""
Helix — Cognitive Journal (Append-only JSONL)

A lightweight, append-only JSON-Lines journal used as the single source
of truth for all Helix memories, beliefs, and thought snapshots.

Each line is a JSON object. Because it is append-only, when a belief 
updates (e.g. confidence changes), a new entry is appended with the same ID.
The `compact()` method can be called nightly to rewrite the journal, 
keeping only the latest entry for each ID.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger("helix.memory.journal")


class CognitiveJournal:
    """JSONL append-only cognitive journal store."""

    def __init__(self, path: str):
        self.path = path
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # Create file if it doesn't exist
        if not os.path.exists(path):
            open(path, 'a').close()
        logger.info(f"CognitiveJournal initialized: {path}")

    def append(self, entry: Dict[str, Any]) -> str:
        """Append a memory/belief entry as a single JSON line."""
        if "id" not in entry:
            entry["id"] = f"mem_{uuid.uuid4().hex[:12]}"
        if "timestamp" not in entry:
            entry["timestamp"] = datetime.now(timezone.utc).isoformat()

        with open(self.path, 'a') as f:
            f.write(json.dumps(entry, default=str) + '\n')

        return entry["id"]

    def load_all(self) -> List[Dict[str, Any]]:
        """Read all entries from the JSONL file.
        
        Because it is append-only, later lines override earlier lines
        with the same ID. This method returns only the latest version
        of each entry.
        """
        if not os.path.exists(self.path):
            return []

        latest_entries = {}
        with open(self.path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "id" in entry:
                        latest_entries[entry["id"]] = entry
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping malformed line {line_num} in journal: {e}")

        # Return them sorted by timestamp
        entries_list = list(latest_entries.values())
        entries_list.sort(key=lambda x: x.get("timestamp", ""))
        return entries_list

    def compact(self) -> int:
        """Compact the journal to remove superseded entries.
        
        Reads all entries (which collapses duplicates by keeping only
        the latest version of each ID), and rewrites the file.
        Returns the number of entries removed.
        """
        if not os.path.exists(self.path):
            return 0
            
        original_size = os.path.getsize(self.path)
        
        # Count raw lines first
        raw_lines = 0
        with open(self.path, 'r') as f:
            raw_lines = sum(1 for line in f if line.strip())
            
        compacted_entries = self.load_all()
        compacted_lines = len(compacted_entries)
        
        if compacted_lines == raw_lines:
            logger.info("Journal already compact. No changes made.")
            return 0
            
        # Rewrite the file safely
        temp_path = self.path + ".tmp"
        with open(temp_path, 'w') as f:
            for entry in compacted_entries:
                f.write(json.dumps(entry, default=str) + '\n')
                
        os.replace(temp_path, self.path)
        new_size = os.path.getsize(self.path)
        
        removed = raw_lines - compacted_lines
        saved_bytes = original_size - new_size
        logger.info(f"Journal compacted: removed {removed} superseded entries, saved {saved_bytes} bytes.")
        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Return stats about the journal."""
        size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        entries = len(self.load_all())
        return {
            "total_unique_entries": entries,
            "backend": "CognitiveJournal",
            "file_path": self.path,
            "file_size_bytes": size,
        }
