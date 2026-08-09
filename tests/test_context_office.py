#!/usr/bin/env python3
"""Specialist desk routing and evidence-brief tests."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.context_office import ContextOffice, plan_office
from core.office_workflows import DESK_CONTRACTS, OfficeArbiter, worker_request
from core.unified_retrieval import UnifiedRetrieval
from memory.mrag.corpus import _structured_position


def _item(item_id, scope, turn, content, *, tier=0):
    return {
        "id": item_id,
        "content": content,
        "tier": tier,
        "scope_id": scope,
        "session_id": scope,
        "turn_id": turn,
        "created_at": f"2026-01-{turn:02d}",
        "_category": "memory" if tier == 0 else "preferences",
        "relevance": 0.75,
    }


class _Corpus:
    def __init__(self, items):
        self.items = items
        self.version = 1

    def all_items(self):
        return self.items


class OfficeRoutingTests(unittest.TestCase):
    def test_query_routes_to_specialist_desks(self):
        relation = plan_office("Who leads the team that owns Aurora?")
        self.assertIn("relations", relation.desks)
        self.assertTrue(relation.expand_scope)

        current = plan_office("What is the current staging domain?")
        self.assertIn("state", current.desks)
        self.assertTrue(current.prefer_latest)

        stance = plan_office("What is the agent's stance on vector embedding stores?")
        self.assertIn("beliefs", stance.desks)
        self.assertEqual(stance.subject, "vector embedding stores")
        self.assertNotIn("s", stance.terms)

    def test_identity_and_affect_are_narrowly_routed(self):
        ordinary = plan_office("Can you tell me the launch date?")
        self.assertNotIn("identity", ordinary.desks)
        self.assertNotIn("affect", ordinary.desks)

        identity = plan_office("How do you normally handle conflict with friends?")
        self.assertIn("identity", identity.desks)
        self.assertIn("beliefs", identity.desks)

        affect = plan_office("Do you feel worried about that relationship?")
        self.assertIn("affect", affect.desks)

    def test_worker_contracts_are_small_and_identity_free(self):
        records = [
            _item(str(index), "scope", index, f"record {index}")
            for index in range(1, 20)
        ]
        request = worker_request("beliefs", "What do you prefer?", records)
        self.assertEqual(len(request["candidates"]), DESK_CONTRACTS["beliefs"].max_candidates)
        self.assertNotIn("example", request["task"].lower())
        self.assertNotIn("you are helix", str(request).lower())

    def test_import_tags_preserve_office_episode_identity(self):
        position = _structured_position(
            "[BENCHMARK ITEM: fallback] [TURN: 9] body",
            ["item:q_12", "turn:2", "session:q_12:t2", "chunk:1"],
            "2026-01-01T00:00:00", 99,
        )
        self.assertEqual(position, ("q_12", 2, "q_12:t2", 1))


class OfficeBriefTests(unittest.TestCase):
    def test_board_is_consulted_only_when_initial_slice_is_insufficient(self):
        exact = _item("exact", "release", 1, "The launch date is August 14.")
        other = _item("other", "other", 1, "Mara likes tea.")
        direct = ContextOffice(_Corpus([exact, other])).prepare(
            "What is the launch date?", [exact], max_items=4,
        )
        self.assertFalse(direct.diagnostics["office_board_consulted"])

        expanded = ContextOffice(_Corpus([exact, other])).prepare(
            "What is the current launch date?", [other], max_items=4,
        )
        self.assertTrue(expanded.diagnostics["office_board_consulted"])

    def test_all_unprotected_desks_compete_for_shared_slots(self):
        candidates = [
            {
                "id": "preference", "content": "Prefers direct explanations.",
                "office_desk": "beliefs", "relevance": 0.95,
                "confidence": 0.9, "stability_index": 0.9,
            },
            {
                "id": "fact", "content": "A distant unrelated fact.",
                "office_desk": "facts", "relevance": 0.2,
                "confidence": 0.9, "stability_index": 0.9,
            },
        ]
        selected = OfficeArbiter().allocate(
            candidates, active_desks={"beliefs"}, max_items=1,
        )
        self.assertEqual(selected[0]["id"], "preference")
        self.assertIn("task-fit", selected[0]["office_bid_reason"])

    def test_exact_foreground_reservation_precedes_profile_competition(self):
        candidates = [
            {
                "id": "profile", "content": "A polished but broad person profile.",
                "office_desk": "case", "relevance": 1.0,
                "confidence": 0.95, "formation_type": "session_profile",
            },
            {
                "id": "exact", "content": "Bob: Pistachio is my favorite flavor.",
                "office_desk": "semantic_advisor", "relevance": 0.45,
                "tier": 0,
            },
        ]
        selected = OfficeArbiter().allocate(
            candidates,
            active_desks={"facts"},
            max_items=1,
            reserve_ids=["exact"],
            max_profile_items=0,
        )
        self.assertEqual([item["id"] for item in selected], ["exact"])
        self.assertTrue(selected[0]["office_bid_reserved"])

    def test_state_desk_places_current_before_history(self):
        old = _item("old", "staging", 1, "The retired staging domain was old.internal.")
        new = _item("new", "staging", 2, "The staging domain is staging.internal.")
        other = _item("other", "people", 1, "Alan Reyes is a manager.")
        result = ContextOffice(_Corpus([old, new, other])).prepare(
            "What is the current staging domain?", [other, old], max_items=10,
        )
        self.assertTrue(result.diagnostics["verified"])
        self.assertEqual([item["id"] for item in result.items], ["new", "old"])
        self.assertEqual(result.items[0]["office_role"], "current_state")
        self.assertEqual(result.items[1]["office_role"], "state_history")

    def test_relations_desk_keeps_complete_calculation_episode(self):
        first = _item("a", "team11", 1, "Team 11 deployed 2 servers.")
        second = _item("b", "team11", 2, "Team 11 added 5 more servers.")
        result = ContextOffice(_Corpus([first, second])).prepare(
            "How many servers does Team 11 have in total after Session 2?",
            [second], max_items=10,
        )
        self.assertEqual([item["id"] for item in result.items], ["a", "b"])
        self.assertTrue(all(item["office_desk"] == "relations" for item in result.items))

    def test_relations_desk_keeps_every_path_member(self):
        owner = _item("owner", "aurora", 1, "Aurora is owned by the Platform team.")
        lead = _item("lead", "aurora", 2, "The Platform team is led by Dana Whitfield.")
        wrong = _item("wrong", "telemetry", 1, "Telemetry is led by Nina Kaplan.")
        result = ContextOffice(_Corpus([owner, lead, wrong])).prepare(
            "Who leads the team that owns Aurora?", [owner, wrong], max_items=10,
        )
        self.assertEqual([item["id"] for item in result.items], ["owner", "lead"])
        self.assertEqual(result.diagnostics["scope"], "aurora")

    def test_catalog_desk_preserves_rejected_counterevidence(self):
        items = [
            _item("east", "rollout", 1, "us-east was approved for rollout."),
            _item("west", "rollout", 2, "eu-west was approved for rollout."),
            _item("reject", "rollout", 3, "sa-east was rejected for rollout."),
        ]
        result = ContextOffice(_Corpus(items)).prepare(
            "Which regions were approved for rollout?", [items[1]], max_items=10,
        )
        self.assertEqual([item["id"] for item in result.items], ["east", "west", "reject"])
        self.assertTrue(all(item["office_role"] == "catalog_member" for item in result.items))

    def test_beliefs_desk_binds_one_semantic_paraphrase_episode(self):
        policy = _item(
            "policy", "socket_policy", 1,
            "User enforces loopback default with token auth for security.",
        )
        distractor = _item("other", "other", 1, "A service uses public networking.")
        result = ContextOffice(_Corpus([policy, distractor])).prepare(
            "What is the agent's stance on unprotected LAN sockets?",
            [policy, distractor], max_items=10,
        )
        self.assertTrue(result.diagnostics["verified"])
        self.assertEqual(result.diagnostics["binding_method"], "semantic_belief_episode")
        self.assertEqual([item["id"] for item in result.items], ["policy"])
        self.assertEqual(
            result.items[0]["office_implication"],
            'negative stance toward "unprotected LAN sockets"',
        )

    def test_beliefs_desk_projects_contrastive_preference(self):
        preference = _item(
            "preference", "memory_policy", 1,
            "User prefers non-vector human-readable stores over vector embeddings.",
        )
        result = ContextOffice(_Corpus([preference])).prepare(
            "What is the agent's stance on vector embedding stores?",
            [preference], max_items=10,
        )
        self.assertEqual(
            result.items[0]["office_implication"],
            'negative stance toward "vector embedding stores"',
        )

    def test_causality_desk_does_not_confuse_event_with_reason(self):
        event = _item("event", "audit", 1, "The compliance audit was cancelled.")
        result = ContextOffice(_Corpus([event])).prepare(
            "Why was the compliance audit cancelled?", [event], max_items=10,
        )
        self.assertFalse(result.diagnostics["verified"])
        self.assertEqual(result.items, [])

    def test_unbound_state_keeps_semantic_candidate_visibly_unverified(self):
        event = _item("event", "audit", 1, "The compliance audit was cancelled.")
        result = ContextOffice(_Corpus([event])).prepare(
            "What is the current status of the incident tabletop?", [event], max_items=10,
        )
        self.assertFalse(result.diagnostics["verified"])
        self.assertEqual(result.items[0]["office_role"], "unverified_semantic")

    def test_duplicate_purge_preserves_office_proof_members(self):
        retriever = UnifiedRetrieval.__new__(UnifiedRetrieval)
        retriever.corpus = SimpleNamespace(embedding=lambda _item: None)
        records = [
            {
                "id": "a", "content": "Team 11 deployed 2 servers",
                "office_verified": True, "office_scope": "q_11",
                "office_role": "calculation_member",
            },
            {
                "id": "b", "content": "Team 11 added 5 servers",
                "office_verified": True, "office_scope": "q_11",
                "office_role": "calculation_member",
            },
        ]
        kept, purged = retriever._purge_near_duplicates(records)
        self.assertEqual([item["id"] for item in kept], ["a", "b"])
        self.assertEqual(purged, set())

    def test_downstream_token_guard_does_not_split_atomic_proof(self):
        retriever = UnifiedRetrieval.__new__(UnifiedRetrieval)
        records = [
            {
                "id": "a", "content": "The first necessary proof record is long.",
                "lane": "semantic", "office_bid_atomic": True,
            },
            {
                "id": "b", "content": "The second necessary proof record is also long.",
                "lane": "semantic", "office_bid_atomic": True,
            },
        ]
        selected = retriever._fill_budget(records, max_items=2, token_budget=1)
        self.assertEqual([item["id"] for item in selected], ["a", "b"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
