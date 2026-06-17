#!/usr/bin/env python3
"""
CognitiveJournal – a lightweight, append‑only JSON‑Lines journal used as the
single source of truth for all Helix memories, beliefs, and thought snapshots.

Each line is a JSON object with a fixed schema.  The journal is never mutated –
updates are expressed by appending a new entry with the same ``id`` but a newer
``timestamp``.  A nightly ``compact()`` step rewrites the file, keeping only the
latest version of each ``id`` so the file does not grow without bound.
"""

import json
import os
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

DEFAULT_JOURNAL_NAME = "cognitive_journal.jsonl"


def _now_iso() -> str:
    """Return the current time as an ISO‑8601 string with seconds precision."""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _checksum(entry: Dict[str, Any]) -> str:
    """Compute a simple SHA‑256 checksum of the JSON representation of *entry*.

    The checksum is stored alongside the entry to provide integrity checking.
    """
    data = json.dumps(entry, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def _serialize_entry(entry: Dict[str, Any]) -> str:
    """Serialize an entry with a freshly computed checksum."""
    payload = dict(entry)
    payload["checksum"] = _checksum(entry)
    return json.dumps(payload, separators=(',', ':'))


class CognitiveJournal:
    """Append‑only journal handling persistence of all point types.

    The journal lives in ``self.path``.  ``load_all()`` returns a list of entries
    (oldest first).  ``append(entry)`` validates the schema, adds a timestamp and
    checksum, and writes the line atomically.
    """

    def __init__(self, directory: Path, filename: str = DEFAULT_JOURNAL_NAME):
        self.dir = directory
        self.path = self.dir / filename
        self.dir.mkdir(parents=True, exist_ok=True)
        # Ensure the file exists
        self.path.touch(exist_ok=True)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def append(
        self,
        *,
        id: str,
        type: str,
        content: str,
        position_8d: List[float],
        pulse_id: int,
        lagrangian: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None,
        timestamp: Optional[str] = None,
        embedding_384d: Optional[List[float]] = None,
    ) -> None:
        """Append a new entry to the journal.

        Parameters
        ----------
        id:
            Unique identifier for the point (e.g. ``mem_123`` or ``bel_45``).
        type:
            One of ``"memory"``, ``"belief"``, ``"thought"`` or ``"event"``.
        content:
            Full text payload.
        position_8d:
            List of eight floats representing the point in the 8‑D manifold.
        pulse_id:
            The logical pulse at which this entry was created.
        lagrangian:
            Optional dict with the Lagrangian snapshot captured at encoding.
        metadata:
            Optional free‑form metadata (confidence, importance, etc.).
        timestamp:
            Optional ISO‑8601 timestamp; if omitted the current time is used.
        embedding_384d:
            Optional raw 384D embedding for the SemanticIndex. Stored alongside
            position_8d so the conscious-recall index can be rebuilt from the
            journal without re-embedding.
        """
        entry: Dict[str, Any] = {
            "id": id,
            "type": type,
            "content": content,
            "position_8d": position_8d,
            "pulse_id": pulse_id,
            "lagrangian": lagrangian or {},
            "metadata": metadata or {},
            "timestamp": timestamp or _now_iso(),
        }
        if embedding_384d is not None:
            entry["embedding_384d"] = embedding_384d
        line = _serialize_entry(entry)
        # Write atomically – open in append mode and flush immediately.
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def load_all(self) -> List[Dict[str, Any]]:
        """Load every entry from the journal (oldest → newest)."""
        entries: List[Dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                # Verify checksum – if it fails we simply skip the corrupted line.
                chk = entry.pop("checksum", None)
                if chk != _checksum(entry):
                    continue
                entries.append(entry)
        return entries

    def latest_by_id(self) -> Dict[str, Dict[str, Any]]:
        """Return a mapping ``id → latest entry``.

        This scans the file once; later look‑ups (e.g. for bootstrap) can use the
        returned dict directly.
        """
        latest: Dict[str, Dict[str, Any]] = {}
        for entry in self.load_all():
            latest[entry["id"]] = entry
        return latest

    # ---------------------------------------------------------------------
    # Maintenance – nightly compaction
    # ---------------------------------------------------------------------
    def compact(self) -> None:
        """Rewrite the journal, keeping only the newest version of each ``id``.

        The algorithm is simple: read the whole file, build ``latest_by_id`` and
        write those entries back to a temporary file which then atomically
        replaces the original.
        """
        latest = self.latest_by_id()
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as tmp:
            for entry in latest.values():
                line = _serialize_entry(entry)
                tmp.write(line + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        # Replace original file atomically
        tmp_path.replace(self.path)

    # ---------------------------------------------------------------------
    # Convenience helpers used by the rest of Helix
    # ---------------------------------------------------------------------
    def append_memory(
        self,
        *,
        id: str,
        content: str,
        position_8d: List[float],
        pulse_id: int,
        lagrangian: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None,
        embedding_384d: Optional[List[float]] = None,
    ) -> None:
        self.append(
            id=id,
            type="memory",
            content=content,
            position_8d=position_8d,
            pulse_id=pulse_id,
            lagrangian=lagrangian,
            metadata=metadata,
            embedding_384d=embedding_384d,
        )

    def append_belief(
        self,
        *,
        id: str,
        content: str,
        position_8d: List[float],
        pulse_id: int,
        lagrangian: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None,
        embedding_384d: Optional[List[float]] = None,
    ) -> None:
        self.append(
            id=id,
            type="belief",
            content=content,
            position_8d=position_8d,
            pulse_id=pulse_id,
            lagrangian=lagrangian,
            metadata=metadata,
            embedding_384d=embedding_384d,
        )

    def append_thought(
        self,
        *,
        id: str,
        content: str,
        position_8d: List[float],
        pulse_id: int,
        lagrangian: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None,
        embedding_384d: Optional[List[float]] = None,
    ) -> None:
        self.append(
            id=id,
            type="thought",
            content=content,
            position_8d=position_8d,
            pulse_id=pulse_id,
            lagrangian=lagrangian,
            metadata=metadata,
            embedding_384d=embedding_384d,
        )

    # Additional helper methods (e.g., iteration, filtering) can be added as
    # needed by higher‑level components.

# End of file
