"""Persistent entity case views over Helix's canonical memory corpus.

A case stores references, never ownership of the underlying memory.  This
keeps exact records in the central journal while giving a person/topic desk a
small, high-precision search space for questions explicitly about that case.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set


_ENVELOPE_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+")
_SPEAKER_RE = re.compile(r"^([A-Za-z][\w .'-]{0,39}):\s*")
_CHANNEL_SPEAKER_RE = re.compile(
    r"^([A-Za-z][\w .'-]{0,39}) is talking to me via\b", re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does",
    "for", "from", "had", "has", "have", "how", "i", "in", "is", "it",
    "of", "on", "or", "that", "the", "their", "them", "this", "to", "was",
    "were", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your", "about", "currently", "both",
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _case_key(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")
    return value[:80]


def _speaker(content: Any) -> str:
    payload = _ENVELOPE_RE.sub("", str(content or "").strip())
    match = _SPEAKER_RE.match(payload) or _CHANNEL_SPEAKER_RE.match(payload)
    return "" if not match else " ".join(match.group(1).split())


def _terms(text: Any) -> List[str]:
    return [
        _stem(token.lower().strip("._-"))
        for token in _TOKEN_RE.findall(str(text or ""))
        if len(token.strip("._-")) > 1
        and token.lower().strip("._-") not in _STOPWORDS
    ]


def _stem(token: str) -> str:
    irregular = {
        "went": "go", "gone": "go", "lost": "lose", "likes": "like",
        "liked": "like", "favourite": "favorite", "thought": "think",
    }
    if token in irregular:
        return irregular[token]
    if len(token) <= 3 or token.isdigit():
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        root = token[:-3]
        if len(root) > 2 and root[-1] == root[-2]:
            root = root[:-1]
        return root
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


class CaseMemoryOffice:
    """Maintain and query source-referenced entity case files."""

    VERSION = 1

    def __init__(self, data_dir: str, corpus):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "office_board.json"
        self.corpus = corpus
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("cases"), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"version": self.VERSION, "cases": {}}

    def _save(self, board: Mapping[str, Any]) -> None:
        payload = dict(board)
        payload["version"] = self.VERSION
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp_path, self.path)

    def register_records(
        self,
        records: Sequence[Dict[str, Any]],
        *,
        session_id: str = "",
        explicit_subjects: Optional[Mapping[str, Sequence[str]]] = None,
    ) -> Dict[str, Any]:
        """Copy exact-record references into all applicable entity cases."""
        with self._lock:
            board = self._load()
            cases = board["cases"]
            speakers = {_speaker(item.get("content")) for item in records}
            speakers.discard("")
            for name in sorted(speakers):
                key = _case_key(name)
                cases.setdefault(key, self._new_case(key, name))

            known_names = {
                key: str(case.get("name") or "")
                for key, case in cases.items()
                if case.get("name")
            }
            linked = 0
            touched: Set[str] = set()
            for item in records:
                item_id = str(item.get("id") or "")
                if not item_id:
                    continue
                content = str(item.get("content") or "")
                subjects: Set[str] = set()
                speaker = _speaker(content)
                if speaker:
                    subjects.add(speaker)
                for supplied in (explicit_subjects or {}).get(item_id, ()):
                    if supplied:
                        subjects.add(str(supplied))
                lowered = content.lower()
                for case_key, name in known_names.items():
                    if re.search(r"\b" + re.escape(name.lower()) + r"\b", lowered):
                        subjects.add(name)
                for name in subjects:
                    key = _case_key(name)
                    if not key:
                        continue
                    case = cases.setdefault(key, self._new_case(key, name))
                    refs = list(case.get("memory_refs") or [])
                    if item_id not in refs:
                        refs.append(item_id)
                        linked += 1
                    case["memory_refs"] = refs[-20_000:]
                    if session_id:
                        sessions = list(case.get("sessions") or [])
                        if session_id not in sessions:
                            sessions.append(session_id)
                        case["sessions"] = sessions[-2_000:]
                        session_refs = dict(case.get("session_refs") or {})
                        scoped_refs = list(session_refs.get(session_id) or [])
                        if item_id not in scoped_refs:
                            scoped_refs.append(item_id)
                        session_refs[session_id] = scoped_refs[-5_000:]
                        # Keep the most recent bounded set of session indexes.
                        case["session_refs"] = {
                            key: session_refs[key]
                            for key in list(session_refs)[-2_000:]
                        }
                    case["updated_at"] = _now_iso()
                    touched.add(key)
            self._save(board)
            return {
                "cases_touched": len(touched),
                "references_linked": linked,
                "case_names": [cases[key]["name"] for key in sorted(touched)],
            }

    def attach_beliefs(self, name: str, belief_ids: Iterable[str]) -> None:
        key = _case_key(name)
        if not key:
            return
        with self._lock:
            board = self._load()
            case = board["cases"].setdefault(key, self._new_case(key, name))
            refs = list(case.get("belief_refs") or [])
            for belief_id in belief_ids:
                value = str(belief_id or "")
                if value and value not in refs:
                    refs.append(value)
            case["belief_refs"] = refs[-5_000:]
            case["updated_at"] = _now_iso()
            self._save(board)

    def session_memory_refs(self, name: str, session_id: str) -> List[str]:
        """Return this person's exact refs that belong to one session."""
        case = self.get_case(name)
        if not case:
            return []
        indexed = (case.get("session_refs") or {}).get(session_id)
        if indexed is not None:
            return [str(item_id) for item_id in indexed]
        result = []
        for item_id in case.get("memory_refs", []):
            item = self.corpus.get(str(item_id))
            if item is None:
                continue
            item_session = str(item.get("session_id") or item.get("scope_id") or "")
            tags = {str(tag) for tag in (item.get("tags") or [])}
            if (
                not session_id
                or item_session == session_id
                or f"session:{session_id}" in tags
            ):
                result.append(str(item_id))
        return result

    def get_case(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            case = self._load()["cases"].get(_case_key(name))
            return dict(case) if case else None

    def summary(self) -> List[Dict[str, Any]]:
        """Return non-content case counts for maintenance audits."""
        with self._lock:
            cases = self._load()["cases"].values()
        return sorted(
            [
                {
                    "case_id": case.get("case_id", ""),
                    "name": case.get("name", ""),
                    "memory_refs": len(case.get("memory_refs") or []),
                    "belief_refs": len(case.get("belief_refs") or []),
                    "sessions": len(case.get("sessions") or []),
                    "updated_at": case.get("updated_at", ""),
                }
                for case in cases
            ],
            key=lambda case: str(case.get("name", "")).lower(),
        )

    def route(self, query: str, *, max_items: int = 8) -> Dict[str, Any]:
        """Route an entity-specific question to matching case-local search."""
        with self._lock:
            board = self._load()
        lowered = str(query or "").lower()
        matches = []
        for case in board["cases"].values():
            names = [case.get("name", ""), *(case.get("aliases") or [])]
            if any(
                name and re.search(r"\b" + re.escape(str(name).lower()) + r"\b", lowered)
                for name in names
            ):
                matches.append(case)
        if not matches:
            return {"case_names": [], "items": [], "candidates": 0}

        case_name_terms = {
            term for case in matches for term in _terms(case.get("name", ""))
        }
        query_terms = [term for term in _terms(query) if term not in case_name_terms]
        candidates: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for case in matches:
            refs = list(case.get("memory_refs") or []) + list(case.get("belief_refs") or [])
            for ordinal, item_id in enumerate(reversed(refs)):
                item_id = str(item_id)
                if item_id in seen:
                    continue
                source = self.corpus.get(item_id)
                if source is None:
                    continue
                seen.add(item_id)
                counts = Counter(_terms(source.get("content", "")))
                matched = {term for term in query_terms if counts.get(term)}
                # Entity-only questions get a recent profile view; topical
                # questions require at least one case-local term match.
                if query_terms and not matched:
                    continue
                coverage = len(matched) / max(1, len(set(query_terms)))
                recency = 1.0 / (ordinal + 2.0)
                score = 0.82 * coverage + 0.18 * recency
                item = dict(source)
                item["office_role"] = "case_record"
                item["office_desk"] = "case"
                item["office_verified"] = False
                item["case_name"] = case.get("name", "")
                item["case_route_score"] = round(score, 6)
                item["relevance"] = max(float(item.get("relevance") or 0.0), score)
                candidates.append(item)
        candidates.sort(
            key=lambda item: (-float(item.get("case_route_score", 0.0)), str(item.get("id", "")))
        )
        return {
            "case_names": [str(case.get("name", "")) for case in matches],
            "items": candidates[:max(0, int(max_items))],
            "candidates": len(candidates),
        }

    @staticmethod
    def _new_case(key: str, name: str) -> Dict[str, Any]:
        now = _now_iso()
        return {
            "case_id": key,
            "name": " ".join(str(name or "").split()),
            "aliases": [],
            "memory_refs": [],
            "belief_refs": [],
            "sessions": [],
            "session_refs": {},
            "created_at": now,
            "updated_at": now,
        }
