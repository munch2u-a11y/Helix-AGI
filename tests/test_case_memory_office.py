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
    }


class CaseMemoryOfficeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
