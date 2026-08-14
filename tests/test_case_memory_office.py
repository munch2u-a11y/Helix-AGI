#!/usr/bin/env python3
"""Tests for reusable entity-case filing and between-session maintenance."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.case_memory_office import CaseMemoryOffice
from core.session_memory_maintenance import SessionMemoryMaintenance
from memory.belief_store import BeliefStore


class _Corpus:
    def __init__(self, items):
        self.items = {item["id"]: item for item in items}

    def get(self, item_id):
        return self.items.get(item_id)


def _record(item_id, session_id, content):
    return {
        "id": item_id,
        "content": content,
        "tier": 0,
        "session_id": session_id,
        "scope_id": session_id,
        "relevance": 0.4,
        "created_at": "2026-08-09T10:00:00-04:00",
        "source": "pulse_input",
        "importance": 0.7,
        "tags": [],
    }


class CaseMemoryOfficeTests(unittest.TestCase):
    def test_outbound_record_links_helix_to_recipient(self):
        record = _record("sent_1", "s1", "I replied to Mara: Done.")
        record.update(
            source="helix_outbound",
            tags=["outbound", "recipient:Mara"],
        )
        subjects = {}
        relations = {}

        SessionMemoryMaintenance._add_output_links(
            [record], subjects, relations,
        )

        self.assertEqual(subjects["sent_1"], ["Helix"])
        self.assertEqual(relations["sent_1"], [["Helix", "Mara"]])

    def test_person_question_routes_to_small_exact_case(self):
        records = [
            _record("mem_1", "s1", "[event] Bob: Pistachio is my favorite ice cream flavor."),
            _record("mem_2", "s1", "[event] Alice: I bought a red bicycle."),
            _record("mem_3", "s2", "[event] Bob: My train arrives on Friday."),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(tmp, _Corpus(records))
            cases.register_records(records[:2], session_id="s1")
            cases.register_records(records[2:], session_id="s2")
            result = cases.route("What is Bob's favorite ice cream flavor?", max_items=3)

        self.assertEqual(result["case_names"], ["Bob"])
        self.assertEqual([item["id"] for item in result["items"]], ["mem_1"])
        self.assertEqual(result["items"][0]["office_role"], "case_record")

    def test_live_channel_event_is_filed_under_sender(self):
        record = _record(
            "mem_1",
            "s1",
            '[10:00] Mara is talking to me via dashboard. They said: "I like mint tea."',
        )
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(tmp, _Corpus([record]))
            cases.register_records([record], session_id="s1")
            result = cases.route("What tea does Mara like?", max_items=2)
        self.assertEqual(result["case_names"], ["Mara"])
        self.assertEqual([item["id"] for item in result["items"]], ["mem_1"])

    def test_worker_failure_does_not_undo_exact_filing(self):
        record = _record("mem_1", "s1", "Bob: I enjoy quiet Sunday walks.")
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(Path(tmp) / "cases", _Corpus([record]))
            store = BeliefStore(str(Path(tmp) / "beliefs"))

            def fail(_request):
                raise RuntimeError("worker unavailable")

            result = SessionMemoryMaintenance(
                cases=cases, belief_store=store, worker=fail,
            ).run("s1", [record])

            self.assertEqual(cases.get_case("Bob")["memory_refs"], ["mem_1"])
            self.assertIn("worker unavailable", result["worker_error"])
            self.assertEqual(store.get_category("people"), [])

    def test_derived_person_profile_keeps_source_references(self):
        record = _record("mem_1", "s1", "Bob: I enjoy quiet Sunday walks.")
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(Path(tmp) / "cases", _Corpus([record]))
            store = BeliefStore(str(Path(tmp) / "beliefs"))

            result = SessionMemoryMaintenance(
                cases=cases,
                belief_store=store,
                worker=lambda _request: {
                    "people": [{
                        "name": "Bob",
                        "source_ids": ["mem_1"],
                        "preferences": ["enjoys quiet Sunday walks"],
                        "communication_style": ["speaks plainly about routines"],
                    }],
                },
            ).run("s1", [record])

            profiles = store.get_category("people")
            self.assertEqual(result["profiles_written"], 1)
            self.assertEqual(profiles[0]["term"], "Bob")
            self.assertEqual(profiles[0]["memory_refs"], ["mem_1"])
            self.assertIn(profiles[0]["id"], cases.get_case("Bob")["belief_refs"])

    def test_discussed_non_speaker_gets_source_bounded_case(self):
        records = [
            _record("mem_1", "s1", "Alice: Bob always orders pistachio ice cream."),
            _record("mem_2", "s1", "Alice: My own bicycle is red."),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(Path(tmp) / "cases", _Corpus(records))
            store = BeliefStore(str(Path(tmp) / "beliefs"))
            SessionMemoryMaintenance(
                cases=cases,
                belief_store=store,
                worker=lambda _request: {
                    "people": [{
                        "name": "Bob",
                        "source_ids": ["mem_1"],
                        "preferences": ["orders pistachio ice cream"],
                    }],
                },
            ).run("s1", records)

            case = cases.get_case("Bob")
            profile = next(
                item for item in store.get_category("people")
                if item.get("term") == "Bob"
            )
            self.assertEqual(case["memory_refs"], ["mem_1"])
            self.assertEqual(case["session_refs"]["s1"], ["mem_1"])
            self.assertEqual(profile["memory_refs"], ["mem_1"])

    def test_vocative_is_not_filed_as_a_fact_about_addressee(self):
        records = [
            _record("gina_fact", "s1", "Gina: I chose oak flooring for my studio."),
            _record("jon_fact", "s1", "Jon: Thanks, Gina! Marley is my favorite dog."),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(Path(tmp) / "cases", _Corpus(records))
            cases.register_records(records, session_id="s1")
            gina = cases.get_case("Gina")
            result = cases.route(
                "What flooring did Gina choose?",
                subjects=["Gina"],
                include_profiles=False,
            )

        self.assertEqual(gina["memory_refs"], ["gina_fact"])
        self.assertIn("jon_fact", gina["role_refs"]["addressee"])
        self.assertEqual([item["id"] for item in result["items"]], ["gina_fact"])

    def test_malformed_worker_output_is_reported_without_losing_exact_records(self):
        record = _record("mem_1", "s1", "Bob: I enjoy quiet Sunday walks.")
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(Path(tmp) / "cases", _Corpus([record]))
            store = BeliefStore(str(Path(tmp) / "beliefs"))
            result = SessionMemoryMaintenance(
                cases=cases, belief_store=store, worker=lambda _request: {},
            ).run("s1", [record])

        self.assertIn("no valid people list", result["worker_error"].lower())
        self.assertEqual(result["references_linked"], 1)

    def test_exact_records_are_copied_to_time_session_and_subject_logs_once(self):
        record = _record("mem_1", "s1", "Bob: I enjoy quiet Sunday walks.")
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(Path(tmp) / "cases", _Corpus([record]))
            store = BeliefStore(str(Path(tmp) / "beliefs"))
            maintenance = SessionMemoryMaintenance(cases=cases, belief_store=store)

            first = maintenance.run("s1", [record])
            second = maintenance.run("s1", [record])
            root = Path(tmp) / "memory_logs"
            timeline = (root / "timeline" / "2026-08-09" / "mem_1.md").read_text()
            session = (root / "sessions" / "s1" / "mem_1.md").read_text()
            subject = (root / "subjects" / "bob" / "mem_1.md").read_text()
            summary = (root / "sessions" / "s1" / "summary.md").read_text()

        self.assertIn("Bob: I enjoy quiet Sunday walks.", timeline)
        self.assertEqual(timeline, session)
        self.assertEqual(session, subject)
        self.assertIn("Chronological session view", summary)
        self.assertEqual(first["log_copies_written"], 3)
        self.assertEqual(second["log_copies_written"], 0)

    def test_maintenance_views_deduplicate_canonical_ids_before_top_k(self):
        records = [
            _record("mem_1", "s1", "Bob: Alice and I planned the orchard."),
            _record("mem_2", "s1", "Alice: Bob prefers pistachio ice cream."),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(Path(tmp) / "cases", _Corpus(records))
            store = BeliefStore(str(Path(tmp) / "beliefs"))
            result = SessionMemoryMaintenance(
                cases=cases,
                belief_store=store,
                worker=lambda _request: {
                    "people": [{
                        "name": "Bob",
                        "source_ids": ["mem_2"],
                        "preferences": ["prefers pistachio ice cream"],
                    }],
                    "session": {
                        "overture": "Bob and Alice discussed an orchard and a preference.",
                        "key_details": [{
                            "text": "Bob prefers pistachio ice cream.",
                            "source_ids": ["mem_2"],
                        }],
                    },
                    "views": [{
                            "kind": "topic",
                            "key": "ice cream",
                            "source_ids": ["mem_2"],
                            "overture": "A stated flavor preference.",
                        }, {
                            "kind": "relation",
                            "key": "Alice--Bob",
                            "source_ids": ["mem_1"],
                            "overture": "They planned the orchard together.",
                        }],
                },
            ).run("s1", records)
            routed = cases.logs.route(
                "What ice cream does Bob prefer?", subjects=["Bob"], max_items=10,
            )
            session_summary = (
                Path(tmp) / "memory_logs" / "sessions" / "s1" / "summary.md"
            ).read_text()

        ids = [item["id"] for item in routed["items"]]
        self.assertEqual(ids.count("mem_2"), 1)
        self.assertGreater(routed["duplicates_suppressed"], 0)
        self.assertGreaterEqual(result["derived_summaries_written"], 3)
        self.assertIn("Bob and Alice discussed", session_summary)

    def test_output_is_filed_under_helix_and_recipient_relation(self):
        record = _record("mem_9", "s1", "[response] Pistachio, definitely.")
        record["source"] = "office_speaker"
        record["tags"] = ["outbound", "recipient:Bob"]
        with tempfile.TemporaryDirectory() as tmp:
            cases = CaseMemoryOffice(Path(tmp) / "cases", _Corpus([record]))
            store = BeliefStore(str(Path(tmp) / "beliefs"))
            SessionMemoryMaintenance(cases=cases, belief_store=store).run("s1", [record])
            root = Path(tmp) / "memory_logs"

            helix_copy = (root / "subjects" / "helix" / "mem_9.md").exists()
            relation_copy = (root / "relations" / "bob--helix" / "mem_9.md").exists()

        self.assertTrue(helix_copy)
        self.assertTrue(relation_copy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
