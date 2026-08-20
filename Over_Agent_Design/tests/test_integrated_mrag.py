"""Deterministic coverage for the embedded Helix mRAG boundary."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
except ImportError:
    class _DummyNumPy:
        float32 = float
        @staticmethod
        def zeros(shape, dtype=None):
            if isinstance(shape, tuple):
                if len(shape) == 1:
                    return [0.0] * shape[0]
                return [[0.0] * shape[1] for _ in range(shape[0])]
            return [0.0] * shape
        @staticmethod
        def repeat(arr, repeats, axis=0):
            return [arr[0]] * repeats
    np = _DummyNumPy()

APP_DIR = Path(__file__).resolve().parents[1]
HELIX_ROOT = APP_DIR.parent
for path in (APP_DIR, HELIX_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from document_ingester import DocumentIngester
from mrag_adapter import (
    HelixMRAGAdapter,
    HelixMRAGRuntime,
    LAYER2_BELIEF_CATEGORIES,
    MRAGConfig,
)
from subconscious_conductor import SubconsciousConductor


class TestEmbeddedMRAG(unittest.TestCase):
    def test_real_semantic_lane_prioritizes_layer2_term(self):
        from memory.belief_store import BeliefStore

        with tempfile.TemporaryDirectory(prefix="helix_overagent_mrag_") as tmp:
            data_dir = Path(tmp) / "data"
            beliefs = BeliefStore(str(data_dir / "beliefs"))
            fixtures = {
                "people": ("Nemo", "Nemo builds local, inspectable agent memory systems."),
                "concepts": ("provenance", "Provenance keeps every derived belief linked to source evidence."),
                "skills": ("verification", "Verification requires authoritative read-back after an action."),
                "desires": ("local autonomy", "Local autonomy minimizes optional external API dependence."),
            }
            for category, (term, content) in fixtures.items():
                beliefs.add_belief(
                    category,
                    f"{category}_fixture",
                    content,
                    mass=2.0,
                    confidence=0.9,
                    term=term,
                    aliases=[term.lower()],
                    memory_refs=[],
                )

            runtime = HelixMRAGRuntime(MRAGConfig(
                repo_root=HELIX_ROOT,
                data_dir=data_dir,
                bootstrap=False,
            ))
            # Keep this test provider-free. Exact Layer-2 lexicon priority is
            # part of the real semantic lane and does not require a cosine hit.
            runtime.physics_engine.embed_text = lambda _text: np.zeros(384, dtype=np.float32)
            semantic_vector = np.zeros(1024, dtype=np.float32)
            if isinstance(semantic_vector, list):
                semantic_vector[0] = 1.0
            else:
                semantic_vector[0] = 1.0
            runtime.physics_engine.embed_semantic_text = (
                lambda _text, is_query=False: semantic_vector.copy() if hasattr(semantic_vector, 'copy') else list(semantic_vector)
            )
            runtime.physics_engine.embed_semantic_batch = (
                lambda texts, is_query=False: np.repeat(
                    semantic_vector.reshape(1, -1) if hasattr(semantic_vector, 'reshape') else [semantic_vector], len(texts), axis=0
                )
            )

            adapter = HelixMRAGAdapter(runtime=runtime)
            context = adapter.retrieve_mrag_context("What does Nemo build?", top_k=3)
            status = adapter.get_status()

            self.assertTrue(adapter.last_retrieval)
            self.assertEqual(adapter.last_retrieval[0]["id"], "people_fixture")
            self.assertEqual(adapter.last_retrieval[0]["tier"], 2)
            self.assertIn("LAYER 2 BELIEF ANCHORS", context)
            self.assertIn("category=people", context)
            self.assertEqual(
                tuple(status["layer2_categories"]),
                LAYER2_BELIEF_CATEGORIES,
            )
            self.assertTrue(all(
                status["layer2_categories"][category] == 1
                for category in LAYER2_BELIEF_CATEGORIES
            ))
            runtime.close()

    def test_document_ingester_uses_mrag_write_boundary(self):
        class RecordingAdapter:
            def __init__(self):
                self.calls = []

            def ingest_document_chunks(self, filename, chunks):
                self.calls.append((filename, list(chunks)))
                return ["mem_41", "mem_42"]

        recorder = RecordingAdapter()
        ingester = DocumentIngester(
            chunk_size_words=50,
            overlap_words=10,
            mrag_adapter=recorder,
        )
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("evidence " * 80)
            path = handle.name
        try:
            result = ingester.process_file_upload(path, "../unsafe/source.txt")
        finally:
            os.unlink(path)

        self.assertTrue(result["success"])
        self.assertEqual(result["filename"], "source.txt")
        self.assertEqual(result["saved_nodes"], ["mem_41", "mem_42"])
        self.assertEqual(recorder.calls[0][0], "source.txt")
        self.assertGreater(len(recorder.calls[0][1]), 1)


class _RecordingMRAG:
    def __init__(self):
        self.queries = []
        self.memories = []

    def retrieve_mrag_context(self, query, top_k=5):
        self.queries.append((query, top_k))
        return "--- HELIX mRAG RECALLED CONTEXT ---\n- [id=people_nemo tier=2 category=people] Nemo prefers local systems."

    def remember(self, content, **kwargs):
        self.memories.append((content, kwargs))
        return f"mem_{len(self.memories)}"


class _ScriptedBackend:
    def __init__(self):
        self.responses = iter([
            'open_focus_window(type="speaker", prompt="Answer with grounded context")',
            "Hello from the grounded speaker.",
        ])

    def generate(self, **_kwargs):
        return next(self.responses)


class TestConductorMRAGFlow(unittest.TestCase):
    def test_turn_recalls_then_records_inbound_and_outbound(self):
        mrag = _RecordingMRAG()
        with tempfile.TemporaryDirectory(prefix="helix_overagent_state_") as tmp:
            seeded_path = os.path.join(tmp, "seed.pkl")
            with patch("subconscious_conductor.SEEDED_STATE_PATH", seeded_path):
                conductor = SubconsciousConductor(
                    backend=_ScriptedBackend(),
                    enable_autonomous_background=False,
                    mrag_adapter=mrag,
                )
                conductor.identity_compiler.affect_pipeline.state_file = os.path.join(
                    tmp, "affect.json"
                )
                response = conductor.process_user_event("Do you remember Nemo?")

        self.assertEqual(response, "Hello from the grounded speaker.")
        self.assertEqual(mrag.queries, [("Do you remember Nemo?", 5)])
        self.assertEqual(len(mrag.memories), 2)
        self.assertEqual(mrag.memories[0][1]["record_metadata"]["record_kind"], "inbound_message")
        self.assertEqual(mrag.memories[1][1]["record_metadata"]["record_kind"], "outbound_message")
        self.assertTrue(mrag.memories[1][1]["persist_index"])
        self.assertFalse(any(
            "Preconscious mRAG observation" in event["content"]
            for event in conductor.event_stream
        ))


if __name__ == "__main__":
    unittest.main()
