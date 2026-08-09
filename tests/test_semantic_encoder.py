#!/usr/bin/env python3
"""Regression tests for the independent 1024D semantic representation."""

import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.physics_engine import PhysicsEngine, SPATIAL_EMBEDDING_DIM
from memory.semantic_encoder import SemanticEncoder
from memory.semantic_index import SemanticIndex


class SemanticEncoderTests(unittest.TestCase):
    def test_query_instruction_and_native_width(self):
        calls = []

        def fake_embed(**kwargs):
            calls.append(kwargs)
            rows = []
            for index, _text in enumerate(kwargs["input"]):
                vector = np.zeros(1024, dtype=np.float32)
                vector[index] = 1.0
                rows.append(vector.tolist())
            return SimpleNamespace(embeddings=rows)

        encoder = SemanticEncoder(dim=1024)
        with patch("ollama.embed", side_effect=fake_embed):
            query = encoder.encode_queries(["guilt and family"])
            document = encoder.encode_documents(["A memory about family"])

        self.assertEqual(query.shape, (1, 1024))
        self.assertEqual(document.shape, (1, 1024))
        self.assertTrue(calls[0]["input"][0].startswith("Instruct:"))
        self.assertEqual(calls[1]["input"][0], "A memory about family")
        self.assertEqual(calls[0]["dimensions"], 1024)

    def test_spatial_and_semantic_dimensions_are_decoupled(self):
        with tempfile.TemporaryDirectory() as tmp:
            physics = PhysicsEngine(tmp)

        self.assertEqual(SPATIAL_EMBEDDING_DIM, 384)
        self.assertEqual(physics.spatial_mind.embedding_dim, 384)
        self.assertEqual(physics.semantic_index.dim, 1024)
        self.assertEqual(
            physics.spatial_mind.belief_space.projection.W.shape,
            (384, 8),
        )

    def test_semantic_migration_does_not_create_or_move_spatial_points(self):
        class FakeEncoder:
            dim = 1024
            batch_size = 4
            identity = "fake:1024"

            @staticmethod
            def encode_documents(texts):
                rows = np.zeros((len(texts), 1024), dtype=np.float32)
                rows[:, 0] = 1.0
                return rows

        with tempfile.TemporaryDirectory() as tmp:
            physics = PhysicsEngine(tmp)
            physics.semantic_encoder = FakeEncoder()
            physics.semantic_index = SemanticIndex(
                dim=1024,
                faiss_threshold=10_000,
                model_id=physics.semantic_encoder.identity,
            )

            before = physics.spatial_mind.belief_space.point_count
            added = physics._bootstrap_semantic_records([
                {
                    "id": "belief_1",
                    "content": "Guilt sometimes recalls a relationship with Mom.",
                    "position_8d": [0.1] * 8,
                }
            ], [])

            self.assertEqual(added, 1)
            self.assertTrue(physics.semantic_index.contains("belief_1"))
            self.assertEqual(physics.spatial_mind.belief_space.point_count, before)

    def test_precomputed_semantic_vector_bypasses_document_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            physics = PhysicsEngine(tmp)
            vector = np.zeros(1024, dtype=np.float32)
            vector[17] = 1.0
            with patch.object(
                physics.semantic_encoder,
                "encode_document",
                side_effect=AssertionError("batch vector should be reused"),
            ):
                point_id, _position, _embedding = physics.register_memory_entry(
                    memory_id=1,
                    content="A batch-indexed benchmark session.",
                    embedding_384d=np.ones(384, dtype=np.float32).tolist(),
                    semantic_embedding_1024d=vector.tolist(),
                )

            self.assertEqual(point_id, "mem_1")
            self.assertTrue(physics.semantic_index.contains(point_id))

    def test_spatial_ingest_batches_embedding_calls(self):
        calls = []

        def fake_embed(texts):
            calls.append(list(texts))
            return np.stack([
                np.full(384, index + 1, dtype=np.float32)
                for index, _text in enumerate(texts)
            ])

        with tempfile.TemporaryDirectory() as tmp:
            physics = PhysicsEngine(tmp)
            physics._embedder = fake_embed
            result = physics.embed_text_batch(["first", "second"])

        self.assertEqual(calls, [["first", "second"]])
        self.assertEqual(result.shape, (2, 384))
        self.assertEqual(float(result[1, 0]), 2.0)


class SemanticIndexTests(unittest.TestCase):
    def test_legacy_vector_cannot_be_padded_into_native_index(self):
        index = SemanticIndex(dim=1024)
        with self.assertRaises(ValueError):
            index.add("legacy", np.ones(384, dtype=np.float32))

    def test_batch_exact_search_matches_each_query(self):
        index = SemanticIndex(dim=3, faiss_threshold=10_000)
        index.add("x", np.array([1.0, 0.0, 0.0], dtype=np.float32))
        index.add("y", np.array([0.0, 1.0, 0.0], dtype=np.float32))

        rows = index.search_batch(np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ], dtype=np.float32), k=1)

        self.assertEqual(rows[0][0]["id"], "x")
        self.assertEqual(rows[1][0]["id"], "y")

    @unittest.skipUnless(importlib.util.find_spec("faiss"), "faiss not installed")
    def test_default_faiss_mode_is_exact_flat_ip(self):
        index = SemanticIndex(dim=3, faiss_threshold=1)
        index.add("x", np.array([1.0, 0.0, 0.0], dtype=np.float32))

        self.assertEqual(index.get_stats()["search_strategy"], "faiss_flat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
