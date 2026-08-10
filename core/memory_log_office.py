"""Simple redundant text-file views over Helix's canonical journal.

Each exact memory is one Markdown file. The same filename may be copied under
time, session, subject, topic, and relation folders. Retrieval unions obvious
folders, deduplicates filenames, then resolves those IDs through the canonical
corpus before top-K. The journal remains authoritative.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence
from urllib.parse import quote, unquote


_SOURCE_RE = re.compile(r"<!-- sources:([^>]*) -->")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "how", "i", "in", "is", "it", "of", "on", "or",
    "that", "the", "this", "to", "was", "were", "what", "when", "where",
    "which", "who", "why", "with", "would", "you", "your",
}


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")[:100]


def _terms(value: Any) -> set[str]:
    return {
        word.lower().strip("._-") for word in _TOKEN_RE.findall(str(value or ""))
        if len(word.strip("._-")) > 1
        and word.lower().strip("._-") not in _STOPWORDS
    }


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class MemoryLogOffice:
    """Write and read disposable exact-text memory views."""

    def __init__(self, root: str | Path, corpus):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.corpus = corpus

    def file_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        session_id: str,
        subjects_by_id: Mapping[str, Sequence[str]] | None = None,
        topics_by_id: Mapping[str, Sequence[str]] | None = None,
        relations_by_id: Mapping[str, Sequence[Sequence[str]]] | None = None,
    ) -> Dict[str, int]:
        subjects_by_id = subjects_by_id or {}
        topics_by_id = topics_by_id or {}
        relations_by_id = relations_by_id or {}
        stats = {"records": 0, "copies_written": 0, "copies_already_present": 0}

        for record in records:
            item_id = str(record.get("id") or "")
            content = str(record.get("content") or "").strip()
            if not item_id or not content:
                continue
            stats["records"] += 1
            created = str(record.get("created_at") or record.get("timestamp") or "")
            day = created[:10] if re.match(r"\d{4}-\d{2}-\d{2}", created) else "undated"
            folders = {
                self.root / "timeline" / day,
                self.root / "sessions" / (_slug(session_id) or "unscoped"),
            }
            folders.update(
                self.root / "subjects" / _slug(value)
                for value in subjects_by_id.get(item_id, ()) if _slug(value)
            )
            folders.update(
                self.root / "topics" / _slug(value)
                for value in topics_by_id.get(item_id, ()) if _slug(value)
            )
            for relation in relations_by_id.get(item_id, ()):
                names = sorted({_slug(value) for value in relation if _slug(value)})
                if len(names) >= 2:
                    folders.add(self.root / "relations" / "--".join(names[:4]))

            filename = quote(item_id, safe="._-") + ".md"
            body = self._record_text(record, session_id)
            for folder in folders:
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / filename
                if path.exists():
                    stats["copies_already_present"] += 1
                    continue
                path.write_text(body, encoding="utf-8")
                stats["copies_written"] += 1
        return stats

    def write_summary(
        self,
        view: str,
        key: str,
        *,
        session_id: str,
        overture: str,
        key_details: Sequence[Any],
        source_ids: Iterable[str],
    ) -> Path | None:
        view = _slug(view)
        if view not in {"sessions", "subjects", "topics", "relations"}:
            return None
        item_key = (
            "--".join(filter(None, (_slug(part) for part in str(key).split("--"))))
            if view == "relations" else _slug(key)
        )
        if not item_key:
            return None
        folder = self.root / view / item_key
        path = (
            folder / "summary.md" if view == "sessions"
            else folder / "summaries" / f"{_slug(session_id) or 'unscoped'}.md"
        )
        if isinstance(source_ids, str):
            source_ids = [source_ids]
        refs = list(dict.fromkeys(str(ref) for ref in source_ids if str(ref)))
        details = []
        for detail in key_details:
            if isinstance(detail, Mapping):
                text = _clip(detail.get("text") or detail.get("detail") or "", 700)
                detail_refs = detail.get("source_ids") or refs
            else:
                text, detail_refs = _clip(detail, 700), refs
            if text:
                if isinstance(detail_refs, str):
                    detail_refs = [detail_refs]
                source_note = ",".join(str(ref) for ref in detail_refs if str(ref))
                details.append(f"- {text} <!-- sources:{source_note} -->")
        body = "\n".join((
            f"# {str(key).strip() or item_key}", "", f"Session: `{session_id}`", "",
            "## Overture", "",
            _clip(overture, 1600) or "Exact records filed; consult the log.", "",
            "## Key details", "",
            *(details or ["- No derived key details; consult the exact log."]), "",
            f"<!-- sources:{','.join(refs)} -->", "",
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
        return path

    def write_exact_session_summary(
        self, session_id: str, records: Sequence[Mapping[str, Any]],
    ) -> Path | None:
        valid = [item for item in records if item.get("id") and item.get("content")]
        if not valid:
            return None
        existing = self.root / "sessions" / (_slug(session_id) or "unscoped") / "summary.md"
        if existing.exists() and "This is a source index" not in existing.read_text(
            encoding="utf-8", errors="replace",
        ):
            return existing
        important = sorted(
            valid, key=lambda item: float(item.get("importance") or 0.0), reverse=True,
        )[:5]
        return self.write_summary(
            "sessions", session_id, session_id=session_id,
            overture=(
                f"Chronological session view containing {len(valid)} exact input/output "
                "records. This is a source index, not an interpretation."
            ),
            key_details=[{
                "text": _clip(item.get("content", ""), 500),
                "source_ids": [str(item.get("id"))],
            } for item in important],
            source_ids=[str(item.get("id")) for item in valid],
        )

    def route(
        self,
        query: str,
        *,
        subjects: Sequence[str] = (),
        max_items: int = 10,
    ) -> Dict[str, Any]:
        """Union matching folders and deduplicate exact files before top-K."""
        query_terms = _terms(query)
        subject_keys = {_slug(value) for value in subjects if _slug(value)}
        folders = []
        for view in ("subjects", "topics", "relations"):
            root = self.root / view
            if not root.exists():
                continue
            for folder in root.iterdir():
                name_terms = _terms(folder.name.replace("--", " ").replace("_", " "))
                subject_match = view != "topics" and any(
                    key in folder.name for key in subject_keys
                )
                if folder.is_dir() and (subject_match or (name_terms and name_terms <= query_terms)):
                    folders.append(folder)

        views_by_id: Dict[str, set[str]] = {}
        summaries = []
        copies_seen = 0
        for folder in folders:
            for path in folder.glob("*.md"):
                if path.name == "summary.md":
                    continue
                copies_seen += 1
                views_by_id.setdefault(unquote(path.stem), set()).add(
                    str(folder.relative_to(self.root))
                )
            for path in sorted((folder / "summaries").glob("*.md"))[-3:]:
                text = path.read_text(encoding="utf-8", errors="replace")
                overlap = len(query_terms & _terms(text)) / max(1, len(query_terms))
                if overlap:
                    summaries.append({
                        "id": "log_summary_" + hashlib.sha1(str(path).encode()).hexdigest()[:12],
                        "content": _clip(text, 2400),
                        "tier": -1,
                        "office_desk": "semantic_advisor",
                        "office_role": "maintenance_summary",
                        "office_verified": False,
                        "relevance": min(0.88, 0.55 + (0.25 * overlap)),
                        "memory_refs": self._summary_refs(text),
                    })

        candidates = []
        for item_id, views in views_by_id.items():
            source = self.corpus.get(item_id)
            if source is None:
                continue
            item = dict(source)
            coverage = len(query_terms & _terms(item.get("content", ""))) / max(1, len(query_terms))
            item["office_role"] = item.get("office_role") or "filed_log_record"
            item["log_views"] = sorted(views)
            item["relevance"] = max(
                float(item.get("relevance") or 0.0),
                min(0.92, 0.52 + (0.34 * coverage) + (0.02 * min(3, len(views)))),
            )
            candidates.append(item)
        candidates.extend(summaries)
        candidates.sort(key=lambda item: (-float(item.get("relevance") or 0.0), str(item.get("id"))))
        return {
            "items": candidates[:max(0, int(max_items))],
            "candidates": len(candidates),
            "folders": len(folders),
            "copies_seen": copies_seen,
            "duplicates_suppressed": max(0, copies_seen - len(views_by_id)),
        }

    @staticmethod
    def _record_text(record: Mapping[str, Any], session_id: str) -> str:
        return "\n".join((
            f"# {record.get('id')}", "",
            f"Time: {record.get('created_at') or record.get('timestamp') or 'undated'}",
            f"Session: {session_id}",
            f"Source: {record.get('source') or record.get('memory_type') or 'memory'}",
            "", str(record.get("content") or "").rstrip(), "",
        ))

    @staticmethod
    def _summary_refs(text: str) -> List[str]:
        return list(dict.fromkeys(
            ref.strip() for group in _SOURCE_RE.findall(text)
            for ref in group.split(",") if ref.strip()
        ))
