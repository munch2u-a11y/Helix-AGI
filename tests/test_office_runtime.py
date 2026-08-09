#!/usr/bin/env python3
"""Office-first source routing, evidence capsules, and truth-boundary tests."""

import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.office_runtime import (
    OfficeFirstCoordinator,
    TurnEnvelope,
    classify_source,
)
from core.pulse_loop import PulseLoop
from llm.providers.base import ProviderConfig


class _Memory:
    def __init__(self, recent=()):
        self.recent = list(recent)

    def get_recent(self, limit=20):
        return self.recent[:limit]


class _Physics:
    def __init__(self, items=()):
        self.items = list(items)

    def query_neighborhood(self, **_kwargs):
        return list(self.items)


class _Lane:
    def __init__(self, items=()):
        self.items = list(items)
        self.queries = []

    def retrieve(self, query, limit=None):
        self.queries.append((query, limit))
        return list(self.items)


class _Office:
    def __init__(self, items=(), names=()):
        self.items = list(items)
        self.cases = SimpleNamespace(known_names=lambda: list(names))

    def prepare(self, query, semantic_items, max_items, work_order=None):
        return SimpleNamespace(
            items=self.items or list(semantic_items)[:max_items],
            diagnostics={"verified": True, "query": query},
        )


class _Unified:
    def __init__(self, items=(), office_items=(), names=()):
        self.lane_a = _Lane(items)
        self.context_office = _Office(office_items, names)
        self.corpus = SimpleNamespace()
        self.injected = []

    def note_injected(self, ids):
        self.injected.append(list(ids))


def _coordinator(*, items=(), office_items=(), recent=(), spatial=(), names=()):
    unified = _Unified(items=items, office_items=office_items, names=names)
    coordinator = OfficeFirstCoordinator(
        _Memory(recent), SimpleNamespace(), _Physics(spatial), unified=unified,
    )
    return coordinator, unified


class SourceProfileTests(unittest.TestCase):
    def test_source_types_are_classified_before_model_reasoning(self):
        self.assertEqual(
            classify_source("tool_result", {"tool": "read_file"}), "file_read",
        )
        self.assertEqual(
            classify_source("tool_result", {"tool": "web_search"}), "search_result",
        )
        self.assertEqual(
            classify_source("tool_result", {"tool": "moltbook_feed"}), "social_post",
        )
        self.assertEqual(
            classify_source("user_message", {"channel": "email"}), "email",
        )
        self.assertEqual(
            classify_source("incoming_message", {"channel": "direct"}),
            "direct_message",
        )

    def test_envelope_preserves_provenance_without_copying_body_to_metadata(self):
        envelope = TurnEnvelope.from_event("tool_result", {
            "tool": "read_file",
            "result": "file body",
            "filepath": "/tmp/example.txt",
        })
        self.assertEqual(envelope.source_kind, "file_read")
        self.assertEqual(envelope.content, "file body")
        self.assertEqual(envelope.metadata["tool"], "read_file")
        self.assertEqual(envelope.metadata["filepath"], "/tmp/example.txt")
        self.assertNotIn("result", envelope.metadata)


class ContextCapsuleTests(unittest.TestCase):
    def test_direct_turn_uses_slim_source_aware_capsule_without_identity(self):
        item = {
            "id": "mem_7",
            "content": "Joshua prefers direct, careful answers.",
            "tier": 2,
            "_category": "preferences",
            "office_desk": "beliefs",
            "office_role": "supporting_belief",
            "office_verified": True,
            "confidence": 0.9,
            "stability_index": 0.8,
        }
        coordinator, _ = _coordinator(office_items=[item], names=["Joshua"])
        envelope = TurnEnvelope.from_event("incoming_message", {
            "sender": "Joshua",
            "channel": "direct",
            "content": "How do you feel about the memory design?",
        })
        capsule = coordinator.prepare([envelope], pulse_count=4)

        self.assertEqual(capsule.response_mode, "respond")
        self.assertIn("source=direct_message", capsule.rendered_prompt)
        self.assertIn("intent,continuity,relationship,tone,affect", capsule.rendered_prompt)
        self.assertIn("[STANCE / LEARNED PATTERN]", capsule.rendered_prompt)
        self.assertNotIn("[IDENTITY]", capsule.rendered_prompt)
        self.assertNotIn("you are helix", capsule.rendered_prompt.lower())
        self.assertLess(len(coordinator.SPEAKER_INSTRUCTION.split()), 40)

    def test_identity_records_are_conditional(self):
        identity = {
            "id": "pre_1",
            "content": "I am Helix, a persistent developing agent.",
            "tier": 1,
            "office_desk": "identity",
            "office_role": "identity_source",
            "office_verified": True,
        }
        coordinator, _ = _coordinator(office_items=[identity])
        ordinary = TurnEnvelope.from_event("incoming_message", {
            "sender": "User", "content": "What time is the meeting?",
        })
        self.assertNotIn(
            "I am Helix", coordinator.prepare([ordinary]).rendered_prompt,
        )

        identity_query = TurnEnvelope.from_event("incoming_message", {
            "sender": "User", "content": "Who are you, really?",
        })
        prompt = coordinator.prepare([identity_query]).rendered_prompt
        self.assertIn("[IDENTITY]", prompt)
        self.assertIn("I am Helix", prompt)

    def test_character_voice_requests_can_use_identity_but_not_stale_name_claims(self):
        recent = [{
            "id": "old_reply",
            "point_id": "mem_old_reply",
            "content": "I replied to Joshua: I am Gemini.",
            "source": "pulse_input",
            "tags": ["conversation", "outbound"],
        }]
        identity = {
            "id": "pre_current",
            "content": "I am Helix, shaped by memory and reflection.",
            "tier": 1,
            "office_desk": "identity",
            "office_role": "identity_source",
            "office_verified": True,
        }
        coordinator, _ = _coordinator(office_items=[identity], recent=recent)
        envelope = TurnEnvelope.from_event("incoming_message", {
            "sender": "Joshua",
            "content": "Could this make Helix sound less like himself?",
        })
        capsule = coordinator.prepare([envelope])
        self.assertTrue(capsule.identity_needed)
        self.assertIn("I am Helix", capsule.rendered_prompt)
        self.assertNotIn("I am Gemini", capsule.rendered_prompt)

    def test_action_claims_require_a_successful_receipt(self):
        coordinator, _ = _coordinator()
        request = TurnEnvelope.from_event("incoming_message", {
            "sender": "User", "content": "Please read the project file.",
        })
        without_receipt = coordinator.prepare([request]).rendered_prompt
        self.assertIn("no successful receipt", without_receipt.lower())

        receipt = TurnEnvelope.from_event("tool_result", {
            "tool": "read_file",
            "result": "Read 42 lines from project.txt.",
            "filepath": "project.txt",
        })
        with_receipt = coordinator.prepare([request, receipt])
        self.assertIn("[ACTION RECEIPTS]", with_receipt.rendered_prompt)
        self.assertIn("read_file; success", with_receipt.rendered_prompt)
        self.assertNotIn("no successful receipt", with_receipt.rendered_prompt.lower())

    def test_failed_tool_text_cannot_certify_success(self):
        coordinator, _ = _coordinator()
        receipt = TurnEnvelope.from_event("tool_result", {
            "tool": "web_search",
            "result": "Error: request timed out",
        })
        capsule = coordinator.prepare([receipt])
        self.assertEqual(capsule.receipts[0].status, "failed")
        self.assertIn("web_search; failed", capsule.rendered_prompt)

    def test_recent_and_spatial_returns_keep_distinct_truth_roles(self):
        recent = [{
            "id": "11",
            "point_id": "mem_11",
            "content": "[response] We were discussing the cap salesman story.",
            "source": "office_speaker",
            "tags": ["conversation", "outbound"],
        }]
        spatial = [{
            "point_id": "mem_2",
            "content": "Monkeys once stole all of the salesman's caps.",
            "relevance": 0.7,
            "distance": 0.4,
        }]
        coordinator, _ = _coordinator(recent=recent, spatial=spatial)
        envelope = TurnEnvelope.from_event("incoming_message", {
            "sender": "User", "content": "What does that remind you of?",
        })
        capsule = coordinator.prepare([envelope])
        self.assertIn("[CONTINUITY]", capsule.rendered_prompt)
        continuity = [bid for bid in capsule.evidence if bid.desk == "continuity"]
        self.assertTrue(continuity)
        self.assertTrue(all(not bid.verified for bid in continuity))
        self.assertIn("do not independently verify claims", capsule.rendered_prompt)
        self.assertIn("[ASSOCIATION — NON-EVIDENTIARY]", capsule.rendered_prompt)
        lateral = [bid for bid in capsule.evidence if bid.desk == "lateral"]
        self.assertEqual(len(lateral), 1)
        self.assertFalse(lateral[0].verified)

    def test_same_pulse_messages_are_not_lost(self):
        coordinator, _ = _coordinator()
        first = TurnEnvelope.from_event("incoming_message", {
            "sender": "User", "content": "First, remember the blue folder.",
            "event_id": "first",
        })
        second = TurnEnvelope.from_event("incoming_message", {
            "sender": "User", "content": "Where should I put it?",
            "event_id": "second",
        })
        prompt = coordinator.prepare([first, second]).rendered_prompt
        self.assertIn("[SAME-PULSE CONTEXT]", prompt)
        self.assertIn("remember the blue folder", prompt)
        self.assertIn("Where should I put it?", prompt)

    def test_file_return_adds_one_bounded_source_focus_search(self):
        coordinator, unified = _coordinator()
        envelope = TurnEnvelope.from_event("tool_result", {
            "tool": "read_file",
            "result": "def compile_capsule(): pass",
            "filepath": "core/office_runtime.py",
            "objective": "review the context compiler",
        })
        capsule = coordinator.prepare([envelope])
        self.assertEqual(len(unified.lane_a.queries), 2)
        self.assertEqual(capsule.diagnostics["office"]["search_heads"], [
            "full", "source_focus",
        ])
        focus_query = unified.lane_a.queries[1][0]
        self.assertIn("core/office_runtime.py", focus_query)
        self.assertIn("active task", focus_query)
        self.assertIn("active_task,path,requested_section,project_context", capsule.rendered_prompt)

    def test_source_focused_belief_gets_a_real_competing_slot(self):
        fact = {
            "id": "mem_1", "content": "The meeting starts at noon.",
            "tier": 0, "office_desk": "facts", "office_verified": True,
        }
        style = {
            "id": "prf_1", "content": "Joshua prefers plain, candid wording.",
            "tier": 2, "_category": "preferences", "lane_a_score": 0.88,
        }
        coordinator, _ = _coordinator(items=[style], office_items=[fact])
        envelope = TurnEnvelope.from_event("incoming_message", {
            "sender": "Joshua", "content": "What time is the meeting?",
        })
        capsule = coordinator.prepare([envelope])
        self.assertEqual(capsule.diagnostics["office"]["source_focus_advisors"], 1)
        self.assertIn("The meeting starts at noon", capsule.rendered_prompt)
        self.assertIn("Joshua prefers plain, candid wording", capsule.rendered_prompt)

    def test_current_sender_case_can_bid_for_relationship_context(self):
        case_item = {
            "id": "mem_case",
            "content": "Joshua often opens uncertain proposals with 'Hmm, maybe'.",
            "tier": 0,
            "case_name": "Joshua",
        }
        coordinator, _ = _coordinator(names=["Joshua"])
        coordinator.context_office.cases.route = Mock(return_value={
            "case_names": ["Joshua"], "items": [case_item], "candidates": 1,
        })
        envelope = TurnEnvelope.from_event("incoming_message", {
            "sender": "Joshua", "content": "Hmm, maybe we should revise this?",
        })
        capsule = coordinator.prepare([envelope])
        self.assertIn("Joshua often opens uncertain proposals", capsule.rendered_prompt)
        case_bids = [bid for bid in capsule.evidence if bid.desk == "case"]
        self.assertEqual(len(case_bids), 1)
        self.assertEqual(case_bids[0].role, "source_relationship_case")
        self.assertFalse(case_bids[0].verified)


class PulseOfficeBoundaryTests(unittest.TestCase):
    def test_incoming_alias_wakes_and_keeps_typed_event(self):
        loop = PulseLoop.__new__(PulseLoop)
        loop._event_queue = []
        loop._office_event_queue = []
        loop._event_lock = threading.Lock()
        loop._office_first_enabled = True
        loop._last_event_time = 0
        loop._last_incoming_time = 0
        loop._last_activity_time = 0
        loop._state = "RESTING"
        loop.channel_router = None
        loop.sentinel = None
        loop.wake = Mock(side_effect=lambda trigger="external": setattr(loop, "_state", "ACTIVE"))

        loop.emit("incoming_message", {
            "sender": "User", "channel": "direct", "content": "Hello",
        })
        self.assertEqual(loop._state, "ACTIVE")
        self.assertIn("User is talking to me", loop._event_queue[0])
        self.assertEqual(loop._office_event_queue[0].source_kind, "direct_message")
        self.assertTrue(loop._office_event_queue[0].response_required)

    def test_speaking_session_is_fresh_schema_free_and_closed(self):
        loop = PulseLoop.__new__(PulseLoop)
        loop._provider_config = ProviderConfig(
            "ollama", "granite4.1:8b", max_output_tokens=4096,
        )
        loop._office_coordinator = SimpleNamespace(
            SPEAKER_INSTRUCTION="Return only the response.",
        )
        loop._office_last_token_count = 0
        loop._session_token_count = 0
        session = Mock()
        session.send_message.return_value = "Grounded response"
        session.get_last_token_count.return_value = 77

        with patch("core.pulse_loop.create_session", return_value=session) as factory:
            result = loop._send_office_pulse("[TURN] test")

        self.assertEqual(result, "Grounded response")
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["tool_declarations"])
        self.assertIsNone(kwargs["tool_executor"])
        self.assertIsNone(kwargs["preconscious"])
        self.assertEqual(factory.call_args.args[1], "Return only the response.")
        self.assertEqual(loop._session_token_count, 77)
        session.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
