"""Provider-neutral between-session memory organization workflow."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from core.case_memory_office import CaseMemoryOffice


FACETS = (
    "facts", "preferences", "opinions", "traits", "communication_style", "affect",
)


class SessionMemoryMaintenance:
    """Index exact records, then optionally form source-linked person facets.

    ``worker`` receives a small request dictionary and returns a dictionary.
    It may be an LLM-backed specialist, a rules engine, or absent. Exact case
    filing always completes even when derived-belief formation fails.
    """

    def __init__(
        self,
        *,
        cases: CaseMemoryOffice,
        belief_store,
        worker: Optional[Callable[[Dict[str, Any]], Mapping[str, Any]]] = None,
    ):
        self.cases = cases
        self.beliefs = belief_store
        self.worker = worker

    def run(self, session_id: str, records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        filing = self.cases.register_records(records, session_id=session_id)
        topics_by_id = self._tag_topics(records)
        subjects_by_id = {
            key: list(values)
            for key, values in (filing.get("subjects_by_record") or {}).items()
        }
        relations_by_id = {
            key: [list(value) for value in values]
            for key, values in (filing.get("relations_by_record") or {}).items()
        }
        self._add_output_links(records, subjects_by_id, relations_by_id)
        log_filing = self.cases.logs.file_records(
            records,
            session_id=session_id,
            subjects_by_id=subjects_by_id,
            topics_by_id=topics_by_id,
            relations_by_id=relations_by_id,
        )
        exact_summary = self.cases.logs.write_exact_session_summary(session_id, records)
        stats = {
            "session_id": session_id,
            **filing,
            "log_records": log_filing["records"],
            "log_copies_written": log_filing["copies_written"],
            "exact_summary_written": bool(exact_summary),
            "derived_summaries_written": 0,
            "worker_called": False,
            "profiles_written": 0,
            "profiles_reinforced": 0,
            "worker_error": "",
        }
        if self.worker is None or not records:
            return stats

        request = {
            "task": (
                "Organize this session using explicit support only. Return person-specific "
                "facets, a session overture with key details, and subject/topic/relation "
                "views. Every derived item must cite source_ids."
            ),
            "session_id": session_id,
            "records": [
                {
                    "id": item.get("id"),
                    "time": item.get("created_at") or item.get("timestamp"),
                    "source": item.get("source") or item.get("memory_type"),
                    "content": item.get("content", ""),
                }
                for item in records[:80]
            ],
            "limits": {"people": 8, "items_per_facet": 2},
            "output_fields": {
                "people": (
                    "name, source_ids, facts, preferences, opinions, traits, "
                    "communication_style, affect"
                ),
                "session": "overture, key_details, source_ids",
                "views": "kind, key, overture, key_details, source_ids",
            },
        }
        stats["worker_called"] = True
        try:
            response = self.worker(request)
        except Exception as exc:
            stats["worker_error"] = str(exc)[:500]
            return stats
        if not isinstance(response, Mapping) or "people" not in response:
            stats["worker_error"] = "Maintenance worker returned no valid people list."
            return stats
        people = response.get("people", [])
        if not isinstance(people, list):
            stats["worker_error"] = "Maintenance worker people field was not a list."
            return stats

        record_by_id = {
            str(item.get("id")): item for item in records if item.get("id")
        }
        stats["derived_summaries_written"] = self._write_worker_views(
            session_id=session_id,
            records=records,
            record_by_id=record_by_id,
            response=response,
            people=people,
            base_subjects=subjects_by_id,
            base_topics=topics_by_id,
            base_relations=relations_by_id,
        )
        existing = {
            self._signature(item.get("term", ""), item.get("content", "")): item
            for item in self.beliefs.get_category("people", limit=100_000)
        }
        for person in people[:8]:
            if not isinstance(person, Mapping):
                continue
            name = " ".join(str(person.get("name") or "").split())[:80]
            if not name:
                continue
            source_ids = self._valid_refs(person.get("source_ids"), record_by_id)
            if self.cases.get_case(name) is None:
                # A person can be discussed without speaking. The maintenance
                # worker must bind that person to explicit source IDs; a bare
                # name mention or vocative is only a weak relation.
                explicit_subjects = {
                    str(item.get("id")): [name]
                    for item in records
                    if str(item.get("id")) in source_ids
                }
                if explicit_subjects:
                    additional = self.cases.register_records(
                        records,
                        session_id=session_id,
                        explicit_subjects=explicit_subjects,
                    )
                    stats["references_linked"] += int(
                        additional.get("references_linked", 0)
                    )
                    stats["case_names"] = sorted(set(
                        list(stats.get("case_names") or [])
                        + list(additional.get("case_names") or [])
                    ))
                    stats["cases_touched"] = len(stats["case_names"])
            if self.cases.get_case(name) is None:
                continue
            elif source_ids:
                # Source IDs are claim-level attribution supplied by the
                # worker even when the case already exists as a speaker.
                self.cases.register_records(
                    [record_by_id[item_id] for item_id in source_ids],
                    session_id=session_id,
                    explicit_subjects={item_id: [name] for item_id in source_ids},
                )
            clauses = self._facet_clauses(person)
            if not clauses:
                continue
            content = (f"{name} — " + " | ".join(clauses))[:500].rstrip(" |")
            signature = self._signature(name, content)
            prior = existing.get(signature)
            memory_refs = source_ids or self.cases.session_memory_refs(name, session_id)
            if prior:
                merged_refs = list(dict.fromkeys(
                    list(prior.get("memory_refs") or []) + memory_refs
                ))
                self.beliefs.update_belief(
                    prior["id"],
                    memory_refs=merged_refs,
                    verifications=float(prior.get("verifications", 1.0)) + 1.0,
                )
                self.cases.attach_beliefs(name, [prior["id"]])
                stats["profiles_reinforced"] += 1
                continue
            belief_id = self.beliefs.generate_id("people")
            added = self.beliefs.add_belief(
                "people",
                belief_id,
                content,
                confidence=0.72,
                stability_index=0.68,
                source="session_memory_maintenance",
                memory_refs=memory_refs,
                term=name,
                formation_type="session_profile",
                maintenance_session=session_id,
            )
            if added:
                self.cases.attach_beliefs(name, [belief_id])
                existing[signature] = {
                    "id": belief_id, "term": name, "content": content,
                    "memory_refs": memory_refs, "verifications": 1.0,
                }
                stats["profiles_written"] += 1
        return stats

    def _write_worker_views(
        self,
        *,
        session_id: str,
        records: Sequence[Dict[str, Any]],
        record_by_id: Mapping[str, Dict[str, Any]],
        response: Mapping[str, Any],
        people: Sequence[Any],
        base_subjects: Mapping[str, Sequence[str]],
        base_topics: Mapping[str, Sequence[str]],
        base_relations: Mapping[str, Sequence[Sequence[str]]],
    ) -> int:
        """Materialize the worker's one response into several cheap read views."""
        subjects = {key: list(values) for key, values in base_subjects.items()}
        topics = {key: list(values) for key, values in base_topics.items()}
        relations = {key: [list(value) for value in values] for key, values in base_relations.items()}
        summaries: List[tuple[str, str, str, List[Any], List[str]]] = []

        for person in people[:8]:
            if not isinstance(person, Mapping):
                continue
            name = " ".join(str(person.get("name") or "").split())[:80]
            refs = self._valid_refs(person.get("source_ids"), record_by_id)
            if not name or not refs:
                continue
            for item_id in refs:
                subjects.setdefault(item_id, [])
                if name not in subjects[item_id]:
                    subjects[item_id].append(name)
            details = self._facet_clauses(person)
            if details:
                summaries.append((
                    "subjects", name,
                    f"Source-linked observations about {name} from this session.",
                    details, refs,
                ))

        session = response.get("session")
        if not isinstance(session, Mapping):
            session = {}
        session_refs = self._valid_refs(session.get("source_ids"), record_by_id)
        key_details = session.get("key_details", [])
        if isinstance(key_details, str):
            key_details = [key_details]
        if not isinstance(key_details, list):
            key_details = []
        for detail in key_details:
            if isinstance(detail, Mapping):
                session_refs.extend(self._valid_refs(detail.get("source_ids"), record_by_id))
        session_refs = list(dict.fromkeys(session_refs)) or list(record_by_id)
        overture = " ".join(str(session.get("overture") or "").split())
        if overture or key_details:
            summaries.append((
                "sessions", session_id, overture, key_details, session_refs,
            ))

        views = response.get("views", [])
        if not isinstance(views, list):
            views = []
        for view in views:
            if not isinstance(view, Mapping):
                continue
            kind = str(view.get("kind") or "").lower().rstrip("s")
            key = " ".join(str(view.get("key") or "").split())[:180]
            refs = self._valid_refs(view.get("source_ids"), record_by_id)
            if kind not in {"subject", "topic", "relation"} or not key or not refs:
                continue
            for item_id in refs:
                target = subjects if kind == "subject" else topics
                values = key.split("--") if kind == "relation" else [key]
                if kind == "relation":
                    relations.setdefault(item_id, []).append(values)
                elif key not in target.setdefault(item_id, []):
                    target[item_id].append(key)
            details = view.get("key_details", [])
            if isinstance(details, str):
                details = [details]
            summaries.append((
                kind + "s", key,
                " ".join(str(view.get("overture") or "").split()),
                details if isinstance(details, list) else [], refs,
            ))

        self.cases.logs.file_records(
            records,
            session_id=session_id,
            subjects_by_id=subjects,
            topics_by_id=topics,
            relations_by_id=relations,
        )
        written = 0
        for view, key, note, details, refs in summaries:
            if self.cases.logs.write_summary(
                view,
                key,
                session_id=session_id,
                overture=note,
                key_details=details,
                source_ids=refs,
            ) is not None:
                written += 1
        return written

    @staticmethod
    def _valid_refs(raw: Any, record_by_id: Mapping[str, Any]) -> List[str]:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        return list(dict.fromkeys(
            str(item_id) for item_id in raw if str(item_id) in record_by_id
        ))

    @staticmethod
    def _tag_topics(records: Sequence[Mapping[str, Any]]) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for record in records:
            item_id = str(record.get("id") or "")
            topics = [
                str(tag).split(":", 1)[1]
                for tag in (record.get("tags") or [])
                if str(tag).startswith(("topic:", "focus:")) and ":" in str(tag)
            ]
            if item_id and topics:
                result[item_id] = list(dict.fromkeys(topics))
        return result

    @staticmethod
    def _facet_clauses(person: Mapping[str, Any]) -> List[str]:
        clauses = []
        for facet in FACETS:
            values = person.get(facet, [])
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list):
                continue
            cleaned = [
                " ".join(str(value).split()).strip(" .")
                for value in values[:2] if str(value).strip()
            ]
            if cleaned:
                clauses.append(f"{facet.replace('_', ' ')}: " + "; ".join(cleaned))
        return clauses

    @staticmethod
    def _add_output_links(
        records: Sequence[Mapping[str, Any]],
        subjects: Dict[str, List[str]],
        relations: Dict[str, List[List[str]]],
    ) -> None:
        for record in records:
            if record.get("source") not in {
                "office_speaker", "pulse_output", "helix_outbound",
            }:
                continue
            item_id = str(record.get("id") or "")
            if not item_id:
                continue
            if "Helix" not in subjects.setdefault(item_id, []):
                subjects[item_id].append("Helix")
            recipients = [
                str(tag).split(":", 1)[1]
                for tag in (record.get("tags") or [])
                if str(tag).startswith("recipient:") and ":" in str(tag)
            ]
            for recipient in recipients:
                relations.setdefault(item_id, []).append(["Helix", recipient])

    @staticmethod
    def _signature(name: Any, content: Any) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(content or "").lower()).strip()
        return str(name or "").lower().strip() + "|" + normalized
