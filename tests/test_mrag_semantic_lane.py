#!/usr/bin/env python3
"""Focused tests for high-dimensional multi-head mRAG behavior."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.mrag.semantic_lane import SemanticLane
from memory.semantic_index import SemanticIndex


def _item(item_id, content, embedding):
    return {
        "id": item_id,
        "content": content,
        "tier": 0,
        "term": "",
        "aliases": [],
        "relevance": 0.5,
        "session_id": None,
        "turn_id": None,
        "event_id": None,
        "chunk_index": None,
        "embedding": np.asarray(embedding, dtype=np.float32),
    }


class _Corpus:
    def __init__(self, items):
        self.items = items
        self.version = 1

    def all_items(self):
        return self.items

    def get_all_concept_expansions(self):
        return {}

    def get_all_relation_expansions(self):
        return {}

    def conceptual_tags(self, item):
        return []

    def embedding(self, item):
        return item["embedding"]


class _VectorStore:
    def __init__(self, raw_vector, derived_vector):
        self.raw = raw_vector
        self.derived = derived_vector

    def embed_text(self, text):
        return self.raw if text == "What achievement mattered?" else self.derived

    def query_top_k(self, query_embedding, k=10):
        if np.array_equal(query_embedding, self.raw):
            return [("direct", 0.80)]
        return [("concrete", 0.90)]

    @staticmethod
    def cosine_similarity(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class TestMultiHeadScoring(unittest.TestCase):
    def test_small_corpus_does_not_turn_top_k_into_full_store_injection(self):
        class _AllResultsStore:
            @staticmethod
            def embed_text(_text):
                return np.array([1.0, 0.0], dtype=np.float32)

            @staticmethod
            def query_top_k(_query_embedding, k=10):
                return [("relevant", 0.9), ("unrelated", 0.0)]

            @staticmethod
            def cosine_similarity(a, b):
                return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

        items = [
            _item("relevant", "alpha memory", [1.0, 0.0]),
            _item("unrelated", "orthogonal memory", [0.0, 1.0]),
        ]
        lane = SemanticLane(_Corpus(items), _AllResultsStore())
        with patch("memory.mrag.tagger.extract_keywords_and_phrases", return_value=[]), \
                patch("memory.mrag.tagger.get_tag_counts", return_value={}):
            ranked = lane.retrieve("alpha")

        self.assertEqual([item["id"] for item in ranked], ["relevant"])

    def test_derived_faiss_head_score_survives_final_ranking(self):
        raw = np.array([1.0, 0.0], dtype=np.float32)
        derived = np.array([0.0, 1.0], dtype=np.float32)
        items = [
            _item("direct", "A broad achievement discussion", [0.80, 0.60]),
            _item("concrete", "She finished her screenplay", [0.0, 1.0]),
        ]
        lane = SemanticLane(_Corpus(items), _VectorStore(raw, derived))

        with patch("memory.mrag.tagger.extract_keywords_and_phrases", return_value=[]), \
                patch("memory.mrag.tagger.get_tag_counts", return_value={}):
            ranked = lane.retrieve("What achievement mattered?")

        # Derived similarity is discounted to 0.90 * 0.92 = 0.828, but that
        # still correctly beats the full-query candidate at 0.80. The old
        # port threw this score away and ranked the concrete memory at 0.0.
        self.assertEqual([item["id"] for item in ranked[:2]], ["concrete", "direct"])
        self.assertGreater(ranked[0]["lane_a_score"], ranked[1]["lane_a_score"])

    def test_full_sentence_and_rake_heads_are_all_searched(self):
        raw = np.array([1.0, 0.0], dtype=np.float32)
        lane = SemanticLane(_Corpus([]), _VectorStore(raw, raw))
        trigger = (
            "Alice described recurring guilt about her childhood. "
            "Her mother used stories about monkeys stealing caps."
        )

        heads = lane._generate_search_heads(trigger)
        kinds = [record["kind"] for record in lane.last_search_heads]

        self.assertEqual(heads[0], trigger)
        self.assertIn("full", kinds)
        self.assertIn("sentence", kinds)
        self.assertIn("rake", kinds)
        self.assertLessEqual(len(heads), 16)


class TestFaissFreshness(unittest.TestCase):
    def test_new_vector_is_incrementally_added_to_live_faiss_index(self):
        class _FakeFaiss:
            def __init__(self):
                self.added = []

            def add(self, vectors):
                self.added.append(vectors.copy())

        index = SemanticIndex(dim=2, faiss_threshold=1)
        fake = _FakeFaiss()
        index._faiss_available = True
        index._faiss_index = fake

        index.add("new_memory", np.array([1.0, 0.0], dtype=np.float32))

        self.assertEqual(len(fake.added), 1)
        np.testing.assert_allclose(fake.added[0], np.array([[1.0, 0.0]], dtype=np.float32))

    def test_metadata_only_touch_does_not_rebuild_faiss(self):
        class _FakeFaiss:
            def add(self, vectors):
                pass

        index = SemanticIndex(dim=2, faiss_threshold=1)
        index._faiss_available = True
        index._faiss_index = _FakeFaiss()
        index.add("belief", np.array([1.0, 0.0], dtype=np.float32), {"access": 0})

        rebuilds = []
        index._rebuild_faiss_index = lambda: rebuilds.append(True)
        index.add("belief", np.array([1.0, 0.0], dtype=np.float32), {"access": 1})

        self.assertEqual(rebuilds, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
