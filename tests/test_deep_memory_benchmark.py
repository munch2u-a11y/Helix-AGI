#!/usr/bin/env python3
"""Tests for the progressive learned-association benchmark."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.providers.codex_subscription_provider import _parse_json_stream
from core.preconscious import Preconscious
from memory.mrag.semantic_lane import SemanticLane
from tests.locomo_deep_memory_sandbox import (
    DEFAULT_DATASET,
    score_probe,
    validate_dataset,
)
from tests.locomo_sandbox import run_operational_pulse


class _Corpus:
    version = 1

    def all_items(self):
        return []

    def get_all_concept_expansions(self):
        return {}

    def get_all_relation_expansions(self):
        return {}


class _VectorStore:
    def embed_text(self, _text):
        return np.array([1.0, 0.0], dtype=np.float32)


class DeepMemoryFixtureTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))

    def test_fixture_is_valid_and_progressive(self):
        self.assertEqual(validate_dataset(self.data), [])
        checkpoints = {probe["checkpoint"] for probe in self.data[0]["qa"]}
        self.assertEqual(checkpoints, {1, 2, 3})
        association = [
            probe for probe in self.data[0]["qa"]
            if probe["probe_type"] == "arbitrary_association"
        ]
        self.assertEqual([probe["checkpoint"] for probe in association], [1, 2, 3])

    def test_marker_group_scoring_is_partial_credit(self):
        probe = {
            "answer": "",
            "scoring": {
                "method": "marker_groups",
                "groups": [["might we"], ["blue minute"], ["check"]],
            },
        }
        self.assertAlmostEqual(
            score_probe("Might we pause and check it?", probe),
            2 / 3,
        )

    def test_association_scoring_accepts_specific_or_short_form(self):
        probe = {
            "answer": "the brass compass",
            "scoring": {"method": "contains_any", "terms": ["brass compass", "compass"]},
        }
        self.assertEqual(score_probe("Oddly, a compass.", probe), 1.0)
        self.assertEqual(score_probe("A blue vase.", probe), 0.0)


class RetrievalProfileTests(unittest.TestCase):
    def test_frontier_profile_expands_heads_and_candidate_pool(self):
        with patch.dict(os.environ, {"HELIX_MRAG_PROFILE": "frontier"}, clear=False):
            lane = SemanticLane(_Corpus(), _VectorStore())
        self.assertEqual(lane.profile, "frontier")
        self.assertEqual(lane.max_search_heads, 32)
        self.assertEqual(lane.max_candidate_pool, 160)
        self.assertEqual(lane.min_per_head_k, 8)


class NonTeachingExamTests(unittest.TestCase):
    def test_association_payload_strips_volatile_event_envelope(self):
        first = "[D1:3] [TIME: 2026-03-02 09:00] Mara: Write BRINDLE on the card."
        second = "[D8:9] [TIME: 2031-11-04 17:45] Mara: Write BRINDLE on the card."
        self.assertEqual(
            Preconscious._association_payload(first),
            Preconscious._association_payload(second),
        )
        self.assertEqual(
            Preconscious._association_payload(first),
            "Write BRINDLE on the card.",
        )

    def test_exam_pulse_passes_learn_false_and_skips_writes(self):
        class _Unified:
            last_stats = {"associative_selected": 1}

        class _Preconscious:
            _unified = _Unified()

            def __init__(self):
                self.learn_values = []

            def inject(self, **kwargs):
                self.learn_values.append(kwargs["learn"])
                return ["remembered context"], "", [], None

        class _Physics:
            def step_pulse(self, **_kwargs):
                raise AssertionError("exam must not step physics")

        class _Session:
            def send_message(self, _message):
                return '{"answer":"compass"}'

        preconscious = _Preconscious()
        result = run_operational_pulse(
            {"preconscious": preconscious, "physics": _Physics()},
            _Session(),
            previous_thought="",
            events=["Operator question"],
            trigger_type="user_message",
            mode="qa",
            pulse_number=1,
            question="What comes to mind?",
            learn=False,
            store_artifacts=False,
            advance_physics=False,
        )
        self.assertEqual(preconscious.learn_values, [False])
        self.assertEqual(result["retrieval_stats"]["associative_selected"], 1)

    def test_frontier_renderer_preserves_association_provenance(self):
        preconscious = Preconscious.__new__(Preconscious)
        preconscious._unified = object()
        preconscious._last_surfaced_memory_ids = []
        preconscious._last_cluster_centroid = None
        preconscious._is_repetitive = lambda _content: False
        selection = [{
            "id": "mem_compass",
            "content": "The brass compass is beside the blue vase.",
            "category": "memory",
            "tier": 0,
            "lane": "spatial",
            "association_linked": True,
            "position_8d": None,
            "gravity": 1.0,
        }]
        with patch.dict(os.environ, {"HELIX_MRAG_PROFILE": "frontier"}, clear=False):
            annotation, surfaced = preconscious._render_selection(
                selection, ["BRINDLE"], budget=1, learn=False,
            )
        self.assertIn("[learned follow-on association]", annotation)
        self.assertEqual(surfaced, [])

    def test_local_renderer_preserves_exact_office_evidence(self):
        preconscious = Preconscious.__new__(Preconscious)
        preconscious._unified = object()
        preconscious._last_surfaced_memory_ids = []
        preconscious._last_cluster_centroid = None
        preconscious._is_repetitive = lambda _content: False
        selection = [{
            "id": "mem_release",
            "content": "Mara scheduled the release for August 14, 2032.",
            "category": "memory",
            "tier": 0,
            "lane": "semantic",
            "office_role": "direct_fact",
            "office_verified": True,
            "position_8d": None,
            "gravity": 1.0,
        }]
        with patch.dict(os.environ, {
            "HELIX_MRAG_PROFILE": "local",
            "HELIX_MRAG_RENDER_MODE": "",
        }, clear=False):
            # An empty override is not a supported mode; remove it so the
            # local profile exercises its exact default.
            os.environ.pop("HELIX_MRAG_RENDER_MODE", None)
            annotation, _ = preconscious._render_selection(
                selection, ["release"], budget=1, learn=False,
            )
        self.assertIn("August 14, 2032", annotation)
        self.assertIn("FACTS DESK", annotation)


class CodexTransportParsingTests(unittest.TestCase):
    def test_codex_jsonl_parser_extracts_thread_and_message(self):
        stream = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"answer":"mint tea"}'},
            }),
        ])
        self.assertEqual(
            _parse_json_stream(stream),
            ("thread-123", '{"answer":"mint tea"}'),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
