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
        stats = {
            "session_id": session_id,
            **filing,
            "worker_called": False,
            "profiles_written": 0,
            "profiles_reinforced": 0,
            "worker_error": "",
        }
        if self.worker is None or not records:
            return stats

        request = {
            "task": (
                "Extract durable person-specific facts, preferences, opinions, traits, "
                "communication style, and affect. Keep people separate. For each person, "
                "include source_ids containing only records specifically about that person. "
                "Use only explicit support."
            ),
            "session_id": session_id,
            "records": [
                {"id": item.get("id"), "content": item.get("content", "")}
                for item in records[:80]
            ],
            "limits": {"people": 8, "items_per_facet": 2},
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
            raw_source_ids = person.get("source_ids", [])
            if isinstance(raw_source_ids, str):
                raw_source_ids = [raw_source_ids]
            source_ids = list(dict.fromkeys(
                str(item_id) for item_id in raw_source_ids
                if str(item_id) in record_by_id
            )) if isinstance(raw_source_ids, list) else []
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
            clauses: List[str] = []
            for facet in FACETS:
                values = person.get(facet, [])
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, list):
                    continue
                cleaned = [
                    " ".join(str(value).split()).strip(" .")
                    for value in values[:2]
                    if str(value).strip()
                ]
                if cleaned:
                    clauses.append(f"{facet.replace('_', ' ')}: " + "; ".join(cleaned))
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

    @staticmethod
    def _signature(name: Any, content: Any) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(content or "").lower()).strip()
        return str(name or "").lower().strip() + "|" + normalized
